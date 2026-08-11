"""Application factory."""

from __future__ import annotations

import logging
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_wtf.csrf import CSRFError

from .cli import register_cli
from .config import get_config
from .crypto import init_encryption
from .extensions import csrf, db, limiter, migrate
from .security import apply_security_headers, current_user, load_current_user
from .services.hf_client import HuggingFaceService, NullHuggingFaceService

BASE_DIR = Path(__file__).resolve().parent.parent


class ConfigurationError(RuntimeError):
    """Raised when production is missing a secret it cannot safely invent."""


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )


def _validate_secrets(app: Flask) -> None:
    """Fail fast in production rather than running insecurely.

    The previous app logged a warning and carried on with a hard-coded
    development signing key. Anyone reading the public source could forge a
    session cookie for any account. Production now refuses to start.
    """
    is_prod = not (app.debug or app.testing)

    if not app.config.get("SECRET_KEY"):
        if is_prod:
            raise ConfigurationError(
                "SECRET_KEY is not set. Generate one with:\n"
                '  python -c "import secrets; print(secrets.token_hex(32))"'
            )
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        app.logger.warning(
            "SECRET_KEY unset; generated an ephemeral one. Sessions reset on restart."
        )

    if not app.config.get("ENCRYPTION_KEY"):
        if is_prod:
            raise ConfigurationError(
                "ENCRYPTION_KEY is not set and message content must not be stored in "
                "plaintext. Generate one with:\n"
                '  python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )
        # Derived from SECRET_KEY so local data survives restarts within a session.
        app.config["ENCRYPTION_KEY"] = app.config["SECRET_KEY"]
        app.logger.warning("ENCRYPTION_KEY unset; derived one from SECRET_KEY for development.")


def _build_hf_service(app: Flask):
    if not app.config.get("HF_TOKEN"):
        app.logger.warning(
            "HF_TOKEN is not set. Generation is disabled and the app will reply with "
            "safe fallbacks; rule-based crisis detection still runs."
        )
        return NullHuggingFaceService()
    return HuggingFaceService(
        app.config["HF_TOKEN"],
        chat_model=app.config["HF_CHAT_MODEL"],
        suicide_model=app.config["HF_SUICIDE_MODEL"],
        emotion_model=app.config["HF_EMOTION_MODEL"],
        sentiment_model=app.config["HF_SENTIMENT_MODEL"],
        provider=app.config.get("HF_PROVIDER"),
        timeout=app.config["LLM_TIMEOUT_SECONDS"],
        max_tokens=app.config["LLM_MAX_TOKENS"],
        temperature=app.config["LLM_TEMPERATURE"],
    )


def create_app(config_name: str | None = None) -> Flask:
    load_dotenv(BASE_DIR / ".env")

    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "Templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.config.from_object(get_config(config_name))
    _configure_logging(app.config["LOG_LEVEL"])
    _validate_secrets(app)

    init_encryption(app.config["ENCRYPTION_KEY"])

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    if app.config.get("RATELIMIT_ENABLED", True):
        limiter.init_app(app)
        if app.config["RATELIMIT_STORAGE_URI"] == "memory://" and not app.testing:
            app.logger.warning(
                "Rate limiting is using in-process memory. With more than one gunicorn "
                "worker each worker counts separately -- set RATELIMIT_STORAGE_URI to a "
                "redis:// URL in production."
            )

    app.extensions["huggingface"] = _build_hf_service(app)

    from .blueprints import auth, chat, main, wellness

    app.register_blueprint(main.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(chat.bp)
    app.register_blueprint(wellness.bp)

    # JSON endpoints are protected by the SameSite=Lax cookie plus an explicit
    # CSRF header from the client; exempting them from form-token validation
    # keeps fetch() calls simple without weakening the browser-form paths.
    csrf.exempt(chat.api_guest_chat)
    csrf.exempt(chat.api_guest_reset)

    app.before_request(load_current_user)
    app.after_request(apply_security_headers)

    @app.context_processor
    def inject_globals():
        return {"current_user": current_user()}

    _register_error_handlers(app)
    register_cli(app)

    if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite") and not app.testing:
        app.logger.warning(
            "Using SQLite. On Render, Railway and most container platforms the "
            "filesystem is ephemeral -- every deploy will erase all user data. "
            "Set DATABASE_URL to a managed Postgres instance before launch."
        )

    return app


def _wants_json() -> bool:
    return (
        request.path.startswith("/api/")
        or request.is_json
        or request.accept_mimetypes.best == "application/json"
    )


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(400)
    def bad_request(error):
        if _wants_json():
            return jsonify({"error": "bad_request"}), 400
        return render_template("404.html", message="That request wasn't valid."), 400

    @app.errorhandler(401)
    def unauthorised(error):
        if _wants_json():
            return jsonify({"error": "authentication_required"}), 401
        return render_template("404.html", message="Please log in to continue."), 401

    @app.errorhandler(404)
    def not_found(error):
        if _wants_json():
            return jsonify({"error": "not_found"}), 404
        return render_template("404.html"), 404

    @app.errorhandler(429)
    def rate_limited(error):
        message = (
            "You're sending messages faster than I can keep up with. "
            "Give it a moment and try again."
        )
        if _wants_json():
            return jsonify({"error": "rate_limited", "message": message}), 429
        return render_template("404.html", message=message), 429

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        if _wants_json():
            return jsonify({"error": "csrf_failed", "message": "Please refresh the page."}), 400
        return render_template("404.html", message="Your session expired. Please refresh."), 400

    @app.errorhandler(Exception)
    def unhandled(error):
        # Let Werkzeug's own HTTP exceptions through to the handlers above.
        from werkzeug.exceptions import HTTPException

        if isinstance(error, HTTPException):
            return error

        app.logger.exception("Unhandled exception on %s", request.path)
        db.session.rollback()

        if _wants_json():
            # A user mid-conversation should never see a raw error. Give them
            # something human, and the crisis line regardless.
            return (
                jsonify(
                    {
                        "error": "server_error",
                        "message": (
                            "Something went wrong on my end — that's not on you. "
                            "Please try again. If you need someone right now, call 15 "
                            "or 1122, or the Umang helpline on 0311-7786264."
                        ),
                    }
                ),
                500,
            )
        return render_template("500.html"), 500
