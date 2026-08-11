"""Authentication helpers and HTTP security headers."""

from __future__ import annotations

import hashlib
from functools import wraps

from flask import current_app, flash, g, jsonify, redirect, request, session, url_for

from .extensions import db
from .models import AuditEvent, User

SESSION_USER_ID = "uid"
SESSION_VERSION = "sv"


def login_user(user: User) -> None:
    session.clear()  # rotate the session id to defeat session fixation
    session[SESSION_USER_ID] = user.id
    session[SESSION_VERSION] = user.session_version
    session.permanent = True


def logout_user() -> None:
    session.clear()


def load_current_user() -> None:
    """Resolve ``g.user`` once per request from the signed session cookie."""
    g.user = None
    user_id = session.get(SESSION_USER_ID)
    if not user_id:
        return
    user = db.session.get(User, user_id)
    if user is None or not user.is_active:
        session.clear()
        return
    # A password change or "log out everywhere" bumps session_version, which
    # invalidates every cookie issued before it.
    if session.get(SESSION_VERSION) != user.session_version:
        session.clear()
        return
    g.user = user


def current_user() -> User | None:
    return getattr(g, "user", None)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            if request.accept_mimetypes.best == "application/json" or request.is_json:
                return jsonify({"error": "authentication_required"}), 401
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def hash_ip(ip: str | None) -> str | None:
    """Store a salted digest rather than the raw address.

    An IP tied to mental health activity is itself sensitive; the digest is
    enough to spot brute force without retaining an identifier.
    """
    if not ip:
        return None
    salt = current_app.config.get("SECRET_KEY", "")
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:64]


def audit(event: str, *, user_id: int | None = None, detail: str | None = None) -> None:
    """Record a security event. Never stores message content."""
    try:
        db.session.add(
            AuditEvent(
                user_id=user_id,
                event=event,
                detail=(detail or "")[:500] or None,
                ip_hash=hash_ip(request.remote_addr),
            )
        )
        db.session.commit()
    except Exception:  # auditing must never break the request it describes
        current_app.logger.exception("Failed to write audit event %s", event)
        db.session.rollback()


# Inline handlers and styles still live in the templates, so 'unsafe-inline' is
# required for now; scripts are otherwise locked to same-origin and no external
# host can be contacted.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data:",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    ]
)


def apply_security_headers(response):
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=(), interest-cohort=()"
    )
    if current_app.config.get("SESSION_COOKIE_SECURE"):
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    # Conversations are private and must never be cached by an intermediary.
    if request.path.startswith(("/api/", "/chat", "/history", "/insights", "/streak")):
        response.headers.setdefault("Cache-Control", "no-store, private")
    return response
