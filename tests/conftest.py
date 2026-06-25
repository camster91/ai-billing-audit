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
