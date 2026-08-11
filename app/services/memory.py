"""Conversation memory.

The original bot sent exactly one message to the model -- the current one --
with no history at all. It could not remember your name from the previous
sentence, let alone that you told it yesterday your father was ill. That is
the difference between a chatbot and something that can actually help.

Strategy: keep the most recent N turns verbatim, and roll everything older
into a compact summary stored on the conversation row. The prompt stays a
bounded size no matter how long someone talks, while the thread survives.
"""

from __future__ import annotations

import logging

from ..extensions import db
from ..models import Conversation, Message
from .hf_client import GenerationError
from .prompts import SUMMARISER_PROMPT

logger = logging.getLogger(__name__)


def recent_messages(conversation: Conversation, window: int) -> list[Message]:
    """The last ``window`` messages, oldest first."""
    rows = (
        db.session.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.id.desc())
        .limit(window)
        .all()
    )
    return list(reversed(rows))


def build_prompt_messages(
    conversation: Conversation | None,
    system_prompt: str,
    user_input: str,
    window: int,
) -> list[dict]:
    """Assemble the OpenAI-style message array sent to the chat model."""
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    if conversation is not None:
        for msg in recent_messages(conversation, window):
            role = "assistant" if msg.role == "assistant" else "user"
            messages.append({"role": role, "content": msg.content})

    messages.append({"role": "user", "content": user_input})
    return messages


def build_guest_messages(
    system_prompt: str, history: list[dict], user_input: str, window: int
) -> list[dict]:
    """Same as above, but sourced from an in-session list rather than the
    database. Guest conversations are never persisted."""
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for turn in history[-window:]:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        content = (turn.get("content") or "").strip()
        if content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_input})
    return messages


def maybe_summarise(
    conversation: Conversation,
    hf,
    *,
    trigger: int,
    window: int,
) -> None:
    """Fold messages that have aged out of the verbatim window into the summary.

    Runs after a reply has already been sent, so a summarisation failure costs
    the user nothing. Silent on error by design -- degraded memory is a far
    better outcome than a failed request.
    """
    total = (
        db.session.query(db.func.count(Message.id))
        .filter(Message.conversation_id == conversation.id)
        .scalar()
        or 0
    )
    if total < trigger:
        return

    # Everything older than the verbatim window that has not yet been folded in.
    cutoff_ids = [
        m.id
        for m in db.session.query(Message.id)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.id.desc())
        .limit(window)
        .all()
    ]
    oldest_kept = min(cutoff_ids) if cutoff_ids else 0

    stale = (
        db.session.query(Message)
        .filter(
            Message.conversation_id == conversation.id,
            Message.id < oldest_kept,
            Message.id > conversation.summarised_upto,
        )
        .order_by(Message.id.asc())
        .all()
    )
    if not stale:
        return

    transcript = "\n".join(
        f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}" for m in stale
    )
    existing = conversation.summary or "(no notes yet)"

    try:
        summary = hf.chat(
            [
                {"role": "system", "content": SUMMARISER_PROMPT},
                {
                    "role": "user",
                    "content": f"EXISTING NOTES:\n{existing}\n\nNEW EXCHANGES:\n{transcript}",
                },
            ],
            max_tokens=260,
            temperature=0.3,
        )
    except GenerationError as exc:
        logger.warning("Could not summarise conversation %s: %s", conversation.id, exc)
        return

    conversation.summary = summary
    conversation.summarised_upto = stale[-1].id
    db.session.commit()


def get_or_create_conversation(user_id: int) -> Conversation:
    """Return the user's active conversation, creating one if needed."""
    # Ordered by id, not updated_at. Primary keys are monotonic and unique;
    # timestamps are neither once two rows land in the same tick, which made
    # "start a new conversation" silently keep serving the old one.
    conversation = (
        db.session.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .order_by(Conversation.id.desc())
        .first()
    )
    if conversation is None:
        conversation = Conversation(user_id=user_id, title="Conversation")
        db.session.add(conversation)
        db.session.commit()
    return conversation
