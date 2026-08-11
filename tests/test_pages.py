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


def test_hidden_attribute_is_forced(client):
    """A class that sets `display` beats the UA rule for [hidden].

    That put the check-in form and the "already checked in" banner on screen
    simultaneously, so the override has to stay.
    """
    body = client.get("/").get_data(as_text=True)
    assert "[hidden]{display:none !important}" in body


def test_no_css_selector_opens_a_jinja_comment():
    """`{#id` in a stylesheet is a Jinja comment opener, not CSS.

    It swallows the rest of the template and every page using it 500s. Caught
    the hard way in `@media (...){#thread{...}}` -- and then again in the
    comment that explained the first one.
    """
    from pathlib import Path

    offenders = []
    for path in (Path(__file__).resolve().parent.parent / "Templates").glob("*.html"):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            # A real Jinja comment closes on the same line or is a block we
            # accept; an accidental one is `{#` glued to a selector character.
            for idx in range(len(line) - 1):
                if line[idx:idx + 2] == "{#" and line[idx + 2:idx + 3].isalnum():
                    offenders.append(f"{path.name}:{lineno}")
    assert offenders == [], f"Accidental Jinja comment openers: {offenders}"


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


def test_pwa_manifest_icons_all_exist(client):
    """Every icon the manifest names must resolve.

    All eight 404'd before: the manifest listed them, the directory was empty,
    and "Add to Home Screen" produced a blank tile.
    """
    import json

    manifest = json.loads(client.get("/static/manifest.json").get_data(as_text=True))
    assert manifest["icons"], "manifest declares no icons"
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).status_code == 200, icon["src"]


def test_service_worker_never_caches_personal_routes(client):
    """A cache-first worker on a shared phone can serve one user's chat to the
    next. The exclusion list is what prevents that, so assert it stays."""
    sw = client.get("/static/sw.js").get_data(as_text=True)
    for route in ["/api/", "/chat", "/history", "/insights", "/account"]:
        assert route in sw, f"{route} missing from the service worker exclusion list"
    assert "NEVER_CACHE" in sw


def test_offline_page_carries_crisis_numbers(client):
    """The offline fallback is the last line of help when nothing else loads."""
    body = client.get("/static/offline.html").get_data(as_text=True)
    assert "1122" in body and "tel:1122" in body
    assert "0311-7786264" in body


def test_manifest_is_branded(client):
    import json

    manifest = json.loads(client.get("/static/manifest.json").get_data(as_text=True))
    assert "Dil-e-Azaad" in manifest["name"]
    assert manifest["theme_color"] == "#1F5F4B"
