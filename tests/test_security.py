"""Security posture: headers, XSS, CSRF, secret handling, error leakage."""

from __future__ import annotations

import pytest

from app import ConfigurationError, create_app
from app.config import ProductionConfig


def test_security_headers_are_present(client):
    res = client.get("/")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in res.headers
    assert "Referrer-Policy" in res.headers


def test_csp_blocks_external_scripts_and_framing(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp


def test_private_pages_are_not_cacheable(auth_client):
    assert "no-store" in auth_client.get("/chat").headers.get("Cache-Control", "")


def test_stored_script_is_escaped_in_history(auth_client, hf):
    """chat_history.html used `| safe`, which made this payload executable."""
    payload = "<script>alert('xss')</script>"
    auth_client.post("/api/chat", json={"message": payload})
    body = auth_client.get("/history").get_data(as_text=True)
    assert "<script>alert('xss')</script>" not in body
    assert "&lt;script&gt;" in body


def test_model_output_is_never_returned_as_html(auth_client, app):
    from .conftest import FakeHF

    app.extensions["huggingface"] = FakeHF(reply="<img src=x onerror=alert(1)>")
    data = auth_client.post("/api/chat", json={"message": "hello"}).get_json()
    # Returned verbatim as text; the client sets it via textContent, never innerHTML.
    assert data["response"] == "<img src=x onerror=alert(1)>"
    assert data["response"].startswith("<img")


def test_csrf_is_enforced_on_forms():
    """The testing config disables CSRF, so assert it against a real config."""
    app = create_app("development")
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with app.app_context():
        from app.extensions import db

        db.create_all()
        client = app.test_client()
        res = client.post(
            "/register",
            data={"username": "x", "email": "x@y.com", "password": "aA1!aA1!aA1!",
                  "confirm": "aA1!aA1!aA1!", "accept": "y"},
        )
        assert res.status_code == 400


def test_production_refuses_to_boot_without_a_secret_key(monkeypatch):
    """The old app fell back to a hard-coded key published in the repo, which
    let anyone forge a session cookie for any account."""
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", None, raising=False)
    monkeypatch.setattr(ProductionConfig, "ENCRYPTION_KEY", "x" * 32, raising=False)
    with pytest.raises(ConfigurationError, match="SECRET_KEY"):
        create_app("production")


def test_production_refuses_to_boot_without_an_encryption_key(monkeypatch):
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "a" * 64, raising=False)
    monkeypatch.setattr(ProductionConfig, "ENCRYPTION_KEY", None, raising=False)
    with pytest.raises(ConfigurationError, match="ENCRYPTION_KEY"):
        create_app("production")


def test_no_api_key_is_hard_coded_anywhere_in_the_source():
    """Regression guard for the live Gemini key that shipped in app.py."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    patterns = [
        re.compile(r"AIzaSy[0-9A-Za-z_\-]{20,}"),   # Google API keys
        re.compile(r"hf_[0-9A-Za-z]{30,}"),          # Hugging Face tokens
        re.compile(r"sk-[0-9A-Za-z]{30,}"),          # OpenAI-style keys
    ]
    offenders = []
    for path in list(root.rglob("*.py")) + list(root.rglob("Templates/*.html")):
        if ".git" in path.parts or "site-packages" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in patterns:
            if pattern.search(text):
                offenders.append(str(path))
    assert offenders == []


def test_unhandled_errors_do_not_leak_internals(app, auth_client, monkeypatch):
    from app.services import counselor

    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail: db password is hunter2")

    monkeypatch.setattr(counselor, "respond", boom)
    res = auth_client.post("/api/chat", json={"message": "hi"})
    assert res.status_code == 500
    body = res.get_data(as_text=True)
    assert "hunter2" not in body
    assert "Traceback" not in body
    # Even on a hard failure, the user is pointed at real help.
    assert "1122" in body


def test_health_endpoint_reports_dependencies(client):
    data = client.get("/healthz").get_json()
    assert data["checks"]["database"] == "ok"
    assert "huggingface" in data["checks"]
    assert data["checks"]["encryption"] == "enabled"


def test_404_renders_without_leaking(client):
    res = client.get("/definitely-not-a-page")
    assert res.status_code == 404
    assert "Traceback" not in res.get_data(as_text=True)
