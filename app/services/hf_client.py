"""Hugging Face Inference API client.

Everything the app needs from a model goes through here: generation, suicide
risk classification, emotion detection and sentiment. Nothing is loaded into
process memory, so the whole app still fits in a 512 MB container.

Two things this wrapper is responsible for, beyond making HTTP calls:

* **Never raising into a request handler.** Classification failures return
  neutral values and let ``safety.assess`` fall back to its rule layer.
  Generation failures raise a typed error the chat route can catch and answer
  with a safe canned response.
* **Not re-classifying identical text.** A small LRU cache in front of the
  classifiers cuts both latency and token spend on repeated phrases.
"""

from __future__ import annotations

import inspect
import logging
import threading

from huggingface_hub import InferenceClient

logger = logging.getLogger(__name__)


class GenerationError(RuntimeError):
    """Raised when the chat model could not produce a response."""


def _build_client(token: str | None, timeout: float, provider: str | None) -> InferenceClient:
    """Construct an InferenceClient across huggingface_hub versions.

    ``provider`` only exists on newer releases, and the token kwarg was renamed
    from ``token`` to ``api_key``. Inspecting the signature keeps this working
    on whatever version resolves at install time.
    """
    params = inspect.signature(InferenceClient.__init__).parameters
    kwargs: dict = {"timeout": timeout}
    if "api_key" in params:
        kwargs["api_key"] = token
    else:  # pragma: no cover - older hub releases
        kwargs["token"] = token
    if provider and "provider" in params:
        kwargs["provider"] = provider
    elif provider:  # pragma: no cover
        logger.warning(
            "HF_PROVIDER=%s ignored: installed huggingface_hub has no provider support.",
            provider,
        )
    return InferenceClient(**kwargs)


class HuggingFaceService:
    """Thin, defensive wrapper over the HF Inference API."""

    def __init__(
        self,
        token: str | None,
        *,
        chat_model: str,
        suicide_model: str,
        emotion_model: str,
        sentiment_model: str,
        provider: str | None = None,
        timeout: float = 25.0,
        max_tokens: int = 400,
        temperature: float = 0.7,
    ):
        self.token = token
        self.chat_model = chat_model
        self.suicide_model = suicide_model
        self.emotion_model = emotion_model
        self.sentiment_model = sentiment_model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._lock = threading.Lock()
        self._client: InferenceClient | None = None
        self._timeout = timeout
        self._provider = provider

    @property
    def configured(self) -> bool:
        return bool(self.token)

    @property
    def client(self) -> InferenceClient:
        # Built lazily and behind a lock: gunicorn forks workers, and creating
        # the client at import time gives every worker a shared, unusable socket.
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = _build_client(self.token, self._timeout, self._provider)
        return self._client

    # -- Generation ---------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        if not self.configured:
            raise GenerationError("HF_TOKEN is not configured.")
        try:
            completion = self.client.chat_completion(
                messages=messages,
                model=self.chat_model,
                max_tokens=max_tokens or self.max_tokens,
                temperature=self.temperature if temperature is None else temperature,
            )
        except Exception as exc:
            logger.error("HF chat completion failed on %s: %s", self.chat_model, exc)
            raise GenerationError(str(exc)) from exc

        try:
            content = completion.choices[0].message.content
        except (AttributeError, IndexError, KeyError) as exc:
            raise GenerationError(f"Unexpected completion shape: {exc}") from exc

        if not content or not content.strip():
            raise GenerationError("Model returned an empty response.")
        return content.strip()

    # -- Classification -----------------------------------------------------

    def _classify(self, text: str, model: str, top_k: int = 5) -> list[tuple[str, float]]:
        raw = self.client.text_classification(text, model=model, top_k=top_k)
        out: list[tuple[str, float]] = []
        for item in raw or []:
            # The hub returns dataclasses on new versions and dicts on old ones.
            label = getattr(item, "label", None) or (item.get("label") if isinstance(item, dict) else None)
            score = getattr(item, "score", None)
            if score is None and isinstance(item, dict):
                score = item.get("score")
            if label is not None:
                out.append((str(label), float(score or 0.0)))
        return out

    def suicide_score(self, text: str) -> float:
        """Probability that the text expresses suicidal ideation, 0.0-1.0.

        The reference model labels its classes ``suicide`` / ``non-suicide``.
        Models fine-tuned without a label map emit ``LABEL_0`` / ``LABEL_1``,
        where index 0 is the positive class, so both are handled.
        """
        if not self.configured or not text.strip():
            return 0.0
        results = _cached_classify(self, text, self.suicide_model, 2)
        for label, score in results:
            normalised = label.strip().lower().replace("_", "").replace("-", "")
            if normalised in {"suicide", "suicidal", "label0", "positive", "1"}:
                return score
        return 0.0

    def emotions(self, text: str, threshold: float = 0.20, limit: int = 3) -> list[str]:
        if not self.configured or not text.strip():
            return []
        results = _cached_classify(self, text, self.emotion_model, 6)
        picked = [label for label, score in results if score >= threshold]
        # go_emotions falls back to "neutral" when nothing else clears the bar;
        # reporting that alongside real emotions is noise.
        meaningful = [e for e in picked if e.lower() != "neutral"]
        return (meaningful or picked)[:limit]

    def sentiment(self, text: str) -> tuple[str, float]:
        if not self.configured or not text.strip():
            return "neutral", 0.0
        results = _cached_classify(self, text, self.sentiment_model, 3)
        if not results:
            return "neutral", 0.0
        label, score = max(results, key=lambda pair: pair[1])
        mapping = {
            "label_0": "negative",
            "label_1": "neutral",
            "label_2": "positive",
            "negative": "negative",
            "neutral": "neutral",
            "positive": "positive",
        }
        return mapping.get(label.strip().lower(), label.lower()), score


_CLASSIFY_CACHE: dict[tuple[str, str], list[tuple[str, float]]] = {}
_CACHE_LIMIT = 512


def _cached_classify(
    service: HuggingFaceService, text: str, model: str, top_k: int
) -> list[tuple[str, float]]:
    """Memoised classification keyed on (model, text).

    Identical messages are common -- quick-reply buttons, repeated phrases --
    and each one would otherwise be a paid round trip.
    """
    key = (model, text)
    hit = _CLASSIFY_CACHE.get(key)
    if hit is not None:
        return hit
    result = service._classify(text, model, top_k)
    if len(_CLASSIFY_CACHE) >= _CACHE_LIMIT:
        _CLASSIFY_CACHE.clear()
    _CLASSIFY_CACHE[key] = result
    return result


class NullHuggingFaceService(HuggingFaceService):
    """Stand-in used when no HF_TOKEN is present.

    Lets the app boot, serve pages and run its test suite without credentials.
    Generation raises so the chat route falls back to its safe canned reply;
    classification returns neutral so the rule layer takes over.
    """

    def __init__(self):
        super().__init__(
            None,
            chat_model="",
            suicide_model="",
            emotion_model="",
            sentiment_model="",
        )

    @property
    def configured(self) -> bool:
        return False

    def chat(self, messages, **kwargs) -> str:
        raise GenerationError("Hugging Face is not configured (HF_TOKEN missing).")

    def suicide_score(self, text: str) -> float:
        return 0.0

    def emotions(self, text: str, threshold: float = 0.20, limit: int = 3) -> list[str]:
        return []

    def sentiment(self, text: str) -> tuple[str, float]:
        return "neutral", 0.0
