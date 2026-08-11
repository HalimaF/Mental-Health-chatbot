# Slim image: nothing is loaded into process memory at runtime — all models are
# called over the Hugging Face Inference API — so this runs comfortably in 512 MB.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# psycopg2 needs libpq at build time; the runtime image keeps only the shared lib.
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && apt-get purge -y gcc libpq-dev \
 && apt-get autoremove -y

COPY . .

# Normalise line endings in case the file was checked out on Windows -- a CRLF
# here produces the notoriously unhelpful "exec format error" at container start.
RUN sed -i 's/\r$//' docker-entrypoint.sh && chmod +x docker-entrypoint.sh

# Never run as root.
RUN useradd --create-home --uid 10001 appuser \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://localhost:${PORT:-8000}/healthz" || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
