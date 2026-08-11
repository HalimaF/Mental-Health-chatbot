# Deploying Dil-e-Azaad

## Why the last attempt failed

The old app used SQLite (`dil_azaad.db`) and called `init_db()` at import time.
On Render, Railway, Fly and every container platform, **the filesystem is
ephemeral**: it is recreated from the image on every deploy, restart, crash and
autoscale event. So the database was created empty on boot, filled up while the
instance lived, and vanished the moment anything restarted — taking every account
with it. There was also no migration system, so there was no way to change the
schema without losing everything.

Both are fixed: the schema is managed by Alembic migrations, and `DATABASE_URL`
points at a real Postgres server whose lifetime is independent of the app.

---

## Before you start

Generate your keys and keep them somewhere safe:

```bash
flask --app wsgi generate-keys
```

You need three secrets:

| Secret | Where it comes from | If you lose it |
|---|---|---|
| `SECRET_KEY` | the command above | everyone is logged out; no data lost |
| `ENCRYPTION_KEY` | the command above | **every stored conversation is unreadable forever** |
| `HF_TOKEN` | huggingface.co/settings/tokens (read scope) | generation stops; app still runs |

Back up `ENCRYPTION_KEY`. There is deliberately no recovery path.

---

## Option A — Render + Neon Postgres (recommended)

Render's own free Postgres expires after 30 days. [Neon](https://neon.tech) has a
free tier that does not, which matters for a project you want to leave running.

**1. Create the database**

Sign up at neon.tech → create a project → copy the connection string. It looks like:

```
postgresql://user:pass@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
```

Pick the region closest to your users (`ap-southeast-1` for Pakistan).

**2. Create the web service on Render**

New → Web Service → connect your repo.

| Field | Value |
|---|---|
| Runtime | Python 3 |
| Build command | `pip install -r requirements.txt` |
| Start command | `flask --app wsgi db upgrade && gunicorn wsgi:app --workers 2 --threads 4 --timeout 60` |
| Health check path | `/healthz` |

**3. Set environment variables**

```
DATABASE_URL          = <your Neon connection string>
SECRET_KEY            = <from generate-keys>
ENCRYPTION_KEY        = <from generate-keys>
HF_TOKEN              = hf_...
FLASK_ENV             = production
SESSION_COOKIE_SECURE = 1
PYTHON_VERSION        = 3.12.7
```

`postgres://` URLs are rewritten to the SQLAlchemy dialect automatically, so paste
whatever your provider gives you.

**4. Deploy.** The start command applies migrations before gunicorn binds, so the
schema is correct on the very first request. Watch the log for:

```
INFO [alembic.runtime.migration] Running upgrade -> 6c4a46ecbad7
[INFO] Listening at: http://0.0.0.0:10000
```

**5. Verify**

```bash
curl https://your-app.onrender.com/healthz
```

```json
{"status":"ok","checks":{"database":"ok","encryption":"enabled","huggingface":"configured"}}
```

All three must read `ok` / `enabled` / `configured`. Anything else, see
[Troubleshooting](#troubleshooting).

---

## Option B — Render blueprint

`render.yaml` provisions the web service, Postgres and Redis in one go:

Render dashboard → New → Blueprint → select the repo.

Then set the two `sync: false` variables manually in the dashboard:
`ENCRYPTION_KEY` and `HF_TOKEN`. Everything else is wired automatically.

---

## Option C — Docker

```bash
docker build -t dil-e-azaad .
docker run -p 8000:8000 --env-file .env dil-e-azaad
```

The entrypoint runs migrations, then gunicorn. Works anywhere that takes a
container: Fly.io, Railway, Cloud Run, a VPS.

---

## Pre-flight check

Run against your production environment before pointing anyone at it:

```bash
DATABASE_URL="postgresql://..." HF_TOKEN="hf_..." flask --app wsgi check-all
```

It verifies the database connection, the schema, the migration revision, the HF
token, and every one of the four models with a real API call. It exits non-zero if
anything is wrong, so it works in CI too.

---

## Database operations

| Task | Command |
|---|---|
| Create or update the schema | `flask --app wsgi bootstrap` |
| Check connection and schema | `flask --app wsgi check-db` |
| Wipe and rebuild (destructive) | `flask --app wsgi reset-db` |
| Change the schema | edit `app/models.py`, then `flask --app wsgi db migrate -m "what changed"` |
| Apply a new migration | `flask --app wsgi db upgrade` |
| Roll one back | `flask --app wsgi db downgrade` |
| Delete old messages | `flask --app wsgi purge-old-data` |

There is nothing else to manage. No SQL to run by hand, no schema file to keep in
sync — `bootstrap` is safe on an empty database and on a populated one.

---

## Troubleshooting

**`check-db` says "cannot connect"**
Wrong `DATABASE_URL`. On Render's own Postgres use the *Internal* Database URL
(the external one is slower and may be firewalled). On Neon, keep
`?sslmode=require` on the end.

**`healthz` reports `"database":"error"`**
The app booted but cannot reach Postgres. Usually the database is asleep (Neon
free tier idles after 5 minutes — the first request wakes it) or the URL is wrong.

**`"huggingface":"unconfigured"`**
`HF_TOKEN` is not set on the server. The app still serves every page and
rule-based crisis detection still works, but replies are canned fallbacks.

**Users get logged out at random**
`SECRET_KEY` is not set, so a new one is generated at each boot. Set it explicitly.

**Everyone's history is gone after a deploy**
You are still on SQLite. Check `/healthz` and the boot log — the app logs a loud
warning when it detects this.

**`exec format error` from Docker**
`docker-entrypoint.sh` was checked out with Windows line endings. The Dockerfile
strips them, so rebuild without cache: `docker build --no-cache -t dil-e-azaad .`

**Rate limits behave inconsistently**
With more than one worker and no `RATELIMIT_STORAGE_URI`, each worker counts
separately. Set a `redis://` URL.

---

## After deploying

- Set `RETENTION_DAYS` and schedule `flask --app wsgi purge-old-data` if you do not
  want to hold conversations indefinitely.
- Keep `ENCRYPTION_KEY` backed up somewhere that is not the server.
- The crisis helpline numbers in `app/services/safety.py` should be re-verified
  before real users arrive; helpline numbers change.
