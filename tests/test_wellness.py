"""Check-ins, streak arithmetic, insights and export."""

from __future__ import annotations

from datetime import date, timedelta

from app.extensions import db
from app.models import CheckIn, checkin_calendar, compute_streaks


def _seed(user_id, offsets, today=None):
    today = today or date.today()
    for off in offsets:
        db.session.add(CheckIn(user_id=user_id, checkin_date=today - timedelta(days=off)))
    db.session.commit()


def test_no_checkins(app, user):
    s = compute_streaks(user.id)
    assert s == {
        "current_streak": 0,
        "longest_streak": 0,
        "total_checkins": 0,
        "last_checkin": None,
        "checked_in_today": False,
    }


def test_consecutive_days_build_a_streak(app, user):
    _seed(user.id, [2, 1, 0])
    s = compute_streaks(user.id)
    assert s["current_streak"] == 3
    assert s["longest_streak"] == 3
    assert s["checked_in_today"] is True


def test_streak_survives_until_a_full_day_is_missed(app, user):
    """Checked in yesterday but not yet today: the streak is still alive."""
    _seed(user.id, [2, 1])
    assert compute_streaks(user.id)["current_streak"] == 2


def test_streak_resets_after_two_missed_days(app, user):
    _seed(user.id, [5, 4, 3])
    s = compute_streaks(user.id)
    assert s["current_streak"] == 0
    assert s["longest_streak"] == 3  # the record is kept
    assert s["total_checkins"] == 3


def test_longest_streak_is_found_in_history(app, user):
    _seed(user.id, [20, 19, 18, 17, 16, 10, 1, 0])
    s = compute_streaks(user.id)
    assert s["longest_streak"] == 5
    assert s["current_streak"] == 2


def test_checkin_endpoint(auth_client, user):
    res = auth_client.post("/api/checkin", json={"mood_score": 4, "note": "ok day"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["streak"]["current_streak"] == 1
    assert len(data["calendar"]) == 30


def test_double_checkin_is_rejected_by_the_database(auth_client, user):
    """The old code checked in Python and could double-count on a fast retry."""
    assert auth_client.post("/api/checkin", json={}).status_code == 200
    res = auth_client.post("/api/checkin", json={})
    assert res.status_code == 409
    assert res.get_json()["error"] == "already_checked_in"
    assert db.session.query(CheckIn).count() == 1


def test_invalid_mood_score_is_discarded_not_stored(auth_client, user):
    auth_client.post("/api/checkin", json={"mood_score": 99})
    assert db.session.query(CheckIn).one().mood_score is None


def test_checkin_note_is_encrypted(auth_client, user):
    from sqlalchemy import text as sql_text

    auth_client.post("/api/checkin", json={"note": "felt awful about the interview"})
    raw = db.session.execute(sql_text("SELECT note FROM checkins")).scalar()
    assert "interview" not in raw


def test_calendar_covers_thirty_days(app, user):
    _seed(user.id, [0, 3])
    cal = checkin_calendar(user.id)
    assert len(cal) == 30
    assert sum(1 for c in cal if c["checked_in"]) == 2
    assert cal[-1]["date"] == date.today().isoformat()


def test_insights_are_empty_before_any_chat(auth_client, user):
    data = auth_client.get("/api/insights").get_json()
    assert data["total_messages"] == 0
    assert data["observations"]


def test_insights_aggregate_after_chatting(auth_client, hf, user):
    auth_client.post("/api/chat", json={"message": "I feel hopeless and alone"})
    auth_client.post("/api/chat", json={"message": "today was actually alright"})
    data = auth_client.get("/api/insights").get_json()
    assert data["total_messages"] == 2
    assert data["trend"]
    assert "sentiment_counts" in data


def test_insights_never_leak_message_text(auth_client, hf, user):
    auth_client.post("/api/chat", json={"message": "a very private disclosure"})
    body = auth_client.get("/api/insights").get_data(as_text=True)
    assert "very private disclosure" not in body


def test_insights_day_range_is_clamped(auth_client, user):
    assert auth_client.get("/api/insights?days=99999").get_json()["range_days"] == 365
    assert auth_client.get("/api/insights?days=-5").get_json()["range_days"] == 7
    assert auth_client.get("/api/insights?days=abc").get_json()["range_days"] == 30


def test_export_returns_everything_decrypted(auth_client, hf, user):
    auth_client.post("/api/chat", json={"message": "export me please"})
    auth_client.post("/api/checkin", json={"note": "a note"})
    res = auth_client.get("/api/export")
    assert res.status_code == 200
    assert "attachment" in res.headers["Content-Disposition"]
    data = res.get_json()
    assert data["account"]["username"] == "amina"
    assert data["conversations"][0]["messages"][0]["content"] == "export me please"
    assert data["checkins"][0]["note"] == "a note"


def test_export_requires_login(client):
    assert client.get("/api/export").status_code in (302, 401)
