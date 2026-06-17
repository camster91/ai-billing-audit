"""End-to-end reproduction entry point.

This is the single command the README's "Reproducing results" section
points at. It delegates to ``scripts/optimize.py`` (the DSPy MIPROv2
loop) so there is one canonical invocation surface — no separate flags,
no separate env-var contract.

Two run modes, selected entirely by env vars (no CLI flags):

  * **Hermetic / smoke** (no network, no API key) — ``LLM_PROVIDER`` is
    unset or set to ``smoke``. The dev loop uses DSPy's deterministic
    in-process ``DummyLM``. This is the mode the README recipe shows
    first because it is the only one a fresh contributor can run
    end-to-end without external credentials.

  * **Live** (hits a real LLM) — ``LLM_PROVIDER`` is one of
    ``minimax`` (default), ``claude``, ``openai``, ``gemini``, plus
    the matching ``*_API_KEY`` env var. See the README for the full
    matrix.

Run the hermetic recipe::

    python run.py

Run on a real backend::

    LLM_PROVIDER=minimax MINIMAX_API_KEY=sk-... python run.py

Exit code is propagated from ``scripts/optimize.py`` — non-zero means
the optimization loop did not complete (network error, bad API key,
non-deterministic finding, etc.). The artifact path is printed on
stdout at the end of the run.

Why a shim, not a symlink or a direct call site? Two reasons:

  1. The user-facing surface (``python run.py``) is stable; the
     internals of ``scripts/optimize.py`` can move without breaking
     contributors who followed the README.
  2. The shim gives us a single, greppable point to add future
     pre-run hooks (determinism guard, environment check) without
     editing the optimization loop.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

# Resolve scripts/ relative to this file so the shim works no matter
# what the caller's CWD is — a fresh clone that runs ``python run.py``
# from a parent directory must still hit the right script.
SCRIPTS_DIR = Path(__file__).resolve().parent / "scripts"
OPTIMIZE_SCRIPT = SCRIPTS_DIR / "optimize.py"


def main() -> None:
    if not OPTIMIZE_SCRIPT.is_file():
        sys.stderr.write(
            f"run.py: cannot find {OPTIMIZE_SCRIPT}. "
            f"Are you running from inside the ai-billing-audit checkout?\n"
        )
        sys.exit(2)

    # Forward argv to the underlying script so flags like --help (if
    # added later) reach it. Drop argv[0] (this shim's path) and let
    # the script see its own argv[0] for clean tracebacks.
    sys.argv = [str(OPTIMIZE_SCRIPT)] + sys.argv[1:]

    # Make scripts/ importable so optimize.py can `from <sibling>`
    # (it doesn't today, but the seam is here when it does).
    sys.path.insert(0, str(SCRIPTS_DIR))

    # Hand off. runpy.run_path executes the script in this process so
    # any env vars or sys.path tweaks the script makes are visible to
    # the rest of the run.
    try:
        runpy.run_path(str(OPTIMIZE_SCRIPT), run_name="__main__")
    except SystemExit as exc:
        # Propagate the script's exit code (0 = success, 1 = loop
        # error, 2 = arg error, etc.) verbatim.
        raise SystemExit(exc.code) from None


if __name__ == "__main__":
    main()
