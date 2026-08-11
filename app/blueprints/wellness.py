"""Check-ins, streaks, mood insights, and data export."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy.exc import IntegrityError

from ..extensions import db, limiter
from ..models import (
    CheckIn,
    Conversation,
    Message,
    MoodEntry,
    RiskLevel,
    SafetyPlan,
    checkin_calendar,
    compute_streaks,
)
from ..security import current_user, login_required

bp = Blueprint("wellness", __name__)

ENCOURAGEMENTS = [
    "Showing up again today counts. That's {n} days.",
    "{n} days of checking in with yourself. That's not nothing.",
    "Day {n}. Consistency like this is how change actually happens.",
    "{n} days running. However today felt, you turned up for it.",
]


@bp.get("/streak")
@login_required
def streak_page():
    user = current_user()
    return render_template(
        "streak.html",
        streak=compute_streaks(user.id),
        calendar=checkin_calendar(user.id),
        today=date.today().isoformat(),
    )


@bp.get("/api/streak")
@login_required
def api_streak():
    user = current_user()
    return jsonify(
        {"streak": compute_streaks(user.id), "calendar": checkin_calendar(user.id)}
    )


@bp.post("/api/checkin")
@login_required
@limiter.limit("20 per hour")
def api_checkin():
    user = current_user()
    payload = request.get_json(silent=True) or {}

    mood_score = payload.get("mood_score")
    try:
        mood_score = int(mood_score) if mood_score is not None else None
        if mood_score is not None and not 1 <= mood_score <= 5:
            mood_score = None
    except (TypeError, ValueError):
        mood_score = None

    note = payload.get("note")
    note = note.strip()[:1000] if isinstance(note, str) and note.strip() else None

    today = date.today()
    entry = CheckIn(user_id=user.id, checkin_date=today, mood_score=mood_score, note=note)
    db.session.add(entry)
    try:
        db.session.commit()
    except IntegrityError:
        # The unique constraint is what enforces one check-in per day. Two
        # simultaneous taps used to both succeed and double-count the streak.
        db.session.rollback()
        streak = compute_streaks(user.id)
        return (
            jsonify(
                {
                    "error": "already_checked_in",
                    "message": "You've already checked in today. See you tomorrow.",
                    "streak": streak,
                }
            ),
            409,
        )

    streak = compute_streaks(user.id, today)
    n = streak["current_streak"]
    return jsonify(
        {
            "ok": True,
            "message": ENCOURAGEMENTS[n % len(ENCOURAGEMENTS)].format(n=n),
            "streak": streak,
            "calendar": checkin_calendar(user.id),
        }
    )


@bp.get("/insights")
@login_required
def insights_page():
    return render_template("sentiment_insights.html")


@bp.get("/api/insights")
@login_required
def api_insights():
    """Aggregated mood data for the insights dashboard.

    Returns counts and trends only -- never message text. The excerpt column is
    encrypted and deliberately not exposed through this endpoint.
    """
    user = current_user()
    try:
        days = min(max(int(request.args.get("days", 30)), 7), 365)
    except (TypeError, ValueError):
        days = 30

    since = date.today() - timedelta(days=days)
    entries = (
        db.session.query(MoodEntry)
        .filter(MoodEntry.user_id == user.id, MoodEntry.created_at >= since)
        .order_by(MoodEntry.created_at.asc())
        .all()
    )

    sentiment_counts = Counter(e.sentiment for e in entries)
    emotion_counts: Counter = Counter()
    for e in entries:
        emotion_counts.update(e.emotion_list)

    by_day: dict[str, list[float]] = {}
    for e in entries:
        key = e.created_at.date().isoformat()
        polarity = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}.get(e.sentiment, 0.0)
        by_day.setdefault(key, []).append(polarity)

    trend = [
        {"date": k, "score": round(sum(v) / len(v), 3), "messages": len(v)}
        for k, v in sorted(by_day.items())
    ]

    checkins = compute_streaks(user.id)
    elevated = sum(1 for e in entries if e.risk_level >= int(RiskLevel.MODERATE))

    return jsonify(
        {
            "range_days": days,
            "total_messages": len(entries),
            "sentiment_counts": dict(sentiment_counts),
            "top_emotions": emotion_counts.most_common(8),
            "trend": trend,
            "streak": checkins,
            "elevated_risk_messages": elevated,
            "observations": _observations(entries, trend, checkins, elevated),
        }
    )


def _observations(entries, trend, streak, elevated) -> list[str]:
    """Plain-language read of the data.

    Framed as observations, never as diagnosis -- "you've logged more low days
    this week", not "you are depressed".
    """
    out: list[str] = []
    if not entries:
        return ["Once you've chatted a few times, patterns will start showing up here."]

    negative = sum(1 for e in entries if e.sentiment == "negative")
    ratio = negative / len(entries)
    if ratio > 0.6:
        out.append(
            "Most of what you've written recently has carried a heavy tone. That's worth "
            "taking seriously, and worth mentioning to someone qualified."
        )
    elif ratio < 0.25:
        out.append("Your recent messages have leaned steadier than not.")

    if len(trend) >= 6:
        first = sum(d["score"] for d in trend[: len(trend) // 2])
        second = sum(d["score"] for d in trend[len(trend) // 2 :])
        if second > first + 0.5:
            out.append("The overall direction over this period has been upward.")
        elif first > second + 0.5:
            out.append(
                "Things have trended downward over this period. A dip is not a failure, "
                "but it's a signal worth paying attention to."
            )

    if streak["current_streak"] >= 7:
        out.append(f"You've checked in {streak['current_streak']} days running.")

    if elevated:
        out.append(
            f"{elevated} message{'s' if elevated != 1 else ''} in this period flagged as "
            "higher distress. Support lines are always on the resources page."
        )
    return out


@bp.get("/api/export")
@login_required
@limiter.limit("5 per hour")
def api_export():
    """Everything held about this user, decrypted, as JSON.

    The counterpart to account deletion: people can see exactly what is stored
    before deciding whether to keep it.
    """
    user = current_user()
    conversations = (
        db.session.query(Conversation).filter(Conversation.user_id == user.id).all()
    )
    payload = {
        "account": {
            "username": user.username,
            "email": user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login": user.last_login.isoformat() if user.last_login else None,
        },
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "summary": c.summary,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "messages": [
                    {
                        "role": m.role,
                        "content": m.content,
                        "risk": m.risk.label,
                        "timestamp": m.created_at.isoformat() if m.created_at else None,
                    }
                    for m in db.session.query(Message)
                    .filter(Message.conversation_id == c.id)
                    .order_by(Message.id.asc())
                    .all()
                ],
            }
            for c in conversations
        ],
        "mood_entries": [
            {
                "sentiment": e.sentiment,
                "emotions": e.emotion_list,
                "risk": RiskLevel.from_value(e.risk_level).label,
                "excerpt": e.excerpt,
                "timestamp": e.created_at.isoformat() if e.created_at else None,
            }
            for e in db.session.query(MoodEntry)
            .filter(MoodEntry.user_id == user.id)
            .order_by(MoodEntry.created_at.asc())
            .all()
        ],
        "safety_plan": (
            db.session.query(SafetyPlan).filter(SafetyPlan.user_id == user.id).first().to_dict()
            if db.session.query(SafetyPlan).filter(SafetyPlan.user_id == user.id).first()
            else None
        ),
        "checkins": [
            {
                "date": c.checkin_date.isoformat(),
                "mood_score": c.mood_score,
                "note": c.note,
            }
            for c in db.session.query(CheckIn)
            .filter(CheckIn.user_id == user.id)
            .order_by(CheckIn.checkin_date.asc())
            .all()
        ],
    }
    response = jsonify(payload)
    response.headers["Content-Disposition"] = "attachment; filename=dil-e-azaad-export.json"
    return response
