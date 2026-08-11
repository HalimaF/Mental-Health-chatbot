"""Operational CLI commands.

These are what someone reaches for when a deploy is broken, so they have to
behave correctly in exactly the situations where everything else is failing.
"""

from __future__ import annotations

import pytest

from app.cli import _explain_hf_error
from app.extensions import db
from app.services.hf_client import GenerationError

from .conftest import FakeHF


def _run(app, name, args=None):
    return app.test_cli_runner().invoke(app.cli.get_command(None, name), args or [])


# --- generate-keys ---------------------------------------------------------

def test_generate_keys_emits_usable_values(app):
    from cryptography.fernet import Fernet

    out = _run(app, "generate-keys").output
    secret = next(line for line in out.splitlines() if line.startswith("SECRET_KEY="))
    enc = next(line for line in out.splitlines() if line.startswith("ENCRYPTION_KEY="))

    assert len(secret.split("=", 1)[1]) == 64
    Fernet(enc.split("=", 1)[1].encode())  # raises if not a valid Fernet key


def test_generate_keys_warns_about_backing_up(app):
    assert "back up" in _run(app, "generate-keys").output.lower()


def test_generated_keys_differ_each_run(app):
    assert _run(app, "generate-keys").output != _run(app, "generate-keys").output


# --- check-db --------------------------------------------------------------

def test_check_db_passes_on_a_healthy_database(app):
    result = _run(app, "check-db")
    assert result.exit_code == 0
    assert "connection established" in result.output
    assert "all 6 tables present" in result.output


def test_check_db_fails_when_tables_are_missing(app):
    db.drop_all()
    result = _run(app, "check-db")
    assert result.exit_code == 1
    assert "missing tables" in result.output
    assert "db upgrade" in result.output


def test_check_db_warns_about_sqlite(app):
    """The exact trap that lost the previous deployment's data."""
    result = _run(app, "check-db")
    assert "ephemeral" in result.output


def test_check_db_does_not_print_database_credentials(app):
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        "postgresql+psycopg2://admin:sup3rs3cret@db.example.com/prod"
    )
    output = _run(app, "check-db").output
    assert "sup3rs3cret" not in output
    assert "db.example.com" in output


def test_check_db_reports_row_counts(app, user):
    assert "users:" in _run(app, "check-db").output


# --- check-hf --------------------------------------------------------------

def test_check_hf_fails_clearly_without_a_token(app):
    from app.services.hf_client import NullHuggingFaceService

    app.extensions["huggingface"] = NullHuggingFaceService()
    result = _run(app, "check-hf")
    assert result.exit_code == 1
    assert "HF_TOKEN is not set" in result.output
    assert "huggingface.co/settings/tokens" in result.output


def test_check_hf_reports_generation_failure_without_crashing(app, monkeypatch):
    fake = FakeHF(fail=True)
    fake.token = "hf_fake"
    fake.chat_model = "some/model"
    fake.suicide_model = "s"
    fake.emotion_model = "e"
    fake.sentiment_model = "t"
    app.extensions["huggingface"] = fake

    monkeypatch.setattr(
        "huggingface_hub.HfApi.whoami", lambda self, *a, **k: {"name": "tester"}
    )
    result = _run(app, "check-hf")
    assert result.exit_code == 1
    assert "token valid" in result.output
    assert "Failed: generation" in result.output
    # Explains what still works, so nobody assumes the app is entirely down.
    assert "rule-based crisis detection" in result.output.lower() or \
           "Rule-based crisis detection" in result.output


# --- error explanations ----------------------------------------------------

@pytest.mark.parametrize(
    "message,expected",
    [
        ("401 Client Error: Unauthorized", "token rejected"),
        # The exact string the hub returns for a bad token, captured live.
        ("Invalid user token. If you didn't pass a user token...", "token rejected"),
        ("403 Forbidden: gated repo", "gated"),
        ("404 Client Error: Not Found", "not found"),
        ("503 Model is currently loading", "cold-starting"),
        ("429 Too Many Requests: rate limit", "rate limited"),
        ("Request timed out", "timed out"),
    ],
)
def test_hf_errors_are_translated_into_actions(message, expected):
    assert expected in _explain_hf_error(GenerationError(message))


def test_unknown_hf_error_is_passed_through_truncated():
    out = _explain_hf_error(RuntimeError("x" * 500))
    assert len(out) <= 200


def test_provider_error_suggests_changing_the_model():
    out = _explain_hf_error(RuntimeError("model is not supported by any provider"))
    assert "HF_CHAT_MODEL" in out


# --- bootstrap / reset -----------------------------------------------------

def test_bootstrap_is_safe_to_run_repeatedly(app):
    assert _run(app, "bootstrap").exit_code == 0
    assert _run(app, "bootstrap").exit_code == 0


def test_reset_db_requires_confirmation(app, user):
    from app.models import User

    result = _run(app, "reset-db")  # no --yes, and no input -> aborts
    assert result.exit_code != 0
    assert db.session.query(User).count() == 1


# --- purge -----------------------------------------------------------------

def test_purge_is_a_no_op_when_retention_is_disabled(app):
    app.config["RETENTION_DAYS"] = 0
    assert "disabled" in _run(app, "purge-old-data").output


def test_purge_deletes_content_past_the_retention_window(app, user):
    from datetime import timedelta

    from app.models import Conversation, Message, utcnow

    app.config["RETENTION_DAYS"] = 30
    convo = Conversation(user_id=user.id, title="t")
    db.session.add(convo)
    db.session.commit()

    db.session.add(
        Message(
            conversation_id=convo.id, role="user", content="old",
            created_at=utcnow() - timedelta(days=60),
        )
    )
    db.session.add(Message(conversation_id=convo.id, role="user", content="recent"))
    db.session.commit()

    _run(app, "purge-old-data")
    remaining = db.session.query(Message).all()
    assert [m.content for m in remaining] == ["recent"]
