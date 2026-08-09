"""Tests for ``audit_logging.JsonFormatter`` + the LOG_FORMAT=json switch.

Structured JSON logs are the contract the production log shipper
(Loki / Datadog / CloudWatch) parses. These tests pin:

1. ``JsonFormatter`` produces valid JSON with the documented fields
   (ts, level, logger, msg, module, func, line, pid).
2. ``extra={...}`` fields merge into the top-level JSON object so
   callers can attach arbitrary structured data.
3. Exception tracebacks land under ``exc_info`` as a multi-line
   string (so Loki can index them).
4. ``LOG_FORMAT=json`` activates the formatter; ``LOG_FORMAT`` unset
   or set to anything else keeps plain text.
5. ``configure_json_logging_if_requested`` is idempotent — calling
   twice doesn't double-install handlers.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def clean_logger():
    """Yield a logger with no inherited handlers; tear down after."""
    logger = logging.getLogger("test.audit_logging")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    yield logger
    logger.handlers.clear()


def test_json_formatter_emits_core_fields(clean_logger):
    from ai_billing_audit.audit_logging import JsonFormatter

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    clean_logger.addHandler(handler)

    record = clean_logger.makeRecord(
        name="test.audit_logging",
        level=logging.INFO,
        fn="audit_logging.py",
        lno=42,
        msg="hello %s",
        args=("world",),
        exc_info=None,
        func="test_json_formatter_emits_core_fields",
    )
    out = handler.format(record)
    parsed = json.loads(out)
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test.audit_logging"
    assert parsed["msg"] == "hello world"
    assert parsed["module"] == "audit_logging"
    assert parsed["func"] == "test_json_formatter_emits_core_fields"
    assert parsed["line"] == 42
    assert isinstance(parsed["pid"], int)
    assert parsed["pid"] > 0
    assert "ts" in parsed
    # ts is ISO-8601 with millisecond precision and UTC tz
    assert parsed["ts"].endswith("+00:00")


def test_json_formatter_merges_extra_fields(clean_logger):
    """swarm-audit B-Test-4: previously this test assigned a value
    to a local variable but asserted nothing — it passed for any
    reason. Now it actually exercises the merge path and pins
    the contract: ``extra=`` keys land in the top-level JSON
    output (under their original names), not nested."""
    from ai_billing_audit.audit_logging import JsonFormatter

    # Capture the formatted output by hooking a fake stream
    class _Capture(list):
        def write(self, s):
            self.append(s)

        def flush(self):
            pass

    cap = _Capture()
    handler = logging.StreamHandler(cap)
    handler.setFormatter(JsonFormatter())
    clean_logger.addHandler(handler)

    clean_logger.info(
        "user action",
        extra={
            "user_id": "u-123",
            "action": "accept_finding",
            "n_findings": 4,
            "tenant_id": "default",
        },
    )

    raw = "".join(cap)
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    parsed = json.loads(lines[-1])
    # The extra keys must land at the top level, not nested under
    # an "extra" sub-object.
    for k in ("user_id", "action", "n_findings", "tenant_id"):
        assert k in parsed, (
            f"extra key {k!r} did not land at the top level; "
            f"got JSON keys: {list(parsed.keys())}"
        )
    assert parsed["user_id"] == "u-123"
    assert parsed["action"] == "accept_finding"
    assert parsed["n_findings"] == 4


def test_json_formatter_extra_merge_via_handler(clean_logger):
    from ai_billing_audit.audit_logging import JsonFormatter

    # Capture the formatted output by hooking a fake stream
    class _Capture(list):
        def write(self, s):
            self.append(s)

        def flush(self):
            pass

    cap = _Capture()
    handler = logging.StreamHandler(cap)
    handler.setFormatter(JsonFormatter())
    clean_logger.addHandler(handler)

    clean_logger.info(
        "user action",
        extra={
            "user_id": "u-123",
            "action": "accept_finding",
            "n_findings": 4,
        },
    )

    raw = "".join(cap)
    # The handler flushes per record; the last record is the one
    # we just emitted.
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    parsed = json.loads(lines[-1])
    assert parsed["user_id"] == "u-123"
    assert parsed["action"] == "accept_finding"
    assert parsed["n_findings"] == 4


def test_json_formatter_renders_exc_info():
    from ai_billing_audit.audit_logging import JsonFormatter

    cap: list[str] = []

    class _Cap(list):
        def write(self, s):
            self.append(s)

        def flush(self):
            pass

    cap = _Cap()
    handler = logging.StreamHandler(cap)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test.exc_info")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("operation failed")

    lines = [ln for ln in cap if ln.strip()]
    parsed = json.loads(lines[-1])
    assert parsed["level"] == "ERROR"
    assert "exc_info" in parsed
    assert "ValueError: boom" in parsed["exc_info"]
    assert "Traceback" in parsed["exc_info"]


def test_is_json_logging_enabled_reflects_env(monkeypatch):
    from ai_billing_audit import audit_logging

    monkeypatch.delenv("LOG_FORMAT", raising=False)
    assert audit_logging.is_json_logging_enabled() is False

    monkeypatch.setenv("LOG_FORMAT", "json")
    assert audit_logging.is_json_logging_enabled() is True

    monkeypatch.setenv("LOG_FORMAT", "JSON")
    assert audit_logging.is_json_logging_enabled() is True

    monkeypatch.setenv("LOG_FORMAT", "plain")
    assert audit_logging.is_json_logging_enabled() is False


def test_configure_json_logging_is_idempotent(monkeypatch):
    from ai_billing_audit import audit_logging

    monkeypatch.setenv("LOG_FORMAT", "json")
    # Reset module state so the test isn't sensitive to import order
    audit_logging._CONFIGURED = False
    try:
        result1 = audit_logging.configure_json_logging_if_requested()
        n_after_first = len(logging.getLogger().handlers)
        result2 = audit_logging.configure_json_logging_if_requested()
        n_after_second = len(logging.getLogger().handlers)
        assert result1 is True
        assert result2 is True
        # Second call must NOT add another handler
        assert n_after_first == n_after_second
    finally:
        audit_logging._CONFIGURED = False
        for h in list(logging.getLogger().handlers):
            logging.getLogger().removeHandler(h)


def test_configure_json_logging_noop_when_log_format_not_json(monkeypatch):
    from ai_billing_audit import audit_logging

    monkeypatch.delenv("LOG_FORMAT", raising=False)
    audit_logging._CONFIGURED = False
    result = audit_logging.configure_json_logging_if_requested()
    assert result is False
    # No JSON formatter should have been installed
    for h in logging.getLogger().handlers:
        assert not isinstance(h.formatter, audit_logging.JsonFormatter)


def test_json_safe_coercion():
    from ai_billing_audit.audit_logging import _json_safe

    assert _json_safe("hello") == "hello"
    assert _json_safe(42) == 42
    assert _json_safe({"a", "b"}) == ["a", "b"]  # set → sorted list
    assert _json_safe({"a", "b", "c"}) == ["a", "b", "c"]
    assert _json_safe(b"bytes") == "bytes"
    import datetime as _dt

    assert _json_safe(_dt.datetime(2026, 7, 4, 12, 0, 0)) == "2026-07-04T12:00:00"
    assert _json_safe(_dt.date(2026, 7, 4)) == "2026-07-04"
    assert _json_safe(ValueError("x")) == "ValueError: x"
    assert _json_safe(None) is None
