"""Registration, login, logout, password change and account deletion."""

from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import func, or_
from werkzeug.security import generate_password_hash

from ..extensions import db, limiter
from ..forms import ChangePasswordForm, DeleteAccountForm, LoginForm, RegistrationForm
from ..models import User, utcnow
from ..security import audit, current_user, login_required, login_user, logout_user

bp = Blueprint("auth", __name__)


def _safe_next(target: str | None) -> str:
    """Only ever redirect to a path on this host.

    Accepting a full URL here would turn the login page into an open redirect
    that phishing campaigns can point at a fake login screen.
    """
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("chat.chat_page")


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour; 20 per day", methods=["POST"])
def register():
    if current_user():
        return redirect(url_for("chat.chat_page"))

    form = RegistrationForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        email = form.email.data.strip().lower()

        existing = (
            db.session.query(User)
            .filter(
                or_(
                    func.lower(User.username) == username.lower(),
                    User.email == email,
                )
            )
            .first()
        )
        if existing:
            # Deliberately non-specific: saying which field collided lets an
            # attacker enumerate who has an account here, and an account here
            # is itself sensitive information.
            flash("That username or email is not available.", "error")
            return render_template("register.html", form=form), 400

        user = User(username=username, email=email)
        user.set_password(form.password.data)
        db.session.add(user)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Registration failed for %s", username)
            flash("We couldn't create your account. Please try again.", "error")
            return render_template("register.html", form=form), 500

        audit("user.register", user_id=user.id)
        flash("Account created. Please log in.", "success")
        return redirect(url_for("auth.login"))

    if form.errors:
        return render_template("register.html", form=form), 400
    return render_template("register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per 15 minutes; 50 per day", methods=["POST"])
def login():
    if current_user():
        return redirect(url_for("chat.chat_page"))

    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        user = (
            db.session.query(User)
            .filter(func.lower(User.username) == username.lower())
            .first()
        )

        if user is None:
            # Hash anyway so a missing account and a wrong password take the
            # same amount of time. Otherwise response timing reveals which
            # usernames exist -- and here, having an account is itself sensitive.
            generate_password_hash(form.password.data)
            valid = False
        else:
            valid = user.check_password(form.password.data)

        if user is not None and valid and user.is_active:
            login_user(user)
            user.last_login = utcnow()
            db.session.commit()
            audit("auth.login.success", user_id=user.id)
            return redirect(_safe_next(request.args.get("next")))

        audit("auth.login.failure", detail=username[:64])
        flash("Invalid username or password.", "error")
        return render_template("login.html", form=form), 401

    if form.errors:
        return render_template("login.html", form=form), 400
    return render_template("login.html", form=form)


@bp.post("/logout")
def logout():
    user = current_user()
    if user:
        audit("auth.logout", user_id=user.id)
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.welcome"))


@bp.route("/account", methods=["GET"])
@login_required
def account():
    return render_template(
        "account.html",
        password_form=ChangePasswordForm(),
        delete_form=DeleteAccountForm(),
        user=current_user(),
    )


@bp.post("/account/password")
@login_required
@limiter.limit("5 per hour")
def change_password():
    user = current_user()
    form = ChangePasswordForm()
    if not form.validate_on_submit():
        for errors in form.errors.values():
            for error in errors:
                flash(error, "error")
        return redirect(url_for("auth.account"))

    if not user.check_password(form.current_password.data):
        audit("auth.password_change.failure", user_id=user.id)
        flash("Your current password is incorrect.", "error")
        return redirect(url_for("auth.account"))

    # set_password bumps session_version, invalidating every existing cookie.
    user.set_password(form.password.data)
    db.session.commit()
    audit("auth.password_change.success", user_id=user.id)
    logout_user()
    flash("Password updated. Please log in again.", "success")
    return redirect(url_for("auth.login"))


@bp.post("/account/delete")
@login_required
@limiter.limit("3 per hour")
def delete_account():
    """Hard delete. Cascades remove every conversation, message, mood entry
    and check-in. This is a right-to-erasure path, so nothing is retained."""
    user = current_user()
    form = DeleteAccountForm()
    if not form.validate_on_submit() or not user.check_password(form.password.data):
        flash("Could not verify your identity. Account not deleted.", "error")
        return redirect(url_for("auth.account"))

    user_id = user.id
    db.session.delete(user)
    db.session.commit()
    audit("user.delete", user_id=user_id)
    logout_user()
    flash("Your account and all of your data have been permanently deleted.", "success")
    return redirect(url_for("main.welcome"))
