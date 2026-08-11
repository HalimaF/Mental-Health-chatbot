"""Operational CLI commands.

`flask --app wsgi <command>`. The diagnostics here exist so that the two things
most likely to break a deployment -- the Hugging Face token and the database --
can be checked directly instead of inferred from a 500 page.
"""

from __future__ import annotations

import secrets
import time
from datetime import timedelta

import click
from flask import Flask
from flask.cli import with_appcontext
from sqlalchemy import inspect, text

from .extensions import db

OK = "  [ok]  "
BAD = "  [FAIL]"
WARN = "  [warn]"


def _explain_hf_error(exc: Exception) -> str:
    """Turn an HF exception into something actionable."""
    msg = str(exc)
    low = msg.lower()
    if (
        "401" in msg
        or "unauthorized" in low
        or "invalid credentials" in low
        # The wording the hub actually returns for a bad token -- verified live.
        or "invalid user token" in low
        or "invalid token" in low
    ):
        return "token rejected. Check HF_TOKEN at https://huggingface.co/settings/tokens"
    if "403" in msg or "forbidden" in low or "gated" in low or "awaiting a review" in low:
        return (
            "access denied. This model is gated -- open its page on huggingface.co "
            "and accept the licence with the same account that owns the token."
        )
    if "404" in msg or "not found" in low:
        return "model id not found. Check the spelling, or the model was removed."
    if "503" in msg or "loading" in low or "currently loading" in low:
        return "model is cold-starting. Wait ~30s and run this again."
    if "429" in msg or "rate limit" in low or "quota" in low:
        return "rate limited or out of credits on your HF account."
    if "supported" in low and "provider" in low:
        return (
            "no inference provider serves this model. Pick a different HF_CHAT_MODEL, "
            "or set HF_PROVIDER to one that hosts it."
        )
    if "timed out" in low or "timeout" in low:
        return "request timed out. Network issue, or raise LLM_TIMEOUT_SECONDS."
    return msg[:200]


def register_cli(app: Flask) -> None:
    # ---------------------------------------------------------------- keys --

    @app.cli.command("generate-keys")
    def generate_keys():
        """Print a fresh SECRET_KEY and ENCRYPTION_KEY."""
        from cryptography.fernet import Fernet

        click.echo(f"SECRET_KEY={secrets.token_hex(32)}")
        click.echo(f"ENCRYPTION_KEY={Fernet.generate_key().decode()}")
        click.echo("")
        click.secho(
            "Back up ENCRYPTION_KEY somewhere durable. If you lose it, every stored "
            "conversation becomes permanently unreadable.",
            fg="yellow",
        )

    # ------------------------------------------------------------ database --

    @app.cli.command("check-db")
    @with_appcontext
    def check_db():
        """Verify the database connection, schema and migration state."""
        uri = app.config["SQLALCHEMY_DATABASE_URI"]
        # Never print credentials from a Postgres URL.
        safe = uri.split("@")[-1] if "@" in uri else uri
        click.echo(f"Database: {safe}")

        failed = False
        try:
            db.session.execute(text("SELECT 1"))
            click.secho(f"{OK} connection established", fg="green")
        except Exception as exc:
            click.secho(f"{BAD} cannot connect: {exc.__class__.__name__}: {exc}", fg="red")
            click.echo("\n  Check DATABASE_URL. For Render, copy the Internal Database URL.")
            raise SystemExit(1) from exc

        if uri.startswith("sqlite"):
            click.secho(
                f"{WARN} SQLite in use. Fine locally; on Render/Railway the filesystem is "
                "ephemeral and every deploy wipes it. Set DATABASE_URL to Postgres.",
                fg="yellow",
            )

        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        expected = {
            "users", "conversations", "messages",
            "mood_entries", "checkins", "audit_events",
        }
        missing = expected - tables
        if missing:
            click.secho(f"{BAD} missing tables: {', '.join(sorted(missing))}", fg="red")
            click.echo("\n  Run: flask --app wsgi db upgrade")
            failed = True
        else:
            click.secho(f"{OK} all {len(expected)} tables present", fg="green")

        if "alembic_version" in tables:
            rev = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()
            click.secho(f"{OK} migration revision: {rev}", fg="green")
        else:
            click.secho(f"{WARN} no migration history. Run: flask --app wsgi db upgrade", fg="yellow")

        if not failed and not missing:
            from .models import CheckIn, Message, User

            click.echo("")
            click.echo(f"  users:    {db.session.query(User).count()}")
            click.echo(f"  messages: {db.session.query(Message).count()}")
            click.echo(f"  checkins: {db.session.query(CheckIn).count()}")

        raise SystemExit(1 if failed else 0)

    @app.cli.command("bootstrap")
    @with_appcontext
    def bootstrap():
        """Create or upgrade the database to the current schema.

        Handles all three states a database can be in, so it is always the right
        command to run and never needs a decision from the operator:

        * empty                     -> run every migration
        * managed by Alembic        -> apply whatever is outstanding
        * has tables, no history    -> stamp it at head, then upgrade

        That third case is the one that bites: a database created by an older
        ``db.create_all()`` has the tables but no ``alembic_version`` row, so a
        plain ``db upgrade`` tries to create them again and dies with
        "table already exists".
        """
        from flask_migrate import stamp as alembic_stamp
        from flask_migrate import upgrade as alembic_upgrade

        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        has_schema = "users" in tables
        has_history = "alembic_version" in tables

        if has_schema and not has_history:
            click.secho(
                "Found existing tables with no migration history. Stamping at head.",
                fg="yellow",
            )
            alembic_stamp()
        elif not tables:
            click.echo("Empty database. Creating schema...")
        else:
            click.echo("Checking for outstanding migrations...")

        alembic_upgrade()
        click.secho("Database is up to date.", fg="green")

    @app.cli.command("reset-db")
    @click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
    @with_appcontext
    def reset_db(yes):
        """DESTRUCTIVE. Drop every table and rebuild from migrations."""
        uri = app.config["SQLALCHEMY_DATABASE_URI"]
        safe = uri.split("@")[-1] if "@" in uri else uri
        if not yes:
            click.confirm(
                f"This permanently deletes ALL data in {safe}. Continue?", abort=True
            )
        from flask_migrate import upgrade as alembic_upgrade

        db.drop_all()
        db.session.execute(text("DROP TABLE IF EXISTS alembic_version"))
        db.session.commit()
        alembic_upgrade()
        click.secho("Database reset and rebuilt.", fg="green")

    @app.cli.command("purge-old-data")
    @with_appcontext
    def purge_old_data():
        """Delete message content older than RETENTION_DAYS."""
        from .models import Message, MoodEntry, utcnow

        days = app.config["RETENTION_DAYS"]
        if days <= 0:
            click.echo("RETENTION_DAYS is 0; automatic purging is disabled.")
            return
        cutoff = utcnow() - timedelta(days=days)
        messages = db.session.query(Message).filter(Message.created_at < cutoff).delete()
        moods = db.session.query(MoodEntry).filter(MoodEntry.created_at < cutoff).delete()
        db.session.commit()
        click.secho(
            f"Deleted {messages} messages and {moods} mood entries older than {days} days.",
            fg="green",
        )

    # ------------------------------------------------------- hugging face --

    @app.cli.command("check-hf")
    @click.option("--verbose", is_flag=True, help="Print full model output.")
    @with_appcontext
    def check_hf(verbose):
        """Verify the Hugging Face token and every configured model.

        Makes one real call per model, so it proves the whole path end to end:
        token, network, provider routing, model availability and label format.
        """
        hf = app.extensions["huggingface"]
        failures = []

        click.echo("Hugging Face check\n" + "=" * 52)

        # 1. Token ---------------------------------------------------------
        if not hf.configured:
            click.secho(f"{BAD} HF_TOKEN is not set.", fg="red")
            click.echo("\n  Create a read token at https://huggingface.co/settings/tokens")
            click.echo("  then add it to .env as:  HF_TOKEN=hf_...")
            raise SystemExit(1)

        try:
            from huggingface_hub import HfApi

            who = HfApi(token=hf.token).whoami()
            click.secho(f"{OK} token valid — account: {who.get('name', '?')}", fg="green")
        except Exception as exc:
            click.secho(f"{BAD} token check failed: {_explain_hf_error(exc)}", fg="red")
            raise SystemExit(1) from exc

        # 2. Chat model ----------------------------------------------------
        click.echo(f"\nGeneration model: {hf.chat_model}")
        started = time.perf_counter()
        try:
            reply = hf.chat(
                [
                    {"role": "system", "content": "Reply with exactly one short sentence."},
                    {"role": "user", "content": "Say hello."},
                ],
                max_tokens=32,
                temperature=0.1,
            )
            elapsed = time.perf_counter() - started
            click.secho(f"{OK} responded in {elapsed:.1f}s", fg="green")
            click.echo(f"       > {reply[:100]}")
        except Exception as exc:
            click.secho(f"{BAD} {_explain_hf_error(exc)}", fg="red")
            failures.append("generation")

        # 3. Classifiers ---------------------------------------------------
        click.echo("\nClassifiers")

        probes = [
            (
                "suicide risk",
                hf.suicide_model,
                lambda: hf.suicide_score("I don't want to be alive anymore"),
                lambda v: (
                    f"score {v:.2f} on a crisis phrase"
                    + ("" if v >= 0.5 else "  <- unexpectedly low, check the label map")
                ),
                lambda v: v >= 0.5,
            ),
            (
                "emotion",
                hf.emotion_model,
                lambda: hf.emotions("I am so scared and completely alone"),
                lambda v: f"detected {v or '[]'}",
                lambda v: bool(v),
            ),
            (
                "sentiment",
                hf.sentiment_model,
                lambda: hf.sentiment("Today was genuinely awful"),
                lambda v: f"{v[0]} ({v[1]:.2f})",
                lambda v: v[0] in {"negative", "neutral", "positive"},
            ),
        ]

        for label, model_id, call, describe, is_sane in probes:
            click.echo(f"  {label}: {model_id}")
            started = time.perf_counter()
            try:
                value = call()
                elapsed = time.perf_counter() - started
                if is_sane(value):
                    click.secho(f"{OK} {describe(value)}  [{elapsed:.1f}s]", fg="green")
                else:
                    click.secho(f"{WARN} {describe(value)}  [{elapsed:.1f}s]", fg="yellow")
            except Exception as exc:
                click.secho(f"{BAD} {_explain_hf_error(exc)}", fg="red")
                failures.append(label)

        # 4. Verdict -------------------------------------------------------
        click.echo("\n" + "=" * 52)
        if not failures:
            click.secho("All Hugging Face checks passed.", fg="green", bold=True)
            raise SystemExit(0)

        click.secho(f"Failed: {', '.join(failures)}", fg="red", bold=True)
        if "generation" in failures:
            click.echo(
                "\nWithout generation the app still runs, but every reply is a canned "
                "fallback. Rule-based crisis detection is unaffected."
            )
        if set(failures) & {"suicide risk", "emotion", "sentiment"}:
            click.echo(
                "\nWithout classifiers, risk assessment falls back to the offline rule "
                "layer and is flagged 'degraded'. The app stays safe, just less sensitive."
            )
        raise SystemExit(1)

    @app.cli.command("check-all")
    @click.pass_context
    def check_all(ctx):
        """Run every pre-deploy check."""
        problems = []
        for name in ("check-db", "check-hf"):
            click.echo(f"\n{'#' * 52}\n# {name}\n{'#' * 52}")
            try:
                ctx.invoke(app.cli.get_command(ctx, name))
            except SystemExit as exc:
                if exc.code:
                    problems.append(name)

        click.echo("\n" + "=" * 52)
        if problems:
            click.secho(f"Not ready to deploy — failing: {', '.join(problems)}", fg="red", bold=True)
            raise SystemExit(1)
        click.secho("Ready to deploy.", fg="green", bold=True)
