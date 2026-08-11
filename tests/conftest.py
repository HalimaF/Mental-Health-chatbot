from __future__ import annotations

import pytest

from app import create_app
from app.extensions import db as _db
from app.models import User


class FakeHF:
    """Stands in for the Hugging Face Inference API.

    Deterministic, offline, and configurable per test so we can exercise the
    fusion logic between the rule layer and the classifier layer without ever
    making a network call.
    """

    def __init__(self, *, reply="A calm, supportive reply.", suicide=0.0,
                 emotions=None, sentiment=("neutral", 0.5), fail=False):
        self.configured = True
        self.reply = reply
        self._suicide = suicide
        self._emotions = emotions or []
        self._sentiment = sentiment
        self.fail = fail
        self.calls = []

    def chat(self, messages, **kwargs):
        from app.services.hf_client import GenerationError

        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self.fail:
            raise GenerationError("simulated outage")
        return self.reply

    def suicide_score(self, text):
        return self._suicide

    def emotions(self, text, **kwargs):
        return list(self._emotions)

    def sentiment(self, text):
        return self._sentiment


@pytest.fixture
def app():
    application = create_app("testing")
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def hf(app):
    fake = FakeHF()
    app.extensions["huggingface"] = fake
    return fake


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    return _db


PASSWORD = "Str0ng-Passphrase!42"


@pytest.fixture
def user(app):
    u = User(username="amina", email="amina@example.com")
    u.set_password(PASSWORD)
    _db.session.add(u)
    _db.session.commit()
    return u


@pytest.fixture
def auth_client(client, user):
    client.post("/login", data={"username": "amina", "password": PASSWORD})
    return client
