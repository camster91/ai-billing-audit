"""Shared pytest fixtures and env defaults.

Sets ``AUDIT_ALLOW_NO_AUTH=1`` for the test session so the FastAPI
bearer-token middleware lets the test client through without needing
a real token. Also points the UX-polish log directory at a temp
location by default so it doesn't pollute the repo.
"""

from __future__ import annotations

import os


def pytest_configure(config):
    os.environ.setdefault("AUDIT_ALLOW_NO_AUTH", "1")
    # Some test runners carry APP_ENV=production or NODE_ENV=production
    # inherited from a CI parent. That makes ``patient_hash._is_production``
    # return True even in tests, which trips the production fail-fast
    # (32+ char pepper required). Force ``APP_ENV=test`` and drop
    # ``NODE_ENV`` so all patient_hash runs use the dev path unless a
    # specific test monkeypatches APP_ENV back to ``production``.
    os.environ["APP_ENV"] = "test"
    os.environ.pop("NODE_ENV", None)
    # Set a long-enough test pepper for the salted patient_hash so
    # the test runner inherits a working PATIENT_HASH_PEPPER value
    # regardless of what other env vars the test runner's parent
    # process may have leaked (some test runners carry APP_ENV or
    # NODE_ENV=production that would otherwise trigger the
    # production fail-fast). The pepper here is a 64-char constant
    # so the resolve_pepper length check passes. Individual tests
    # that need to assert production-mode behaviour monkeypatch
    # APP_ENV to "production" — the conftest value is just a
    # non-empty default so the test suite as a whole doesn't trip
    # the production fail-fast.
    os.environ.setdefault(
        "PATIENT_HASH_PEPPER",
        "test-pepper-do-not-use-in-production-1234567890",
    )
    # Default the ux_polish log dir to a temp location so tests don't
    # try to write to /app/logs. The test fixtures override this per-test
    # via monkeypatch for isolation.
    import tempfile

    os.environ.setdefault("UX_POLISH_LOG_DIR", tempfile.mkdtemp(prefix="ux-polish-test-"))
    # Default every clinical-impact JSONL log to /tmp/* so import-time
    # Path constants don't try to create /app/logs on a developer
    # laptop. The per-test fixtures override these.
    import uuid
    tmp_root = tempfile.mkdtemp(prefix=f"clinical-metrics-{uuid.uuid4().hex[:8]}-")
    for var, name in [
        ("DOCTOR_DASHBOARD_LOG", "doctor_dashboard.jsonl"),
        ("NOTE_SUGGESTION_LOG", "note_suggestions.jsonl"),
        ("OWNER_EMAIL_LOG", "owner_emails.jsonl"),
        ("SUBMIT_WEBHOOK_LOG", "submit_webhooks.jsonl"),
        ("FEEDBACK_LOOP_LOG", "feedback_loop_runs.jsonl"),
        ("TENANT_RULES_LOG", "tenant_rules.jsonl"),
        ("ONBOARDING_LOG", "onboarding.jsonl"),
        ("PRE_SUBMIT_BLOCKING_LOG", "pre_submit_blocking.jsonl"),
        ("BROWSER_EXTENSION_LOG", "browser_extension.jsonl"),
        ("SPECIALTY_MIX_LOG", "specialty_mix.jsonl"),
        ("BULK_ACCEPT_LOG", "bulk_accept_patterns.jsonl"),
        ("POSITIVE_FEEDBACK_LOG", "doctor_positive_feedback.jsonl"),
        ("FEEDBACK_LOG", "feedback.jsonl"),
        ("BILLER_CORRECTIONS_LOG", "biller_corrections.jsonl"),
        ("FINDING_COMMENTS_LOG", "finding_comments.jsonl"),
    ]:
        os.environ.setdefault(var, os.path.join(tmp_root, name))
