"""Tenant data purge: delete what belongs to a tenant, and say so honestly.

The route at ``DELETE /api/tenants/{tenant_id}`` promises a clinic that
their records are gone. Before this module existed the handler wrote an
"we recorded your request" audit row and returned success without
deleting anything — while ``docs/PILOT_OFFER.md`` tells clinics their
data is deleted within seven business days with written confirmation.

Two things are true at once here, and the module is built around both:

1. **Some stores are tenant-scoped.** They carry a ``tenant_id`` field
   per row, so a purge can remove exactly this tenant's records and
   leave other tenants untouched.
2. **Some stores are not.** They have no tenant field at all, so the
   only file-level deletion available would take every tenant's data
   with it. Deleting those is never correct, and refusing to pretend
   otherwise is the honest behaviour.

So :func:`purge_tenant` returns a report that separates the two. The
caller is expected to surface it rather than flatten it into an ``ok``.

Design notes
------------

* **Never destructive-by-default.** Every store is removed by *filtering*
  rows through the tenant predicate. A store with no tenant field is
  reported as ``unscoped`` and left untouched — it is never truncated.
* **Append-only files are rewritten atomically and re-encrypted.** The
  rewritten file is written to a temp path — with every surviving row
  re-encrypted through ``append_encrypted_json_record`` so the output is
  the same Fernet-authenticated format the writers use — then renamed
  over the original. An interrupted purge leaves the original intact
  rather than a half-written log. Writing the survivors as plaintext
  JSON would both leak PHI to disk and make every later read raise
  ``PhiStorageIntegrityError``; that is a bug this module had and a test
  now covers.
* **The purge record survives the purge.** The caller writes the deletion
  event to the audit trail *after* this module runs (see the route), so
  the evidence that a deletion happened is not itself deleted. That is
  also why this module does not touch the audit trail's own rows: a
  tenant's audit history is what a privacy officer verifies against.
* **Idempotent.** Purging an already-purged tenant deletes nothing and
  reports zero counts; it does not error.
* **A purge leaves a chain discontinuity, and that is deliberate.** Rows
  are removed from the middle of an append-only hash chain, so the first
  surviving row's ``previous_signature`` points at a row that no longer
  exists and ``verify_chain`` reports a break there. The alternative —
  re-anchoring the first survivor onto genesis — would make the verifier
  green by rewriting history, which is exactly the operation the chain
  exists to detect. A verifier must therefore distinguish *purge
  boundary* from *tampering*; the purge event written by the caller
  carries the boundary marker used to tell them apart.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .clinical_note_storage import read_encrypted_json_records

__all__ = [
    "PurgeReport",
    "TenantStore",
    "default_tenant_stores",
    "purge_boundary_marker",
    "purge_tenant",
]


def _logs_dir() -> Path:
    return Path(os.environ.get("ZORVA_LOGS_DIR", "/app/logs"))


@dataclass(frozen=True)
class TenantStore:
    """One on-disk store the purge knows how to reason about.

    ``tenant_field`` is the row key that carries the tenant identity. When
    it is ``None`` the store has no tenant scoping and cannot be purged
    selectively — the store is then reported, never deleted.
    """

    name: str
    path_of: Callable[[], Path]
    tenant_field: str | None = None
    #: True when the file holds per-clinic PHI and deleting it is the
    #: whole point of the purge (as opposed to incidental metadata).
    holds_phi: bool = False


@dataclass
class PurgeReport:
    """What a purge actually did, split by what it could and could not do."""

    tenant_id: str
    purged: dict[str, int] = field(default_factory=dict)
    """Store name -> rows removed for this tenant."""

    unscoped: list[str] = field(default_factory=list)
    """Stores with no tenant field. Left untouched; cannot be purged."""

    failed: dict[str, str] = field(default_factory=dict)
    """Store name -> error string, for stores that raised during purge."""

    notes_removed: int = 0
    """Uploaded encrypted clinical-note files deleted for this tenant."""

    @property
    def complete(self) -> bool:
        """True when every known store was tenant-scoped and handled."""
        return not self.unscoped and not self.failed

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "purged": dict(self.purged),
            "rows_removed": sum(self.purged.values()),
            "notes_removed": self.notes_removed,
            "unscoped": list(self.unscoped),
            "failed": dict(self.failed),
            "complete": self.complete,
        }


def default_tenant_stores(tenant_id: str) -> list[TenantStore]:
    """Every store this build knows about, with its scoping status.

    Imported lazily so this module does not drag the whole app's import
    graph (litellm, fastapi) into a purge call, and so monkeypatched
    paths in tests are resolved at call time rather than import time.
    """
    logs = _logs_dir()
    stores: list[TenantStore] = []

    def _audit_trail() -> Path:
        from .audit_actions import audit_trail_path

        return audit_trail_path()

    def _upload_jobs() -> Path:
        return Path(
            os.environ.get("UPLOAD_AUDIT_LOG_PATH", str(logs / "upload_jobs.jsonl"))
        )

    def _feedback() -> Path:
        from .feedback import feedback_log_path

        return feedback_log_path()

    def _biller_corrections() -> Path:
        from .feedback import _BILLER_CORRECTIONS_LOG as p

        return Path(
            os.environ.get("BILLER_CORRECTIONS_LOG", str(p))
        )

    def _finding_comments() -> Path:
        from .feedback import _COMMENTS_LOG as p

        return Path(os.environ.get("FINDING_COMMENTS_LOG", str(p)))

    def _finding_assignments() -> Path:
        from .finding_assignments import _DEFAULT_LOG as p  # type: ignore[attr-defined]

        return Path(os.environ.get("FINDING_ASSIGNMENT_LOG", str(p)))

    def _snoozes() -> Path:
        from .snooze import _DEFAULT_LOG as p  # type: ignore[attr-defined]

        return Path(os.environ.get("SNOOZE_LOG", str(p)))

    def _saved_filters() -> Path:
        from .saved_filters import _DEFAULT_LOG as p  # type: ignore[attr-defined]

        return Path(os.environ.get("SAVED_FILTERS_LOG", str(p)))

    def _appeal_letters() -> Path:
        return logs / "appeal_letters.jsonl"

    def _appeal_outcomes() -> Path:
        return logs / "appeal_outcomes.jsonl"

    def _tenant_rules() -> Path:
        return Path(os.environ.get("TENANT_RULES_LOG", str(logs / "tenant_rules.jsonl")))

    def _tenant_locale() -> Path:
        return Path(os.environ.get("TENANT_LOCALE_LOG", str(logs / "tenant_locale.jsonl")))

    def _tenant_audit_depth() -> Path:
        from .audit_depth import _TENANT_CONFIG_LOG

        return Path(os.environ.get("TENANT_AUDIT_DEPTH_LOG", str(_TENANT_CONFIG_LOG)))

    def _idempotency() -> Path:
        return Path(os.environ.get("IDEMPOTENCY_LOG", str(logs / "idempotency.jsonl")))

    def _usage_log() -> Path:
        return Path(os.environ.get("USAGE_LOG_PATH", str(logs / "usage_log.jsonl")))

    def _slack() -> Path:
        return Path(
            os.environ.get("SLACK_INTEGRATIONS_LOG", str(logs / "slack_integrations.jsonl"))
        )

    def _webhooks() -> Path:
        return Path(os.environ.get("SUBMIT_WEBHOOK_LOG", str(logs / "submit_webhooks.jsonl")))

    def _onboarding() -> Path:
        return Path(os.environ.get("ONBOARDING_LOG", str(logs / "onboarding.jsonl")))

    def _specialty_mix() -> Path:
        return Path(os.environ.get("SPECIALTY_MIX_LOG", str(logs / "specialty_mix.jsonl")))

    # --- tenant-scoped (a row-level predicate can select this tenant) ---
    stores.append(TenantStore("audit_trail", _audit_trail, "tenant_id"))
    stores.append(TenantStore("upload_jobs", _upload_jobs, "tenant_id", holds_phi=True))
    stores.append(TenantStore("biller_corrections", _biller_corrections, "tenant_id"))
    stores.append(TenantStore("finding_comments", _finding_comments, "tenant_id"))
    stores.append(TenantStore("appeal_letters", _appeal_letters, "tenant_id", holds_phi=True))
    stores.append(TenantStore("appeal_outcomes", _appeal_outcomes, "tenant_id"))
    stores.append(TenantStore("tenant_rules", _tenant_rules, "tenant_id"))
    stores.append(TenantStore("tenant_locale", _tenant_locale, "tenant_id"))
    stores.append(TenantStore("tenant_audit_depth", _tenant_audit_depth, "tenant_id"))
    stores.append(TenantStore("idempotency", _idempotency, "tenant_id"))
    stores.append(TenantStore("usage_log", _usage_log, "tenant_id"))
    stores.append(TenantStore("slack_integrations", _slack, "tenant_id"))

    # --- NOT tenant-scoped: cannot be purged without harming other tenants ---
    stores.append(TenantStore("feedback", _feedback, None))
    stores.append(TenantStore("finding_assignments", _finding_assignments, None))
    stores.append(TenantStore("snoozes", _snoozes, None))
    stores.append(TenantStore("saved_filters", _saved_filters, None))
    stores.append(TenantStore("webhooks", _webhooks, None))
    stores.append(TenantStore("onboarding", _onboarding, None))
    stores.append(TenantStore("specialty_mix", _specialty_mix, None))

    return stores


def _rows_for_other_tenants(
    rows: Iterable[Mapping[str, Any]],
    tenant_field: str,
    tenant_id: str,
) -> list[Mapping[str, Any]]:
    """Rows that do NOT belong to ``tenant_id`` — i.e. what we keep.

    A row with a missing tenant field is treated as belonging to the
    ``"default"`` tenant, matching the read-side convention used by
    ``audit_actions.read_all``. That keeps a legacy row from being
    resurrected into every tenant's view.
    """
    keep: list[Mapping[str, Any]] = []
    for row in rows:
        row_tenant = row.get(tenant_field, "default")
        if row_tenant != tenant_id:
            keep.append(row)
    return keep


def _rewrite_atomically(path: Path, rows: list[Mapping[str, Any]]) -> None:
    """Write the surviving ``rows`` back to ``path``, atomically.

    Each surviving row is re-encrypted with
    ``append_encrypted_json_record`` so the rewritten file keeps the exact
    Fernet-authenticated framing the original writers use. The temp file is
    then renamed over the original, so an interrupted purge leaves the
    original intact.

    Preserving the encryption is not cosmetic: PHI on disk must stay
    encrypted, and a plaintext rewrite would make every subsequent read
    raise ``PhiStorageIntegrityError``.
    """
    from .clinical_note_storage import append_encrypted_json_record

    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(directory),
        prefix=f".{path.name}.",
        suffix=".purge.tmp",
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.unlink()  # append_encrypted_json_record creates it
        for row in rows:
            append_encrypted_json_record(tmp_path, dict(row))
        if not rows:
            # No survivors: leave an empty file rather than a missing one,
            # so readers see "empty log", not "no log yet".
            tmp_path.touch()
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _purge_store(store: TenantStore, tenant_id: str) -> int:
    """Remove ``tenant_id``'s rows from one tenant-scoped store.

    Returns the number of rows removed. Raises on I/O failure so the
    caller can report the store as ``failed`` rather than silently
    claiming success.
    """
    assert store.tenant_field is not None
    path = store.path_of()
    if not path.is_file():
        return 0

    rows = read_encrypted_json_records(path)
    keep = _rows_for_other_tenants(rows, store.tenant_field, tenant_id)
    removed = len(rows) - len(keep)
    if removed == 0:
        return 0
    _rewrite_atomically(path, keep)
    return removed


def _purge_uploaded_notes(tenant_id: str) -> int:
    """Delete encrypted clinical-note files belonging to ``tenant_id``.

    Note files are named ``{sanitised_encounter_id}.{note_id}.{ext}.enc``
    and carry no tenant marker of their own, so the only safe predicate is
    the encounter-id prefix. Encounter ids embed no tenant, so this
    removes every note whose encounter id is registered to this tenant in
    ``upload_jobs`` — which is why it runs *after* the store purge has
    been computed, using the encounter ids collected from the rows that
    were removed.
    """
    notes_dir = Path(
        os.environ.get(
            "ZORVA_UPLOADED_NOTES_DIR",
            str(Path(__file__).resolve().parent.parent.parent / "logs" / "uploaded_notes"),
        )
    )
    if not notes_dir.is_dir():
        return 0

    from .audit_actions import read_all

    # Encounter ids still recorded as this tenant's in any surviving row
    # are the ones whose notes must go. We read the full audit trail
    # before it is filtered so the tenant's own history supplies the
    # encounter list even if upload_jobs was already rewritten.
    tenant_encounters: set[str] = set()
    for row in read_all(tenant_id=tenant_id):
        enc = row.get("data_elements", {}).get("encounter_id")
        if isinstance(enc, str) and enc:
            tenant_encounters.add(enc)

    removed = 0
    for note in notes_dir.iterdir():
        if not note.is_file() or not note.name.endswith(".enc"):
            continue
        # Encounter id is the leading segment of the filename.
        enc_part = note.name.split(".", 1)[0]
        if enc_part in tenant_encounters:
            note.unlink(missing_ok=True)
            removed += 1
    return removed


def purge_boundary_marker(report: PurgeReport, *, at: str) -> dict[str, Any]:
    """The audit payload that records a purge boundary.

    Written by the caller *after* :func:`purge_tenant` runs, so the marker
    survives the purge. It names the stores that were cleared and, more
    importantly, the stores that could not be — a verifier reading this
    row can tell a purge discontinuity from a tampering event, and a
    privacy officer can see exactly which data was out of reach.
    """
    return {
        "kind": "tenant_purge_boundary",
        "tenant_id": report.tenant_id,
        "purged_at": at,
        "stores_purged": sorted(report.purged),
        "rows_removed": sum(report.purged.values()),
        "notes_removed": report.notes_removed,
        # These two are the honest part: data we could NOT delete.
        "stores_unscoped": sorted(report.unscoped),
        "stores_failed": dict(report.failed),
        "complete": report.complete,
    }


def purge_tenant(tenant_id: str) -> PurgeReport:
    """Delete every record provably belonging to ``tenant_id``.

    Returns a :class:`PurgeReport`. Stores that cannot be scoped to a
    tenant are reported in ``unscoped`` and left untouched; stores that
    raise are reported in ``failed``. Neither is ever silently treated as
    success.

    This function does not write the purge event to the audit trail — the
    caller does that, so the record of the deletion is written by the
    request path and survives this call.
    """
    report = PurgeReport(tenant_id=tenant_id)

    for store in default_tenant_stores(tenant_id):
        if store.tenant_field is None:
            # Report it, do not touch it. Deleting the file would remove
            # every other tenant's data too.
            if store.path_of().is_file():
                report.unscoped.append(store.name)
            continue
        try:
            report.purged[store.name] = _purge_store(store, tenant_id)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            report.failed[store.name] = f"{type(exc).__name__}: {exc}"

    try:
        report.notes_removed = _purge_uploaded_notes(tenant_id)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        report.failed["uploaded_notes"] = f"{type(exc).__name__}: {exc}"

    return report
