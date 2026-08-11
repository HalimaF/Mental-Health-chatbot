#!/bin/sh
# Applies migrations, then starts the server.
#
# Running `db upgrade` here rather than in a separate deploy hook means the
# schema is correct before the first request on every platform, including the
# ones with no pre-deploy step. Alembic is idempotent and takes an advisory
# lock on Postgres, so a rolling restart cannot corrupt the schema.
set -e

: "${PORT:=8000}"
: "${WEB_CONCURRENCY:=2}"

echo "==> Applying database migrations"
if ! flask --app wsgi db upgrade; then
    echo "!!! Migration failed."
    echo "!!! Check DATABASE_URL is reachable, then run: flask --app wsgi check-db"
    exit 1
fi

echo "==> Starting gunicorn on port ${PORT} with ${WEB_CONCURRENCY} workers"
exec gunicorn wsgi:app \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WEB_CONCURRENCY}" \
    --threads 4 \
    --timeout 60 \
    --graceful-timeout 30 \
    --access-logfile - \
    --error-logfile -
