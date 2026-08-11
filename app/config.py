"""Application configuration.

Every setting is read from the environment. Nothing sensitive is ever
hard-coded here -- the previous version of this app shipped a live Gemini
key in source, which is exactly what this module exists to prevent.
"""

from __future__ import annotations

import os


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _normalise_db_url(url: str) -> str:
    """Render and Heroku hand out ``postgres://`` URLs that SQLAlchemy 2.x
    refuses to parse. Rewrite to the dialect it expects."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


class BaseConfig:
    # --- Core ---------------------------------------------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY")
    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

    # --- Database -----------------------------------------------------------
    SQLALCHEMY_DATABASE_URI = _normalise_db_url(
        os.environ.get("DATABASE_URL", "sqlite:///dil_azaad.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        # Long-lived Postgres connections get culled by proxies and by Render's
        # network layer; recycling below that window avoids stale-connection 500s.
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }

    # --- Sessions -----------------------------------------------------------
    # Signed cookies, deliberately. The previous filesystem backend broke the
    # moment gunicorn ran more than one worker: each worker had its own session
    # directory, so users were randomly logged out. Cookies are stateless and
    # correct across any number of workers. Only an opaque user id and a session
    # version live in the cookie -- never message content.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    PERMANENT_SESSION_LIFETIME = _int("SESSION_LIFETIME_SECONDS", 60 * 60 * 24 * 14)

    # --- CSRF ---------------------------------------------------------------
    WTF_CSRF_TIME_LIMIT = None  # tie CSRF validity to the session, not a timer

    # --- Rate limiting ------------------------------------------------------
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI") or "memory://"
    RATELIMIT_HEADERS_ENABLED = True

    # --- Hugging Face -------------------------------------------------------
    HF_TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
    HF_PROVIDER = os.environ.get("HF_PROVIDER") or None
    HF_CHAT_MODEL = os.environ.get("HF_CHAT_MODEL", "meta-llama/Llama-3.3-70B-Instruct")
    HF_SUICIDE_MODEL = os.environ.get(
        "HF_SUICIDE_MODEL", "vibhorag101/roberta-base-suicide-prediction-phr"
    )
    HF_EMOTION_MODEL = os.environ.get(
        "HF_EMOTION_MODEL", "SamLowe/roberta-base-go_emotions"
    )
    HF_SENTIMENT_MODEL = os.environ.get(
        "HF_SENTIMENT_MODEL", "cardiffnlp/twitter-roberta-base-sentiment-latest"
    )

    # --- Generation ---------------------------------------------------------
    LLM_MAX_TOKENS = _int("LLM_MAX_TOKENS", 400)
    LLM_TEMPERATURE = _float("LLM_TEMPERATURE", 0.7)
    LLM_TIMEOUT_SECONDS = _float("LLM_TIMEOUT_SECONDS", 25.0)

    # --- Memory -------------------------------------------------------------
    MEMORY_TURN_WINDOW = _int("MEMORY_TURN_WINDOW", 12)
    MEMORY_SUMMARY_TRIGGER = _int("MEMORY_SUMMARY_TRIGGER", 20)

    # --- Data retention -----------------------------------------------------
    RETENTION_DAYS = _int("RETENTION_DAYS", 0)  # 0 disables automatic purging

    TESTING = False
    DEBUG = False


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class ProductionConfig(BaseConfig):
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", True)
    PREFERRED_URL_SCHEME = "https"


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "testing-only-key"
    # Deterministic Fernet key so encrypted fixtures round-trip between runs.
    ENCRYPTION_KEY = "1EDoBsdzKcSC7Ib7c1p9nQnrLBHXNVOBc1CBBmvBIeY="
    RATELIMIT_ENABLED = False
    HF_TOKEN = None


_CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config(name: str | None = None):
    key = (name or os.environ.get("FLASK_ENV") or "production").lower()
    return _CONFIGS.get(key, ProductionConfig)
