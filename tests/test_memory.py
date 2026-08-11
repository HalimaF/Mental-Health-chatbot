"""Conversation memory and rolling summarisation."""

from __future__ import annotations

from app.extensions import db
from app.models import Conversation, Message
from app.services import memory as memory_service
from app.services.hf_client import GenerationError

from .conftest import FakeHF


def _conversation(user, n=0):
    convo = Conversation(user_id=user.id, title="t")
    db.session.add(convo)
    db.session.commit()
    for i in range(n):
        db.session.add(
            Message(
                conversation_id=convo.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"message {i}",
            )
        )
    db.session.commit()
    return convo


def test_prompt_window_is_bounded(app, user):
    convo = _conversation(user, 40)
    msgs = memory_service.build_prompt_messages(convo, "SYSTEM", "newest", window=8)
    # system + 8 history + the new user turn
    assert len(msgs) == 10
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["content"] == "newest"


def test_window_keeps_the_most_recent_turns(app, user):
    convo = _conversation(user, 20)
    msgs = memory_service.build_prompt_messages(convo, "SYSTEM", "now", window=4)
    history = [m["content"] for m in msgs[1:-1]]
    assert history == ["message 16", "message 17", "message 18", "message 19"]


def test_roles_alternate_correctly(app, user):
    convo = _conversation(user, 4)
    msgs = memory_service.build_prompt_messages(convo, "SYSTEM", "now", window=4)
    assert [m["role"] for m in msgs] == [
        "system", "user", "assistant", "user", "assistant", "user",
    ]


def test_summary_is_created_once_the_trigger_is_passed(app, user):
    convo = _conversation(user, 30)
    hf = FakeHF(reply="They are stressed about final exams and their father's illness.")
    memory_service.maybe_summarise(convo, hf, trigger=20, window=8)

    db.session.refresh(convo)
    assert convo.summary == "They are stressed about final exams and their father's illness."
    assert convo.summarised_upto > 0


def test_no_summary_below_the_trigger(app, user):
    convo = _conversation(user, 5)
    hf = FakeHF()
    memory_service.maybe_summarise(convo, hf, trigger=20, window=8)
    db.session.refresh(convo)
    assert convo.summary is None
    assert hf.calls == []


def test_summarisation_is_incremental(app, user):
    convo = _conversation(user, 30)
    hf = FakeHF(reply="first summary")
    memory_service.maybe_summarise(convo, hf, trigger=20, window=8)
    db.session.refresh(convo)
    first_mark = convo.summarised_upto

    # Nothing new has aged out yet, so it must not re-summarise.
    memory_service.maybe_summarise(convo, hf, trigger=20, window=8)
    db.session.refresh(convo)
    assert convo.summarised_upto == first_mark
    assert len(hf.calls) == 1


def test_summary_failure_leaves_the_conversation_usable(app, user):
    convo = _conversation(user, 30)
    hf = FakeHF(fail=True)
    memory_service.maybe_summarise(convo, hf, trigger=20, window=8)  # must not raise
    db.session.refresh(convo)
    assert convo.summary is None


def test_summary_is_injected_into_the_system_prompt(auth_client, hf, user):
    convo = memory_service.get_or_create_conversation(user.id)
    convo.summary = "They mentioned their sister Ayesha is unwell."
    db.session.commit()

    auth_client.post("/api/chat", json={"message": "any update advice?"})
    system = hf.calls[-1]["messages"][0]["content"]
    assert "sister Ayesha" in system


def test_summary_is_encrypted_at_rest(app, user):
    from sqlalchemy import text as sql_text

    convo = _conversation(user)
    convo.summary = "They disclosed self-harm last week."
    db.session.commit()
    raw = db.session.execute(sql_text("SELECT summary FROM conversations")).scalar()
    assert "self-harm" not in raw


def test_guest_history_is_windowed(app):
    history = [{"role": "user", "content": f"m{i}"} for i in range(30)]
    msgs = memory_service.build_guest_messages("SYS", history, "now", window=6)
    assert len(msgs) == 8
    assert msgs[1]["content"] == "m24"


def test_guest_history_skips_blank_turns(app):
    history = [{"role": "user", "content": "  "}, {"role": "assistant", "content": "hi"}]
    msgs = memory_service.build_guest_messages("SYS", history, "now", window=6)
    assert [m["content"] for m in msgs] == ["SYS", "hi", "now"]


def test_generation_error_is_typed():
    hf = FakeHF(fail=True)
    try:
        hf.chat([])
    except GenerationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected GenerationError")
