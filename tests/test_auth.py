"""Registration, login, session handling and account deletion."""

from __future__ import annotations

from app.extensions import db
from app.models import CheckIn, Conversation, Message, User

from .conftest import PASSWORD

GOOD = {
    "username": "newuser",
    "email": "new@example.com",
    "password": "Str0ng-Passphrase!42",
    "confirm": "Str0ng-Passphrase!42",
    "accept": "y",
}


def test_register_then_login(client):
    assert client.post("/register", data=GOOD, follow_redirects=True).status_code == 200
    assert db.session.query(User).filter_by(username="newuser").one()

    res = client.post("/login", data={"username": "newuser", "password": GOOD["password"]})
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/chat")


def test_short_password_is_rejected(client):
    """The original app accepted six characters."""
    bad = dict(GOOD, password="short1!", confirm="short1!")
    res = client.post("/register", data=bad)
    assert res.status_code == 400
    assert db.session.query(User).count() == 0


def test_common_password_is_rejected(client):
    bad = dict(GOOD, password="password123456", confirm="password123456")
    assert client.post("/register", data=bad).status_code == 400
    assert db.session.query(User).count() == 0


def test_password_needs_character_variety(client):
    bad = dict(GOOD, password="alllowercaseletters", confirm="alllowercaseletters")
    assert client.post("/register", data=bad).status_code == 400


def test_terms_must_be_accepted(client):
    bad = dict(GOOD)
    bad.pop("accept")
    assert client.post("/register", data=bad).status_code == 400


def test_duplicate_registration_does_not_reveal_which_field_collided(client, user):
    dup = dict(GOOD, username="amina", email="different@example.com")
    res = client.post("/register", data=dup)
    body = res.get_data(as_text=True)
    assert res.status_code == 400
    assert "not available" in body
    assert "username already" not in body.lower()


def test_username_lookup_is_case_insensitive(client, user):
    res = client.post("/login", data={"username": "AMINA", "password": PASSWORD})
    assert res.status_code == 302


def test_wrong_password_is_rejected(client, user):
    res = client.post("/login", data={"username": "amina", "password": "wrong-password-1!"})
    assert res.status_code == 401


def test_protected_pages_require_login(client):
    for path in ["/chat", "/history", "/streak", "/insights", "/account"]:
        res = client.get(path)
        assert res.status_code == 302, path
        assert "/login" in res.headers["Location"]


def test_protected_api_returns_401_not_a_redirect(client):
    res = client.post("/api/chat", json={"message": "hi"})
    assert res.status_code == 401
    assert res.get_json()["error"] == "authentication_required"


def test_logout_requires_post(auth_client):
    """A GET logout could be fired by any <img src="/logout"> on the page."""
    assert auth_client.get("/logout").status_code == 405
    assert auth_client.post("/logout").status_code == 302
    assert auth_client.get("/chat").status_code == 302


def test_password_change_invalidates_existing_sessions(auth_client, user):
    assert auth_client.get("/chat").status_code == 200
    user.set_password("An0ther-Passphrase!99")
    db.session.commit()
    # The cookie still carries the old session_version, so it stops authenticating.
    assert auth_client.get("/chat").status_code == 302


def test_open_redirect_is_blocked(client, user):
    res = client.post(
        "/login?next=https://evil.example.com/steal",
        data={"username": "amina", "password": PASSWORD},
    )
    assert "evil.example.com" not in res.headers["Location"]


def test_login_next_allows_local_paths(client, user):
    res = client.post(
        "/login?next=/streak", data={"username": "amina", "password": PASSWORD}
    )
    assert res.headers["Location"].endswith("/streak")


def test_account_deletion_removes_all_user_data(auth_client, user, hf):
    auth_client.post("/api/chat", json={"message": "I feel low today"})
    auth_client.post("/api/checkin", json={"mood_score": 3})
    assert db.session.query(Message).count() > 0

    res = auth_client.post(
        "/account/delete", data={"password": PASSWORD, "confirm_text": "DELETE"}
    )
    assert res.status_code == 302
    assert db.session.query(User).count() == 0
    assert db.session.query(Conversation).count() == 0
    assert db.session.query(Message).count() == 0
    assert db.session.query(CheckIn).count() == 0


def test_deletion_requires_the_correct_password(auth_client, user):
    auth_client.post(
        "/account/delete", data={"password": "wrong-password-1!", "confirm_text": "DELETE"}
    )
    assert db.session.query(User).count() == 1
