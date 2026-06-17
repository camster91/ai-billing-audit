# ai-billing-audit — API + worker image
#
# Single image that runs as either the FastAPI service (default CMD) or the
# job-queue worker (override CMD). Both entrypoints share the same
# ai_billing_audit Python package; the difference is which process boots.
#
# Built on python:3.12-slim to keep the image lean. The /data and /artifacts
# mount points match the persistent-volume convention from the deploy script
# (../data and ../artifacts on the host bind-mounted into the container).

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src

# System deps: gcc for any C-extension wheels (psycopg, etc.) and curl for
# the container-level healthcheck in docker-compose.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so layer caching kicks in for code changes.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip \
    && pip install -e . \
    && pip install "psycopg[binary]>=3.1"

# Persistent data + audit-output mounts. Compose binds ../data and
# ../artifacts into these paths; on a fresh deploy the dirs are created
# automatically so the api process can append job-queue logs.
RUN mkdir -p /data /artifacts
VOLUME ["/data", "/artifacts"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

# Default entrypoint: uvicorn serving the FastAPI app defined in
# src/ai_billing_audit/api.py. The worker service overrides CMD to
# `python -m ai_billing_audit.worker` (or a sleep loop if no worker
# module exists yet — see deploy docs).
CMD ["uvicorn", "ai_billing_audit.api:app", "--host", "0.0.0.0", "--port", "8000"]
