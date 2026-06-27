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
# Synthetic data files (train.json, val.json, etc.) are needed by
# the demo dashboard to render encounter detail pages. Without
# this, the home page lists registered encounters but /encounter/{id}
# 404s because load_encounter_record() can't find the underlying data.
#
# We copy the whole data/ tree so the synth/ subdirectory structure
# is preserved (load_encounter_record() resolves paths relative to
# `data/synth/`). The .dockerignore excludes data/private/ (real PHI,
# empty today) so production deployments never ship real patient
# data in the image layer.
COPY data ./data
# Overwrite the bundled v0 prompt with the current production prompt
# (v12 as of 2026-06-24, F1=0.690 on the cleaned AHCIP val set). The
# `_DEFAULT_PROMPT_NAME = "auditor_prompt.txt"` resolution in
# src/ai_billing_audit/auditor.py:60 picks this up at module import.
# To bump the live prompt: copy the new file over auditor_prompt.txt
# here (or via the deploy script's rsync), then rebuild the image.
# The prompts/MANIFEST.json entry is the source of truth for which
# version is in production.
COPY prompts/v12/auditor_prompt.txt ./src/ai_billing_audit/auditor_prompt.txt
RUN pip install --upgrade pip \
    && pip install -e . \
    && pip install "psycopg[binary]>=3.1" "uvicorn[standard]>=0.27"

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
