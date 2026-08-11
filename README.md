# Dil-e-Azaad (دلِ آزاد)

A mental health support companion for Pakistani and South Asian users, built on
Hugging Face models with a two-layer crisis detection pipeline.

> **This is not a medical device.** It cannot diagnose, prescribe, or intervene in
> an emergency. It is designed to listen well, notice risk, and route people to
> real human help quickly. Read [Safety model](#safety-model) before deploying it
> to anyone.

---

## What it does

- **Remembers the conversation.** Recent turns go to the model verbatim; older ones
  are folded into a rolling summary, so the thread survives indefinitely without an
  unbounded prompt.
- **Assesses risk on every message** with a deterministic rule layer *and* a
  Hugging Face classifier, fused rather than substituted.
- **Adapts how it replies to that risk** — the system prompt for someone venting
  about exams is not the system prompt for someone who has a plan.
- **Encrypts everything sensitive at rest.** Messages, summaries, mood excerpts and
  check-in notes are Fernet-encrypted before they touch the database.
- **Tracks mood over time** — daily check-ins, streaks, sentiment trend and emotion
  frequency, framed as observations rather than diagnosis.
- **Works without an account.** Guest mode persists nothing.

## Architecture

```
Browser
   │  JSON only — the server never returns HTML for the client to innerHTML
   ▼
Flask app factory ── blueprints: main · auth · chat · wellness
   │
   ├── services/safety.py     Layer 1: rules (offline, always runs)
   │                          Layer 2: HF classifiers  → fused risk level
   ├── services/prompts.py    System prompt selected by risk level
   ├── services/memory.py     Verbatim window + rolling summary
   ├── services/counselor.py  Orchestration; guarantees a reply always exists
   └── services/hf_client.py  Hugging Face Inference API (nothing loaded locally)
   │
   ▼
Postgres (SQLite for local dev) — sensitive columns encrypted via EncryptedText
```

No model weights are loaded into process memory, so the app runs in ~512 MB.

### Models

All are configurable by environment variable.

| Job | Default model |
|---|---|
| Generation | `meta-llama/Llama-3.3-70B-Instruct` |
| Suicide risk | `vibhorag101/roberta-base-suicide-prediction-phr` |
| Emotion (28 classes) | `SamLowe/roberta-base-go_emotions` |
| Sentiment | `cardiffnlp/twitter-roberta-base-sentiment-latest` |

## Safety model

Risk is graded `NONE → LOW → MODERATE → HIGH → IMMINENT` and computed from two
independent layers:

**Layer 1 — deterministic rules.** Pure Python regex. No network, no model, runs in
microseconds, always executes. Covers explicit intent, plan/means/timeframe
disclosures, self-harm, hopelessness and entrapment, in English, Urdu script and
Roman Urdu. Critically, it also *suppresses* false positives: negated and
past-tense disclosures ("I used to want to die but therapy helped"), informational
questions ("what are the warning signs of suicide"), and third-party concern ("my
brother said he wants to die") are stepped down rather than treated as crises.

**Layer 2 — Hugging Face classifiers.** Catches phrasings no keyword list will
enumerate.

**Fusion** is `max(rules, classifier)`, so a model shrug can never downgrade an
explicit disclosure. Informational and negated text is capped unless the classifier
is highly confident.

Two guarantees hold regardless of infrastructure state:

1. **If Hugging Face is unreachable, the rule layer still runs.** The assessment is
   marked `degraded`, never skipped.
2. **A user in crisis always receives a response and always receives resources.**
   Crisis contacts are attached by the application, never left to the model to
   remember. If generation fails entirely, a written fallback is used.

`tests/test_safety.py` is the specification. Change the rules only alongside it.

## Quick start

```bash
git clone <repo> && cd mentalhealthchatbot
python -m venv .venv && . .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env
flask --app wsgi generate-keys                     # prints SECRET_KEY and ENCRYPTION_KEY
# paste both into .env, then add your HF_TOKEN from
# https://huggingface.co/settings/tokens

flask --app wsgi bootstrap        # creates the database
flask --app wsgi check-all        # verifies the database and every HF model
flask --app wsgi run --debug
```

Without `HF_TOKEN` the app still boots and serves every page; generation returns a
safe fallback and rule-based crisis detection keeps working. That is deliberate —
it makes the app developable and testable offline.

### Tests

```bash
pytest                      # 162 tests
pytest --cov=app            # coverage
ruff check .
```

## Configuration

| Variable | Required | Notes |
|---|---|---|
| `SECRET_KEY` | **yes in production** | Session signing. Production refuses to boot without it. |
| `ENCRYPTION_KEY` | **yes in production** | Fernet key. **Back it up.** Lose it and every stored conversation is unreadable forever. |
| `HF_TOKEN` | recommended | Without it, generation is disabled. |
| `DATABASE_URL` | recommended | Defaults to SQLite. Use Postgres in production. |
| `HF_CHAT_MODEL` | no | Any chat-completion model on HF Inference Providers. |
| `HF_PROVIDER` | no | Pin an inference provider (`together`, `fireworks-ai`, …). |
| `RATELIMIT_STORAGE_URI` | no | Set a `redis://` URL when running >1 worker. |
| `SESSION_COOKIE_SECURE` | production | Set to `1` when serving over HTTPS. |
| `RETENTION_DAYS` | no | `0` disables auto-purge. See `flask purge-old-data`. |
| `MEMORY_TURN_WINDOW` | no | Turns kept verbatim before summarisation. Default 12. |

The full list with comments is in [`.env.example`](.env.example).

## Deployment

### Render

`render.yaml` provisions the web service, managed Postgres and Redis. Set
`ENCRYPTION_KEY` and `HF_TOKEN` manually in the dashboard (both are `sync: false`).

> **Do not deploy with SQLite.** Render, Railway and most container platforms have
> ephemeral filesystems — every deploy erases the database. The app logs a warning
> at boot if it detects this.

### Docker

```bash
docker build -t dil-e-azaad .
docker run -p 8000:8000 --env-file .env dil-e-azaad
```

Runs as a non-root user with a healthcheck on `/healthz`.

## Operations

| Command | Purpose |
|---|---|
| `flask --app wsgi bootstrap` | Create or update the database. Safe on empty, populated, and un-migrated databases alike. |
| `flask --app wsgi check-all` | Full pre-deploy check: database, schema, HF token, all four models |
| `flask --app wsgi check-db` | Database connection, tables, migration revision, row counts |
| `flask --app wsgi check-hf` | One real API call per model; explains any failure |
| `flask --app wsgi generate-keys` | Print fresh `SECRET_KEY` / `ENCRYPTION_KEY` |
| `flask --app wsgi reset-db` | **Destructive.** Drop everything and rebuild |
| `flask --app wsgi purge-old-data` | Delete content older than `RETENTION_DAYS` |
| `GET /healthz` | Liveness plus database / HF / encryption status |

Deployment instructions, including why the previous SQLite-based deploy lost its
data, are in **[DEPLOY.md](DEPLOY.md)**.

## Privacy

- Message content, conversation summaries, mood excerpts and check-in notes are
  encrypted at rest with `EncryptedText`.
- `GET /api/export` returns everything held about a user as JSON.
- Account deletion is a hard delete and cascades to every related row. SQLite's
  foreign key enforcement is explicitly enabled so this actually happens.
- IP addresses in the audit log are stored as salted digests, never in the clear.
- The insights API returns aggregates only and never message text.
- Guest mode persists nothing at all.

## Security

- CSRF protection on every state-changing route; JSON endpoints use an
  `X-CSRFToken` header.
- Rate limits on login, registration, chat, check-in, export and password change.
- CSP, HSTS, `X-Frame-Options: DENY`, `nosniff`, referrer policy, `no-store` on
  private pages.
- Passwords: 12-character minimum, character-class variety, common-password
  rejection. Changing one invalidates every existing session.
- Login is timing-equalised and errors are non-enumerable — an account existing here
  is itself sensitive information.
- CI fails the build if a provider API key ever appears in the tree.

Report vulnerabilities privately rather than opening a public issue.

## Contributing

Run `ruff check .` and `pytest` before opening a PR. Changes to `services/safety.py`
must come with tests covering both the true-positive and the false-positive side —
a rule that catches more crises by also flagging every student essay is a
regression, not an improvement.

## Licence

MIT.
