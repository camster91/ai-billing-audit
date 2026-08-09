"""Per-tenant feature flags with audit trail.

Kanban: t_11b04a94 (clinical-impact board).

The product uses feature flags for two reasons:

1. **Gradual rollout.** When we add a new feature, we ship to 10%
   of clinics first, measure impact, then roll out to everyone.
2. **Tenant-specific config.** Some clinics need a feature on,
   some off (e.g. a Quebec clinic has Law 25 + BAA, so the
   ``locale.fr_ca`` flag is permanently on for them).

Schema
------
Each row in the audit log records one state change::

    {
      "event_id": "...",
      "timestamp": "2026-06-25T01:00:00Z",
      "tenant_id": "clinic_42",
      "flag": "doctor_dashboard",
      "enabled": true,
      "previous_signature": "..."
    }

The log is append-only and SHA-256 chained (same shape as
``audit_actions.py`` / ``feedback.py``) so the enable/disable
history is tamper-evident.

API
---
* ``is_enabled(tenant_id, flag)`` — boolean (default off)
* ``enable(tenant_id, flag, actor)`` — flip on, write row
* ``disable(tenant_id, flag, actor)`` — flip off, write row
* ``list_enabled(tenant_id)`` — set of enabled flag names
* ``flag_history(tenant_id, flag)`` — chronological list of changes
* ``register_flag(name, ...)`` — pre-declare known flags

We deliberately do NOT use a heavyweight flag service (LaunchDarkly
et al.) — this is a single-process Python app. When/if we migrate,
the ``FlagRegistry`` is the seam.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

FlagName = str

# Reserved / pre-declared flags. Adding a new feature? Add the flag
# name here so the dashboard and audit log can show a stable list.
KNOWN_FLAGS: tuple[FlagName, ...] = (
    "doctor_dashboard",  # t_af26abdb
    "doctor_note_suggestion",  # t_df188436
    "doctor_fixit_workflow",  # t_f5ea3bf2
    "monthly_owner_email",  # t_a8eeb0de
    "submit_time_webhook",  # t_3b15809f
    "reviewer_feedback_loop",  # t_2ab66102
    "per_tenant_rules",  # t_06ceaa04
    "onboarding_wizard",  # t_58fbe2dd
    "doctor_effectiveness_metric",  # t_267a1ad6
    "pre_submit_claim_blocking",  # t_d080595b
    "browser_extension",  # t_8b915264
    "rejected_fix_teaching_signal",  # t_a26d25be
    "per_tenant_prompt_version",  # t_17ec5fec
    "specialty_mix_detection",  # t_da44c384
    "bulk_accept_known_good",  # t_f3d392b2
    "locale_fr_ca",  # t_843317a2
    "locale_es_us",  # t_843317a2
    "configurable_audit_depth",  # t_e2c5afab
    "doctor_positive_feedback",  # t_585dcaed
)

# Known-flag registry — extra flags passed at runtime are accepted
# (so a deploy doesn't break) but won't show in dashboard listings.
_REGISTRY_PATH = Path(
    os.environ.get("FEATURE_FLAG_REGISTRY", "/app/logs/feature_flags_registry.json")
)


@dataclass
class FlagEvent:
    """One enable / disable row."""

    tenant_id: str
    flag: FlagName
    enabled: bool
    timestamp: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    actor: str = "system"
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    previous_signature: str = ""
    cryptographic_signature: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "tenant_id": self.tenant_id,
            "flag": self.flag,
            "enabled": self.enabled,
            "actor": self.actor,
            "previous_signature": self.previous_signature,
            "cryptographic_signature": self.cryptographic_signature,
        }


# Module-level path. Stored at import time so legacy
# `monkeypatch.setattr(module, '_LOG_PATH', log)` patches still
# work (the audit_actions / feedback / feature_flags / i18n
# test suites depend on this contract). Tests that need to
# override the path per-test should patch this attribute; the
# accessors below read the attribute each call so a patch
# takes effect immediately.
_LOG_PATH = Path(os.environ.get("FEATURE_FLAG_LOG", "/app/logs/feature_flags.jsonl"))


def feature_flag_log_path() -> Path:
    """Return the audit-trail JSONL path.

    Reads the module-level ``_LOG_PATH`` attribute every call so
    tests that monkey-patch the attribute at module scope
    (``monkeypatch.setattr(aa_mod, '_LOG_PATH', log)``) see the
    patched path on every call. The path is selected from the
    ``FEATURE_FLAG_LOG`` env var at import time; absent that var, falls
    back to ``/app/logs/feature_flags.jsonl`` (the production layout).
    """
    return _LOG_PATH


_GENESIS_SIG = "0" * 64


def _last_signature(path: Path) -> str:
    if not path.exists():
        return _GENESIS_SIG
    last = _GENESIS_SIG
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            last = row.get("cryptographic_signature") or last
    return last


def _sign(previous: str, row: dict[str, object]) -> str:
    import hashlib

    payload = "|".join(
        str(row.get(k, ""))
        for k in sorted(row.keys())
        if k != "cryptographic_signature"
    )
    return hashlib.sha256(f"{previous}|{payload}".encode("utf-8")).hexdigest()


def _read_log(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    out: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _state_for(
    rows: list[dict[str, object]], tenant_id: str, flag: FlagName
) -> bool | None:
    """Most-recent state for (tenant, flag) or None if no events yet."""
    state: bool | None = None
    for row in rows:
        if row.get("tenant_id") == tenant_id and row.get("flag") == flag:
            enabled = row.get("enabled")
            if isinstance(enabled, bool):
                state = enabled
    return state


def register_flag(name: FlagName, description: str = "") -> bool:
    """Add ``name`` to the flag registry. Idempotent.

    Returns True if a new flag was added, False if it was already
    known.
    """
    registry_path = Path(os.environ.get("FEATURE_FLAG_REGISTRY", str(_REGISTRY_PATH)))
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry: dict[str, dict[str, str]] = {}
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            registry = {}
    if name in registry:
        return False
    registry[name] = {
        "description": description,
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    registry_path.write_text(
        json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8"
    )
    return True


def list_known_flags() -> list[FlagName]:
    """Return all pre-declared flag names (sorted, stable)."""
    return sorted(set(KNOWN_FLAGS))


def enable(tenant_id: str, flag: FlagName, actor: str = "admin") -> FlagEvent:
    """Enable ``flag`` for ``tenant_id`` (writes a row)."""
    return _set(tenant_id, flag, True, actor)


def disable(tenant_id: str, flag: FlagName, actor: str = "admin") -> FlagEvent:
    """Disable ``flag`` for ``tenant_id`` (writes a row)."""
    return _set(tenant_id, flag, False, actor)


def _set(tenant_id: str, flag: FlagName, enabled: bool, actor: str) -> FlagEvent:
    if not tenant_id:
        raise ValueError("tenant_id required")
    if not flag:
        raise ValueError("flag required")
    path = Path(os.environ.get("FEATURE_FLAG_LOG", str(feature_flag_log_path())))
    path.parent.mkdir(parents=True, exist_ok=True)
    evt = FlagEvent(tenant_id=tenant_id, flag=flag, enabled=enabled, actor=actor)
    evt.previous_signature = _last_signature(path)
    evt.cryptographic_signature = _sign(evt.previous_signature, evt.to_dict())
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(evt.to_dict(), ensure_ascii=False) + "\n")
    return evt


def is_enabled(
    tenant_id: str,
    flag: FlagName,
    *,
    log_path: Path | str | None = None,
    default: bool = False,
) -> bool:
    """Return True iff ``flag`` is enabled for ``tenant_id``.

    Default is ``False`` for unknown flags — explicit opt-in only.
    """
    path = Path(log_path) if log_path is not None else feature_flag_log_path()
    state = _state_for(_read_log(path), tenant_id, flag)
    return state if state is not None else default


def list_enabled(
    tenant_id: str, *, log_path: Path | str | None = None
) -> set[FlagName]:
    """Return the set of flags currently enabled for ``tenant_id``."""
    path = Path(log_path) if log_path is not None else feature_flag_log_path()
    rows = _read_log(path)
    by_flag: dict[FlagName, bool] = {}
    for row in rows:
        if row.get("tenant_id") != tenant_id:
            continue
        flag = row.get("flag")
        enabled = row.get("enabled")
        if isinstance(flag, str) and isinstance(enabled, bool):
            by_flag[flag] = enabled
    return {f for f, on in by_flag.items() if on}


def flag_history(
    tenant_id: str, flag: FlagName, *, log_path: Path | str | None = None
) -> list[FlagEvent]:
    """Return all state-change rows for (tenant, flag), oldest first."""
    path = Path(log_path) if log_path is not None else feature_flag_log_path()
    out: list[FlagEvent] = []
    for row in _read_log(path):
        if row.get("tenant_id") == tenant_id and row.get("flag") == flag:
            try:
                evt = FlagEvent(
                    tenant_id=str(row["tenant_id"]),
                    flag=str(row["flag"]),
                    enabled=bool(row["enabled"]),
                    actor=str(row.get("actor", "system")),
                    timestamp=str(row.get("timestamp", "")),
                    event_id=str(row.get("event_id", "")),
                    previous_signature=str(row.get("previous_signature", "")),
                    cryptographic_signature=str(row.get("cryptographic_signature", "")),
                )
                out.append(evt)
            except (KeyError, TypeError):
                continue
    return out


def rollout_percent(flag: FlagName, percent: int) -> dict[FlagName, bool]:
    """Generate a deterministic rollout map for ``flag``.

    Hashes the tenant_id (``str``) and maps the first 4 hex chars
    into ``[0, 100)``. Tenants whose bucket is ``< percent`` get
    the flag on; everyone else gets it off. Deterministic so the
    same tenant always lands on the same side of a rollout.

    Use this in an admin script — the result is meant to be passed
    to ``enable`` for each tenant that lands in the rollout.
    """
    if not 0 <= percent <= 100:
        raise ValueError("percent must be in [0, 100]")
    import hashlib

    # The map is keyed by tenant_id. We don't have a tenant list
    # here, so we return a *predicate* the caller can apply. The
    # function shape lets us unit-test the bucketing.
    def _should_enable(tenant_id: str) -> bool:
        h = hashlib.sha256(f"{flag}|{tenant_id}".encode("utf-8")).hexdigest()
        return (int(h[:8], 16) % 100) < percent

    # Return the predicate bound to the flag name for testability.
    return {f"_predicate_for_{flag}": _should_enable}  # type: ignore[dict-item]


def bucket_for(flag: FlagName, tenant_id: str) -> int:
    """Return the integer bucket ``[0, 100)`` for ``(flag, tenant_id)``.

    Stable for the same inputs — used by ``rollout_percent`` and by
    tests that want to assert which side of a rollout a tenant
    landed on.
    """
    import hashlib

    h = hashlib.sha256(f"{flag}|{tenant_id}".encode("utf-8")).hexdigest()
    return int(h[:8], 16) % 100


# Module-level ``__getattr__`` (Python 3.7+) defers legacy
# ``module._LOG_PATH`` reads to the accessor function so late-set
# env vars (the bulk_actions / rbac / monthly_report test suites
# all set ``AUDIT_TRAIL_LOG`` after import) take effect on the very
# next call. ``monkeypatch.setattr(module, '_LOG_PATH', log)``
# still wins cleanly because the patch adds the name to the
# module's __dict__ and __getattr__ runs ONLY for missing names.
def __getattr__(name: str):
    if name == "_LOG_PATH":
        return feature_flag_log_path()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
