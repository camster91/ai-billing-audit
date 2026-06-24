# ai_billing_audit

Pre-submit medical-claim auditor — the FastAPI application that powers Zorva's
audit pipeline (encounter upload, LLM-driven review, audit trail, doctor
notifications, appeal generation).

This directory is the main application package. The customer-facing marketing
and checkout surface lives in `apps/portal/` and has its own README. The test
suite lives one level up in `tests/`.

## Package layout

- `__init__.py` — package marker; exports the public version string.
- `api.py` — FastAPI app, route registration, and module-level `app` object
  used by `uvicorn ai_billing_audit.api:app` (port 8765).
- `auditor.py` — LLM-based auditor agent; runs the prompt that decides whether
  a clinical note contains a billing finding.
- `llm.py` — single access layer for LLM calls; provider is selected by the
  `LLM_PROVIDER` environment variable. No other module may import provider SDKs.
- `job_queue.py` — in-process job queue driving the upload portal; orchestrates
  the synth agent and the audit pipeline per accepted file.
- `audit_actions.py` — append-only reviewer audit trail with a SHA-256 hash
  chain (`previous_signature || payload`) for tamper evidence.
- `doctor_email.py` — sends the plain-English "1-sentence fix" email to the
  authoring clinician when a flag-worthy finding is detected.
- `zorva_context.py` — per-market compliance context (rules, payer policies,
  downstream consumers) injected into the auditor prompt.
- `appeal_letter.py` — generates the formal payer appeal letter for a denied
  claim, citing CPT/ICD-10 and the audit finding.
- `x12_parser.py` — minimal ANSI X12 5010 837P parser; projects the relevant
  segments into the flat dict the upload endpoint expects.
- `ground_truth.py` — synthetic encounter dataset and a deterministic rule
  library used as the reference for the LLM auditor.
- `demo_entries.py` — per-difficulty demo encounter registrations shown on
  the index page; each demo card wires its encounter in here.
- `denial_risk.py`, `roi.py`, `contact.py`, `case_studies.py` — supporting
  feature modules (risk scoring, ROI calculator, contact form, case studies).

## Entry points

- **API server:** `uvicorn ai_billing_audit.api:app` (or `create_app()` for
  tests). Routes are registered inside `create_app()` in `api.py`.
- **Worker:** `python -m ai_billing_audit.worker` runs the background job
  consumer that pulls from `job_queue.py`.
- **Config:** environment variables (e.g. `LLM_PROVIDER`, `LLM_MODEL`); see
  module docstrings for the full list.

## Tests

Tests live in `tests/` at the repository root. Run them with:

```
pytest
pytest tests/test_auditor_module.py -q   # single file
```

Tests are written against the public module surface (no private imports).
