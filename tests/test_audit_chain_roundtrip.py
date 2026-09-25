"""Round-trip tests for the canonical audit chain (issue #113).

The defect this file exists to prevent: ``audit_actions.append()`` wrote
``cryptographic_signature`` by hashing ``data_elements`` as canonical JSON,
while ``verify_chain`` hashed ``str()`` of the parsed dict. Every row the
append path produced therefore failed verification from index 0.

The QA harness in ``scripts/qa_audit_chain_verify.py`` passed anyway,
because it read rows through ``psql -A``, which returns ``data_elements``
as text — the one shape where the two rules agreed. A test that reads rows
back the way a verifier actually does would have caught it, so that is
what this file does.

Three shapes are covered, because storage returns all three:

* ``dict``      — Postgres ``JSONB`` via psycopg
* ``str``       — JSONL, and ``psql -A``
* ``None``      — a row written with no ``data_elements`` at all

Both writers are exercised: the JSONL append path
(``ai_billing_audit.audit_actions``) and the field-ordered digest that the
Postgres table and the portal's TypeScript port use.
"""

from __future__ import annotations

import json

import pytest

from ai_billing_audit import audit_actions
from ai_billing_audit.audit_chain import (
    CHAIN_FIELDS,
    GENESIS_PREVIOUS_SIGNATURE,
    coerce_field,
    compute_signature,
    verify_chain,
    walk_chain,
)


def _row(
    *,
    event_id: str,
    timestamp: str,
    data_elements,
    previous: str,
    action: str = "accept_all",
) -> dict:
    """Build a row shaped like a stored audit-trail record."""
    base = {
        "event_id": event_id,
        "timestamp": timestamp,
        "user_identifier": "biller@example.ca",
        "action": action,
        "patient_hash": "a" * 64,
        "data_elements": data_elements,
        "model_run_id": "",
    }
    signature = compute_signature(previous, base)
    return dict(
        base,
        previous_signature=previous,
        cryptographic_signature=signature,
    )


def _read_back_as_jsonb(row: dict) -> dict:
    """Simulate a psycopg read of a ``JSONB`` column: text becomes a dict."""
    value = row["data_elements"]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return dict(row)
        return dict(row, data_elements=parsed)
    return dict(row)


# ---------------------------------------------------------------------------
# The equivalence that #113 was about
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"encounter_id": "enc1", "n_findings": 2, "finding_ids": ["f1", "f2"], "note": ""},
        {"note": "dismissed", "n_findings": 0, "finding_ids": [], "encounter_id": "enc2"},
        {"nested": {"b": 2, "a": 1}, "list": [3, 1, 2]},
        {},
    ],
)
def test_dict_and_canonical_string_hash_identically(payload):
    """A JSONB read and a JSONL read must produce the same digest."""
    as_text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    prev = GENESIS_PREVIOUS_SIGNATURE
    row_dict = _row(event_id="e1", timestamp="2026-09-21T00:00:00Z", data_elements=payload, previous=prev)
    row_text = _row(
        event_id="e1",
        timestamp="2026-09-21T00:00:00Z",
        data_elements=as_text,
        previous=prev,
    )
    assert row_dict["cryptographic_signature"] == row_text["cryptographic_signature"]


def test_none_and_missing_render_as_empty_string():
    """``None`` must not hash as the text ``"None"`` — that would invalidate on-disk rows."""
    assert coerce_field({"model_run_id": None}, "model_run_id") == ""
    assert coerce_field({}, "model_run_id") == ""
    assert coerce_field({"model_run_id": ""}, "model_run_id") == ""


def test_chain_fields_order_is_pinned():
    """Reordering CHAIN_FIELDS changes every signature — pin the order."""
    assert CHAIN_FIELDS == (
        "event_id",
        "timestamp",
        "user_identifier",
        "action",
        "patient_hash",
        "data_elements",
        "model_run_id",
    )


# ---------------------------------------------------------------------------
# The round-trip the acceptance criteria ask for
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reader", ["text", "jsonb"])
def test_append_then_read_back_then_verify(reader):
    """Write rows through the canonical rule, read them back, verify clean."""
    payloads = [
        {"encounter_id": "enc1", "n_findings": 1, "finding_ids": ["f1"], "note": ""},
        "not-json-at-all",
        None,
        {"encounter_id": "enc4", "n_findings": 0, "finding_ids": [], "note": "clean"},
    ]
    rows: list[dict] = []
    previous = GENESIS_PREVIOUS_SIGNATURE
    for index, payload in enumerate(payloads):
        row = _row(
            event_id=f"e{index}",
            timestamp=f"2026-09-21T0{index}:00:00Z",
            data_elements=payload,
            previous=previous,
        )
        rows.append(row)
        previous = row["cryptographic_signature"]

    read_back = (
        [_read_back_as_jsonb(r) for r in rows] if reader == "jsonb" else rows
    )
    assert verify_chain(read_back) is None


def test_verify_reports_first_broken_row():
    """A mutated row is reported at its own index, not swallowed."""
    rows: list[dict] = []
    previous = GENESIS_PREVIOUS_SIGNATURE
    for index in range(3):
        row = _row(
            event_id=f"e{index}",
            timestamp=f"2026-09-21T0{index}:00:00Z",
            data_elements={"encounter_id": f"enc{index}", "n_findings": 0, "finding_ids": [], "note": ""},
            previous=previous,
        )
        rows.append(row)
        previous = row["cryptographic_signature"]

    assert verify_chain(rows) is None
    rows[1]["action"] = "dismiss"
    assert verify_chain(rows) == 1


def test_verify_reports_fabricated_previous_signature():
    """The link check catches a row whose ``previous_signature`` was rewritten."""
    rows = [
        _row(event_id="e0", timestamp="2026-09-21T00:00:00Z", data_elements={"a": 1}, previous=GENESIS_PREVIOUS_SIGNATURE),
    ]
    rows.append(
        _row(event_id="e1", timestamp="2026-09-21T01:00:00Z", data_elements={"a": 2}, previous=rows[0]["cryptographic_signature"])
    )
    rows[1]["previous_signature"] = "f" * 64
    assert verify_chain(rows) == 1


def test_walk_chain_orders_by_timestamp_then_event_id():
    rows = [
        {"timestamp": "2026-09-21T02:00:00Z", "event_id": "b"},
        {"timestamp": "2026-09-21T01:00:00Z", "event_id": "z"},
        {"timestamp": "2026-09-21T02:00:00Z", "event_id": "a"},
    ]
    assert [r["event_id"] for r in walk_chain(rows)] == ["z", "a", "b"]


# ---------------------------------------------------------------------------
# The writer that actually shipped the bug
# ---------------------------------------------------------------------------


def test_audit_actions_append_verifies_against_the_canonical_verifier(tmp_path, monkeypatch):
    """The live JSONL append path must produce rows its own verifier accepts.

    This is the regression gate for #113: before the consolidation,
    ``audit_actions.verify_chain`` reported index 0 for every row written
    by ``audit_actions.append``.
    """
    log = tmp_path / "audit_trail.jsonl"
    monkeypatch.setattr(audit_actions, "_LOG_PATH", log, raising=False)
    monkeypatch.setenv("AUDIT_TRAIL_LOG", str(log))
    audit_actions._reset_last_signature_cache()

    for index in range(3):
        audit_actions.append(
            action="accept_all",
            encounter_id=f"enc-{index}",
            user_identifier="biller@example.ca",
            findings=[{"finding_id": f"f{index}"}],
        )

    rows = audit_actions.read_all(tenant_id="*")
    assert len(rows) == 3

    # data_elements is a dict on these rows — exactly the shape that broke.
    assert all(isinstance(r["data_elements"], dict) for r in rows)

    assert audit_actions.verify_chain(rows) is None
    assert verify_chain(rows) is None

    # And the same rows read the way JSONB comes back must also verify.
    assert verify_chain([_read_back_as_jsonb(r) for r in rows]) is None


def test_feedback_and_audit_chains_share_one_rule():
    """The feedback chain must not re-invent its own stringifier.

    It keeps its own *field set* (a biller decision has different fields
    from a reviewer action) but must delegate the digest rule. Before
    #113 it injected a ``b"|"`` separator per field, so it matched neither
    of the other implementations.
    """
    from ai_billing_audit import feedback

    row = {
        "event_id": "e1",
        "timestamp": "2026-09-21T00:00:00Z",
        "encounter_id": "enc1",
        "finding_id": "f1",
        "action": "dismiss",
        "biller_id": "b1",
        "rule_id": "rule_x",
        "category": "documentation",
        "severity": "medium",
    }
    canonical = compute_signature(GENESIS_PREVIOUS_SIGNATURE, row, fields=feedback._CHAIN_FIELDS)
    assert feedback.compute_signature(GENESIS_PREVIOUS_SIGNATURE, row) == canonical

    # The legacy rule must differ, or the fallback would be a no-op that
    # silently accepts anything the canonical rule accepts.
    assert feedback._legacy_separator_signature(GENESIS_PREVIOUS_SIGNATURE, row) != canonical


def test_audit_log_shim_reexports_the_canonical_implementation():
    """``src/audit_log.py`` is a shim; it must not drift from the rule."""
    import audit_log

    assert audit_log.CHAIN_FIELDS == CHAIN_FIELDS
    assert audit_log.GENESIS_PREVIOUS_SIGNATURE == GENESIS_PREVIOUS_SIGNATURE
    assert audit_log.compute_signature is compute_signature
    assert audit_log.verify_chain is verify_chain
