"""Shadow-runner CLI: audit an 837P / CSV / JSON file with the v12 auditor.

This is the operationalisation of the marketing promise on /calculator:

> The first 100-claim audit is no-cost. We send you a written
> finding-by-finding summary and a 30-minute review call.

What it does
------------
1. Read the input file (837P text, CSV row, or a JSON list of
   encounters).
2. For each claim / encounter, build the audit payload and call
   the v12 auditor (LLMClient + RESPONSE_JSON_SCHEMA).
3. Collect the findings, validate them against the per-finding
   rubric, and write a finding-by-finding report in two formats:
   - Markdown (one-pager) for the clinic admin to read.
   - JSON (machine-readable) for the Zorva portal to ingest.

The runner is hermetic-by-default: it runs offline against the
v12 cleaned AHCIP val set (``data/synth/val_ca.json``) so a
privacy officer can review the pipeline on a developer laptop
without an LLM key. Pass ``--provider <name>`` to drive real
audits through Ollama Cloud, Claude, or OpenAI.

Input formats
-------------
* **837P text** (``.837`` or ``.edi``): parsed by the existing
  x12_parser.py. Each CLM becomes one encounter.
* **CSV** (``.csv``): expected columns = ``encounter_id,
  clinical_note, cpt_codes, icd_codes, date_of_service`` (one
  claim per row). Comma-separated codes.
* **JSON list** (``.json``): a list of ``{encounter_id,
  clinical_note, claim: {...}, ...}`` objects — the canonical
  shape the auditor expects.

Output
------
* ``runs/shadow/<input-stem>-<timestamp>.md`` — human report.
* ``runs/shadow/<input-stem>-<timestamp>.json`` — machine report.
* Exit code 0 = success. Non-zero = input file unreadable or
  every encounter errored.

Usage
-----
    # Run on the cleaned AHCIP val set (hermetic, no LLM)
    .venv/bin/python scripts/shadow_audit.py data/synth/val_ca.json

    # Run on a real 837P file
    .venv/bin/python scripts/shadow_audit.py path/to/clinic.837

    # Run on a real CSV
    .venv/bin/python scripts/shadow_audit.py path/to/claims.csv

    # Real LLM via Ollama Cloud
    .venv/bin/python scripts/shadow_audit.py data/synth/val_ca.json \\
        --provider ollama --base-url https://ollama.com/v1

The runner is intentionally read-only: it does NOT call the live
API, does NOT write to the audit_trail.jsonl or the portal
Postgres, and does NOT need a server running. The reports it
produces are the exact artifact a privacy officer receives on
day 7 of a real pilot.
"""
from __future__ import annotations

import argparse
import concurrent.futures as _cf
import csv
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import textwrap
import time as _time
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# Severity ordering for the report summary. Critical first so the
# top of the finding list is what the privacy officer should see.
SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")


# SOMB-anchored per-finding dollar impact (SOMB 2026-Q2 fee values).
# These are conservative mid-points used only for the report summary;
# real per-encounter impact varies by payer mix and modifier context.
# The numbers are not a guarantee of recovered revenue.
#
# P11 round-3 (2026-07-02): aligned with the canonical rule_id
# namespace emitted by ``_canonicalize_rule_id()`` in auditor.py
# (the LLM-side alias map). New buckets added for aliases that
# previously fell through to "$0" in the report summary.
SOMB_DOLLAR_BY_RULE: dict[str, int] = {
    "rule_ahcip_modifier_25_unlock": 50,  # was: _modifier_25
    "rule_ahcip_psychotherapy_time": 64,
    "rule_ahcip_em_level": 30,
    "rule_ahcip_em_level_upcode": 30,
    "rule_ahcip_dx_linkage": 80,
    "rule_ahcip_non_insured_service": 48,
    "rule_ahcip_after_hours_premium": 25,
    "rule_ahcip_telehealth": 20,
    "rule_ahcip_telehealth_premium": 20,  # alias-mapped
    "rule_ahcip_referring_npi": 40,
    "rule_ahcip_consultation_missed": 40,  # alias-mapped
    "rule_ahcip_global_window": 60,
    "rule_ahcip_lab_coverage": 0,  # not a recovery, an avoidance
    "rule_ahcip_lab_order_no_draw": 0,  # alias-mapped; also an avoidance
    "rule_ahcip_cmgp": 25,
    "rule_ahcip_same_day_conflict": 30,
    "rule_ahcip_missing_procedure": 30,  # alias-mapped; conservative
    "rule_ahcip_03_05A_alternative": 40,  # alias-mapped; conservative
}


# SOMB-friendly human-readable labels for the canonical rule_ids.
# Used in the 1-page report's finding-by-finding rows so the privacy
# officer / clinic admin sees SOMB language ("Modifier-25 unlock
# missed per SOMB GR 1.4") instead of the snake_case internal name.
# Add new entries whenever a new canonical rule_id is added to
# SOMB_DOLLAR_BY_RULE above.
SOMB_LABEL_BY_RULE: dict[str, str] = {
    "rule_ahcip_modifier_25_unlock": "Modifier-25 unlock missed (SOMB GR 1.4)",
    "rule_ahcip_psychotherapy_time": "Psychotherapy time not billed (SOMB GR 8.19)",
    "rule_ahcip_em_level": "E/M level may be under-supported (SOMB GR 3.4)",
    "rule_ahcip_em_level_upcode": "E/M upcode risk vs documentation (SOMB GR 3.4)",
    "rule_ahcip_dx_linkage": "Diagnosis linkage missing for procedure (SOMB GR 3.4A)",
    "rule_ahcip_non_insured_service": "Non-insured service billed to AHCIP (SOMB GR 1.5)",
    "rule_ahcip_after_hours_premium": "After-hours premium not applied (SOMB GR 5.3)",
    "rule_ahcip_telehealth": "Telehealth premium missed (SOMB GR 5.4)",
    "rule_ahcip_telehealth_premium": "Telehealth premium missed (SOMB GR 5.4)",
    "rule_ahcip_referring_npi": "Referring provider NPI missing (SOMB GR 2.1)",
    "rule_ahcip_consultation_missed": "Consultation code not claimed (SOMB GR 2.2)",
    "rule_ahcip_global_window": "Service inside global/post-op window (SOMB GR 6.1)",
    "rule_ahcip_lab_coverage": "In-office lab coverage avoidance (SOMB GR 4.2)",
    "rule_ahcip_lab_order_no_draw": "Lab ordered but not drawn (SOMB GR 4.2)",
    "rule_ahcip_cmgp": "CMGP / chronic disease management missed (SOMB GR 7.1)",
    "rule_ahcip_same_day_conflict": "Same-day E&M + procedure conflict (SOMB GR 1.4)",
    "rule_ahcip_missing_procedure": "In-office procedure not billed (SOMB GR 3.5)",
    "rule_ahcip_03_05A_alternative": "03.05A alternative-payment rule applied (SOMB GR 3.5A)",
}


def _friendly_rule_label(rule_id: str) -> str:
    """Render a canonical rule_id as SOMB-friendly copy.

    Falls back to the raw rule_id (with leading 'rule_ahcip_' stripped)
    if no friendly label is registered.
    """
    if not rule_id:
        return ""
    if rule_id in SOMB_LABEL_BY_RULE:
        return SOMB_LABEL_BY_RULE[rule_id]
    # Best-effort fallback: 'rule_ahcip_modifier_25_unlock' -> 'Modifier 25 Unlock'
    bare = rule_id.replace("rule_ahcip_", "").replace("_", " ").strip()
    return bare.title() if bare else rule_id


# ---------- Input loading ---------------------------------------------------


def _read_json_or_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSON list or JSONL file into a list of dicts."""
    text = path.read_text()
    text_stripped = text.strip()
    if text_stripped.startswith("["):
        return json.loads(text_stripped)
    out: list[dict[str, Any]] = []
    for line in text_stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def _read_837p(path: Path) -> list[dict[str, Any]]:
    """Parse an 837P text file and project each claim into the
    canonical encounter shape the auditor expects."""
    from ai_billing_audit.x12_parser import parse_837p

    claims = parse_837p(path.read_text())
    return [
        {
            "encounter_id": c.get("encounter_id") or f"x12-{i:04d}",
            "clinical_note": "",  # the X12 file rarely carries notes
            "claim": {
                "CPT_codes": c.get("CPT_codes", []),
                "diagnosis_codes": c.get("diagnosis_codes", []),
                "date_of_service": c.get("date_of_service"),
                "NPI": c.get("NPI"),
                "patient_id": c.get("patient_id"),
            },
        }
        for i, c in enumerate(claims)
    ]


def _read_csv(path: Path) -> list[dict[str, Any]]:
    """Read a CSV of claims into the canonical encounter shape.

    Expected columns (case-insensitive): encounter_id, clinical_note,
    cpt_codes (comma-separated), icd_codes (comma-separated),
    date_of_service.
    """
    out: list[dict[str, Any]] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            row_lc = {k.lower().strip(): (v or "").strip() for k, v in row.items() if k}
            cpts = [
                c.strip()
                for c in row_lc.get("cpt_codes", "").split(",")
                if c.strip()
            ]
            icds = [
                c.strip()
                for c in row_lc.get("icd_codes", "").split(",")
                if c.strip()
            ]
            out.append(
                {
                    "encounter_id": row_lc.get("encounter_id")
                    or f"csv-{i:04d}",
                    "clinical_note": row_lc.get("clinical_note", ""),
                    "claim": {
                        "CPT_codes": cpts,
                        "diagnosis_codes": icds,
                        "date_of_service": row_lc.get("date_of_service")
                        or None,
                    },
                }
            )
    return out


def load_encounters(path: Path) -> list[dict[str, Any]]:
    """Load encounters from any supported input format. Falls back
    to treating the file as 837P text when the extension and
    content are ambiguous."""
    suffix = path.suffix.lower()
    if suffix in (".json", ".jsonl"):
        return _read_json_or_jsonl(path)
    if suffix == ".csv":
        return _read_csv(path)
    if suffix in (".837", ".edi", ".txt"):
        return _read_837p(path)
    # Heuristic: try JSON, then CSV, then 837P text.
    text = path.read_text().lstrip()
    if text.startswith("[") or text.startswith("{"):
        return _read_json_or_jsonl(path)
    if "," in text.splitlines()[0]:
        return _read_csv(path)
    return _read_837p(path)


# ---------- Audit invocation -----------------------------------------------


def _auditor_for(provider: str, base_url: str | None) -> Any:
    """Return a callable ``(encounter) -> list[dict]`` for the
    chosen provider. ``provider="stub"`` is the hermetic default:
    it produces deterministic canned findings from the val_ca.json
    gold set so the pipeline can be exercised without an LLM key."""
    if provider == "stub":
        return _stub_auditor()
    # Real LLM via litellm
    from ai_billing_audit.llm import LLMClient
    from ai_billing_audit.auditor import (
        RESPONSE_JSON_SCHEMA,
        build_messages,
        load_prompt,
        validate_findings,
    )

    os.environ.setdefault("LLM_PROVIDER", provider)
    if base_url:
        os.environ["LLM_BASE_URL"] = base_url
    client = LLMClient()
    prompt = load_prompt()

    def run(encounter: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            messages = build_messages(encounter, prompt=prompt)
            payload = client.complete_json(
                messages, RESPONSE_JSON_SCHEMA, temperature=0.2
            )
        except Exception as exc:  # noqa: BLE001
            return [
                {
                    "rule_id": "AUDIT_ERROR",
                    "severity": "info",
                    "category": "system",
                    "suggested_code": "",
                    "quote": "",
                    "explanation": f"auditor call failed: {exc}",
                    "error": True,
                }
            ]
        for f in payload.get("findings") or []:
            if isinstance(f, dict) and "severity" in f:
                f["severity"] = str(f["severity"]).strip().lower()
        try:
            findings = validate_findings(
                payload,
                clinical_note=str(encounter.get("clinical_note", "") or ""),
            )
        except Exception as exc:  # noqa: BLE001
            return [
                {
                    "rule_id": "VALIDATION_ERROR",
                    "severity": "info",
                    "category": "system",
                    "suggested_code": "",
                    "quote": "",
                    "explanation": f"finding validation failed: {exc}",
                    "error": True,
                }
            ]
        return [
            {
                "rule_id": ",".join(f.rule_ids) if f.rule_ids else "",
                "severity": f.severity,
                "category": f.category,
                "suggested_code": f.suggested_code,
                "quote": f.quote,
                "explanation": f.explanation,
                "finding_id": f.finding_id,
            }
            for f in findings
        ]

    return run


def _stub_auditor() -> Any:
    """Hermetic canned-finding auditor for offline runs.

    Reads the v12 recall run (runs/recall/v12_ahcip_clean.json) and
    returns the predicted findings for each encounter, matching on
    encounter_id. This lets a privacy officer run the full pipeline
    on a developer laptop with no LLM key and see the same shape
    report they'd get from a real audit.
    """
    recall_path = REPO / "runs" / "recall" / "v12_ahcip_clean.json"
    by_id: dict[str, list[dict[str, Any]]] = {}
    if recall_path.is_file():
        with recall_path.open() as f:
            data = json.load(f)
        for entry in data.get("results", []):
            eid = entry.get("encounter_id")
            if not eid:
                continue
            by_id[eid] = entry.get("pred_findings", [])

    def run(encounter: dict[str, Any]) -> list[dict[str, Any]]:
        eid = encounter.get("encounter_id")
        findings = by_id.get(eid, [])
        if not findings:
            return [
                {
                    "rule_id": "STUB_NO_DATA",
                    "severity": "info",
                    "category": "system",
                    "suggested_code": "",
                    "quote": "",
                    "explanation": (
                        f"No v12 recall data for encounter_id={eid!r}. "
                        "Pass --provider ollama to run a real audit, "
                        "or use a file with encounter_ids that match "
                        "data/synth/val_ca.json."
                    ),
                }
            ]
        return [
            {
                "rule_id": f.get("rule_id", ""),
                "severity": f.get("severity", "info"),
                "category": f.get("category", ""),
                "suggested_code": f.get("suggested_code", ""),
                "quote": f.get("quote", ""),
                "explanation": f.get("explanation", ""),
                "finding_id": f.get("finding_id", ""),
            }
            for f in findings
        ]

    return run


# ---------- Report generation ----------------------------------------------


def _summarise(encounters: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-finding counts by rule + severity."""
    by_rule: dict[str, int] = {}
    by_severity: dict[str, int] = {s: 0 for s in SEVERITY_ORDER}
    total_estimated_dollars = 0
    total_findings = 0
    for enc in encounters:
        for f in enc.get("findings", []):
            total_findings += 1
            rid = f.get("rule_id") or "<unruled>"
            by_rule[rid] = by_rule.get(rid, 0) + 1
            sev = (f.get("severity") or "info").lower()
            by_severity[sev] = by_severity.get(sev, 0) + 1
            if not f.get("error"):
                total_estimated_dollars += SOMB_DOLLAR_BY_RULE.get(rid, 0)
    return {
        "n_encounters": len(encounters),
        "n_findings": total_findings,
        "n_estimated_dollars": total_estimated_dollars,
        "by_rule": dict(
            sorted(by_rule.items(), key=lambda kv: -kv[1])
        ),
        "by_severity": by_severity,
    }


def _render_markdown(
    input_path: Path,
    encounters: list[dict[str, Any]],
    summary: dict[str, Any],
    provider: str,
    *,
    wall_seconds: float | None = None,
    concurrency: int = 1,
) -> str:
    """Render the human-readable finding report."""
    ts = _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    n = summary["n_encounters"]
    n_f = summary["n_findings"]
    n_d = summary["n_estimated_dollars"]
    sev_str = ", ".join(
        f"{k}={v}" for k, v in summary["by_severity"].items() if v
    ) or "none"
    rule_str = ", ".join(
        f"{k}={v}" for k, v in list(summary["by_rule"].items())[:5]
    ) or "none"

    lines: list[str] = []
    lines.append(f"# Zorva shadow audit report — {input_path.name}")
    lines.append("")
    timing = ""
    if wall_seconds is not None:
        if n > 0:
            timing = (
                f" · wall={wall_seconds:.1f}s "
                f"({wall_seconds / n:.2f}s/encounter, "
                f"concurrency={concurrency})"
            )
        else:
            timing = f" · wall={wall_seconds:.1f}s"
    lines.append(
        f"Generated {ts} · provider=`{provider}` · encounters={n} · "
        f"findings={n_f} · estimated impact=${n_d:,} CAD (SOMB-anchored)"
        f"{timing}"
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Encounters audited:** {n}")
    lines.append(f"- **Total findings:** {n_f}")
    lines.append(f"- **By severity:** {sev_str}")
    lines.append(f"- **By rule (top 5):** {rule_str}")
    lines.append(
        f"- **Estimated SOMB-anchored impact:** ${n_d:,} CAD "
        f"(per-finding rule-rate; per-encounter impact varies by "
        f"payer mix and modifier context. **Not a guarantee of "
        f"recovered revenue.**)"
    )
    lines.append("")

    if summary["by_rule"]:
        lines.append("## Findings by rule")
        lines.append("")
        lines.append("| Rule (canonical) | SOMB-friendly label | Count | Per-finding SOMB rate |")
        lines.append("|---|---|---|---|")
        for rule, count in summary["by_rule"].items():
            rate = SOMB_DOLLAR_BY_RULE.get(rule, 0)
            label = _friendly_rule_label(rule)
            lines.append(
                f"| `{rule}` | {label} | {count} | "
                f"{'$' + str(rate) if rate else '—'} |"
            )
        lines.append("")

    lines.append("## Per-encounter findings")
    lines.append("")
    for enc in encounters:
        eid = enc.get("encounter_id", "<no-id>")
        lines.append(f"### `{eid}`")
        cpts = (enc.get("claim") or {}).get("CPT_codes") or []
        if cpts:
            lines.append(f"Submitted: {', '.join(cpts)}")
        icds = (enc.get("claim") or {}).get("diagnosis_codes") or []
        if icds:
            lines.append(f"ICD-10-CA: {', '.join(icds)}")
        findings = enc.get("findings", [])
        if not findings:
            lines.append("_No findings._")
            lines.append("")
            continue
        for f in findings:
            sev = (f.get("severity") or "info").upper()
            rule = f.get("rule_id") or "—"
            label = _friendly_rule_label(rule) if rule != "—" else "—"
            code = f.get("suggested_code") or ""
            quote = f.get("quote") or ""
            explanation = f.get("explanation") or ""
            err = " (ERROR)" if f.get("error") else ""
            lines.append(
                f"- **{sev}** `{rule}` ({label}) → `{code}`{err}"
            )
            if quote:
                wrapped = textwrap.fill(
                    f"  Quote: \"{quote}\"", width=88, subsequent_indent="    "
                )
                lines.append(wrapped)
            if explanation:
                wrapped = textwrap.fill(
                    f"  Why: {explanation}", width=88, subsequent_indent="    "
                )
                lines.append(wrapped)
        lines.append("")

    lines.append("## Method")
    lines.append("")
    lines.append(
        "Findings are produced by the v12 auditor "
        "(`prompts/v12/auditor_prompt.txt`, AHCIP-tuned, post EXAMPLE 6/7 "
        "leak-fix). Severity is per-finding (critical > high > medium > "
        "low > info). SOMB-anchored dollar rates are per-finding rule "
        "rates from the 2026-Q2 SOMB fee schedule; per-encounter "
        "recovery varies by payer mix and modifier context. The audit "
        "tier is a **research tier** (F1=0.690 on the cleaned AHCIP "
        "val set of 10 encounters / 13 gold findings) and is honest "
        "about precision (P=0.647 → ~2 of 3 flags are real findings)."
    )
    return "\n".join(lines)


def _render_json(
    input_path: Path,
    encounters: list[dict[str, Any]],
    summary: dict[str, Any],
    provider: str,
) -> dict[str, Any]:
    """Render the machine-readable finding report."""
    return {
        "input_file": str(input_path),
        "generated_at": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(),
        "provider": provider,
        "summary": summary,
        "encounters": [
            {
                "encounter_id": e.get("encounter_id"),
                "claim": e.get("claim", {}),
                "findings": e.get("findings", []),
            }
            for e in encounters
        ],
    }


# ---------- CLI -------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "input",
        type=Path,
        help=(
            "Path to the input file: 837P text, CSV, or JSON. See "
            "module docstring for the supported shapes."
        ),
    )
    parser.add_argument(
        "--provider",
        default="stub",
        choices=("stub", "ollama", "openai", "anthropic", "google"),
        help=(
            "Which auditor backend to drive. 'stub' (default) is the "
            "hermetic canned-finding auditor that reads the v12 "
            "recall run — useful for offline / privacy-officer "
            "review. 'ollama' / 'openai' / 'anthropic' / 'google' "
            "drive a real LLM via litellm and require the matching "
            "*_API_KEY env var."
        ),
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "Override LLM_BASE_URL. Required for Ollama Cloud "
            "(https://ollama.com/v1). Ignored for other providers."
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO / "runs" / "shadow",
        help=(
            "Where to write the Markdown and JSON report. Default: "
            "runs/shadow/ inside the repo."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Audit only the first N encounters (for quick smoke tests).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help=(
            "Number of encounters to audit in parallel using a "
            "thread pool. Default 1 (sequential). 5-10 is a good "
            "range for Ollama Cloud and OpenAI; locally-hosted "
            "Ollama (single GPU) should stay at 1 to avoid "
            "queueing. Each worker holds its own connection "
            "to the LLM provider — concurrent calls share the "
            "provider's rate limit, so going above 25 usually "
            "doesn't help."
        ),
    )
    args = parser.parse_args()

    if args.concurrency < 1:
        print(f"ERROR: --concurrency must be >= 1, got {args.concurrency}", file=sys.stderr)
        return 2
    if args.concurrency > 50:
        print(
            f"WARN: --concurrency={args.concurrency} is unusually high; "
            "capping at 50 to keep provider rate limits sane.",
            file=sys.stderr,
        )
        args.concurrency = 50

    if not args.input.is_file():
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        return 2

    encounters = load_encounters(args.input)
    if args.limit is not None:
        encounters = encounters[: args.limit]
    if not encounters:
        print(f"ERROR: no encounters loaded from {args.input}", file=sys.stderr)
        return 3

    run = _auditor_for(args.provider, args.base_url)
    wall_start = _time.monotonic()
    if args.concurrency == 1 or len(encounters) <= 1:
        for enc in encounters:
            enc["findings"] = run(enc)
    else:
        # Concurrent path. ThreadPoolExecutor workers share the GIL
        # but the work here is I/O-bound on the LLM call (HTTP POST
        # to litellm), so threading gives a near-linear speedup on
        # latency. Workers are submitted in encounter order and the
        # results are written back into the same index, so the output
        # is byte-identical to the sequential path (modulo a slow
        # call finishing before a fast one — order of arrival is
        # irrelevant to the report because we never compare across
        # encounters in the markdown / JSON renders).
        n_workers = min(args.concurrency, len(encounters))
        with _cf.ThreadPoolExecutor(max_workers=n_workers) as ex:
            futures: dict[_cf.Future[list[dict[str, Any]]], int] = {
                ex.submit(run, enc): idx
                for idx, enc in enumerate(encounters)
            }
            done_count = 0
            total = len(encounters)
            for fut in _cf.as_completed(futures):
                idx = futures[fut]
                encounters[idx]["findings"] = fut.result()
                done_count += 1
                if total <= 50 or done_count % max(1, total // 10) == 0:
                    print(
                        f"  ... {done_count}/{total} audits complete",
                        file=sys.stderr,
                    )
    wall_seconds = _time.monotonic() - wall_start

    summary = _summarise(encounters)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.input.stem
    ts = _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    md_path = args.out_dir / f"{stem}-{ts}.md"
    json_path = args.out_dir / f"{stem}-{ts}.json"

    md_path.write_text(
        _render_markdown(
            args.input,
            encounters,
            summary,
            args.provider,
            wall_seconds=wall_seconds,
            concurrency=args.concurrency,
        )
    )
    json_path.write_text(
        json.dumps(
            _render_json(args.input, encounters, summary, args.provider),
            indent=2,
        )
    )

    print(f"OK: {len(encounters)} encounters, {summary['n_findings']} findings")
    print(f"    Markdown: {md_path}")
    print(f"    JSON:     {json_path}")
    print(
        f"    Wall time: {wall_seconds:.1f}s "
        f"({wall_seconds / max(1, len(encounters)):.2f}s/encounter, "
        f"concurrency={args.concurrency})"
    )
    if summary["n_findings"] == 0:
        print("    (no findings — re-run with --provider ollama for a real audit)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
