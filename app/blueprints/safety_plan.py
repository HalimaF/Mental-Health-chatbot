"""Safety plan routes.

A safety plan is written while someone is calm and read while they are not.
That asymmetry drives the design: saving is forgiving (every field optional,
autosave, no validation gates), and reading is instant and unmissable.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from ..extensions import db, limiter
from ..models import SafetyPlan
from ..security import current_user, login_required

bp = Blueprint("safety_plan", __name__)

MAX_FIELD = 2000


def get_or_create_plan(user_id: int) -> SafetyPlan:
    plan = db.session.query(SafetyPlan).filter(SafetyPlan.user_id == user_id).first()
    if plan is None:
        plan = SafetyPlan(user_id=user_id)
        db.session.add(plan)
        db.session.commit()
    return plan


@bp.get("/safety-plan")
@login_required
def page():
    plan = get_or_create_plan(current_user().id)
    return render_template("safety_plan.html", plan=plan)


@bp.get("/api/safety-plan")
@login_required
def api_get():
    plan = get_or_create_plan(current_user().id)
    return jsonify(plan.to_dict())


@bp.post("/api/safety-plan")
@login_required
@limiter.limit("60 per hour")
def api_save():
    """Partial save. Only the fields present in the body are touched, so an
    autosave of one section can never blank out the rest of the plan."""
    payload = request.get_json(silent=True) or {}
    plan = get_or_create_plan(current_user().id)

    updated = []
    for field in SafetyPlan.FIELDS:
        if field not in payload:
            continue
        value = payload.get(field)
        if value is None:
            value = ""
        if not isinstance(value, str):
            return jsonify({"error": "invalid_field", "field": field}), 400
        setattr(plan, field, value.strip()[:MAX_FIELD] or None)
        updated.append(field)

    if not updated:
        return jsonify({"error": "nothing_to_update"}), 400

    db.session.commit()
    return jsonify({"ok": True, "updated": updated, "plan": plan.to_dict()})


@bp.post("/api/safety-plan/clear")
@login_required
@limiter.limit("10 per hour")
def api_clear():
    plan = get_or_create_plan(current_user().id)
    for field in SafetyPlan.FIELDS:
        setattr(plan, field, None)
    db.session.commit()
    return jsonify({"ok": True, "plan": plan.to_dict()})
