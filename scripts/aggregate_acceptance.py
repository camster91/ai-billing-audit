"""Top-level orchestrator for the MVP acceptance run.

For each of {minimax, claude, openai, gemini}, run
``scripts/run_cross_provider.py --provider <name>`` once, then run
``scripts/compare_acceptance.py`` to produce the side-by-side report
and PASS/FAIL verdict.

This is a thin shell — the real work lives in the two scripts it
delegates to. Splitting it this way lets an operator re-run a single
provider (after a transient API failure, for example) without
re-paying for the other three, and lets a CI pipeline drive just the
compare step against an already-populated runs/ directory.

Real-mode prerequisites
-----------------------
The four env vars below must be set in the shell that invokes this
script. A missing key causes the per-provider run to fail with a
loud error from run_cross_provider.py.

    MINIMAX_API_KEY
    ANTHROPIC_API_KEY
    OPENAI_API_KEY
    GEMINI_API_KEY       (or GOOGLE_API_KEY as a fallback)

A hermetic dry-run is available via ``--dry-run``; it drives all
four providers through the deterministic stub and produces a 100%
valid baseline against which real-provider runs can be diffed. The
dry-run is the right starting point for a first-time setup or for
verifying the pipeline after a code change.

Usage
-----
    .venv/bin/python scripts/aggregate_acceptance.py            # real, 150 each
    .venv/bin/python scripts/aggregate_acceptance.py --dry-run  # hermetic
    .venv/bin/python scripts/aggregate_acceptance.py --n 10     # 10 each, real
    .venv/bin/python scripts/aggregate_acceptance.py --skip-run # compare only
    .venv/bin/python scripts/aggregate_acceptance.py --compare-only  # same
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_CROSS_PROVIDER = PROJECT_ROOT / "scripts" / "run_cross_provider.py"
COMPARE_ACCEPTANCE = PROJECT_ROOT / "scripts" / "compare_acceptance.py"
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"

PROVIDERS: tuple[str, ...] = ("minimax", "claude", "openai", "gemini")


def _run(cmd: list[str]) -> int:
    print(f"\n$ {' '.join(cmd)}\n", flush=True)
    rc = subprocess.call(cmd, cwd=PROJECT_ROOT)
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pass --dry-run to each run_cross_provider.py invocation (no API key, no network).",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=None,
        help="Cap encounters per provider (default: all 150). Useful for cost-controlled smoke runs.",
    )
    parser.add_argument(
        "--skip-run",
        "--compare-only",
        action="store_true",
        dest="compare_only",
        help="Skip the per-provider runs and just run compare_acceptance.py against the existing runs/ tree.",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable),
        help="Python interpreter to invoke. Defaults to .venv/bin/python.",
    )
    args = parser.parse_args()

    py = str(args.python)

    print("=== MVP acceptance aggregate run ===")
    print(f"Started: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"Python:  {py}")
    print(f"Mode:    {'dry-run' if args.dry_run else 'real'}")
    if args.n is not None:
        print(f"Cap:     {args.n} encounters per provider")
    print(f"Compare only: {args.compare_only}")

    if not args.compare_only:
        for provider in PROVIDERS:
            cmd = [py, str(RUN_CROSS_PROVIDER), "--provider", provider]
            if args.dry_run:
                cmd.append("--dry-run")
            if args.n is not None:
                cmd.extend(["--n", str(args.n)])
            rc = _run(cmd)
            if rc != 0:
                print(
                    f"\nERROR: run_cross_provider.py --provider {provider} "
                    f"exited with rc={rc}. Stopping the aggregate run before "
                    f"spending the rest of the budget on the other providers.",
                    file=sys.stderr,
                )
                return rc

    rc = _run([py, str(COMPARE_ACCEPTANCE)])
    print(f"\n=== aggregate_acceptance complete (final rc={rc}) ===")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
