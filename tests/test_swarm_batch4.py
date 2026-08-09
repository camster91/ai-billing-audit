"""Tests pinning the code-quality BLOCKING fixes from swarm-batch4.

Two contracts:

1. ground_truth.__all__ only contains names that are actually
   defined in the module. Pre-fix it advertised ``Encounter``
   and ``GroundTruthFinding`` which don't exist; any caller doing
   ``from ai_billing_audit.ground_truth import *`` would get
   ImportError.

2. audit_actions.append() does NOT print a ``DEBUG: pid=...``
   line on every call. Pre-fix the function printed to stdout
   on every state-changing dashboard click — leaking internal
   state to Docker logs (visible to anyone with container
   access) and polluting the LOG_FORMAT=json shipper.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ai_billing_audit.clinical_note_storage import read_encrypted_json_records


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_ground_truth_all_is_resolvable():
    """Every name in ground_truth.__all__ must be importable from
    the module (no broken promises in the public API contract).
    """
    import ai_billing_audit.ground_truth as gt

    for name in gt.__all__:
        assert hasattr(gt, name), (
            f"ground_truth.__all__ advertises {name!r} but the "
            "module does not define it. Either remove the name "
            "from __all__ or add the missing definition."
        )


def test_ground_truth_star_import_works():
    """``from ai_billing_audit.ground_truth import *`` must succeed
    without ImportError. Pre-fix this raised because Encounter
    and GroundTruthFinding weren't defined.
    """
    # Wipe any cached version
    sys.modules.pop("ai_billing_audit.ground_truth", None)
    import ai_billing_audit.ground_truth  # noqa: F401

    # Run a star-import via exec to mimic ``from X import *``.
    ns: dict = {}
    exec("from ai_billing_audit.ground_truth import *", ns)
    # The names in __all__ should now be in ns.
    import ai_billing_audit.ground_truth as gt

    for name in gt.__all__:
        assert name in ns, f"star-import of ground_truth did not expose {name!r}"


def test_audit_actions_append_does_not_print_debug(monkeypatch, tmp_path):
    """The pre-fix ``DEBUG: pid=... path=... env=...`` print on every
    audit append polluted stdout and the LOG_FORMAT=json shipper.
    Verify the print is gone by capturing stdout during a write.
    """
    import io
    import contextlib
    from ai_billing_audit import audit_actions

    # Set the log path to a tmp file so the append doesn't touch
    # the repo's real audit_trail.jsonl.
    log = tmp_path / "audit_trail.jsonl"
    monkeypatch.setenv("AUDIT_TRAIL_LOG", str(log))

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        audit_actions.append(
            action="test_action",
            encounter_id="enc-test-1",
            user_identifier="test-user",
            findings=[],
            note="swarm-batch4 calibration test",
        )

    stdout_output = captured.getvalue()
    assert "DEBUG:" not in stdout_output, (
        f"audit_actions.append() still prints a DEBUG: line. "
        f"Got: {stdout_output[:200]!r}"
    )
    # And the row was actually written.
    assert log.exists()
    rows = read_encrypted_json_records(log)
    assert len(rows) == 1
    assert rows[0]["action"] == "test_action"
