"""Every page must actually render.

The previous chat template had a CSS block pasted into the middle of its
<meta viewport> tag — the kind of breakage nothing catches until a user sees it.
"""

from __future__ import annotations

import pytest

PUBLIC = ["/", "/guest", "/login", "/register", "/resources", "/healthz"]
PRIVATE = ["/chat", "/history", "/streak", "/insights", "/account"]


@pytest.mark.parametrize("path", PUBLIC)
def test_public_pages_render(client, path):
    res = client.get(path)
    assert res.status_code == 200, path


@pytest.mark.parametrize("path", PRIVATE)
def test_private_pages_render(auth_client, path):
    res = auth_client.get(path)
    assert res.status_code == 200, path


def test_no_external_cdn_is_referenced(auth_client):
    """The CSP forbids third-party hosts, so a CDN link would silently break
    the page. The old templates loaded Bootstrap, Bootstrap Icons and the
    Tailwind CDN compiler on every request."""
    for path in ["/", "/chat", "/guest", "/insights", "/streak"]:
        body = auth_client.get(path).get_data(as_text=True)
        for host in ["cdn.jsdelivr.net", "cdn.tailwindcss.com", "unpkg.com", "cdnjs."]:
            assert host not in body, f"{host} referenced on {path}"


def test_pages_carry_a_csrf_token(auth_client):
    assert 'name="csrf-token"' in auth_client.get("/chat").get_data(as_text=True)


def test_forms_include_a_csrf_field():
    """The testing config turns CSRF off, so this needs an app with it on."""
    from app import create_app
    from app.extensions import db

    app = create_app("development")
    app.config.update(WTF_CSRF_ENABLED=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    with app.app_context():
        db.create_all()
        c = app.test_client()
        for path in ["/login", "/register"]:
            assert 'name="csrf_token"' in c.get(path).get_data(as_text=True), path


def test_viewport_meta_is_intact(client):
    """Directly guards the corruption found in the original chat.html."""
    for path in ["/", "/guest", "/login"]:
        body = client.get(path).get_data(as_text=True)
        assert '<meta name="viewport" content="width=device-width, initial-scale=1.0">' in body


def test_crisis_numbers_appear_on_public_entry_points(client):
    for path in ["/", "/resources"]:
        assert "1122" in client.get(path).get_data(as_text=True), path


def test_logged_out_user_sees_guest_and_login_links(client):
    body = client.get("/").get_data(as_text=True)
    assert "/guest" in body and "/login" in body


def test_logged_in_root_redirects_to_chat(auth_client):
    res = auth_client.get("/")
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/chat")
