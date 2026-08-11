"""Chat endpoint behaviour, memory, and crisis handling."""

from __future__ import annotations

from app.extensions import db
from app.models import Conversation, Message, MoodEntry

from .conftest import FakeHF


def test_chat_returns_structured_json_not_html(auth_client, hf):
    """The old endpoint returned '<div style=...>' blobs for innerHTML."""
    res = auth_client.post("/api/chat", json={"message": "I had a hard day"})
    assert res.status_code == 200
    data = res.get_json()
    assert "<div" not in data["response"]
    assert data["response"] == hf.reply
    assert "risk" in data and "resources" in data


def test_empty_message_is_rejected(auth_client, hf):
    assert auth_client.post("/api/chat", json={"message": "   "}).status_code == 400


def test_overlong_message_is_rejected(auth_client, hf):
    res = auth_client.post("/api/chat", json={"message": "x" * 5000})
    assert res.status_code == 413


def test_turn_is_persisted_and_encrypted(auth_client, hf, user):
    auth_client.post("/api/chat", json={"message": "I feel anxious about work"})
    messages = db.session.query(Message).order_by(Message.id).all()
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "I feel anxious about work"
    assert db.session.query(MoodEntry).count() == 1


def test_conversation_history_is_sent_to_the_model(auth_client, hf):
    """The original bot sent only the current message and had no memory at all."""
    auth_client.post("/api/chat", json={"message": "My name is Bilal"})
    auth_client.post("/api/chat", json={"message": "What did I just tell you?"})

    sent = hf.calls[-1]["messages"]
    roles = [m["role"] for m in sent]
    assert roles[0] == "system"
    contents = " ".join(m["content"] for m in sent)
    assert "My name is Bilal" in contents
    assert roles.count("assistant") >= 1


def test_system_prompt_changes_with_risk(auth_client, hf):
    auth_client.post("/api/chat", json={"message": "what's a good book"})
    calm = hf.calls[-1]["messages"][0]["content"]

    auth_client.post("/api/chat", json={"message": "I want to kill myself"})
    crisis = hf.calls[-1]["messages"][0]["content"]

    assert calm != crisis
    assert "PRIORITY AND OVERRIDES EVERYTHING" in crisis


def test_crisis_attaches_resources_from_the_server(auth_client, hf):
    res = auth_client.post("/api/chat", json={"message": "I want to end my life"})
    data = res.get_json()
    assert data["risk"]["is_crisis"] is True
    assert len(data["resources"]) > 0
    joined = " ".join(r["contact"] for r in data["resources"])
    assert "1122" in joined


def test_crisis_still_gets_resources_when_the_model_fails(app, auth_client):
    """No path may leave someone in crisis with an error and nothing else."""
    app.extensions["huggingface"] = FakeHF(fail=True)
    res = auth_client.post("/api/chat", json={"message": "I am going to kill myself tonight"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["risk"]["is_crisis"] is True
    assert len(data["resources"]) > 0
    assert "1122" in data["response"] or any("1122" in r["contact"] for r in data["resources"])
    assert data["degraded"] is True


def test_generation_failure_outside_crisis_still_replies(app, auth_client):
    app.extensions["huggingface"] = FakeHF(fail=True)
    res = auth_client.post("/api/chat", json={"message": "hello there"})
    assert res.status_code == 200
    assert res.get_json()["response"].strip()


def test_ordinary_message_gets_no_crisis_resources(auth_client, hf):
    data = auth_client.post("/api/chat", json={"message": "I got a promotion!"}).get_json()
    assert data["resources"] == []
    assert data["risk"]["is_crisis"] is False


def test_history_endpoint_returns_plain_text(auth_client, hf):
    auth_client.post("/api/chat", json={"message": "hello"})
    data = auth_client.get("/api/history").get_json()
    assert len(data["messages"]) == 2
    assert all("<div" not in m["content"] for m in data["messages"])


def test_history_is_scoped_to_the_requesting_user(auth_client, hf, app):
    from app.models import User

    auth_client.post("/api/chat", json={"message": "my private disclosure"})

    other = User(username="other", email="other@example.com")
    other.set_password("Str0ng-Passphrase!42")
    db.session.add(other)
    db.session.commit()

    c = app.test_client()
    c.post("/login", data={"username": "other", "password": "Str0ng-Passphrase!42"})
    data = c.get("/api/history").get_json()
    assert data["messages"] == []


def test_conversation_reset_starts_a_new_thread(auth_client, hf):
    auth_client.post("/api/chat", json={"message": "first thread"})
    auth_client.post("/api/conversation/reset")
    auth_client.post("/api/chat", json={"message": "second thread"})

    assert db.session.query(Conversation).count() == 2
    sent = " ".join(m["content"] for m in hf.calls[-1]["messages"])
    assert "first thread" not in sent


# --- Guest mode ------------------------------------------------------------

def test_guest_chat_persists_nothing(client, app):
    app.extensions["huggingface"] = FakeHF()
    res = client.post("/api/guest/chat", json={"message": "I feel lost"})
    assert res.status_code == 200
    assert db.session.query(Message).count() == 0
    assert db.session.query(MoodEntry).count() == 0
    assert db.session.query(Conversation).count() == 0


def test_guest_conversation_has_memory_within_the_session(client, app):
    hf = FakeHF()
    app.extensions["huggingface"] = hf
    client.post("/api/guest/chat", json={"message": "I am Sara"})
    client.post("/api/guest/chat", json={"message": "do you remember me?"})
    contents = " ".join(m["content"] for m in hf.calls[-1]["messages"])
    assert "I am Sara" in contents


def test_guest_crisis_detection_works_without_an_account(client, app):
    app.extensions["huggingface"] = FakeHF()
    data = client.post("/api/guest/chat", json={"message": "I want to die"}).get_json()
    assert data["risk"]["is_crisis"] is True
    assert len(data["resources"]) > 0


def test_guest_reset_clears_the_session(client, app):
    hf = FakeHF()
    app.extensions["huggingface"] = hf
    client.post("/api/guest/chat", json={"message": "remember this"})
    client.post("/api/guest/reset")
    client.post("/api/guest/chat", json={"message": "new topic"})
    contents = " ".join(m["content"] for m in hf.calls[-1]["messages"])
    assert "remember this" not in contents
