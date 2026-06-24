"""Cross-provider comparison + PASS/FAIL verdict for the MVP acceptance run.

Reads every per-provider predictions JSONL produced by
``scripts/run_cross_provider.py`` under ``runs/acceptance/`` and:

  1. Scores each provider against the 150-encounter gold manifest
     (data/test_sample_manifest.json) using the same per-category
     multiset P/R/F1 logic as ``scripts/score_predictions.py``.
  2. Captures per-provider operational metrics: valid-output rate,
     wall-clock time, token usage, error tally.
  3. Produces ``runs/acceptance/comparison.json`` (machine-readable)
     and ``runs/acceptance/comparison.md`` (human-readable side-by-side
     table).
  4. Emits a PASS/FAIL verdict against the task body's acceptance
     criteria:

       * all 4 providers produced 100% valid output
       * all aggregate metrics are within 5% of each other
         ((max - min) / mean <= 0.05 per metric)

  The verdict is written to runs/acceptance/VERDICT.txt and printed to
  stdout. The script exits 0 on PASS, 2 on FAIL (so it can be wired
  into a CI gate).

Usage
-----
After running all four providers:

    LLM_PROVIDER=minimax .venv/bin/python scripts/run_cross_provider.py --provider minimax
    LLM_PROVIDER=claude  .venv/bin/python scripts/run_cross_provider.py --provider claude
    LLM_PROVIDER=openai  .venv/bin/python scripts/run_cross_provider.py --provider openai
    LLM_PROVIDER=gemini  .venv/bin/python scripts/run_cross_provider.py --provider gemini

...then aggregate:

    .venv/bin/python scripts/compare_acceptance.py
    .venv/bin/python scripts/aggregate_acceptance.py  # does both

The script accepts --runs-dir to point at a non-default location
(useful for archived acceptance runs).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_DIR = PROJECT_ROOT / "runs" / "acceptance"
MANIFEST_PATH = PROJECT_ROOT / "data" / "test_sample_manifest.json"

# Spread tolerance from the task body: (max - min) / mean <= 0.05.
SPREAD_TOLERANCE = 0.05

# Providers the acceptance task body requires.
EXPECTED_PROVIDERS: tuple[str, ...] = ("minimax", "claude", "openai", "gemini")


# ---------------------------------------------------------------------------
# Scoring helpers (lifted from scripts/score_predictions.py so this script
# is self-contained — the multiset semantics are the contract, not the file).
# ---------------------------------------------------------------------------

def _safe_div(num: float, den: float) -> float:
    if den == 0:
        return 0.0
    return num / den


def _f1(p: float, r: float) -> float:
    if p + r == 0.0:
        return 0.0
    return 2.0 * p * r / (p + r)


def _score_one(predicted: list[str], gold: list[str]) -> dict[str, dict[str, int]]:
    pc = Counter(predicted)
    gc = Counter(gold)
    cats = set(pc) | set(gc)
    out: dict[str, dict[str, int]] = {}
    for c in cats:
        tp = min(pc[c], gc[c])
        fp = pc[c] - tp
        fn = gc[c] - tp
        out[c] = {"tp": tp, "fp": fp, "fn": fn}
    return out


def _accumulate(per_encounter: list[dict[str, dict[str, int]]]) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = {}
    for enc in per_encounter:
        for cat, c in enc.items():
            row = totals.setdefault(cat, {"tp": 0, "fp": 0, "fn": 0})
            row["tp"] += c["tp"]
            row["fp"] += c["fp"]
            row["fn"] += c["fn"]
    return totals


def _per_category(totals: dict[str, dict[str, int]]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for cat, c in totals.items():
        support = c["tp"] + c["fn"]
        predicted = c["tp"] + c["fp"]
        p = _safe_div(c["tp"], c["tp"] + c["fp"])
        r = _safe_div(c["tp"], c["tp"] + c["fn"])
        rows[cat] = {
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(_f1(p, r), 4),
            "support": support,
            "predicted": predicted,
            "tp": c["tp"],
            "fp": c["fp"],
            "fn": c["fn"],
        }
    return rows


def _micro(totals: dict[str, dict[str, int]]) -> dict[str, Any]:
    tp = sum(c["tp"] for c in totals.values())
    fp = sum(c["fp"] for c in totals.values())
    fn = sum(c["fn"] for c in totals.values())
    p = _safe_div(tp, tp + fp)
    r = _safe_div(tp, tp + fn)
    return {
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(_f1(p, r), 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "support": tp + fn,
        "predicted": tp + fp,
    }


def _macro(per_category: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not per_category:
        return {"precision": None, "recall": None, "f1": None, "n": 0}
    ps = [row["precision"] for row in per_category.values()]
    rs = [row["recall"] for row in per_category.values()]
    fs = [row["f1"] for row in per_category.values()]
    return {
        "precision": round(statistics.fmean(ps), 4),
        "recall": round(statistics.fmean(rs), 4),
        "f1": round(statistics.fmean(fs), 4),
        "n": len(per_category),
    }


# ---------------------------------------------------------------------------
# Per-provider run discovery
# ---------------------------------------------------------------------------

def _discover_provider_runs(runs_dir: Path) -> dict[str, Path]:
    """Return ``{provider_name: latest_run_dir}`` for runs under ``runs_dir``.

    A run dir is identified by the prefix ``<provider>-<UTC-timestamp>``;
    the latest timestamp wins for each provider. We sort by the
    timestamp suffix lexicographically (it is ISO 8601 basic format
    YYYYMMDDTHHMMSSZ, so lexicographic == chronological).
    """
    found: dict[str, Path] = {}
    if not runs_dir.is_dir():
        return found
    for child in sorted(runs_dir.iterdir()):
        if not child.is_dir():
            continue
        # Match ``<provider>-<timestamp>`` (provider is one of the four
        # canonical names; timestamp is at least YYYYMMDDTHHMMSSZ).
        name = child.name
        matched = None
        for provider in EXPECTED_PROVIDERS:
            prefix = f"{provider}-"
            if name.startswith(prefix):
                ts = name[len(prefix):]
                # Cheap validation: length and the Z terminator.
                if len(ts) >= 16 and ts.endswith("Z") and "T" in ts:
                    matched = (provider, ts)
                    break
        if matched is None:
            continue
        provider, ts = matched
        existing = found.get(provider)
        if existing is None or existing.name < name:
            found[provider] = child
    return found


# ---------------------------------------------------------------------------
# Scoring a single provider's run
# ---------------------------------------------------------------------------

def _score_provider_run(
    run_dir: Path,
    manifest: list[dict],
) -> dict[str, Any]:
    """Score one provider's predictions.jsonl against the manifest."""
    predictions_path = run_dir / "predictions.jsonl"
    meta_path = run_dir / "predictions.meta.json"
    if not predictions_path.is_file():
        raise FileNotFoundError(f"predictions.jsonl missing in {run_dir}")
    if not meta_path.is_file():
        raise FileNotFoundError(f"predictions.meta.json missing in {run_dir}")

    predictions: list[dict] = []
    with predictions_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            predictions.append(json.loads(line))
    meta = json.loads(meta_path.read_text())

    pred_by_id = {r["encounter_id"]: r for r in predictions}
    gold_by_id = {e["encounter_id"]: e for e in manifest}

    n_predicted = len(predictions)
    n_ok = sum(1 for r in predictions if r.get("ok", False))
    n_err = n_predicted - n_ok
    valid_output_rate = _safe_div(n_ok, n_predicted)

    per_encounter_counts: list[dict[str, dict[str, int]]] = []
    for eid, gold_rec in gold_by_id.items():
        gold_cats = list(gold_rec.get("gold_categories", []) or [])
        pred_rec = pred_by_id.get(eid)
        if pred_rec is None:
            pred_cats: list[str] = []
        else:
            pred_cats = list(pred_rec.get("predicted_categories", []) or [])
        per_encounter_counts.append(_score_one(pred_cats, gold_cats))

    totals = _accumulate(per_encounter_counts)
    per_category = _per_category(totals)
    micro = _micro(totals)
    macro = _macro(per_category)

    return {
        "run_dir": str(run_dir.relative_to(PROJECT_ROOT)),
        "provider": meta.get("provider", run_dir.name.split("-")[0]),
        "model": meta.get("model", "<unknown>"),
        "mode": meta.get("mode", "unknown"),
        "n_predicted": n_predicted,
        "n_ok": n_ok,
        "n_errors": n_err,
        "valid_output_rate": round(valid_output_rate, 4),
        "error_type_tally": meta.get("error_type_tally", {}),
        "wall_clock_seconds_total": meta.get("wall_clock_seconds_total"),
        "wall_clock_seconds_avg": meta.get("wall_clock_seconds_avg"),
        "token_usage_total": meta.get("token_usage_total", {}),
        "micro": micro,
        "macro": macro,
        "per_category": per_category,
        "ran_at": meta.get("ran_at"),
        "prompt_sha256": meta.get("prompt_sha256"),
        "test_sample_sha256": meta.get("test_sample_sha256"),
    }


# ---------------------------------------------------------------------------
# Spread + verdict
# ---------------------------------------------------------------------------

def _spread(metric: dict[str, float]) -> dict[str, float]:
    """Return ``{max, min, mean, spread}`` for a dict of provider->metric.

    ``spread`` is ``(max - min) / mean``. Mean is None-safe: if every
    provider reports 0.0, spread is 0.0 (no variation, trivially
    within tolerance).
    """
    if not metric:
        return {"max": None, "min": None, "mean": None, "spread": None}
    vals = list(metric.values())
    mx = max(vals)
    mn = min(vals)
    mean = statistics.fmean(vals)
    spread = (mx - mn) / mean if mean != 0 else 0.0
    return {
        "max": mx,
        "min": mn,
        "mean": mean,
        "spread": round(spread, 4),
    }


def _verdict(provider_reports: list[dict]) -> dict:
    """Compute the PASS/FAIL verdict per the task body acceptance criteria.

    Criteria:
      1. All 4 providers present.
      2. All 4 produced 100% valid output (n_errors == 0).
      3. All aggregate metrics (micro-P, micro-R, micro-F1, macro-F1) are
         within 5% of each other across providers: (max - min) / mean
         <= 0.05 per metric.
    """
    providers_present = {r["provider"] for r in provider_reports}
    missing = [p for p in EXPECTED_PROVIDERS if p not in providers_present]

    valid_output_failures: list[dict] = []
    for r in provider_reports:
        if r["valid_output_rate"] < 1.0:
            valid_output_failures.append(
                {
                    "provider": r["provider"],
                    "valid_output_rate": r["valid_output_rate"],
                    "n_errors": r["n_errors"],
                    "error_type_tally": r["error_type_tally"],
                }
            )

    # Spread per aggregate metric, across providers.
    micro_p = {r["provider"]: r["micro"]["precision"] for r in provider_reports}
    micro_r = {r["provider"]: r["micro"]["recall"] for r in provider_reports}
    micro_f1 = {r["provider"]: r["micro"]["f1"] for r in provider_reports}
    macro_f1 = {r["provider"]: (r["macro"]["f1"] or 0.0) for r in provider_reports}

    spread = {
        "micro_precision": _spread(micro_p),
        "micro_recall": _spread(micro_r),
        "micro_f1": _spread(micro_f1),
        "macro_f1": _spread(macro_f1),
    }
    spread_failures: list[dict] = []
    for metric_name, stats in spread.items():
        if stats["spread"] is not None and stats["spread"] > SPREAD_TOLERANCE:
            spread_failures.append(
                {
                    "metric": metric_name,
                    "spread": stats["spread"],
                    "tolerance": SPREAD_TOLERANCE,
                    "per_provider": {k: round(v, 4) for k, v in {
                        "micro_precision": micro_p,
                        "micro_recall": micro_r,
                        "micro_f1": micro_f1,
                        "macro_f1": macro_f1,
                    }[metric_name].items()},
                }
            )

    passed = (
        not missing
        and not valid_output_failures
        and not spread_failures
    )

    return {
        "verdict": "PASS" if passed else "FAIL",
        "criteria": {
            "all_four_providers_present": not missing,
            "missing_providers": missing,
            "all_100_percent_valid_output": not valid_output_failures,
            "valid_output_failures": valid_output_failures,
            "all_metrics_within_5pct_spread": not spread_failures,
            "spread_failures": spread_failures,
            "spread_tolerance": SPREAD_TOLERANCE,
            "spread": spread,
        },
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _fmt(v: Any) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def _render_markdown(
    provider_reports: list[dict],
    verdict: dict,
    manifest: dict,
    runs_dir: Path,
) -> str:
    lines: list[str] = []
    lines.append("# MVP acceptance — cross-provider comparison")
    lines.append("")
    lines.append(
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )
    lines.append(f"Source runs dir: `{runs_dir.relative_to(PROJECT_ROOT)}`")
    lines.append(f"Gold manifest: `data/test_sample_manifest.json` "
                 f"({manifest['size']} encounters, "
                 f"{len(manifest.get('category_distribution', {}))} categories)")
    lines.append("")

    # Headline verdict
    lines.append("## Verdict")
    lines.append("")
    verdict_str = verdict["verdict"]
    crit = verdict["criteria"]
    lines.append(f"**{verdict_str}**")
    lines.append("")
    lines.append(
        f"- All four providers present: "
        f"{'yes' if crit['all_four_providers_present'] else 'no — missing: ' + ', '.join(crit['missing_providers'])}"
    )
    lines.append(
        f"- All providers 100% valid output: "
        f"{'yes' if crit['all_100_percent_valid_output'] else 'no — see failures'}"
    )
    lines.append(
        f"- All metrics within {SPREAD_TOLERANCE*100:.0f}% spread: "
        f"{'yes' if crit['all_metrics_within_5pct_spread'] else 'no — see failures'}"
    )
    lines.append("")

    # Side-by-side table
    lines.append("## Cross-provider headline table")
    lines.append("")
    lines.append(
        "| provider | model | mode | n | n_ok | n_err | valid% | micro_P | micro_R | micro_F1 | macro_F1 | wall_s | tokens |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in provider_reports:
        tokens = r["token_usage_total"].get("total_tokens") or 0
        lines.append(
            f"| {r['provider']} | `{r['model']}` | {r['mode']} | "
            f"{r['n_predicted']} | {r['n_ok']} | {r['n_errors']} | "
            f"{r['valid_output_rate']*100:.2f}% | "
            f"{_fmt(r['micro']['precision'])} | {_fmt(r['micro']['recall'])} | "
            f"{_fmt(r['micro']['f1'])} | {_fmt(r['macro']['f1'])} | "
            f"{_fmt(r['wall_clock_seconds_total'])} | {tokens} |"
        )
    lines.append("")

    # Spread table
    lines.append("## Spread across providers")
    lines.append("")
    lines.append("Tolerance: `(max - min) / mean <= %.2f`" % SPREAD_TOLERANCE)
    lines.append("")
    lines.append("| metric | max | min | mean | spread | within_tol |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for metric_name, stats in crit["spread"].items():
        within = "yes" if stats["spread"] is not None and stats["spread"] <= SPREAD_TOLERANCE else "no"
        lines.append(
            f"| {metric_name} | {_fmt(stats['max'])} | {_fmt(stats['min'])} | "
            f"{_fmt(stats['mean'])} | {_fmt(stats['spread'])} | {within} |"
        )
    lines.append("")

    # Per-provider per-category
    lines.append("## Per-provider per-category F1")
    lines.append("")
    # Union of all categories across all reports
    all_cats: list[str] = sorted(
        {cat for r in provider_reports for cat in r["per_category"].keys()}
    )
    header = "| category | " + " | ".join(r["provider"] for r in provider_reports) + " | spread |"
    sep = "| --- | " + " | ".join("---" for _ in provider_reports) + " | --- |"
    lines.append(header)
    lines.append(sep)
    for cat in all_cats:
        cells = []
        per_provider_f1 = []
        for r in provider_reports:
            f1 = r["per_category"].get(cat, {}).get("f1")
            per_provider_f1.append(f1 or 0.0)
            cells.append(_fmt(f1))
        if len(per_provider_f1) >= 2:
            mx = max(per_provider_f1)
            mn = min(per_provider_f1)
            mean = statistics.fmean(per_provider_f1) or 0.0
            spread = (mx - mn) / mean if mean != 0 else 0.0
            spread_str = f"{spread:.4f}"
        else:
            spread_str = "N/A"
        lines.append(f"| {cat} | " + " | ".join(cells) + f" | {spread_str} |")
    lines.append("")

    # Failure details
    if crit["valid_output_failures"]:
        lines.append("## Valid-output failures")
        lines.append("")
        for f in crit["valid_output_failures"]:
            lines.append(
                f"- **{f['provider']}**: valid_output_rate={f['valid_output_rate']*100:.2f}%, "
                f"n_errors={f['n_errors']}, error_tally={f['error_type_tally']}"
            )
        lines.append("")

    if crit["spread_failures"]:
        lines.append("## Spread failures")
        lines.append("")
        for f in crit["spread_failures"]:
            lines.append(
                f"- **{f['metric']}**: spread={f['spread']} > tolerance {f['tolerance']} — "
                f"per-provider values: {f['per_provider']}"
            )
        lines.append("")

    # Per-provider run details
    lines.append("## Per-provider run details")
    lines.append("")
    for r in provider_reports:
        lines.append(f"### {r['provider']}")
        lines.append("")
        lines.append(f"- run dir: `{r['run_dir']}`")
        lines.append(f"- model: `{r['model']}`")
        lines.append(f"- mode: {r['mode']}")
        lines.append(f"- ran_at: {r['ran_at']}")
        lines.append(f"- prompt_sha256: {r['prompt_sha256']}")
        lines.append(f"- test_sample_sha256: {r['test_sample_sha256']}")
        if r["error_type_tally"]:
            lines.append(f"- error_tally: {r['error_type_tally']}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "Generated by `scripts/compare_acceptance.py`. The PASS verdict means "
        "all 4 providers produced 100% valid output and all aggregate metrics "
        "are within 5% of each other across providers. FAIL is broken out by "
        "the specific provider(s) and metric(s) that broke the contract."
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=DEFAULT_RUNS_DIR,
        help=f"Directory of per-provider run dirs (default: {DEFAULT_RUNS_DIR.relative_to(PROJECT_ROOT)})",
    )
    args = parser.parse_args()

    if not MANIFEST_PATH.is_file():
        print(
            f"ERROR: gold manifest not found at {MANIFEST_PATH}. "
            f"Run scripts/build_test_sample_manifest.py first.",
            file=sys.stderr,
        )
        return 1

    manifest_doc = json.loads(MANIFEST_PATH.read_text())
    manifest = manifest_doc["entries"]

    found = _discover_provider_runs(args.runs_dir)
    if not found:
        print(
            f"ERROR: no provider runs found under {args.runs_dir}. "
            f"Run scripts/run_cross_provider.py for each of "
            f"{', '.join(EXPECTED_PROVIDERS)} first.",
            file=sys.stderr,
        )
        return 1

    # Stable provider order in the report.
    provider_reports: list[dict] = []
    for provider in EXPECTED_PROVIDERS:
        run_dir = found.get(provider)
        if run_dir is None:
            print(
                f"WARNING: no run for provider {provider!r} under {args.runs_dir}; "
                f"verdict will mark it missing",
                file=sys.stderr,
            )
            continue
        try:
            report = _score_provider_run(run_dir, manifest)
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        provider_reports.append(report)

    verdict = _verdict(provider_reports)

    out_dir = args.runs_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    comparison_json = out_dir / "comparison.json"
    comparison_md = out_dir / "comparison.md"
    verdict_path = out_dir / "VERDICT.txt"

    comparison_doc = {
        "verdict": verdict,
        "providers": provider_reports,
        "manifest_size": len(manifest),
        "manifest_sha256_train": manifest_doc.get("train_json_sha256"),
        "manifest_sha256_val": manifest_doc.get("val_json_sha256"),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    comparison_json.write_text(json.dumps(comparison_doc, indent=2) + "\n")
    comparison_md.write_text(
        _render_markdown(provider_reports, verdict, manifest_doc, args.runs_dir)
    )
    verdict_path.write_text(verdict["verdict"] + "\n")

    print(f"wrote {comparison_json}")
    print(f"wrote {comparison_md}")
    print(f"wrote {verdict_path}")
    print(f"\nVERDICT: {verdict['verdict']}")
    return 0 if verdict["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
