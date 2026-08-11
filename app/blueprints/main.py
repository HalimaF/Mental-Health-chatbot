"""Public pages and operational endpoints."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, redirect, render_template, url_for
from sqlalchemy import text

from ..extensions import db
from ..security import current_user
from ..services.safety import CRISIS_RESOURCES

bp = Blueprint("main", __name__)


@bp.get("/")
def welcome():
    if current_user():
        return redirect(url_for("chat.chat_page"))
    return render_template("welcome.html")


@bp.get("/resources")
def resources():
    return render_template("resources.html", resources=CRISIS_RESOURCES)


@bp.get("/healthz")
def healthz():
    """Liveness and dependency check for the platform's health monitor.

    Reports degraded rather than failing when Hugging Face is unconfigured --
    the app still serves pages and its rule-based safety layer still works, so
    an orchestrator should not cycle the container over it.
    """
    checks = {}
    ok = True

    try:
        db.session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc.__class__.__name__}"
        ok = False

    hf = current_app.extensions.get("huggingface")
    checks["huggingface"] = "configured" if getattr(hf, "configured", False) else "unconfigured"
    checks["encryption"] = (
        "enabled" if current_app.config.get("ENCRYPTION_KEY") else "disabled"
    )

    status = "ok" if ok and checks["huggingface"] == "configured" else (
        "ok" if ok else "error"
    )
    return jsonify({"status": status, "checks": checks}), (200 if ok else 503)
