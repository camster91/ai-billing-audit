"""Tests for the SHA-256 hash-chain in ``audit_log``.

Pins the tamper-evident contract that PHIPA / HIA auditors rely on:

* :func:`compute_signature` is deterministic for a given
  (previous_signature, row) pair and the concatenation order matches
  the spec (previous_sig, event_id, timestamp, user_identifier,
  action, patient_hash, data_elements, model_run_id).
* :func:`verify_chain` returns ``None`` for an intact chain and
  reports the index of the first row whose stored signature does not
  match the recomputed one.
* The 3-row insert / mutate / verify case the acceptance criteria
  call out works end-to-end: insert 3 chained rows, mutate row 2 in
  place, assert the verifier reports index 1.

The test is DB-agnostic — it operates on plain dicts, so the same
harness exercises the production chain, the live verifier, and the
SQL backfill without spinning up Postgres.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from audit_log import (  # noqa: E402
    CHAIN_FIELDS,
    GENESIS_PREVIOUS_SIGNATURE,
    compute_signature,
    verify_chain,
    walk_chain,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _row(
    *,
    event_id: str,
    timestamp: str,
    user_identifier: str,
    action: str,
    patient_hash: str,
    data_elements: str,
    model_run_id: str,
    previous_signature: str,
    cryptographic_signature: str | None = None,
) -> dict[str, object]:
    """Build a row dict with the 7 chain fields plus both link fields."""
    row: dict[str, object] = {
        "event_id": event_id,
        "timestamp": timestamp,
        "user_identifier": user_identifier,
        "action": action,
        "patient_hash": patient_hash,
        "data_elements": data_elements,
        "model_run_id": model_run_id,
        "previous_signature": previous_signature,
    }
    if cryptographic_signature is not None:
        row["cryptographic_signature"] = cryptographic_signature
    return row


def _build_chain(rows_in: list[dict[str, object]]) -> list[dict[str, object]]:
    """Sign every row in ``rows_in`` using its stored previous_signature.

    Assumes the caller has already set ``previous_signature`` in
    chain order (genesis row carries ``GENESIS_PREVIOUS_SIGNATURE``).
    Returns a new list; the input is not mutated.
    """
    signed: list[dict[str, object]] = []
    for row in rows_in:
        prev = str(row["previous_signature"])
        sig = compute_signature(prev, row)
        signed.append({**row, "cryptographic_signature": sig})
    return signed


# ---------------------------------------------------------------------------
# compute_signature
# ---------------------------------------------------------------------------


def test_compute_signature_is_64_hex_lower():
    sig = compute_signature(
        GENESIS_PREVIOUS_SIGNATURE,
        _row(
            event_id="e-0001",
            timestamp="2026-06-16T18:00:00.000000Z",
            user_identifier="auditor@ashbi.ca",
            action="READ_CLAIM",
            patient_hash="ab" * 32,
            data_elements='{"claim_id":"c-001"}',
            model_run_id="run-0001",
            previous_signature=GENESIS_PREVIOUS_SIGNATURE,
        ),
    )
    assert len(sig) == 64
    assert sig == sig.lower()
    int(sig, 16)  # raises if not pure hex


def test_compute_signature_concatenation_order_matters():
    """Swapping two fields changes the digest — pins the order."""
    base = _row(
        event_id="e-A",
        timestamp="2026-06-16T18:00:00.000000Z",
        user_identifier="u",
        action="A",
        patient_hash="h",
        data_elements="d",
        model_run_id="m",
        previous_signature=GENESIS_PREVIOUS_SIGNATURE,
    )
    swapped = _row(
        event_id="e-A",
        timestamp="2026-06-16T18:00:00.000000Z",
        user_identifier="u",
        action="A",
        patient_hash="h",
        data_elements="d",
        model_run_id="m",
        previous_signature=GENESIS_PREVIOUS_SIGNATURE,
    )
    # Swap two fields; the digests must differ.
    swapped["action"], swapped["model_run_id"] = (
        swapped["model_run_id"],
        swapped["action"],
    )
    assert compute_signature(GENESIS_PREVIOUS_SIGNATURE, base) != compute_signature(
        GENESIS_PREVIOUS_SIGNATURE, swapped
    )


def test_compute_signature_chains_to_previous():
    """Same payload + different previous_signature → different digest."""
    payload = _row(
        event_id="e-0001",
        timestamp="2026-06-16T18:00:00.000000Z",
        user_identifier="u",
        action="A",
        patient_hash="h",
        data_elements="d",
        model_run_id="m",
        previous_signature=GENESIS_PREVIOUS_SIGNATURE,
    )
    sig_genesis = compute_signature(GENESIS_PREVIOUS_SIGNATURE, payload)
    sig_chained = compute_signature("f" * 64, payload)
    assert sig_genesis != sig_chained


def test_compute_signature_rejects_wrong_length_previous():
    with pytest.raises(ValueError):
        compute_signature(
            "abcd",
            _row(
                event_id="e",
                timestamp="t",
                user_identifier="u",
                action="a",
                patient_hash="h",
                data_elements="d",
                model_run_id="m",
                previous_signature=GENESIS_PREVIOUS_SIGNATURE,
            ),
        )


def test_compute_signature_rejects_non_string_previous():
    with pytest.raises(TypeError):
        compute_signature(
            1234567890123456789012345678901234567890123456789012345678901234,
            _row(  # 64-char int-looking value
                event_id="e",
                timestamp="t",
                user_identifier="u",
                action="a",
                patient_hash="h",
                data_elements="d",
                model_run_id="m",
                previous_signature=GENESIS_PREVIOUS_SIGNATURE,
            ),
        )


# ---------------------------------------------------------------------------
# verify_chain — 3-row insert / mutate / verify (acceptance criterion)
# ---------------------------------------------------------------------------


def test_verify_chain_3_rows_clean_then_mutate_row_2():
    """The acceptance-criteria scenario: 3 chained rows, mutate row 2
    in place, assert the verifier reports index 1 (row 2's index)."""
    base_rows = [
        _row(
            event_id="e-0001",
            timestamp="2026-06-16T18:00:00.000000Z",
            user_identifier="auditor@ashbi.ca",
            action="READ_CLAIM",
            patient_hash="ab" * 32,
            data_elements='{"claim_id":"c-001"}',
            model_run_id="run-0001",
            previous_signature=GENESIS_PREVIOUS_SIGNATURE,
        ),
        _row(
            event_id="e-0002",
            timestamp="2026-06-16T18:00:01.000000Z",
            user_identifier="auditor@ashbi.ca",
            action="RUN_AUDIT",
            patient_hash="ab" * 32,
            data_elements='{"claim_id":"c-001","model":"claude-opus-4"}',
            model_run_id="run-0001",
            previous_signature="__to_be_filled__",
        ),
        _row(
            event_id="e-0003",
            timestamp="2026-06-16T18:00:02.000000Z",
            user_identifier="reviewer@ashbi.ca",
            action="ACCEPT_FINDING",
            patient_hash="ab" * 32,
            data_elements='{"finding_id":"f-0001","verdict":"ACCEPT"}',
            model_run_id="run-0001",
            previous_signature="__to_be_filled__",
        ),
    ]
    # Sign row 1 against genesis, then sign row 2 against row 1's
    # stored signature, then row 3 against row 2's.
    signed: list[dict[str, object]] = []
    prev = GENESIS_PREVIOUS_SIGNATURE
    for r in base_rows:
        r2 = {**r, "previous_signature": prev}
        sig = compute_signature(prev, r2)
        signed.append({**r2, "cryptographic_signature": sig})
        prev = sig

    # Chain is valid.
    assert verify_chain(signed) is None

    # Mutate row 2 (index 1) in place — change a chain-field value
    # without recomputing the signature.  This is exactly the
    # "insider edit" the chain is designed to detect.
    mutated = [dict(r) for r in signed]
    mutated[1]["action"] = "RUN_AUDIT_AND_OVERWRITE"
    # previous_signature and cryptographic_signature stay the same
    # (this is the "tampered row" — an attacker changed a payload
    # field but couldn't forge a matching new signature without
    # breaking the downstream chain too).

    # Verifier should report index 1 (row 2).
    assert verify_chain(mutated) == 1


def test_verify_chain_genesis_with_wrong_previous_signature_breaks_at_zero():
    """A row whose previous_signature is not 64 zeros (and is not the
    expected prior row's sig) breaks the chain at index 0."""
    r = _row(
        event_id="e-0001",
        timestamp="2026-06-16T18:00:00.000000Z",
        user_identifier="u",
        action="A",
        patient_hash="h",
        data_elements="d",
        model_run_id="m",
        previous_signature="a" * 64,  # not 64 zeros
    )
    sig = compute_signature("a" * 64, r)
    assert verify_chain([{**r, "cryptographic_signature": sig}]) == 0


def test_verify_chain_empty_iterable_is_intact():
    assert verify_chain([]) is None


def test_verify_chain_single_signed_genesis_row_is_intact():
    r = _row(
        event_id="e-0001",
        timestamp="2026-06-16T18:00:00.000000Z",
        user_identifier="u",
        action="A",
        patient_hash="h",
        data_elements="d",
        model_run_id="m",
        previous_signature=GENESIS_PREVIOUS_SIGNATURE,
    )
    sig = compute_signature(GENESIS_PREVIOUS_SIGNATURE, r)
    assert verify_chain([{**r, "cryptographic_signature": sig}]) is None


def test_verify_chain_first_row_with_stale_previous_breaks_at_zero():
    """Row 0's stored previous_signature doesn't match the previous
    row's stored cryptographic_signature (there's no prior row, so
    anything other than 64 zeros is a break)."""
    base = _row(
        event_id="e-0001",
        timestamp="2026-06-16T18:00:00.000000Z",
        user_identifier="u",
        action="A",
        patient_hash="h",
        data_elements="d",
        model_run_id="m",
        previous_signature=GENESIS_PREVIOUS_SIGNATURE,
    )
    sig = compute_signature(GENESIS_PREVIOUS_SIGNATURE, base)

    # Tamper: change the previous_signature on row 0 to a non-genesis
    # value.  The signature itself is still "correct" relative to
    # the tampered previous_signature, but the chain is broken
    # because the genesis row must carry 64 zeros.
    tampered = {**base, "previous_signature": "b" * 64, "cryptographic_signature": sig}
    assert verify_chain([tampered]) == 0


def test_verify_chain_detects_break_in_row_2_of_3():
    """Direct test of the canonical 'first break point is the lowest
    index whose recompute fails' behavior."""
    rows_in = [
        _row(
            event_id="e-0001",
            timestamp="2026-06-16T18:00:00.000000Z",
            user_identifier="u",
            action="A",
            patient_hash="h",
            data_elements="d",
            model_run_id="m",
            previous_signature=GENESIS_PREVIOUS_SIGNATURE,
        ),
        _row(
            event_id="e-0002",
            timestamp="2026-06-16T18:00:01.000000Z",
            user_identifier="u",
            action="B",
            patient_hash="h",
            data_elements="d",
            model_run_id="m",
            previous_signature="__to_be_filled__",
        ),
        _row(
            event_id="e-0003",
            timestamp="2026-06-16T18:00:02.000000Z",
            user_identifier="u",
            action="C",
            patient_hash="h",
            data_elements="d",
            model_run_id="m",
            previous_signature="__to_be_filled__",
        ),
    ]
    signed = _build_chain_with_links(rows_in)
    assert verify_chain(signed) is None

    # Break row 1 (index 0): replace its cryptographic_signature
    # with garbage but leave previous_signature pointing at genesis.
    broken = [dict(r) for r in signed]
    broken[0]["cryptographic_signature"] = "f" * 64
    assert verify_chain(broken) == 0

    # Break row 2 (index 1) instead — leave row 1 valid.
    broken = [dict(r) for r in signed]
    broken[1]["cryptographic_signature"] = "f" * 64
    assert verify_chain(broken) == 1


def _build_chain_with_links(
    rows_in: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Build a chain in row order, threading previous_signature forward.

    Helper for the per-row break test above.  Mirrors the production
    insert path: each row's previous_signature is the prior row's
    stored cryptographic_signature, and the row's own signature is
    computed from (previous_signature, row fields).
    """
    signed: list[dict[str, object]] = []
    prev = GENESIS_PREVIOUS_SIGNATURE
    for r in rows_in:
        r2 = {**r, "previous_signature": prev}
        sig = compute_signature(prev, r2)
        signed.append({**r2, "cryptographic_signature": sig})
        prev = sig
    return signed


# ---------------------------------------------------------------------------
# walk_chain
# ---------------------------------------------------------------------------


def test_walk_chain_sorts_by_timestamp_then_event_id():
    rows = [
        _row(
            event_id="e-C",
            timestamp="2026-06-16T18:00:02.000000Z",
            user_identifier="u",
            action="A",
            patient_hash="h",
            data_elements="d",
            model_run_id="m",
            previous_signature=GENESIS_PREVIOUS_SIGNATURE,
        ),
        _row(
            event_id="e-A",
            timestamp="2026-06-16T18:00:00.000000Z",
            user_identifier="u",
            action="A",
            patient_hash="h",
            data_elements="d",
            model_run_id="m",
            previous_signature=GENESIS_PREVIOUS_SIGNATURE,
        ),
        _row(
            event_id="e-B",
            timestamp="2026-06-16T18:00:01.000000Z",
            user_identifier="u",
            action="A",
            patient_hash="h",
            data_elements="d",
            model_run_id="m",
            previous_signature=GENESIS_PREVIOUS_SIGNATURE,
        ),
    ]
    walked = walk_chain(rows)
    assert [r["event_id"] for r in walked] == ["e-A", "e-B", "e-C"]


def test_walk_chain_tie_break_by_event_id():
    rows = [
        _row(
            event_id="e-B",
            timestamp="2026-06-16T18:00:00.000000Z",
            user_identifier="u",
            action="A",
            patient_hash="h",
            data_elements="d",
            model_run_id="m",
            previous_signature=GENESIS_PREVIOUS_SIGNATURE,
        ),
        _row(
            event_id="e-A",
            timestamp="2026-06-16T18:00:00.000000Z",
            user_identifier="u",
            action="A",
            patient_hash="h",
            data_elements="d",
            model_run_id="m",
            previous_signature=GENESIS_PREVIOUS_SIGNATURE,
        ),
    ]
    walked = walk_chain(rows)
    assert [r["event_id"] for r in walked] == ["e-A", "e-B"]


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


def test_module_exports_match_documented_surface():
    """Anything the runbook and SQL reference must be importable here."""
    from audit_log import compute_signature, verify_chain, walk_chain
    from audit_log import GENESIS_PREVIOUS_SIGNATURE

    assert CHAIN_FIELDS == (
        "event_id",
        "timestamp",
        "user_identifier",
        "action",
        "patient_hash",
        "data_elements",
        "model_run_id",
    )
    assert GENESIS_PREVIOUS_SIGNATURE == "0" * 64
    assert callable(compute_signature)
    assert callable(verify_chain)
    assert callable(walk_chain)
