"""Safety plan: storage, encryption, autosave semantics and crisis surfacing."""

from __future__ import annotations

from sqlalchemy import text as sql_text

from app.extensions import db
from app.models import SafetyPlan

from .conftest import FakeHF


def _plan(user_id):
    return db.session.query(SafetyPlan).filter(SafetyPlan.user_id == user_id).first()


def test_page_renders_and_creates_an_empty_plan(auth_client, user):
    assert auth_client.get("/safety-plan").status_code == 200
    assert _plan(user.id) is not None
    assert _plan(user.id).is_empty


def test_requires_login(client):
    assert client.get("/safety-plan").status_code == 302
    assert client.post("/api/safety-plan", json={"warning_signs": "x"}).status_code == 401


def test_save_and_read_back(auth_client, user):
    res = auth_client.post("/api/safety-plan", json={
        "warning_signs": "I stop replying to messages",
        "reasons_for_living": "My sister's wedding",
    })
    assert res.status_code == 200
    data = res.get_json()
    assert set(data["updated"]) == {"warning_signs", "reasons_for_living"}
    assert data["plan"]["filled_count"] == 2

    got = auth_client.get("/api/safety-plan").get_json()
    assert got["warning_signs"] == "I stop replying to messages"
    assert got["reasons_for_living"] == "My sister's wedding"


def test_partial_save_does_not_blank_other_fields(auth_client, user):
    """Autosave sends one field at a time; it must never wipe the rest."""
    auth_client.post("/api/safety-plan", json={"warning_signs": "A", "support_people": "B"})
    auth_client.post("/api/safety-plan", json={"coping_strategies": "C"})

    got = auth_client.get("/api/safety-plan").get_json()
    assert got["warning_signs"] == "A"
    assert got["support_people"] == "B"
    assert got["coping_strategies"] == "C"


def test_empty_string_clears_a_single_field(auth_client, user):
    auth_client.post("/api/safety-plan", json={"warning_signs": "A", "support_people": "B"})
    auth_client.post("/api/safety-plan", json={"warning_signs": ""})
    got = auth_client.get("/api/safety-plan").get_json()
    assert got["warning_signs"] == ""
    assert got["support_people"] == "B"


def test_unknown_fields_are_ignored(auth_client, user):
    res = auth_client.post("/api/safety-plan", json={"is_admin": True, "warning_signs": "A"})
    assert res.status_code == 200
    assert res.get_json()["updated"] == ["warning_signs"]


def test_empty_body_is_rejected(auth_client, user):
    assert auth_client.post("/api/safety-plan", json={}).status_code == 400


def test_non_string_value_is_rejected(auth_client, user):
    assert auth_client.post("/api/safety-plan", json={"warning_signs": 42}).status_code == 400


def test_long_values_are_truncated(auth_client, user):
    auth_client.post("/api/safety-plan", json={"warning_signs": "x" * 5000})
    assert len(_plan(user.id).warning_signs) == 2000


def test_plan_is_encrypted_at_rest(auth_client, user):
    auth_client.post("/api/safety-plan", json={"reasons_for_living": "my sister Ayesha"})
    raw = db.session.execute(sql_text("SELECT reasons_for_living FROM safety_plans")).scalar()
    assert "Ayesha" not in raw
    assert raw.startswith("enc:v1:")


def test_clear_wipes_everything(auth_client, user):
    auth_client.post("/api/safety-plan", json={"warning_signs": "A", "support_people": "B"})
    res = auth_client.post("/api/safety-plan/clear")
    assert res.status_code == 200
    assert res.get_json()["plan"]["filled_count"] == 0
    assert _plan(user.id).is_empty


def test_plan_is_scoped_to_its_owner(auth_client, app, user):
    from app.models import User

    auth_client.post("/api/safety-plan", json={"reasons_for_living": "private to amina"})

    other = User(username="other", email="other@example.com")
    other.set_password("Str0ng-Passphrase!42")
    db.session.add(other)
    db.session.commit()

    c = app.test_client()
    c.post("/login", data={"username": "other", "password": "Str0ng-Passphrase!42"})
    assert c.get("/api/safety-plan").get_json()["reasons_for_living"] == ""


def test_plan_is_deleted_with_the_account(auth_client, user):
    from .conftest import PASSWORD

    auth_client.post("/api/safety-plan", json={"warning_signs": "A"})
    assert db.session.query(SafetyPlan).count() == 1
    auth_client.post("/account/delete", data={"password": PASSWORD, "confirm_text": "DELETE"})
    assert db.session.query(SafetyPlan).count() == 0


def test_plan_is_included_in_data_export(auth_client, user):
    auth_client.post("/api/safety-plan", json={"reasons_for_living": "the cat"})
    body = auth_client.get("/api/export").get_data(as_text=True)
    assert "the cat" in body


# --- crisis surfacing ------------------------------------------------------

def test_crisis_surfaces_the_users_own_plan(auth_client, hf, user):
    auth_client.post("/api/safety-plan", json={
        "coping_strategies": "Cold water on my face",
        "support_people": "Ayesha 03xx",
        "reasons_for_living": "My sister's wedding",
        "warning_signs": "not shown in crisis",
    })
    data = auth_client.post("/api/chat", json={"message": "I want to kill myself"}).get_json()

    assert data["risk"]["is_crisis"] is True
    plan = data["safety_plan"]
    assert plan["coping_strategies"] == "Cold water on my face"
    assert plan["reasons_for_living"] == "My sister's wedding"
    # Only the anchoring subset: a full document competes with "call someone".
    assert "warning_signs" not in plan


def test_ordinary_message_does_not_surface_the_plan(auth_client, hf, user):
    auth_client.post("/api/safety-plan", json={"reasons_for_living": "the cat"})
    data = auth_client.post("/api/chat", json={"message": "I got a promotion!"}).get_json()
    assert data["safety_plan"] is None
    assert data["offer_safety_plan"] is False


def test_crisis_without_a_plan_offers_one(auth_client, hf, user):
    data = auth_client.post("/api/chat", json={"message": "I want to die"}).get_json()
    assert data["safety_plan"] is None
    assert data["offer_safety_plan"] is True


def test_imminent_risk_does_not_ask_someone_to_fill_in_a_form(auth_client, hf, user):
    """At imminent risk the only instruction should be to reach a human."""
    data = auth_client.post(
        "/api/chat", json={"message": "I'm going to kill myself tonight, I have the pills"}
    ).get_json()
    assert data["risk"]["level"] == "imminent"
    assert data["offer_safety_plan"] is False


def test_empty_plan_is_treated_as_no_plan(auth_client, hf, user):
    auth_client.get("/safety-plan")  # creates an empty row
    data = auth_client.post("/api/chat", json={"message": "I want to die"}).get_json()
    assert data["safety_plan"] is None
    assert data["offer_safety_plan"] is True


def test_guests_never_get_a_plan(client, app):
    app.extensions["huggingface"] = FakeHF()
    data = client.post("/api/guest/chat", json={"message": "I want to die"}).get_json()
    assert data["safety_plan"] is None
    assert data["offer_safety_plan"] is False


def test_crisis_still_attaches_resources_alongside_the_plan(auth_client, hf, user):
    auth_client.post("/api/safety-plan", json={"coping_strategies": "breathe"})
    data = auth_client.post("/api/chat", json={"message": "I want to die"}).get_json()
    assert data["safety_plan"]
    assert len(data["resources"]) > 0
