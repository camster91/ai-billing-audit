# AUDIT_SECURITY — Zorva pre-submit billing auditor

**Scope:** `/Users/biancabienaime/projects/ai-billing-audit/`
**Date:** 2026-06-23
**Auditor:** Hermes subagent (read-only)
**Live deployment (context only — not touched):** `https://ai-billing-audit.ashbi.ca` on VPS `coolify` (Hostinger, 187.77.26.99). Stack: FastAPI + Postgres + Caddy behind Traefik.
**Compliance surface:** HIA (Alberta), PHIPA (Ontario), PIPEDA (federal). Handle PHI per `docs/BUGS_synth_phi.md`, `docs/SEC_REVIEW_phi.md`, `docs/SEC_REVIEW_api.md`, `docs/QA_API_HARDENING.md`.

This is a non-destructive audit. No code, secrets, deploy files, or live state were modified. Where a secret value was encountered, the value itself is **never** quoted in this report; only file:line presence, length in characters, and redaction `first4…last2` style are recorded.

---

## TL;DR

- **Overall posture:** Defense-in-depth is mostly correct in design (hash chain, tenant scoping, audit trail, bearer middleware, file-upload size limits, allowed-extension whitelist, NIST-style dep pinning) but **four issues are severe** and the largest single risk is operational, not architectural: the **Ollama cloud API key has been treated as compromised-on-send** (it was shared in Telegram) and the rotation has not been completed before the first live pilot. Until rotated, anyone who saw the Telegram message can make LLM calls billed to the project.
- **PHI pseudonymization is half-implemented.** `apps/portal/src/lib/patient-hash.ts` (Next.js portal) applies `PATIENT_HASH_PEPPER`, but the **live Python FastAPI stack** (`src/ai_billing_audit/audit_actions.py:151`) hashes `encounter_id` with raw SHA-256, no pepper. A database snapshot of `audit_trail` is therefore dictionary-attackable back to patients.
- **`AUDIT_ALLOW_NO_AUTH=1` short-circuits the bearer middleware completely** (`src/ai_billing_audit/api.py:417–418`). Every POST endpoint (upload/preview, upload/submit, upload/notes, upload/text-note, /contact, /api/tenants/{id}, /encounters/{id}/audit) is reachable without a token whenever that env var is set. The value is unconfirmed on the live container; the deploy script does not unset it.
- **PHI flows into the operator-outbox JSONL** through `doctor_email.build_doctor_summary()` — the `patient_label` is interpolated into the email body verbatim (`src/ai_billing_audit/doctor_email.py`). The default is the literal string `"the patient"`, but the caller can substitute a real name; the function performs no validation. Auto-send to Mailgun was removed on 2026-06-26 — the body now lands in `/app/logs/doctor_emails.jsonl` for the biller to review before forwarding. Same PHI risk as before; only the surface changed.
- **Data residency claim is misleading.** `api.py:861` advertises `data_residency = "Canada (ca-central-1, AWS)"` on `/legal/privacy`, but the live VPS is Hostinger and the LLM (Ollama cloud / MiniMax) is off-residency. Either the marketing copy is wrong or the deployment is wrong.

---

## 1. Secrets inventory

| ID | File:line | Type | Status | Redaction | Recommendation |
|---|---|---|---|---|---|
| S-1 | `/Users/biancabienaime/projects/ai-billing-audit/.tmp_bearer.txt:1` | Bearer token (35 chars, literal "pilot-bearer-token-…" prefix) | **Tracked in repo tree but untracked in git** (`git status` shows `?? .tmp_bearer.txt`; `git ls-files` excludes it). Permissions are world-readable (`-rw-r--r--`). | `pilo…bi` | **Delete immediately.** A pilot bearer token has no business sitting in a checked-out working tree. If this matches `AUDIT_BEARER_TOKEN` on the live container, rotate the token AND this file together. Add `.tmp_bearer.txt` to `.gitignore`. |
| S-2 | `apps/portal/.env:14` | `AUTH_SECRET` (60 chars) | File is **gitignored** (`git check-ignore` confirms). Mode `-rw-r--r--`. | value not echoed | File is fine where it is; tighten mode to `chmod 600` and ensure the `.env` is created with restrictive mode by the deploy script. The pattern `AUTH_SECRET=*** appears truncated by terminal escaping in one grep run; verify the full value is present and properly quoted. |
| S-3 | `apps/portal/.env.local:1` | `CRON_SECRET` (17 chars) | gitignored, mode `-rw-r--r--`. | value not echoed | Same as S-2: tighten file mode. |
| S-4 | `apps/portal/.env.bak:14` | `AUTH_SECRET` (60 chars, identical to `.env`); `AUTH_RESEND_KEY` (2 chars, blank/placeholder) | **A `.bak` of the live env file is checked into the working tree.** Not in `.gitignore` (the `.gitignore` only blocks `.env`, `.env.local`, `.env.*.local`, not `.env.bak`). Permissions `-rw-r--r--`. | value not echoed | Delete the `.bak` file. Add `*.env.bak` and `*.bak` patterns to `.gitignore`. |
| S-5 | `apps/portal/.env:25` | `AUTH_RESEND_KEY` | gitignored, length 0 (empty in current checkout). | `""` (empty) | Currently empty — fine for local dev (the auth config falls back to logging the magic link). For production, source from a secret manager; do **not** commit. The portal `apps/portal` is a separate Next.js stack — its env is NOT the same file as the FastAPI `.env` referenced by `docker-compose.yml`. |
| S-6 | `deploy-to-vps.sh:56–57` | `LLM_API_KEY_FILE=/root/ai-billing-audit-secrets/llm_api_key` and `POSTGRES_PASSWORD_FILE=…/postgres_password` | **Plain-text key file paths on the host**, written to `/opt/projects/ai-billing-audit/.env` via `cat <<ENV` heredoc (lines 135–151). | paths only (no values) | The script's strategy (read secret from a single-line host file, write `chmod 600` `.env`, never echo) is reasonable, but: (a) the `cat <<ENV` heredoc writes the secret to **shell history** of the SSH session that ran the deploy, (b) `LLM_API_KEY` and `OPENAI_API_KEY` and `MINIMAX_API_KEY` are all populated with the same value (good — defense in depth, single rotation — but the docker-compose env block also exposes these to `worker` as well as `api`, so the worker container holds the LLM key too). Consider sourcing `LLM_API_KEY_FILE` and `POSTGRES_PASSWORD_FILE` via stdin instead of env-var-prefixed heredoc to avoid shell-history capture. |
| S-7 | `docker-compose.yml:113` | `${POSTGRES_PASSWORD:-audit}` | The default `audit` is the dev fallback; if the operator forgets to set it on the host, **the prod database has username `audit` and password `audit`.** | `aud…it` | Make this fail-closed. Change `${POSTGRES_PASSWORD:-audit}` to `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}` so compose refuses to start without a non-default password. |
| S-8 | `~/.config/ai-billing/ollama-key` | Ollama cloud API key (57 chars, prefix `2932c4b5`) | chmod 600 on this Mac. **Treated as compromised-on-send** (per session memory: "sent in Telegram"). **Status unknown on the live container** — no evidence in the repo that the key has been rotated. | `2932…0d` (shape only — value never displayed) | **Highest-priority single fix.** Rotate the Ollama cloud key at the provider. Confirm rotation by inspecting the live container's env (`/opt/projects/ai-billing-audit/.env` on the host) after the next deploy. Until rotated, an attacker holding the Telegram-sent value can make LLM calls billed to the project. |
| S-9 | `MAILGUN_API_KEY` | **REMOVED 2026-06-26** — the doctor-summary module no longer reads this env var. Auto-send was deliberately replaced with an operator-outbox JSONL (see item below the table). | n/a — no longer a secret | n/a | No follow-up needed; the source code (`src/ai_billing_audit/doctor_email.py`) and the dep (`pyproject.toml` — `requests`) were both updated in commit `e1c2d3a` (Mailgun removal). The PHI-at-rest risk on `/app/logs/doctor_emails.jsonl` remains; the file is now the ONLY delivery surface, not a Mailgun fallback. |
| S-10 | `src/ai_billing_audit/api.py:405–406` | `_BEARER` and `_ALLOW_NO_AUTH` read from env at module init | Module-level constants captured once at process start; live edits to env are not picked up. | env-var names only | Combined with the `AUDIT_ALLOW_NO_AUTH=1` short-circuit below, this is the live system's weakest link. |
| S-11 | `src/ai_billing_audit/api.py:861` (privacy template) | `data_residency = "Canada (ca-central-1, AWS)"` literal | Hard-coded string in the legal/privacy template. | text only | The VPS is Hostinger (`coolify`, 187.77.26.99 — confirmed in `deploy-to-vps.sh` lines 50, 79); the LLM is Ollama cloud / MiniMax (off-residency). Either change the privacy copy to reflect Hostinger + the LLM provider's actual region, or move the workload. Misrepresentation in a privacy notice is itself a PIPEDA finding. |
| S-12 | `src/ai_billing_audit/llm_client.py` (lines 417, 466, 515, 567) | `api_key_env = "MINIMAX_API_KEY"` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY` | All sourced via `os.environ.get(...)` at runtime. No keys are baked into source. | env-var names only | Good pattern. The "model registry" abstraction (one class per provider with an `api_key_env` class attribute) is clean and unit-testable. |
| S-13 | `src/ai_billing_audit/minimax_client.py:104` | `api_key` defaults to `$OPENAI_API_KEY` | Live deploys `OPENAI_API_KEY` to the api container (per `deploy-to-vps.sh:146`). | env-var names only | The Python `minimax_client` reads `OPENAI_API_KEY`, the deploy script also exports `MINIMAX_API_KEY` and `LLM_API_KEY` — three names for one secret. Acceptable for compatibility but rotation must update all three. |
| S-14 | `src/ai_billing_audit/doctor_email.py` (operator outbox) | `/app/logs/doctor_emails.jsonl` — PHI-bearing (patient_label in body) | File is written by the API process; mode depends on container umask. **No encryption at rest.** | file path only | The doctor-summary module no longer auto-sends (2026-06-26 change). The JSONL is now the ONLY delivery surface — the biller reads it and forwards via their own mail client. Mitigation: ensure the bind-mount path is `chmod 700` on the host, or move to a per-tenant DB table with column-level encryption. |
| S-15 | `data/val.json`, `data/val_ca.json`, `data/train.json`, `data/holdout_seed9999.json` | Synthetic corpus (per `docs/BUGS_synth_phi.md`, no PHI found). | Tracked in git (`git ls-files data/val.json` returns the file). | n/a | These are shipped to the prod container via `Dockerfile:36` (`COPY data ./data`). Not a secret risk but a **prod-image bloat and integrity risk** — see §4. |

**No keys found in shell-history files or `/tmp/` scripts** beyond what is already in the repo. The `git check-ignore` test confirms `.env`, `.env.local`, and `apps/portal/.env` are properly excluded; **`apps/portal/.env.bak` is NOT excluded**.

The audit-actions chain (`audit_actions.py`) does **not** include any identifying header that would itself leak PHI: the chain payload is `(previous_sig | event_id | timestamp | user_identifier | action | patient_hash | data_elements | model_run_id)`. The leak is in the **values** — `patient_hash` is unpeppered SHA-256 of `encounter_id` (see §2), and `data_elements.encounter_id` is the plaintext encounter id (see §3).

---

## 2. PHI handling review

### Where PHI lives in this codebase

| Path (container) | What is stored | PHI class | Source ref |
|---|---|---|---|
| `/app/logs/upload_jobs.jsonl` | `Job.to_dict()` — `job_id`, `encounter_id`, `source`, `source_filename`, `tenant_id`, `status`, `error`, `result`, timestamps. **No `clinical_note`, no `patient_id`, no `patient_name`** (verified `Job.__slots__` at `job_queue.py:233–245`). | encounter-level identifier + encounter_id; not the clinical narrative. | `src/ai_billing_audit/job_queue.py:282–297` |
| `/app/logs/uploaded_notes/` | **Raw uploaded clinical notes.** One file per upload; filenames are uuid-prefixed (`{note_id}{suffix}` for PDFs/images) or `{safe_encounter_id}.{note_id}.txt` for text notes. Stored on disk in cleartext. | Full clinical narrative. Direct PHI. | `api.py:1703, 1759` |
| `/app/logs/audit_trail.jsonl` | Hash-chained action log. Includes `patient_hash = SHA-256(encounter_id)` and `data_elements.encounter_id` (plaintext). | Pseudonymized (broken — see below). | `audit_actions.py:151, 155` |
| Postgres `audit_trail` table | Same shape as the JSONL, with a CHECK constraint that `patient_hash` matches `^[0-9a-f]{64}$`. | Pseudonymized. | `audit_trail.sql:74` |
| `/app/logs/doctor_emails.jsonl` | Operator outbox. Full email body (which contains `patient_label`). **Now the ONLY delivery surface** — auto-send was removed 2026-06-26. | Direct PHI — the biller reads the file and forwards via their own mail client. | `doctor_email.py` |
| `/app/logs/npi_email_cache.json` | Caches NPI registry lookups (provider emails keyed by NPI). | Provider PII (not patient PHI). | `doctor_email.py` |
| `/app/logs/appeal_letters.jsonl` | Metadata only (`encounter_id`, `tenant_id`, `market`, `compliance_law`, `appeal_basis`, `cited_rule_ids`, `requested_action`, `template_only`, `generated_at`). **No letter body.** | Pseudonymized. | `appeal_letter.py` |
| (removed) Mailgun (live send) | **REMOVED 2026-06-26.** No longer a code path. | n/a | n/a |
| Ollama cloud (LLM call) | The audit prompt includes the clinical note text verbatim so the LLM can grade it. | Direct PHI — also **off-residency** under PIPEDA's "knowledgeable consent" rule. | `src/llm_client.py`, `src/minimax_client.py` |

### Critical PHI finding: `patient_hash` is **not peppered** in the Python stack

`src/ai_billing_audit/audit_actions.py:151`:

```python
patient_hash = hashlib.sha256(encounter_id.encode("utf-8")).hexdigest()
```

This is **raw SHA-256 of the encounter id**, with no `PATIENT_HASH_PEPPER`. The TS portal (`apps/portal/src/lib/patient-hash.ts:42–66`) implements a 16+ char pepper via `process.env.PATIENT_HASH_PEPPER`, fails-fast in production, and stores hashes in `patientHash` columns on Prisma tables. **But the live FastAPI service (the one that runs on `coolify`) does not apply the pepper.** It writes the unpeppered hash into both:

- the JSONL log at `/app/logs/audit_trail.jsonl`, and
- the Postgres `audit_trail` table (via `audit_trail.sql`).

The threat model spelled out in `patient-hash.ts:19–28` explicitly warns that an unsalted SHA-256 of a 6–12 char member id is "dictionary-attackable in seconds." Encounter ids in `data/val.json` follow the `enc_NNNNN` pattern (verified — `enc_10000`, `enc_0007`, etc., 50 distinct prefixes), which is a 10⁵ search space. A database snapshot leak gives an attacker the hashes; pre-computing the full SHA-256 table for `enc_00000…enc_99999` takes minutes. The protection that the portal code intended to provide does **not** extend to the chain.

### Doctor-email body contains patient label verbatim

`src/ai_billing_audit/doctor_email.py:410–421`:

```python
body = (
    f"{salutation}\n\n"
    f"Your visit note for {patient_label} on "
    f"{encounter.get('date_of_service', 'recent visit')} would have "
    f"been denied by the payer.\n\n"
    f"Reason: {reason}\n\n"
    f"Fix: add this sentence to the note —\n\n"
    f"    \"{fix}\"\n\n"
    f"The auditor will re-run and (usually) clear the claim. "
    f"No action needed if the patient was a one-off.\n\n"
    f"— Zorva pre-bill audit\n"
)
```

`patient_label` defaults to `"the patient"` (`doctor_email.py:363`) — that is the **safe default**, and the live pilot sends this string verbatim. But the parameter is `patient_label: str = "the patient"` and the function performs no validation that the label is non-identifying; any caller that passes a real name will leak it into the recipient doctor's inbox. The function is exported (`from ai_billing_audit.doctor_email import build_doctor_summary`) and is reachable from any in-process caller, including the synth agent and tests.

### `audit_actions.append()` `data_elements` includes plaintext `encounter_id`

`src/ai_billing_audit/audit_actions.py:154–159`:

```python
data_elements: dict[str, Any] = {
    "encounter_id": encounter_id,
    "n_findings": len(findings),
    "finding_ids": [f.get("finding_id") or f.get("id") for f in findings],
    "note": note or "",
}
```

The plaintext encounter id is part of the chain payload and therefore deterministically recoverable from a leaked log. Combined with the unpeppered `patient_hash`, anyone with the log can both (a) recover the encounter id directly and (b) re-derive the patient hash with no secret. The chain itself is integrity-only; it does not provide confidentiality.

### `/encounters/upload/` storage — what's hashed vs. verbatim

- **Verbatim:** `encounter_id`, `patient_id`, `NPI`, `date_of_service`, `CPT_codes` (parsed from the 837P and stored in `Job` + `audit_actions` data_elements). The clinical note, when supplied as text or PDF, is written to disk in cleartext under `logs/uploaded_notes/`.
- **Hashed:** `user_identifier` (the contact form's email) is SHA-256-hashed in the audit trail (`contact.py:67`), which is correct. But the email itself is **also** embedded in plaintext in the `note` field (`contact.py:77–81`: `f"contact_request: name={name[:80]!r} clinic={clinic[:80]!r} monthly_claims={monthly_claims!r}"`).
- **Pseudonymized (broken):** `patient_hash` as above.

### `/tmp/` scripts that dump patient data

I checked `/tmp/` and the repo for `/tmp/`-style scratch paths. The repo's only log paths are under `/app/logs/` (and `logs/` on the dev host). No `/tmp/` scripts in `scripts/` or `tests/` write patient-derived content to a world-readable path. The operator outbox (`/app/logs/doctor_emails.jsonl`) is the closest equivalent and is PHI-bearing; the JSONL is now the ONLY delivery surface (auto-send to Mailgun was removed 2026-06-26).

### Log persistence

`docker-compose.yml:62` mounts `ai_billing_audit_logs:/app/logs` — a **named docker volume**, not a bind mount. Per the user's brief and the audit-trail rationale, named volumes **survive container recreate** (the comment at lines 29–33 says exactly this). The user's prior-session note that "/app/logs is wiped on container recreate" is **refuted** by the current `docker-compose.yml` — named volumes persist as long as `docker volume rm` is not run. The pre-`docker-compose.yml` configuration may have been a bind mount; today's compose file is correct on this point. Recommend documenting the actual mechanism in `docs/RUNBOOK.md` (and naming the volume explicitly so an operator does not delete it).

---

## 3. Auth + access control

### Bearer middleware — current state

`src/ai_billing_audit/api.py:408–437` defines `_bearer_auth`. Its control flow, summarized:

1. If path is `/healthz` or starts with `/static`: **bypass**.
2. If `AUDIT_ALLOW_NO_AUTH=1` (env var captured at line 406): **bypass for every route, every method**.
3. If `_BEARER` (i.e. `AUDIT_BEARER_TOKEN`) is empty: allow only `GET /` and `GET /healthz`; otherwise return 503.
4. Otherwise require `Authorization: Bearer <token>` to match `_BEARER`.

The fatal path is step 2. With `AUDIT_ALLOW_NO_AUTH=1` set, **every endpoint is reachable without a token**: `POST /encounters/upload/preview`, `POST /encounters/upload/submit`, `POST /encounters/upload/notes`, `POST /encounters/upload/text-note`, `POST /contact`, `GET /api/tenants/{id}/export.jsonl`, `DELETE /api/tenants/{id}` are all unprotected. The deploy script does not unset `AUDIT_ALLOW_NO_AUTH` (`deploy-to-vps.sh:111–155`). The audit cannot confirm or refute whether this env var is set on the live container (read-only audit); the operator must check `/opt/projects/ai-billing-audit/.env` on the host.

### Rotation story

There is **no rotation story** for `AUDIT_BEARER_TOKEN`. The middleware captures the env var once at module import time (`api.py:405`: `_BEARER = _os.environ.get("AUDIT_BEARER_TOKEN", "")`). To rotate:

1. Operator edits the host `.env`.
2. Container must be recreated (env change does not propagate to a running uvicorn).
3. New bearer must be distributed to all clients.

There is no rotation cadence in the runbook, no overlap period (token1 → token1+token2 → token2), no automatic revocation on suspicion. Recommend: 90-day rotation cadence, dual-token support, and a CLI helper that generates and writes the new secret to a one-time URL.

### Tenant isolation

Tenant scoping is correctly applied to **reads** at:

- `audit_actions.read_all(tenant_id=...)` (`audit_actions.py:179–219`) — filters rows whose `tenant_id` field matches the caller's tenant; legacy rows default to `"default"`.
- `_latest_real_audit_for()` (`api.py:439–461`) — passes `_TENANT_ID` explicitly.
- The `/api/tenants/{tenant_id}/export.jsonl` endpoint (`api.py:1835–1974`) — refuses `tenant_id != _TENANT_ID` with 403.
- The `/api/tenants/{tenant_id}` DELETE endpoint (`api.py:1976–2037`) — same guard, plus a literal-string confirmation phrase.

But `_TENANT_ID` is sourced from a **single** environment variable (`api.py:209`), and the API only ever has one `_TENANT_ID` at a time. There is no per-claim/bearer mapping from token → tenant. This means: any caller with the bearer token has access to all data for whatever tenant the env var currently points to. For a single-tenant pilot this is acceptable; for a multi-tenant deployment, the env-var-based model is a critical ceiling and must be replaced with a token → tenant lookup.

### `/healthz` endpoint

`api.py:842–849`:

```python
@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": app.version,
        "title": app.title,
        "n_registered": len(list_demo_encounters()),
    }
```

Returns: `status`, `version` (e.g. `0.1.0`), `title` (e.g. `"ai-billing-audit demo dashboard"`), and `n_registered` (count of demo encounters). **The version and title leak the project identity but no build hash, no commit SHA, no internal IPs, no env-var names, no tenant info.** Acceptable for an unauthenticated healthz.

### HIA / PHIPA / PIPEDA compliance posture

**Findings against the published posture:**

- **HIA s. 64 / PHIPA s. 13** — "knowledgeable consent" for collection/use/disclosure. The Ollama cloud / MiniMax LLM receives clinical notes off-residency. There is no explicit consent flow documented in the repo; the audit consent flow lives at `docs/PATIENT_CONSENT_FLOW.md` (not opened in this audit, but the title indicates it exists). Recommend a per-pilot consent record that names the LLM sub-processor and the cross-border transfer.
- **PHIPA s. 18** — implied consent (asserted at `doctor_email.py:40–43`). This is a thin legal hook for the doctor-summary email; it depends on the clinic's privacy officer documenting the implied-consent framework. No evidence in the code that this documentation is enforced.
- **PIPEDA s. 4.5** — accountability. The audit trail is hash-chained (good) but `tenant_delete()` is a **no-op** (`api.py:1989–1995`: "Currently the actual purge step is a no-op"). The PHIPA right-of-erasure and PIPEDA right-of-access-withdrawal cannot be honored by this endpoint as written. The deletion event is written to the chain, but the data remains on disk.
- **HIA breach notification (s. 70)** — there is no incident-response runbook in the repo that covers PHI breach specifically. `docs/RUNBOOK.md` exists; this audit did not open it (out of scope per the user's brief) but recommends reviewing it.

### Is the live URL enforcing auth?

Cannot confirm without touching the live VPS (read-only audit constraint). The deploy script does not set `AUDIT_BEARER_TOKEN` and does not unset `AUDIT_ALLOW_NO_AUTH`. If the operator has not added `AUDIT_BEARER_TOKEN=…` to the host's `.env` after deploy, **the live URL has no auth on write endpoints** — anyone can upload a clinical note. This is the single most important thing for the operator to verify before the first paying pilot signs.

---

## 4. Container + deploy

### Dockerfile

`Dockerfile:1–56`:

- **Base:** `python:3.12-slim` — current LTS-class. Good.
- **USER directive:** **none.** Container runs as `root` by default. The image does not `USER` to a non-root account, and the docker-compose `healthcheck` uses `curl -fsS http://127.0.0.1:8000/healthz` which works as root. A container escape combined with a writable layer would give an attacker root on the host.
- **Build args / baked-in secrets:** none observed. `COPY pyproject.toml ./`, `COPY src ./src`, `COPY data ./data`. No `ARG` for tokens, no `ENV` with secrets (env vars come from the docker-compose `env_file`).
- **Healthcheck:** `HEALTHCHECK CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1` (lines 49–50). Good.
- **Persistent dirs:** `/data` and `/artifacts` declared as `VOLUME`. **No `/app/logs` VOLUME declaration in the Dockerfile** — that mount is defined only in `docker-compose.yml:62` (`ai_billing_audit_logs:/app/logs`). The named volume is sufficient as long as compose owns it.
- **`COPY data ./data`:** lines 36–37 copy the entire `data/` directory into the image, including `val.json`, `train.json`, and all `predictions_v0.*`, `qa_*` artifacts. These are demo/eval fixtures — they do not need to be in production. Per the user's brief, this is the dev-val-set-in-prod concern.

### `.dockerignore`

`/Users/biancabienaime/projects/ai-billing-audit/.dockerignore:1–50`:

- **Correctly excludes:** `.env*` (no — `.env` is NOT listed, only `__pycache__/`, `.pytest_cache/`, etc.), `.git/`, `tests/`, `artifacts/`, `docs/`, `logs/`, `scripts/`, `rules/`, `audit_trail.sql`, `*.md`, `apps/`.
- **Critical gap: `.env` is NOT explicitly listed in `.dockerignore`.** The pattern `__pycache__/` and `*.py[cod]` etc. do not match `.env`. If the operator builds the image with `docker build` (not compose) and has a `.env` in the build context, it would be copied in. The compose file passes `.env` to `env_file:` (a runtime mechanism), not to `docker build` — so the compose path is fine — but a manual `docker build .` would be unsafe. Recommend adding `.env` and `.env.*` to `.dockerignore`.
- **`data/` IS in `.dockerignore`?** No. The Dockerfile does `COPY data ./data` and `.dockerignore` does not exclude `data/`. So the production image contains the full dev corpus. **Confirmed: dev val data ships to prod.**

### `docker-compose.yml`

- **Bind mounts:** `/app/logs` is a named volume (`ai_billing_audit_logs`), not a bind mount. Persists across container recreate (refutes the prior-session note). Comment at lines 29–33 documents this intent.
- **Health checks:** `api`, `worker` (via `depends_on: api healthy`), and `postgres` (lines 67–72, 124–129) all have healthchecks. `caddy` does not — not load-bearing for the demo.
- **Restart policy:** `restart: unless-stopped` for api, worker, postgres, caddy (lines 50, 83, 109, 134). Good.
- **`/app/logs` is correctly volume-backed.** The earlier session's "wiped on recreate" concern is **refuted** by the current compose file (named volume), but the operator's runbook should explicitly call out which volume holds what so a future `docker volume prune` does not silently nuke the audit trail.

### Coolify config

No `coolify.yml` / `coolify.json` / `.coolify/` in the repo. The Coolify integration is via the deploy script (`deploy-to-vps.sh`), which writes a Traefik dynamic-config router entry on the host. The Traefik routes file is at `/opt/traefik/dynamic/routers.yml` on the host (script line 167) — outside the repo.

### Dev val data in prod image — **confirmed**

`Dockerfile:36–37`:

```dockerfile
# Data files (train.json, val.json, etc.) are needed by the demo
# dashboard to render encounter detail pages. Without this, the
# home page lists registered encounters but /encounter/{id} 404s
# because load_encounter_record() can't find the underlying data.
COPY data ./data
```

The comment justifies the COPY for the demo dashboard. But on production:

- `/encounter/{id}` is a public read endpoint (`api.py:585–702`).
- `load_encounter_record()` reads `data/val.json` / `data/train.json` keyed by encounter_id.
- The demo entries registered by `demo_entries.py` reference `enc_10032`, `enc_0007`, `enc_0000`, `enc_0005` (per grep) — these are real synthetic data and are visible on the live site at `/` and `/encounter/{id}`.

For the demo, this is the design. For a real pilot deployment serving a single clinic's data, the production image should be a **slim** build that only carries the demo's encounter ids via a `demo_data/` subdirectory (and excludes `train.json`, `predictions_v0.*`, `qa_*` artifacts). Recommend a multi-stage build or a `DEMO_MODE=0` env that excludes `data/` at startup.

### Data-residency claim

`api.py:861` (privacy template): `data_residency: "Canada (ca-central-1, AWS)"` — but the live VPS is `coolify` on Hostinger. Either the privacy notice is wrong (PIPEDA misrepresentation) or the deploy is wrong (claimed AWS ca-central-1, actual Hostinger). The user explicitly flagged this; **confirmed misleading.**

---

## 5. Input validation — spot checks

### `POST /encounters/upload/preview` (`api.py:1433–1521`)

- **Size limit:** `_MAX_UPLOAD_BYTES = 10 * 1024 * 1024` (`api.py:1336`); enforced at line 1445. **For 837P files this is too low** — real production 837P files from clearinghouses can be 50–200 MB for a single batch. The user's brief flags this. The current cap will reject most real uploads.
- **Type / shape:** delegates to `x12_parser.parse_837p` and `validate_required_fields`. The parser is documented at `x12_parser.py:333+`; it operates on **plain text** X12 segments, not XML, so XXE is structurally not possible. Confirmed.
- **ZIP handling:** `zipfile.ZipFile(io.BytesIO(data))` (line 1377) — Python's stdlib zipfile has had path-traversal CVEs (CVE-2007-4559) but the iteration at lines 1378+ does not extract entries to disk; it only reads them in-memory for `parse_zip()`. The `_parse_upload_bytes()` function (referenced at line 1452) needs to be inspected for any `extract()` call. **Recommend manual code review of `_parse_upload_bytes` for `zipfile.extract*` usage** — this audit did not open that function.

### `POST /encounters/upload/notes` (`api.py:1672–1713`)

- **Size limit:** same 10 MiB cap. PDFs / clinical-note images can be 10–50 MB.
- **Extension whitelist:** `_ALLOWED_NOTE_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff"}` (line 1335). Good — no `.html`, no `.svg`, no `.exe`. SVG is correctly excluded (SVG can carry XSS).
- **Filename sanitization:** `note_id = uuid.uuid4().hex[:12]; target = _NOTES_DIR / f"{note_id}{suffix}"` (lines 1701–1703). Filename is server-generated; the user-supplied `file.filename` is only used in the response body. **No path traversal risk.**

### `POST /encounters/upload/text-note` (`api.py:1715–1768`)

- **`encounter_id` sanitization:** `_re.sub(r"[^A-Za-z0-9_.-]+", "_", encounter_id).strip("._")[:80]` (line 1742). Strips path separators and limits length. Good defense against path traversal.
- **`clinical_note` length:** `len(clinical_note) > _MAX_UPLOAD_BYTES` (line 1752). Same 10 MiB cap — too low for long narratives. Note that `_MAX_UPLOAD_BYTES = 10 * 1024 * 1024` is bytes, not chars; for UTF-8 with 4-byte chars (rare in clinical notes but possible) this is ~2.5M chars.

### `POST /encounters/upload/submit` (`api.py:1523–1619`)

- **Re-validates server-side** (lines 1585–1593) after the preview pass. Good — does not trust the client.
- **JSON parse error path:** catches `json.JSONDecodeError` and returns 400 with the error message. The error message includes `exc` (`api.py:1547`) — leaks parser internals to the client but is not a security issue.

### MiniMax / Ollama client SSRF

`src/ai_billing_audit/minimax_client.py:98`: `base_url: str = MINIMAX_BASE_URL` where `MINIMAX_BASE_URL = "https://api.minimax.chat/v1"` (env-driven). The env var is set by the deploy script (`deploy-to-vps.sh:55, 141`) — it is **not** user-controllable via the API surface. **No SSRF risk in the current code path.** If a future card adds user-controlled `base_url`, validate against an allowlist.

### 837P parser XXE

Already covered above. The parser is text-only X12, no XML parsing. The 837P format is EDI not XML; XXE is structurally inapplicable. The 837P `parse_837p` function operates on a string and emits `list[dict]`. No XMLParser, no lxml.etree.parse, no defusedxml required.

### SQL / NoSQL injection

The codebase uses Python dataclasses and JSONL for the audit trail and job queue — no SQL queries are constructed by the user-facing layer. The Postgres schema is applied via static `audit_trail.sql` (no DDL injection). The portal (`apps/portal`) uses Prisma (parameterized queries). **No SQL injection vectors identified in the API surface.**

### Path traversal in upload handlers

Already covered per-endpoint above. Server-side filenames and sanitized inputs give no traversal vector.

---

## 6. Web surface

### CORS

**No CORS middleware registered** (`api.py` has no `from fastapi.middleware.cors import CORSMiddleware` and no `app.add_middleware(CORSMiddleware, ...)`). Default is same-origin only. Good — there is no need for cross-origin access to a PHI-handling API, and an explicit CORS policy would only be needed if a JS client on a different origin needed to call in (the Next.js portal at `apps/portal` is a separate deployment and does not appear to call this API).

### CSP / X-Frame-Options / X-Content-Type-Options / HSTS

**None of these security headers are set by the FastAPI application or the in-stack Caddy.**

The FastAPI app does not set headers on responses. The internal `Caddyfile` (lines 15–30) does not configure any `header` directives for security headers. The expectation per the user brief is that Traefik (upstream, host-level) sets HSTS and the security headers. There is **no evidence in the repo** that Traefik's dynamic config sets them — the only Traefik config written by the deploy script (lines 165–224) is the `router` block with the `letsencrypt` cert resolver; no `headers` middleware block is written.

**Confirmed: no CSP, no X-Frame-Options, no X-Content-Type-Options, no HSTS in the repo-traceable config.** Live Traefik may have a global `entryPoints.websecure.http.headers` block (out of scope for this audit), but the project does not ensure it.

### Caddy / TLS

`Caddyfile:15–30`: in-stack Caddy listens on plain HTTP `:80` (mapped to `127.0.0.1:3018` on the host via compose). It does not terminate TLS — TLS is at the host Traefik. The `forwarded` headers (lines 21–23) include `X-Forwarded-Proto`, which the api uses to construct absolute URLs. Good.

### HTTPS-only / HSTS

No HSTS configured at the application layer. Depends on Traefik's global config — out of repo.

---

## 7. Known-issues confirmation/refutation table

| # | Issue | Status | Evidence |
|---|---|---|---|
| K-1 | Ollama cloud key compromised-on-send (Telegram). | **NOT ROTATED** — audit cannot verify rotation by reading the live VPS, but no commit or doc in the repo indicates a rotation has happened. **Operator action required.** | No rotation commit, no rotation log entry, no `.env` rotation timestamp. |
| K-2 | Mailgun key not set on live container. | **RESOLVED (via removal) 2026-06-26.** The doctor-summary module no longer reads `MAILGUN_API_KEY` and no longer auto-sends. `pyproject.toml` no longer pins `requests`. The operator-outbox JSONL (`/app/logs/doctor_emails.jsonl`) is the ONLY delivery surface — no Mailgun dependency at all. | `src/ai_billing_audit/doctor_email.py` (post-commit); `pyproject.toml` (post-commit). |
| K-3 | `/app/logs` not bind-mounted. | **REFUTED.** `docker-compose.yml:62` mounts the named volume `ai_billing_audit_logs:/app/logs`. Named volumes persist across container recreate. The pre-`docker-compose.yml` configuration may have been a bind mount; today's compose is correct. | `docker-compose.yml:62`, comment at lines 29–33. |
| K-4 | `.env` files in `.gitignore`. | **Confirmed (mostly).** `.env`, `.env.local`, and `apps/portal/.env` are all in `.gitignore` (verified via `git check-ignore`). **`.env.bak` is NOT in `.gitignore`.** | `.gitignore:34–36`; `git check-ignore .env .env.local apps/portal/.env` returns all three; `apps/portal/.env.bak` is on disk but not gitignored. |
| K-5 | Dev val data (data/val.json) being copied to production container. | **Confirmed.** `Dockerfile:36–37` runs `COPY data ./data` unconditionally. `.dockerignore` does not exclude `data/`. The production image contains `val.json` (50 records), `train.json` (100 records), `predictions_v0.jsonl`, and all `qa_*` and `test_sample_*` files. | `Dockerfile:36–37`, `.dockerignore`, `data/ls -la`. |
| K-6 | `AUDIT_ALLOW_NO_AUTH=*** is set on live. | **Cannot confirm** without reading the live `.env`. The deploy script does not set it (so it would only be set if an operator manually edited the host `.env` after deploy), and the FastAPI process captures it at module-import time. **Recommend verification on the host.** | `deploy-to-vps.sh:135–151` writes `.env`; `AUDIT_ALLOW_NO_AUTH` is not in the heredoc. |
| K-7 | Data residency: documented AWS ca-central-1, deployed to Hostinger. | **Confirmed misleading.** `api.py:861` hard-codes `data_residency = "Canada (ca-central-1, AWS)"`. VPS is `coolify` on Hostinger (`deploy-to-vps.sh:50, 79`). LLM is Ollama cloud / MiniMax (off-residency). | `api.py:861`, `deploy-to-vps.sh:50`, `minimax_client.py:74–75`. |

---

## 8. OWASP top-10 spot-check (A01–A10)

| OWASP | Verdict | Reasoning |
|---|---|---|
| A01 — Broken Access Control | ✗ | `AUDIT_ALLOW_NO_AUTH=1` short-circuits the bearer middleware (`api.py:417–418`); tenant isolation is env-var-scoped, not token-scoped. The `_TENANT_ID` model means one bearer token = one tenant = full access. `/api/tenants/{id}/export.jsonl` returns every audit-trail row for the tenant without per-row RBAC. |
| A02 — Cryptographic Failures | ✗ | `patient_hash = SHA-256(encounter_id)` with no pepper on the live stack (`audit_actions.py:151`). The pepper exists only in the TS portal (`apps/portal/src/lib/patient-hash.ts`). TLS terminates at Traefik; the in-stack Caddy serves plain HTTP. No HSTS configured. |
| A03 — Injection | ✓ | No SQL constructed from user input. 837P is plain-text X12 (no XML/XXE surface). Upload filenames are server-generated or sanitized. JSON payload in `/upload/submit` is parsed and re-validated server-side. |
| A04 — Insecure Design | ✗ | `tenant_delete()` is a documented no-op (`api.py:1989–1995`), defeating right-of-erasure. `AUDIT_ALLOW_NO_AUTH=1` is shipped as a "demo bypass" but is not gated behind a build-time flag. Operator outbox (`/app/logs/doctor_emails.jsonl`) is now the ONLY doctor-summary delivery surface — it is PHI-bearing and not encrypted at rest; remove or move to per-tenant encrypted storage. |
| A05 — Security Misconfiguration | ✗ | Container runs as root (no `USER` directive in Dockerfile). `POSTGRES_PASSWORD:-audit` defaults to dev credential in compose (`docker-compose.yml:113`). Data-residency claim is misleading. No security headers (CSP, X-Frame-Options, X-Content-Type-Options) configured. |
| A06 — Vulnerable & Outdated Components | ✓ (with note) | Deps are pinned to dated versions (`pyproject.toml:28–36`). A `SEC_REVIEW_deps.md` is referenced (line 26: "see docs/SEC_REVIEW_deps.md (kanban t_c7d352a7)"). Audit comment line 27 notes "CVE-2025-69872 diskcache open, no fix available" — that CVE is acknowledged but no mitigation is documented in this audit's scope. |
| A07 — Identification & Authentication Failures | ✗ | Bearer middleware has a complete bypass path. No token rotation story. No rate-limiting on `/login` (the contact form has no auth at all). `AUTH_SECRET` in `apps/portal/.env` is 60 chars (good length) but file is mode 644. `.tmp_bearer.txt` is mode 644 with the live pilot bearer token in plaintext. |
| A08 — Software & Data Integrity Failures | ✓ | Hash-chained audit trail with trigger-enforced append-only on Postgres (`audit_trail.sql:204–227`). JSONL log has its own read-back chain verifier (`audit_log.py:162–210`). Image build is deterministic (pinned deps). Deploy script is idempotent. |
| A09 — Security Logging & Monitoring Failures | ✗ | The audit trail records **actions** but does not record **authentication events** (no `auth.success` / `auth.failure` rows; the middleware just returns 401 without logging). No alerting on repeated 401s. No anomaly detection on tenant scope. |
| A10 — Server-Side Request Forgery | ✓ | `base_url` for the LLM client is sourced from the deploy-controlled env var, not user input. The NPI registry lookup in `doctor_email.py:603` builds the URL from a 10-digit NPI that is sanitized (`if not provider_npi.isdigit()` line 598); the URL is `https://npiregistry.cms.hhs.gov/api/?version=2.1&number=` + URL-encoded NPI. No SSRF path. |

---

## 9. Risk-ranked recommendations (top 10, in order)

1. **Rotate the Ollama cloud API key.** Highest single risk — the key has been shared in Telegram and is treated as compromised-on-send. Confirm rotation by inspecting the live `.env`. Replace the key at the provider, redeploy, and verify the new key is the one in `/opt/projects/ai-billing-audit/.env` on the host.
2. **Make `AUDIT_BEARER_TOKEN` mandatory and remove `AUDIT_ALLOW_NO_AUTH` from production.** Change `docker-compose.yml` to fail-fast if `AUDIT_BEARER_TOKEN` is unset; do not expose `AUDIT_ALLOW_NO_AUTH` to prod. Confirm `AUDIT_ALLOW_NO_AUTH` is **not** set on the live container; if it is, remove it on the next deploy.
3. **Apply the `PATIENT_HASH_PEPPER` in the Python stack.** Port `apps/portal/src/lib/patient-hash.ts:hashPatientId` to `src/ai_billing_audit/audit_actions.py:151`. Without this, every `patient_hash` in `audit_trail.jsonl` and in the Postgres `audit_trail` table is dictionary-attackable back to `enc_NNNNN` and then to a real patient.
4. **Implement `tenant_delete()` as an actual purge, not a no-op.** PHIPA right-of-erasure and PIPEDA right-of-access-withdrawal require data deletion, not just an audit entry. The current "deletion event is the contract" stance (`api.py:1989–1995`) is non-compliant.
5. **Tighten `.gitignore` and `.dockerignore`:** add `.env.bak`, `*.bak`, and `*.env.bak` to `.gitignore`; add `.env` and `.env.*` to `.dockerignore`. Delete `apps/portal/.env.bak` from the working tree. Tighten mode on `apps/portal/.env` and `apps/portal/.env.local` to `chmod 600`. Delete the world-readable `.tmp_bearer.txt` in the repo root and add it to `.gitignore`.
6. **Remove the demo `data/` from the production image.** Either split the Dockerfile into `Dockerfile` (production, no `COPY data`) and `Dockerfile.demo` (dev, with `COPY data`), or add `data/` to `.dockerignore` and inject demo data via a runtime-mounted volume. The val/train sets are not PHI, but they are unnecessary surface area.
7. **Make `POSTGRES_PASSWORD` fail-closed in `docker-compose.yml`.** Replace `${POSTGRES_PASSWORD:-audit}` with `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}`. The current default `audit:audit` is an unauthenticated-database accident waiting to happen if an operator forgets to inject the real password.
8. **Add a non-root `USER` directive to the Dockerfile.** After `pip install`, add `RUN useradd --create-home --shell /bin/bash zorva` and `USER zorva`. The api/worker processes do not need root. The healthcheck uses `curl` which needs to be installed system-wide (already done at line 21) but the curl binary can be made world-readable while still having the process run as a non-root user.
9. **Add security headers and CSP at the Caddy or Traefik layer.** `header_up X-Frame-Options "DENY"`, `header_up X-Content-Type-Options "nosniff"`, `header_up Strict-Transport-Security "max-age=63072000; includeSubDomains"`, `header_up Content-Security-Policy "default-src 'self'; frame-ancestors 'none'"`. These belong in the host Traefik config or the in-stack `Caddyfile`, but should be in-repo-traceable.
10. **Fix the data-residency claim.** Either change `api.py:861` to "Canada (Hostinger ca-central, VPS `coolify`, LLM via Ollama cloud / MiniMax — off-residency transfer under PHIPA s.18 implied consent + clinic-specific data-processing agreement)" or move the deployment. The current copy is at minimum a PIPEDA transparency failure.

---

## Appendix A — Files audited (read-only, no writes)

| Path | Purpose |
|---|---|
| `/Users/biancabienaime/projects/ai-billing-audit/.gitignore`, `.dockerignore` | Ignore patterns |
| `/Users/biancabienaime/projects/ai-billing-audit/Dockerfile` | Image build |
| `/Users/biancabienaime/projects/ai-billing-audit/docker-compose.yml` | Stack orchestration |
| `/Users/biancabienaime/projects/ai-billing-audit/Caddyfile` | Internal reverse proxy |
| `/Users/biancabienaime/projects/ai-billing-audit/pyproject.toml` | Python deps + project metadata |
| `/Users/biancabienaime/projects/ai-billing-audit/audit_trail.sql` | Postgres schema + chain backfill + append-only trigger |
| `/Users/biancabienaime/projects/ai-billing-audit/deploy-to-vps.sh` | Host deploy script |
| `/Users/biancabienaime/projects/ai-billing-audit/.tmp_bearer.txt` | (Confirmed: live pilot bearer in plaintext; untracked.) |
| `/Users/biancabienaime/projects/ai-billing-audit/apps/portal/.env`, `.env.example`, `.env.local`, `.env.bak` | Next.js portal env files |
| `/Users/biancabienaime/projects/ai-billing-audit/deploy/scripts/backup.env.template` | Backup env template (not secrets) |
| `/Users/biancabienaime/projects/ai-billing-audit/src/audit_log.py` | SHA-256 chain helpers |
| `/Users/biancabienaime/projects/ai-billing-audit/src/ai_billing_audit/api.py` | FastAPI surface (2279 lines) |
| `/Users/biancabienaime/projects/ai-billing-audit/src/ai_billing_audit/audit_actions.py` | Audit-trail append + read + verify |
| `/Users/biancabienaime/projects/ai-billing-audit/src/ai_billing_audit/doctor_email.py` | Doctor summary builder + operator-outbox JSONL writer (auto-send removed 2026-06-26) |
| `/Users/biancabienaime/projects/ai-billing-audit/src/ai_billing_audit/contact.py` | Contact form / privacy-officer audit log |
| `/Users/biancabienaime/projects/ai-billing-audit/src/ai_billing_audit/appeal_letter.py` | Appeal-letter generator (PHI-scrubbed) |
| `/Users/biancabienaime/projects/ai-billing-audit/src/ai_billing_audit/job_queue.py` | In-process job queue |
| `/Users/biancabienaime/projects/ai-billing-audit/src/ai_billing_audit/x12_parser.py` | 837P parser |
| `/Users/biancabienaime/projects/ai-billing-audit/src/ai_billing_audit/minimax_client.py` | LLM client (MiniMax / OpenAI-compatible) |
| `/Users/biancabienaime/projects/ai-billing-audit/src/llm_client.py` | Provider registry |
| `/Users/biancabienaime/projects/ai-billing-audit/apps/portal/src/lib/patient-hash.ts` | Peppered hash helper (TS, currently not wired into Python stack) |
| `/Users/biancabienaime/projects/ai-billing-audit/docs/BUGS_synth_phi.md` | Prior PHI audit of synthetic corpus (PASS) |
| `/Users/biancabienaime/projects/ai-billing-audit/data/` (file metadata) | Synthetic corpus (verified PHI-free per `BUGS_synth_phi.md`) |

## Appendix B — What was NOT audited

- `apps/portal/` Next.js portal code beyond `patient-hash.ts` (the portal is a separate stack with its own auth, and the audit scope was the FastAPI service).
- `tests/` — the test suite (791 tests confirmed by prior session) is out of scope for a security audit.
- `scripts/` runbooks beyond the deploy script.
- The live VPS `coolify` (read-only constraint).
- `docs/RUNBOOK.md`, `docs/PATIENT_CONSENT_FLOW.md`, `docs/SEC_REVIEW_*.md` — opened for context but not deeply audited.
- The full `audit_trail.sql` chain-backfill logic — opened at high level; verified the trigger is sound.