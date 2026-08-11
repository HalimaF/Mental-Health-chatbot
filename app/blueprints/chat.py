"""Chat routes.

The API now returns structured JSON -- plain text plus a risk object plus a
resource list. The old endpoint returned pre-built ``<div style="...">`` blobs
that the browser dropped straight into ``innerHTML``, which welded presentation
into the backend and made stored XSS trivial. Rendering belongs to the client.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template, request, session

from ..extensions import db, limiter
from ..models import Conversation, Message
from ..security import current_user, login_required
from ..services import counselor
from ..services.safety import CRISIS_RESOURCES

bp = Blueprint("chat", __name__)

MAX_MESSAGE_LENGTH = 4000
GUEST_HISTORY_KEY = "guest_history"
GUEST_HISTORY_LIMIT = 24


@bp.get("/chat")
@login_required
def chat_page():
    return render_template("chat.html")


@bp.get("/guest")
def guest_page():
    return render_template("guest_chat.html")


def _extract_message() -> str | None:
    payload = request.get_json(silent=True) or {}
    raw = payload.get("message") or payload.get("user_input") or ""
    if not isinstance(raw, str):
        return None
    return raw.strip()


@bp.post("/api/chat")
@login_required
@limiter.limit("30 per minute; 400 per day")
def api_chat():
    message = _extract_message()
    if not message:
        return jsonify({"error": "empty_message", "message": "Please type something first."}), 400
    if len(message) > MAX_MESSAGE_LENGTH:
        return (
            jsonify(
                {
                    "error": "message_too_long",
                    "message": f"Please keep messages under {MAX_MESSAGE_LENGTH} characters.",
                }
            ),
            413,
        )

    reply = counselor.respond(
        message,
        hf=current_app.extensions["huggingface"],
        config=current_app.config,
        user=current_user(),
    )
    return jsonify(reply.to_dict())


@bp.post("/api/guest/chat")
@limiter.limit("15 per minute; 120 per day")
def api_guest_chat():
    """Anonymous chat. Nothing touches the database; history lives only in the
    signed session cookie and disappears when the browser session ends."""
    message = _extract_message()
    if not message:
        return jsonify({"error": "empty_message", "message": "Please type something first."}), 400
    if len(message) > MAX_MESSAGE_LENGTH:
        return jsonify({"error": "message_too_long"}), 413

    history = session.get(GUEST_HISTORY_KEY, [])
    reply = counselor.respond(
        message,
        hf=current_app.extensions["huggingface"],
        config=current_app.config,
        user=None,
        guest_history=history,
    )

    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply.text},
    ]
    # Cookies cap out around 4 KB; keeping the tail bounded avoids silently
    # blowing past that and losing the session entirely.
    session[GUEST_HISTORY_KEY] = history[-GUEST_HISTORY_LIMIT:]
    return jsonify(reply.to_dict())


@bp.post("/api/guest/reset")
def api_guest_reset():
    session.pop(GUEST_HISTORY_KEY, None)
    return jsonify({"ok": True})


@bp.get("/api/history")
@login_required
def api_history():
    user = current_user()
    try:
        limit = min(int(request.args.get("limit", 100)), 500)
    except (TypeError, ValueError):
        limit = 100

    rows = (
        db.session.query(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(Conversation.user_id == user.id)
        .order_by(Message.id.desc())
        .limit(limit)
        .all()
    )
    messages = [
        {
            "role": m.role,
            "content": m.content,
            "risk": m.risk.label,
            "timestamp": m.created_at.isoformat() if m.created_at else None,
        }
        for m in reversed(rows)
    ]
    return jsonify({"messages": messages})


@bp.get("/history")
@login_required
def history_page():
    user = current_user()
    rows = (
        db.session.query(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .filter(Conversation.user_id == user.id)
        .order_by(Message.id.desc())
        .limit(200)
        .all()
    )
    return render_template("chat_history.html", messages=list(reversed(rows)))


@bp.post("/api/conversation/reset")
@login_required
@limiter.limit("10 per hour")
def reset_conversation():
    """Start a fresh conversation without deleting the old one."""
    user = current_user()
    conversation = Conversation(user_id=user.id, title="Conversation")
    db.session.add(conversation)
    db.session.commit()
    return jsonify({"ok": True, "conversation_id": conversation.id})


@bp.get("/api/resources")
def api_resources():
    return jsonify({"resources": CRISIS_RESOURCES})
