"""Database models.

Two deliberate departures from the original schema:

1. Message content, mood notes and conversation summaries use ``EncryptedText``.
2. Check-ins are a normalised table instead of a JSON blob in a ``streak_history``
   column. The old design required parsing JSON behind a bare ``except:`` on every
   read and could not be queried, indexed, or corrected without a rewrite.
"""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from .crypto import EncryptedText
from .extensions import db


def utcnow() -> datetime:
    return datetime.now(UTC)


class RiskLevel(enum.IntEnum):
    """Ordered so that fusing two assessments is just ``max()``."""

    NONE = 0
    LOW = 1
    MODERATE = 2
    HIGH = 3
    IMMINENT = 4

    @property
    def label(self) -> str:
        return self.name.lower()

    @classmethod
    def from_value(cls, value) -> RiskLevel:
        if isinstance(value, cls):
            return value
        try:
            return cls(int(value))
        except (TypeError, ValueError):
            return cls.NONE


class User(db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Bumped on password change or "log out everywhere". The signed session
    # cookie carries this value, so old cookies stop authenticating instantly.
    session_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    mood_entries: Mapped[list[MoodEntry]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )
    checkins: Mapped[list[CheckIn]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )
    safety_plan: Mapped[SafetyPlan | None] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)
        # Column defaults are applied at INSERT, so this is still None on a
        # freshly constructed User. Coalesce rather than crash on registration.
        self.session_version = (self.session_version or 0) + 1

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<User {self.username}>"


class Conversation(db.Model):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(200))
    # Rolling summary of turns that have aged out of the verbatim window.
    summary: Mapped[str | None] = mapped_column(EncryptedText)
    summarised_upto: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.id",
    )


class Message(db.Model):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    risk_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_messages_conv_id", "conversation_id", "id"),)

    @property
    def risk(self) -> RiskLevel:
        return RiskLevel.from_value(self.risk_level)


class MoodEntry(db.Model):
    __tablename__ = "mood_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sentiment: Mapped[str] = mapped_column(String(32), nullable=False)
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)
    # Comma-separated top emotions, e.g. "sadness,fear,disappointment".
    emotions: Mapped[str | None] = mapped_column(String(255))
    risk_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    excerpt: Mapped[str | None] = mapped_column(EncryptedText)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    @property
    def emotion_list(self) -> list[str]:
        return [e for e in (self.emotions or "").split(",") if e]


class CheckIn(db.Model):
    __tablename__ = "checkins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    checkin_date: Mapped[date] = mapped_column(Date, nullable=False)
    mood_score: Mapped[int | None] = mapped_column(Integer)  # 1..5, optional
    note: Mapped[str | None] = mapped_column(EncryptedText)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # The database, not application logic, is what guarantees one check-in per
    # day. The original code raced on this and could double-count a streak.
    __table_args__ = (
        UniqueConstraint("user_id", "checkin_date", name="uq_checkin_user_date"),
    )


class SafetyPlan(db.Model):
    """A Stanley-Brown safety plan, in the user's own words.

    Written while calm, read while not. In a crisis, attention narrows and
    recall degrades — the plan is external memory for exactly that moment, which
    is why the app surfaces it rather than waiting to be asked. Every field is
    optional: a partial plan is far better than an empty one, so nothing here
    blocks on completeness.
    """

    __tablename__ = "safety_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )

    # Step 1 — how I know a hard time is starting.
    warning_signs: Mapped[str | None] = mapped_column(EncryptedText)
    # Step 2 — what helps when I'm on my own.
    coping_strategies: Mapped[str | None] = mapped_column(EncryptedText)
    # Step 3 — people and places that take my mind off it.
    distractions: Mapped[str | None] = mapped_column(EncryptedText)
    # Step 4 — people I can actually ask for help.
    support_people: Mapped[str | None] = mapped_column(EncryptedText)
    # Step 5 — professionals and services.
    professionals: Mapped[str | None] = mapped_column(EncryptedText)
    # Step 6 — making my surroundings safer.
    environment: Mapped[str | None] = mapped_column(EncryptedText)
    # Not a Stanley-Brown step, but consistently the one people re-read.
    reasons_for_living: Mapped[str | None] = mapped_column(EncryptedText)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    FIELDS = (
        "warning_signs",
        "coping_strategies",
        "distractions",
        "support_people",
        "professionals",
        "environment",
        "reasons_for_living",
    )

    @property
    def is_empty(self) -> bool:
        return not any((getattr(self, f) or "").strip() for f in self.FIELDS)

    @property
    def filled_count(self) -> int:
        return sum(1 for f in self.FIELDS if (getattr(self, f) or "").strip())

    def to_dict(self) -> dict:
        data = {f: getattr(self, f) or "" for f in self.FIELDS}
        data["filled_count"] = self.filled_count
        data["total_steps"] = len(self.FIELDS)
        data["updated_at"] = self.updated_at.isoformat() if self.updated_at else None
        return data

    def crisis_extract(self) -> dict:
        """The subset worth putting in front of someone mid-crisis.

        Not the whole plan: at high risk a long document competes with "call
        someone now". These are the steps that act as an immediate anchor.
        """
        return {
            key: (getattr(self, key) or "").strip()
            for key in ("coping_strategies", "support_people", "reasons_for_living")
            if (getattr(self, key) or "").strip()
        }


class AuditEvent(db.Model):
    """Security-relevant events. Deliberately holds no message content."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


# ---------------------------------------------------------------------------
# Streak computation
# ---------------------------------------------------------------------------


def compute_streaks(user_id: int, today: date | None = None) -> dict:
    """Derive streak stats from the check-in table.

    Replaces the old ``user_streaks`` row that was mutated in place. Because
    the numbers are derived rather than stored, they cannot drift out of sync
    with reality, and a missed write can no longer silently reset someone's
    progress.
    """
    today = today or date.today()
    rows = (
        db.session.query(CheckIn.checkin_date)
        .filter(CheckIn.user_id == user_id)
        .order_by(CheckIn.checkin_date.asc())
        .all()
    )
    days = [r[0] for r in rows]
    if not days:
        return {
            "current_streak": 0,
            "longest_streak": 0,
            "total_checkins": 0,
            "last_checkin": None,
            "checked_in_today": False,
        }

    longest = run = 1
    for prev, cur in zip(days, days[1:], strict=False):
        run = run + 1 if (cur - prev).days == 1 else 1
        longest = max(longest, run)

    # A streak stays alive if the last check-in was today or yesterday; miss two
    # days and it resets. Being mid-day on day N+1 should not break a streak.
    last = days[-1]
    gap = (today - last).days
    if gap > 1:
        current = 0
    else:
        current = 1
        for prev, cur in zip(reversed(days), reversed(days[:-1]), strict=False):
            if (prev - cur).days == 1:
                current += 1
            else:
                break

    return {
        "current_streak": current,
        "longest_streak": longest,
        "total_checkins": len(days),
        "last_checkin": last.isoformat(),
        "checked_in_today": last == today,
    }


def checkin_calendar(user_id: int, days: int = 30, today: date | None = None) -> list[dict]:
    """Last ``days`` days as calendar cells for the streak page."""
    today = today or date.today()
    start = today - timedelta(days=days - 1)
    rows = (
        db.session.query(CheckIn.checkin_date, CheckIn.mood_score)
        .filter(CheckIn.user_id == user_id, CheckIn.checkin_date >= start)
        .all()
    )
    by_date = {r[0]: r[1] for r in rows}
    out = []
    for offset in range(days):
        d = start + timedelta(days=offset)
        out.append(
            {
                "date": d.isoformat(),
                "day": d.day,
                "month": d.strftime("%b"),
                "checked_in": d in by_date,
                "mood_score": by_date.get(d),
            }
        )
    return out


__all__ = [
    "User",
    "Conversation",
    "Message",
    "MoodEntry",
    "CheckIn",
    "SafetyPlan",
    "AuditEvent",
    "RiskLevel",
    "compute_streaks",
    "checkin_calendar",
    "utcnow",
    "func",
]
