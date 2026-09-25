"""Round-trip guard for the audit hash chain (issue #113).

The defect this pins
--------------------
``audit_actions.append()`` writes ``cryptographic_signature`` with one
rendering rule for ``data_elements`` (canonical JSON for dicts) while
``audit_actions.verify_chain()`` delegated to ``audit_log.verify_chain()``,
which used a different rule (``str()``). Because ``append()`` always stores
``data_elements`` as a dict, the verifier reported **every row the writer had
just written** as tampered — the chain appeared broken from row 0 on both the
dev JSONL and the Postgres path (``data_elements JSONB`` comes back as a dict).

Why the existing suite missed it
--------------------------------
``tests/test_audit_log.py`` only ever exercises ``data_elements`` as a
*string*, which is the one case where the two rules agree.
``scripts/qa_audit_chain_verify.py`` reads rows through ``psql -A``, which
returns ``data_elements`` as text — again the agreeing case.
``tests/test_rbac.py`` explicitly declined to call ``verify_chain`` and
documented the mismatch as a known follow-up.

So the assertion that was missing everywhere is the plain one: write rows
through the live writer, read them back the way a verifier does, and assert
the chain verifies. That is the first test below.
"""

from __future__ import annotations

import importlib

import pytest

from ai_billing_audit import audit_actions as aa_mod

import audit_log


@pytest.fixture
def tmp_log(tmp_path, monkeypatch):
    """Point the audit_actions module at a throwaway log file.

    Mirrors the fixture in ``tests/test_audit_actions_tenant.py``: set the
    env var and reload so the module re-resolves its path.
    """
    log = tmp_path / "audit_trail.jsonl"
    monkeypatch.setenv("AUDIT_TRAIL_LOG", str(log))
    importlib.reload(aa_mod)
    return log


@pytest.fixture
def tmp_feedback_log(tmp_path, monkeypatch):
    """Throwaway feedback log, for the feedback-chain link test."""
    log = tmp_path / "feedback.jsonl"
    monkeypatch.setenv("FEEDBACK_LOG", str(log))
    return log


# ---------------------------------------------------------------------------
# The assertion that was missing: append -> read back -> verify
# ---------------------------------------------------------------------------


def test_append_read_back_verify_chain_is_intact(tmp_log):
    """Rows written by the live writer must verify against themselves.

    This is the regression guard for issue #113. Before the fix it reported
    index 0 (a false tamper) on a freshly written three-row log.
    """
    aa_mod.append("upload", "enc_ca_001", user_identifier="biller@clinic")
    aa_mod.append(
        "accept_all",
        "enc_ca_001",
        user_identifier="biller@clinic",
        findings=[{"finding_id": "f-1"}],
        note="looks right",
    )
    aa_mod.append("submit", "enc_ca_001", user_identifier="biller@clinic")

    rows = aa_mod.read_all()
    assert len(rows) == 3

    # data_elements really is a dict on the read-back path — that is what
    # made the old verifier disagree with the old writer.
    assert isinstance(rows[0]["data_elements"], dict)

    assert aa_mod.verify_chain(rows) is None


def test_verify_chain_still_detects_real_tampering(tmp_log):
    """Guards against 'fixing' #113 by making the verifier return None.

    A verifier that trivially reports an intact chain would be worse than the
    bug, so the tamper case is asserted alongside the clean case.
    """
    aa_mod.append("upload", "enc_ca_001", user_identifier="b")
    aa_mod.append("accept_all", "enc_ca_002", user_identifier="b")
    aa_mod.append("submit", "enc_ca_003", user_identifier="b")

    rows = aa_mod.read_all()
    assert aa_mod.verify_chain(rows) is None

    # Insider edit: change a payload field, leave the signature alone.
    rows[1] = {**rows[1], "action": "accept_all_and_overwrite"}
    assert aa_mod.verify_chain(rows) == 1


# ---------------------------------------------------------------------------
# The exact rule that diverged: data_elements rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data_elements",
    [
        {"a": 1, "b": 2},  # the case the writer always produces
        {"note": "has spaces, and: colons"},
        {"nested": {"y": [1, 2], "x": None}},
        {},  # empty dict
        '{"a":1,"b":2}',  # already-canonical string
        '{"b": 2, "a": 1}',  # non-canonical string
        "",  # empty string
        None,
        [1, 2, 3],  # list
    ],
    ids=[
        "dict",
        "dict-with-spaces",
        "nested-dict",
        "empty-dict",
        "canonical-str",
        "noncanonical-str",
        "empty-str",
        "none",
        "list",
    ],
)
def test_writer_and_verifier_agree_on_every_data_elements_shape(data_elements):
    """``audit_actions`` and ``audit_log`` must render every shape identically.

    Enumerated rather than spot-checked, because the original defect was a
    single unhandled shape (dict) slipping through a string-only test.
    """
    row = {
        "event_id": "e-1",
        "timestamp": "2026-09-20T00:00:00.000000Z",
        "user_identifier": "u",
        "action": "accept",
        "patient_hash": "ab" * 32,
        "data_elements": data_elements,
        "model_run_id": "run-1",
    }
    from_writer = aa_mod.compute_signature("0" * 64, row)
    from_verifier = audit_log.compute_signature("0" * 64, row)
    assert from_writer == from_verifier


def test_postgres_style_jsonb_rows_verify(tmp_log):
    """JSONB round-trips as a dict; those rows must verify too."""
    aa_mod.append("upload", "enc_ca_001", user_identifier="b")

    rows = aa_mod.read_all()
    # Simulate the psycopg JSONB shape explicitly rather than relying on the
    # JSONL path happening to produce a dict.
    as_jsonb = [{**r, "data_elements": dict(r["data_elements"])} for r in rows]
    assert audit_log.verify_chain(as_jsonb) is None


# ---------------------------------------------------------------------------
# Structural guards
# ---------------------------------------------------------------------------


def test_audit_log_and_chain_share_one_implementation():
    """The shim must re-export the shared implementation, not a copy.

    Identity (not equality) is asserted so that reintroducing a local copy —
    which is how #113 happened — fails this test immediately.
    """
    from ai_billing_audit import chain

    assert audit_log.compute_signature is chain.compute_signature
    assert audit_log.verify_chain is chain.verify_chain
    assert audit_log.CHAIN_FIELDS is chain.CHAIN_FIELDS
    assert audit_log.GENESIS_PREVIOUS_SIGNATURE == chain.GENESIS_PREVIOUS_SIGNATURE
    assert not hasattr(aa_mod, "_local_chain_rule")


def test_no_separator_byte_is_reintroduced():
    """A field separator would change every digest; assert the concat shape.

    Reconstructed independently of the implementation so a change to the
    shared rule has to be deliberate.
    """
    import hashlib
    import json

    row = {
        "event_id": "e-1",
        "timestamp": "t",
        "user_identifier": "u",
        "action": "a",
        "patient_hash": "h",
        "data_elements": {"b": 2, "a": 1},
        "model_run_id": "m",
    }
    expected = hashlib.sha256(
        (
            "0" * 64
            + "e-1"
            + "t"
            + "u"
            + "a"
            + "h"
            + json.dumps({"b": 2, "a": 1}, sort_keys=True, separators=(",", ":"))
            + "m"
        ).encode("utf-8")
    ).hexdigest()
    from ai_billing_audit import chain

    assert chain.compute_signature("0" * 64, row) == expected


def test_feedback_chain_links_every_row(tmp_feedback_log, monkeypatch):
    """The feedback chain must not fork.

    Same class of bug as #113, different root cause: ``_last_signature()``
    cached by mtime alone, and a write that did not advance ``st_mtime``
    returned a stale signature, chaining the next row to the wrong
    predecessor. The result was a log the store had just written failing its
    own ``verify_chain()``.
    """
    from ai_billing_audit import feedback as fb

    store = fb.FeedbackStore(tmp_feedback_log)
    for i in range(6):
        store.append(
            fb.FeedbackEntry(
                encounter_id="enc-1",
                finding_id=f"f-{i}",
                action="accept",
                severity="high",
                rule_id="r-1",
                category="c",
                timestamp=f"2026-09-20T00:00:0{i}Z",
                biller_id="b",
            )
        )
    assert store.verify_chain() is True
