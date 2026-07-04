"""Structured JSON logging for ops aggregation.

The production log shipper (Loki / Datadog / CloudWatch) parses
JSON automatically. The default ``logging.basicConfig`` format is
human-readable plain text — fine for local dev, useless for
shippers that need to query by ``logger``, ``module``, or any
custom ``extra=`` field.

This module adds a :class:`JsonFormatter` that emits one JSON
object per log line. Set ``LOG_FORMAT=json`` in the environment
to switch the api + worker + every ``logging.getLogger(__name__)``
into JSON mode. Default is still plain text so local dev stays
readable.

Wire-up:

* :func:`configure_json_logging_if_requested` reads ``LOG_FORMAT``
  and installs the JSON formatter on the root logger. Idempotent.
* Any module can keep using ``logging.getLogger(__name__)`` and
  pass structured fields via ``logger.info("msg", extra={...})``.
  Those ``extra`` keys land in the JSON output as top-level fields.

Standard fields emitted:
  * ``ts`` — ISO-8601 UTC timestamp with millisecond precision
  * ``level`` — DEBUG / INFO / WARNING / ERROR / CRITICAL
  * ``logger`` — fully-qualified logger name (e.g. ``ai_billing_audit.api``)
  * ``msg`` — the formatted message (no ``extra`` interpolation)
  * ``module`` / ``func`` / ``line`` — source location
  * ``pid`` — process id
  * ``exc_info`` — exception traceback as a string when present

Everything from ``extra={...}`` is merged into the top-level JSON
object. Use snake_case keys so the shipper can index them
predictably.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import threading

__all__ = [
    "JsonFormatter",
    "configure_json_logging_if_requested",
    "is_json_logging_enabled",
]

_CONFIGURED = False
_LOCK = threading.Lock()


def is_json_logging_enabled() -> bool:
    """Return True iff JSON logging has been activated via env var."""
    return os.environ.get("LOG_FORMAT", "").strip().lower() == "json"


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record.

    Drop-in replacement for the default ``logging.Formatter`` —
    install on any handler:

        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())

    All ``extra={"key": "value"}`` fields passed to the logger
    call land as top-level JSON keys. ``exc_info`` (when present)
    is rendered as a multi-line traceback string under the
    ``exc_info`` key — easy to grep in Loki / Datadog.
    """

    # Fields that the standard ``LogRecord`` populates and that
    # we want to expose explicitly in JSON. Anything else is
    # treated as user-provided ``extra=`` data.
    _STANDARD_FIELDS = frozenset({
        "name", "msg", "args", "levelname", "levelno", "pathname",
        "filename", "module", "exc_info", "exc_text", "stack_info",
        "lineno", "funcName", "created", "msecs", "relativeCreated",
        "thread", "threadName", "processName", "process", "message",
        "asctime", "taskName",
    })

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": _dt.datetime.fromtimestamp(
                record.created, tz=_dt.timezone.utc
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
            "pid": record.process,
        }
        # Add any ``extra=`` fields the caller passed. Skip the
        # standard LogRecord attributes so we don't pollute the
        # JSON with internal plumbing.
        for key, value in record.__dict__.items():
            if key in self._STANDARD_FIELDS:
                continue
            if key.startswith("_"):
                continue
            payload[key] = _json_safe(value)
        # Exception traceback: only render when an exception is
        # attached AND the call site didn't already pass it via
        # ``extra=`` (in which case it would have been merged
        # above).
        if record.exc_info and "exc_info" not in payload:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info and "stack_info" not in payload:
            payload["stack_info"] = self.formatStack(record.stack_info)
        try:
            return json.dumps(payload, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            # Last-ditch: serialize manually so we never raise
            # from the logging path. Better to drop fields than
            # to crash the worker.
            return json.dumps({k: str(v) for k, v in payload.items()})


def _json_safe(value: object) -> object:
    """Coerce values that aren't JSON-serializable by default.

    Sets → sorted lists (deterministic output for grep).
    Bytes → decoded as utf-8 with replacement.
    Datetimes / dates → ISO string.
    Everything else: ``json.dumps`` handles it natively.
    """
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, BaseException):
        return f"{type(value).__name__}: {value}"
    # Fall through; the json.dumps(..., default=str) in format()
    # handles anything else.
    return value


def configure_json_logging_if_requested(
    *,
    level: str | None = None,
    force: bool = False,
) -> bool:
    """Install :class:`JsonFormatter` on the root logger iff
    ``LOG_FORMAT=json``.

    Idempotent — calling twice is a no-op unless ``force=True``.
    Returns True if JSON logging is now active.

    Parameters
    ----------
    level:
        Optional override for the log level (defaults to
        ``LOG_LEVEL`` env var, then ``INFO``).
    force:
        Re-install the handler even if already configured. Use
        this in tests that swap env vars after import.
    """
    global _CONFIGURED
    enabled = is_json_logging_enabled()
    with _LOCK:
        if _CONFIGURED and not force:
            return enabled
        if not enabled:
            return False
        # Resolve level: explicit arg > LOG_LEVEL > INFO.
        if level is None:
            level = os.environ.get("LOG_LEVEL", "INFO").upper()
        root = logging.getLogger()
        # Clear existing handlers so the new JSON handler isn't
        # shadowed by a plain-text one.
        for h in list(root.handlers):
            root.removeHandler(h)
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
        root.setLevel(level)
        _CONFIGURED = True
        return True