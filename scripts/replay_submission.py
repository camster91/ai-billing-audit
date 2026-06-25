#!/usr/bin/env python3
"""Replay a previously-submitted Zorva batch through the auditor.

When the v13 prompt is ready (or any future prompt), this script lets
you re-run the same encounters that were previously submitted without
re-uploading the 837P+clinical-note files. The original submissions
live under ``/app/data`` on the VPS:

    /app/data/uploads/YYYY-MM-DD/<submission_id>/
        *.edi                       # the 837P claim file(s)
        *.txt                       # the clinical note(s)
        manifest.json               # SHA-256 + encounter_id mapping

The script:

  1. Loads ``manifest.json`` to get the (encounter_id, file path) pairs.
  2. Re-parses each 837P via ``x12_parser.parse_837p()``.
  3. Re-runs the auditor via ``auditor.run_audit()`` with the
     specified ``--prompt`` path.
  4. Writes a per-encounter replay report to
     ``runs/replay/<timestamp>/<encounter_id>.json``.
  5. Aggregates P/R/F1 against the gold labels in ``data/val_ca.json``
     (only for encounters that are present in the val set; others are
     reported as "no_gold" and the raw findings are still emitted).

Why this exists
---------------

The previous workflow required a real HTTP re-upload of every 837P
file, which:

  - re-passes the file through the FastAPI upload validator (different
    code path from the auditor itself);
  - consumes the live Ollama quota;
  - is not idempotent — the second submit generates a new
    ``upload_jobs.jsonl`` row and a new SHA-256 of the audit-trail
    chain;
  - depends on the bearer token being valid and Caddy being healthy.

Replay avoids all of that. It runs **offline**, against the local
filesystem, and only writes to the audit_trail if you pass
``--write-audit-trail`` (off by default — replay is a measurement
tool, not a customer-facing action).

Usage
-----

::

    # Replay every encounter from the most recent submission, using v12.
    python scripts/replay_submission.py \
        --submission-dir /app/data/uploads/2026-06-25/abc123 \
        --prompt prompts/v12/auditor_prompt.txt

    # Same, but compare against val_ca.json gold labels.
    python scripts/replay_submission.py \
        --submission-dir /app/data/uploads/2026-06-25/abc123 \
        --prompt prompts/v12/auditor_prompt.txt \
        --eval-set data/val_ca.json

    # Write the resulting audit_trail rows (still append-only).
    python scripts/replay_submission.py \
        --submission-dir /app/data/uploads/2026-06-25/abc123 \
        --prompt prompts/v12/auditor_prompt.txt \
        --write-audit-trail

Exit codes
----------

  0  every encounter audited, aggregate metrics (if --eval-set) within
     the threshold set by ``--max-f1-drop`` (default 0.02).
  1  one or more encounters failed parsing or auditing; details in
     stderr / per-encounter JSON.
  2  aggregate F1 dropped more than ``--max-f1-drop`` vs the baseline
     (or no baseline was found and --strict was passed).
  3  bad arguments / missing files.

The script is intentionally dependency-free beyond the project itself:
``x12_parser``, ``auditor``, ``llm`` are the only imports.

Implementation notes
--------------------

* The script does NOT touch ``val_ca.json``, ``prompts/v12/``,
  ``Dockerfile``, or ``deploy-to-vps.sh`` (these are pinned per the
  prompt-iteration playbook).
* It does NOT modify the audit_trail unless ``--write-audit-trail``
  is passed. By default it's a dry run.
* It uses ``Path`` everywhere, not bare strings, so it works on the
  VPS, in a container, and on a dev laptop without path-munging.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

# Repo-root import shim so this works whether you run it from /opt/...
# or from a fresh checkout.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from ai_billing_audit import auditor  # noqa: E402
from ai_billing_audit import x12_parser  # noqa: E402


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest(submission_dir: Path) -> list[dict[str, Any]]:
    """Read manifest.json from the submission directory.

    Schema (loose, because the upload portal has iterated):

      {
        "submission_id": "abc123",
        "uploaded_at":   "2026-06-25T14:32:11Z",
        "tenant":        "north-bay-fp",
        "encounters": [
          {"encounter_id": "nb_2026_06_25_001",
           "edi_file":     "nb_2026_06_25_001.edi",
           "note_file":    "nb_2026_06_25_001.txt"},
          ...
        ]
      }
    """
    mf = submission_dir / "manifest.json"
    if not mf.is_file():
        sys.exit(
            f"[replay] no manifest.json in {submission_dir}\n"
            "         (the upload portal writes one per submission; "
            "if it's missing, the submission predates v0.4.0)"
        )
    with mf.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data.get("encounters"), list):
        sys.exit(f"[replay] manifest.json has no 'encounters' list: {mf}")
    return data


def _load_eval_set(path: Path) -> dict[str, list[dict[str, Any]]]:
    """encounter_id -> list of gold finding dicts (rule_id-keyed)."""
    if not path or not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        rows = json.load(f)
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        eid = row.get("encounter_id")
        if not eid:
            continue
        out[eid] = row.get("ground_truth_findings") or row.get("findings") or []
    return out


def _bucket_metrics(
    pred_findings: Iterable[Any],
    gold_findings: Iterable[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    """Per-rule P/R/F1, micro across the buckets.

    The grader in ``src/ai_billing_audit/grader.py`` does the same math
    but on dict inputs; we re-implement the minimal version here so
    replay works without depending on the LLM-heavy grader.
    """
    pred_by_rule: dict[str, set[str]] = {}
    gold_by_rule: dict[str, set[str]] = {}

    for f in pred_findings:
        # Finding may be a dataclass or a dict; normalise to rule_id + encounter.
        rid = getattr(f, "rule_ids", None) or (
            f.get("rule_ids") if isinstance(f, dict) else []
        )
        eid = getattr(f, "encounter_id", None) or (
            f.get("encounter_id") if isinstance(f, dict) else ""
        )
        if isinstance(rid, (list, tuple)):
            for r in rid:
                pred_by_rule.setdefault(r, set()).add(eid)

    for g in gold_findings:
        rid = g.get("rule_id") or g.get("rule_ids")
        if isinstance(rid, str):
            rid_list = [rid]
        else:
            rid_list = list(rid or [])
        for r in rid_list:
            gold_by_rule.setdefault(r, set()).add(g.get("encounter_id", ""))

    out: dict[str, dict[str, float]] = {}
    all_rules = set(pred_by_rule) | set(gold_by_rule)
    tp_total = fp_total = fn_total = 0
    for r in sorted(all_rules):
        p_set = pred_by_rule.get(r, set())
        g_set = gold_by_rule.get(r, set())
        tp = len(p_set & g_set)
        fp = len(p_set - g_set)
        fn = len(g_set - p_set)
        tp_total += tp
        fp_total += fp
        fn_total += fn
        p = tp / (tp + fp) if (tp + fp) else 0.0
        rc = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * p * rc) / (p + rc) if (p + rc) else 0.0
        out[r] = {
            "p": round(p, 3),
            "r": round(rc, 3),
            "f1": round(f1, 3),
            "n_gold": len(g_set),
            "n_pred": len(p_set),
        }
    # micro row
    mp = tp_total / (tp_total + fp_total) if (tp_total + fp_total) else 0.0
    mr = tp_total / (tp_total + fn_total) if (tp_total + fn_total) else 0.0
    mf = (2 * mp * mr) / (mp + mr) if (mp + mr) else 0.0
    out["__micro__"] = {
        "p": round(mp, 3),
        "r": round(mr, 3),
        "f1": round(mf, 3),
        "tp": tp_total,
        "fp": fp_total,
        "fn": fn_total,
    }
    return out


def _audit_one(
    enc_meta: dict[str, Any],
    submission_dir: Path,
    prompt: str,
    out_dir: Path,
    eval_set: dict[str, list[dict[str, Any]]],
    write_audit_trail: bool,
) -> dict[str, Any]:
    """Run the auditor for one encounter and write its replay report."""
    eid = enc_meta["encounter_id"]
    edi_rel = enc_meta.get("edi_file")
    note_rel = enc_meta.get("note_file")
    edi_path = submission_dir / edi_rel if edi_rel else None
    note_path = submission_dir / note_rel if note_rel else None

    rec: dict[str, Any] = {
        "encounter_id": eid,
        "edi_sha256": _sha256(edi_path) if edi_path and edi_path.is_file() else None,
        "note_sha256": _sha256(note_path) if note_path and note_path.is_file() else None,
        "audit_status": "ok",
        "findings": [],
        "errors": [],
    }

    if not edi_path or not edi_path.is_file():
        rec["audit_status"] = "skipped"
        rec["errors"].append(f"missing edi_file: {edi_rel}")
        return rec

    try:
        parsed = x12_parser.parse_837p(edi_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        rec["audit_status"] = "parse_error"
        rec["errors"].append(f"x12_parser: {exc!r}")
        return rec

    # The auditor takes an encounter dict; the parser's output is the
    # canonical shape. Augment with the clinical note (the v0/v12
    # auditor doesn't use it, but future prompts will).
    encounter = dict(parsed)
    if note_path and note_path.is_file():
        encounter["clinical_note"] = note_path.read_text(encoding="utf-8", errors="replace")

    try:
        result = auditor.run_audit(encounter, prompt_path=Path(prompt) if prompt else None)
    except auditor.AuditValidationError as exc:
        rec["audit_status"] = "audit_validation_error"
        rec["errors"].append(f"auditor: {exc!r}")
        return rec

    rec["findings"] = [
        {**asdict(f), "encounter_id": eid} for f in result.findings
    ]
    rec["summary"] = result.summary

    gold = eval_set.get(eid)
    if gold is not None:
        rec["per_bucket"] = _bucket_metrics(result.findings, gold)
        rec["gold_n"] = len(gold)
    else:
        rec["per_bucket"] = None
        rec["gold_n"] = 0

    if write_audit_trail:
        # The live path is src/ai_billing_audit/audit_actions.append()
        # (see prompts/MANIFEST.json hash_chain_implementations_note).
        # We import here so the no-write path has zero side effects.
        from ai_billing_audit import audit_actions
        audit_actions.append(
            event_id=f"replay:{eid}",
            user_identifier="replay_submission.py",
            action="replay_audit",
            patient_hash=rec["edi_sha256"] or "",
            data_elements={
                "encounter_id": eid,
                "submission_dir": str(submission_dir),
                "prompt_path": prompt,
                "findings_n": len(rec["findings"]),
            },
            model_run_id="replay-no-llm",
        )
    return rec


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Pool per-bucket across records into a single micro row."""
    pooled: dict[str, dict[str, float]] = {}
    for r in records:
        pb = r.get("per_bucket") or {}
        for rule, m in pb.items():
            agg = pooled.setdefault(rule, {"tp": 0, "fp": 0, "fn": 0, "n_gold": 0, "n_pred": 0})
            agg["tp"] += m.get("tp", 0)
            agg["fp"] += m.get("fp", 0)
            agg["fn"] += m.get("fn", 0)
            agg["n_gold"] += m.get("n_gold", 0)
            agg["n_pred"] += m.get("n_pred", 0)
    out: dict[str, Any] = {}
    tp_total = fp_total = fn_total = 0
    for rule, agg in pooled.items():
        tp, fp, fn = agg["tp"], agg["fp"], agg["fn"]
        p = tp / (tp + fp) if (tp + fp) else 0.0
        rc = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * p * rc) / (p + rc) if (p + rc) else 0.0
        out[rule] = {
            "p": round(p, 3),
            "r": round(rc, 3),
            "f1": round(f1, 3),
            "n_gold": agg["n_gold"],
            "n_pred": agg["n_pred"],
        }
        if rule != "__micro__":
            tp_total += tp
            fp_total += fp
            fn_total += fn
    mp = tp_total / (tp_total + fp_total) if (tp_total + fp_total) else 0.0
    mr = tp_total / (tp_total + fn_total) if (tp_total + fn_total) else 0.0
    mf = (2 * mp * mr) / (mp + mr) if (mp + mr) else 0.0
    out["__micro__"] = {
        "p": round(mp, 3),
        "r": round(mr, 3),
        "f1": round(mf, 3),
        "tp": tp_total,
        "fp": fp_total,
        "fn": fn_total,
    }
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument(
        "--submission-dir",
        required=True,
        type=Path,
        help="Directory containing manifest.json + the original EDI/note files",
    )
    p.add_argument(
        "--prompt",
        required=False,
        type=str,
        default=None,
        help="Path to the auditor prompt (defaults to the bundled v12).",
    )
    p.add_argument(
        "--eval-set",
        type=Path,
        default=None,
        help="Optional gold-labels JSON (e.g., data/val_ca.json). "
             "Only encounters present in the set get per-bucket metrics.",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Override the default runs/replay/<timestamp>/ output dir.",
    )
    p.add_argument(
        "--write-audit-trail",
        action="store_true",
        help="Append audit_trail rows (default: dry-run).",
    )
    p.add_argument(
        "--max-f1-drop",
        type=float,
        default=0.02,
        help="Fail (exit 2) if aggregate F1 drops more than this vs --baseline-f1.",
    )
    p.add_argument(
        "--baseline-f1",
        type=float,
        default=None,
        help="Baseline micro F1 to compare against. If omitted and "
             "--strict is passed, exits 2.",
    )
    p.add_argument("--strict", action="store_true", help="Fail when no baseline is set.")
    args = p.parse_args(argv)

    submission_dir: Path = args.submission_dir
    if not submission_dir.is_dir():
        print(f"[replay] not a directory: {submission_dir}", file=sys.stderr)
        return 3

    manifest = _load_manifest(submission_dir)
    eval_set = _load_eval_set(args.eval_set) if args.eval_set else {}

    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or (_REPO_ROOT / "runs" / "replay" / stamp)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[replay] submission_id = {manifest.get('submission_id')}")
    print(f"[replay] tenant        = {manifest.get('tenant')}")
    print(f"[replay] uploaded_at   = {manifest.get('uploaded_at')}")
    print(f"[replay] encounters    = {len(manifest['encounters'])}")
    print(f"[replay] prompt        = {args.prompt or '(bundled default)'}")
    print(f"[replay] out_dir       = {out_dir}")

    records: list[dict[str, Any]] = []
    failures = 0
    for enc_meta in manifest["encounters"]:
        rec = _audit_one(
            enc_meta,
            submission_dir,
            args.prompt or "",
            out_dir,
            eval_set,
            args.write_audit_trail,
        )
        # Write per-encounter report
        report = out_dir / f"{rec['encounter_id']}.json"
        report.write_text(json.dumps(rec, indent=2, sort_keys=True), encoding="utf-8")
        if rec["audit_status"] != "ok":
            failures += 1
        records.append(rec)

    # Aggregate
    agg = _aggregate(records)
    (out_dir / "aggregate.json").write_text(
        json.dumps(agg, indent=2, sort_keys=True), encoding="utf-8"
    )
    micro = agg.get("__micro__", {})
    print(
        f"[replay] micro: P={micro.get('p')} "
        f"R={micro.get('r')} F1={micro.get('f1')} "
        f"(failures={failures})"
    )

    if args.baseline_f1 is not None:
        drop = args.baseline_f1 - micro.get("f1", 0.0)
        print(
            f"[replay] baseline F1 = {args.baseline_f1}, "
            f"drop = {drop:+.3f}, threshold = ±{args.max_f1_drop}"
        )
        if drop > args.max_f1_drop:
            print(
                f"[replay] FAIL — F1 dropped by {drop:.3f} "
                f"(>{args.max_f1_drop}); refusing to ship.",
                file=sys.stderr,
            )
            return 2
    elif args.strict:
        print("[replay] --strict set without --baseline-f1; exiting 2.", file=sys.stderr)
        return 2

    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())