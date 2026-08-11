"""Parsing and degradation logic in the Hugging Face wrapper.

The network call itself is not under test; the label handling is. A silent
mis-mapping here would make the suicide classifier always return 0.0, which
would look like "no crises detected" rather than like a bug.
"""

from __future__ import annotations

import pytest

from app.services import hf_client
from app.services.hf_client import (
    GenerationError,
    HuggingFaceService,
    NullHuggingFaceService,
)


@pytest.fixture(autouse=True)
def clear_cache():
    hf_client._CLASSIFY_CACHE.clear()
    yield
    hf_client._CLASSIFY_CACHE.clear()


class Service(HuggingFaceService):
    """Real class, with only the HTTP boundary replaced."""

    def __init__(self, results):
        super().__init__(
            "fake-token",
            chat_model="m",
            suicide_model="s",
            emotion_model="e",
            sentiment_model="t",
        )
        self.results = results
        self.classify_calls = 0

    def _classify(self, text, model, top_k=5):
        self.classify_calls += 1
        return self.results


def test_named_suicide_label_is_read():
    svc = Service([("suicide", 0.93), ("non-suicide", 0.07)])
    assert svc.suicide_score("x") == pytest.approx(0.93)


def test_unlabelled_model_maps_label_0_to_the_positive_class():
    svc = Service([("LABEL_0", 0.88), ("LABEL_1", 0.12)])
    assert svc.suicide_score("x") == pytest.approx(0.88)


def test_non_suicide_alone_scores_zero():
    svc = Service([("non-suicide", 0.99)])
    assert svc.suicide_score("x") == 0.0


def test_unknown_labels_do_not_raise():
    svc = Service([("weird-label", 0.99)])
    assert svc.suicide_score("x") == 0.0


def test_empty_text_short_circuits_without_a_call():
    svc = Service([("suicide", 0.9)])
    assert svc.suicide_score("   ") == 0.0
    assert svc.classify_calls == 0


def test_emotions_respect_the_threshold():
    svc = Service([("sadness", 0.7), ("fear", 0.3), ("joy", 0.05)])
    assert svc.emotions("x", threshold=0.2) == ["sadness", "fear"]


def test_emotions_are_limited():
    svc = Service([("a", 0.9), ("b", 0.8), ("c", 0.7), ("d", 0.6)])
    assert len(svc.emotions("x", limit=3)) == 3


def test_neutral_is_dropped_when_real_emotions_are_present():
    svc = Service([("neutral", 0.9), ("sadness", 0.6)])
    assert svc.emotions("x") == ["sadness"]


def test_neutral_survives_when_it_is_all_there_is():
    svc = Service([("neutral", 0.9)])
    assert svc.emotions("x") == ["neutral"]


@pytest.mark.parametrize(
    "label,expected",
    [("LABEL_0", "negative"), ("LABEL_1", "neutral"), ("LABEL_2", "positive"),
     ("positive", "positive"), ("negative", "negative")],
)
def test_sentiment_label_mapping(label, expected):
    svc = Service([(label, 0.9)])
    assert svc.sentiment("x")[0] == expected


def test_sentiment_picks_the_highest_scoring_label():
    svc = Service([("negative", 0.2), ("positive", 0.75), ("neutral", 0.05)])
    label, score = svc.sentiment("x")
    assert label == "positive"
    assert score == pytest.approx(0.75)


def test_identical_text_is_only_classified_once():
    svc = Service([("suicide", 0.5)])
    svc.suicide_score("same message")
    svc.suicide_score("same message")
    assert svc.classify_calls == 1


def test_different_text_is_classified_separately():
    svc = Service([("suicide", 0.5)])
    svc.suicide_score("one")
    svc.suicide_score("two")
    assert svc.classify_calls == 2


def test_cache_is_bounded():
    svc = Service([("suicide", 0.1)])
    for i in range(hf_client._CACHE_LIMIT + 5):
        svc.suicide_score(f"message {i}")
    assert len(hf_client._CLASSIFY_CACHE) <= hf_client._CACHE_LIMIT


# --- Null service ----------------------------------------------------------

def test_null_service_reports_unconfigured():
    assert NullHuggingFaceService().configured is False


def test_null_service_generation_raises_a_typed_error():
    with pytest.raises(GenerationError):
        NullHuggingFaceService().chat([])


def test_null_service_classifiers_are_neutral():
    svc = NullHuggingFaceService()
    assert svc.suicide_score("I want to die") == 0.0
    assert svc.emotions("anything") == []
    assert svc.sentiment("anything") == ("neutral", 0.0)


def test_unconfigured_service_never_generates():
    svc = HuggingFaceService(None, chat_model="m", suicide_model="s",
                             emotion_model="e", sentiment_model="t")
    assert svc.configured is False
    with pytest.raises(GenerationError, match="HF_TOKEN"):
        svc.chat([{"role": "user", "content": "hi"}])
