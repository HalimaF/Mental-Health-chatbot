"""Form definitions and validation.

Validation now happens in one declared place instead of being scattered through
route bodies, and CSRF protection comes with it for free.
"""

from __future__ import annotations

import re

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, TextAreaField
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    Regexp,
    ValidationError,
)

# Rejected outright: these are the passwords credential-stuffing lists try first.
_COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789", "qwerty123",
    "iloveyou", "letmein1", "welcome1", "admin123", "abc12345", "11111111",
    "dilazaad", "changeme", "passw0rd", "qwertyuiop", "1q2w3e4r",
}


def _strong_password(form, field):
    value = field.data or ""
    if value.lower() in _COMMON_PASSWORDS:
        raise ValidationError("That password is too common. Please pick something else.")
    checks = (
        bool(re.search(r"[a-z]", value)),
        bool(re.search(r"[A-Z]", value)),
        bool(re.search(r"\d", value)),
        bool(re.search(r"[^A-Za-z0-9]", value)),
    )
    if sum(checks) < 3:
        raise ValidationError(
            "Use at least three of: lowercase, uppercase, a number, and a symbol."
        )


class RegistrationForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[
            DataRequired("Please choose a username."),
            Length(min=3, max=32, message="Username must be 3-32 characters."),
            Regexp(
                r"^[A-Za-z0-9_.-]+$",
                message="Letters, numbers, dots, dashes and underscores only.",
            ),
        ],
    )
    email = StringField(
        "Email",
        validators=[
            DataRequired("Please enter your email."),
            Email("That doesn't look like a valid email address."),
            Length(max=255),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired("Please choose a password."),
            # 12 is the current NIST-aligned floor. The old app allowed 6.
            Length(min=12, max=128, message="Password must be at least 12 characters."),
            _strong_password,
        ],
    )
    confirm = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", "Passwords do not match.")],
    )
    accept = BooleanField(
        "I understand this is not a substitute for professional care",
        validators=[DataRequired("Please confirm you understand before continuing.")],
    )


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(max=64)])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=128)])


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired()])
    password = PasswordField(
        "New password",
        validators=[DataRequired(), Length(min=12, max=128), _strong_password],
    )
    confirm = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("password", "Passwords do not match.")],
    )


class DeleteAccountForm(FlaskForm):
    password = PasswordField("Password", validators=[DataRequired()])
    confirm_text = StringField(
        "Type DELETE to confirm",
        validators=[DataRequired(), Regexp(r"^DELETE$", message="Type DELETE exactly.")],
    )


class CheckInForm(FlaskForm):
    mood_score = StringField("Mood", validators=[])
    note = TextAreaField("Note", validators=[Length(max=1000)])
