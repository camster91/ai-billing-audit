# Contributing to Zorva (ai-billing-audit)

Thanks for your interest in the project. This document
explains how to set up a local dev environment, run the
test suite, file issues, and submit pull requests.

If you only want to file a bug or a feature request, you
can skip straight to the [Filing issues](#filing-issues)
section.

---

## Table of contents

- [Code of conduct](#code-of-conduct)
- [Project layout](#project-layout)
- [Local development setup](#local-development-setup)
  - [Prerequisites](#prerequisites)
  - [First-time setup](#first-time-setup)
  - [Running the dev stack](#running-the-dev-stack)
- [Running tests](#running-tests)
- [Linters and formatters](#linters-and-formatters)
- [Filing issues](#filing-issues)
- [Submitting pull requests](#submitting-pull-requests)
- [Release process](#release-process)
- [Where to get help](#where-to-get-help)

---

## Code of conduct

This project follows the spirit of the
[Contributor Covenant](https://www.contributor-covenant.org/).
Be patient with first-time contributors, assume good faith,
and keep feedback specific and actionable. Security
vulnerabilities are **not** GitHub issues — see
[`SECURITY.md`](./SECURITY.md) for the disclosure flow.

---

## Project layout

```
ai-billing-audit/
├── src/ai_billing_audit/      # FastAPI app (the "api" service)
│   ├── api.py                 # route table + middleware
│   ├── public_api.py          # /v1/audits + /v1/webhooks
│   ├── webhooks.py            # at-least-once delivery
│   ├── auditor_*.py           # DSPy auditor pipeline
│   ├── audit_actions.py       # RBAC + per-finding feedback
│   └── ...                    # the rest of the v0.5.x surface
├── apps/portal/               # Next.js operator portal + marketing site
│   ├── AGENTS.md              # Next.js-version-specific rules (READ FIRST)
│   ├── CLAUDE.md              # alias for AGENTS.md, read by Claude Code
│   ├── src/app/               # App Router pages
│   └── package.json
├── prompts/                   # versioned auditor prompts (v12 is the default)
├── data/val_ca.json           # held-out validation claims
├── audit_trail.sql            # hash-chained audit log schema
├── Dockerfile                 # api + worker image
├── Dockerfile.caddy           # custom Caddy build (rate_limit module)
├── docker-compose.yml         # PRODUCTION stack — do not edit casually
├── docker-compose.dev.yml     # DEV stack — see 'Running the dev stack' below
├── deploy-to-vps.sh           # first-time setup + redeploy (read-only for most PRs)
├── pyproject.toml             # Python deps + pytest config
├── CHANGELOG.md               # release-grouped history (Keep a Changelog format)
├── SECURITY.md                # vulnerability disclosure policy
├── CONTRIBUTING.md            # this file
└── AGENTS.md                  # project-level rules for AI coding agents
```

The two apps — the FastAPI `api` and the Next.js `apps/portal` —
are intentionally separate codebases that share a Postgres
cluster, an `audit_trail.jsonl` log volume, and the public
domain `ai-billing-audit.ashbi.ca`. See
[`README.md`](./README.md) for the deploy-gaps note that
explains why.

**If you are an AI coding agent working in this repo, read
[`AGENTS.md`](./AGENTS.md) at the project root AND
[`apps/portal/AGENTS.md`](./apps/portal/AGENTS.md) AND
[`apps/portal/CLAUDE.md`](./apps/portal/CLAUDE.md) before
writing any code.** The Next.js version pinned in `apps/portal`
has breaking changes vs older Next.js training data; the
project rules in those files are not optional.

---

## Local development setup

### Prerequisites

- **Python 3.10+** (the project tests against 3.10, 3.11, 3.12)
- **Node 20.x or 22.x** (for `apps/portal`)
- **pnpm 9.x** (the portal uses pnpm — npm may work for a
  one-off install but the lockfile is pnpm-only)
- **Docker** (optional, but recommended for the
  Postgres / Caddy parts of the dev stack; pure-Python
  tests do not need it)
- A `MiniMax` (or any LiteLLM-routed) API key for the
  integration tests; **without one the `integration` tests
  are skipped automatically** (see `pyproject.toml`'s
  `pytest` markers)

### First-time setup

```bash
# 1. Clone and enter the repo
git clone https://github.com/camster91/ai-billing-audit.git
cd ai-billing-audit

# 2. Python venv (PEP 668 friendly via uv)
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. (Optional) install the auditor dev-only extras
pip install -e ".[dev]"   # pulls in pytest 9.x, pytest-cov, dspy[optuna]

# 4. apps/portal
cd apps/portal
pnpm install
pnpm dev
# → http://localhost:3000
cd ../..

# 5. Local .env (you will need a real MINIMAX_API_KEY for
#    integration tests, but the unit suite runs without one)
cp .env.example .env  # or: cat .env.example  # to see what's expected
```

### Running the dev stack

For the FastAPI side there are two paths:

**Path A: bare-metal Python (fastest inner loop).**

```bash
source .venv/bin/activate
python -m ai_billing_audit.api        # or: uvicorn ai_billing_audit.api:app --reload --port 8000
```

This runs the API on `http://127.0.0.1:8000`. The unit tests
do not need Postgres, so you can iterate on the auditor
pipeline without standing up the full stack.

**Path B: dev Docker Compose (full stack).**

```bash
docker compose -f docker-compose.dev.yml up --build
```

The dev compose file (`docker-compose.dev.yml`) brings up
`postgres`, `api`, `worker`, `caddy`, and an `ollama` local
LLM proxy side by side, with the API + worker source trees
bind-mounted in for hot reload. **Do not** point your dev
shell at the production `docker-compose.yml` — the volumes
are namespaced differently, the LLM provider is Ollama
instead of MiniMax, and the Caddy is plain HTTP on
`:3018` rather than the Traefik-fronted prod path.

See the file header in `docker-compose.dev.yml` for the
"when to use this vs production" matrix.

---

## Running tests

The Python test suite lives under `tests/`. The most common
incantations:

```bash
# Full suite (unit + integration; integration is skipped
# automatically if MINIMAX_API_KEY is unset)
pytest

# Fast inner loop — unit only
pytest -m "not integration"

# A single file
pytest tests/test_auditor.py

# A single test, with full traceback on failure
pytest tests/test_auditor.py::test_modifier_25 -x --tb=long

# With coverage
pytest --cov=src/ai_billing_audit --cov-report=term-missing
```

The Next.js / `apps/portal` tests live in `apps/portal/`:

```bash
cd apps/portal
pnpm test            # Vitest
pnpm test:e2e        # Playwright (requires `pnpm exec playwright install`)
```

A test that requires a real network endpoint MUST be marked
`@pytest.mark.integration` so it is skipped on offline
workstations. See the `markers` block in `pyproject.toml`.

---

## Linters and formatters

```bash
# Python — ruff (lint + format) and mypy (types)
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/ai_billing_audit

# TypeScript / Next.js — in apps/portal/
cd apps/portal
pnpm lint            # next lint
pnpm tsc --noEmit    # type-check
```

CI runs `ruff check`, `ruff format --check`, `mypy`, and
`pnpm tsc --noEmit` on every push. PRs that don't pass all
four will be flagged automatically.

---

## Filing issues

Use the GitHub issue tracker for **bugs and feature
requests** only. **Security issues** go to
`security@zorva.ca` — see [`SECURITY.md`](./SECURITY.md).

A good bug report includes:

1. The exact version of `ai-billing-audit` (the `/healthz`
   endpoint returns it; `git rev-parse HEAD` of your clone
   is also fine).
2. The reproduction — a `curl` line, a script, a
   screenshot, or a short screen-recording.
3. The expected behaviour and the actual behaviour.
4. Your OS, Python version, and (if relevant) the browser
   and viewport size for a portal UI bug.

Feature requests should be framed as a problem statement
("the biller can't see X") and not as a solution
("please add a button that does Y") — the maintainers
often have context that changes the shape of the fix.

---

## Submitting pull requests

1. **Open an issue first** for any non-trivial change.
   A 200-line PR that closes a 2-paragraph issue is a lot
   easier to review than a 200-line PR that is also the
   feature proposal.
2. **Branch off `main`.** Branch name should be
   `feat/<short-slug>` or `fix/<short-slug>`.
3. **One logical change per PR.** Don't bundle a refactor,
   a feature, and a CI fix into a single commit.
4. **Add a test.** Bug-fix PRs need a regression test
   that fails on `main` and passes on your branch.
   Feature PRs need at least one test that exercises
   the new contract.
5. **Run the full local suite before pushing.**
   ```bash
   pytest -m "not integration"
   ruff check src/ tests/
   ruff format --check src/ tests/
   mypy src/ai_billing_audit
   ```
6. **Update `CHANGELOG.md` under the `[Unreleased]`
   section.** (See the [Release process](#release-process)
   below for what makes it into each release.)
7. **Reference the issue** in the PR body with
   "Closes #NNN" or "Refs #NNN".
8. **Be patient with review.** The maintainer is
   part-time; first response is typically within
   2 business days.

### Commit-message style

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

<body explaining the *why*, not the *what*

<footer with "Closes #NNN" or "Refs #NNN">
```

Common `<type>`s: `feat`, `fix`, `docs`, `refactor`, `test`,
`chore`, `infra`. Common `<scope>`s: `api`, `portal`,
`auditor`, `caddy`, `deploy`, `docs`, `db`.

The "what" is in the diff. The "why" — what trade-off you
made, what alternative you considered — is the part the
reviewer actually needs to make a decision on.

### What we will NOT accept

- Changes to `data/val_ca.json`, the v12 auditor prompt,
  the production `Dockerfile`, or the production
  `deploy-to-vps.sh` outside of a release-cut PR. These
  files are the levers we use to ship; touching them
  casually breaks the audit trail.
- New top-level dependencies without an explanation of
  why `pyproject.toml`'s existing deps don't already
  cover the use case.
- "Drive-by" reformats of large files. A PR that mixes a
  feature with a 500-line whitespace-only reformat will
  be asked to split.

---

## Release process

1. Bump the version in `pyproject.toml`.
2. Move the `[Unreleased]` section in `CHANGELOG.md`
   into a dated release section (`[X.Y.Z] — YYYY-MM-DD`).
3. Cut a release branch: `release/vX.Y.Z`.
4. Tag the merge commit: `git tag -a vX.Y.Z -m "..."`.
5. Deploy via `deploy-to-vps.sh` against the staging VPS
   first, then production.
6. Update the supported-versions table in `SECURITY.md`
   if a `0.X.0` line is now EOL.

The 0.5.0 release cut is the reference example; the
`CHANGELOG.md` entry explains the shape of the
"Features / Bug fixes / Infrastructure / Documentation"
grouping that every release uses.

---

## Where to get help

- **Documentation:** the `README.md` quickstart, the
  `apps/portal/AGENTS.md` rules, and the
  `README.design-history.md` design log.
- **Bugs and features:** the GitHub issue tracker.
- **Security:** `security@zorva.ca` (see
  [`SECURITY.md`](./SECURITY.md)).
- **Email the maintainer:** the address in
  `pyproject.toml`'s `authors` block.

---

_Last updated: 2026-06-24 — covers the `0.5.x` release line._
