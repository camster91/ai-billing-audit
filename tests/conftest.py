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
