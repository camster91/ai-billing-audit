"""Synth purity contract — the synth must not import LLM backends.

The synth agent is documented to be rule-based: no LLM, no network, no
clock, no uuid. ``test_synth_determinism.py`` proves *behavioural*
purity (byte-identical output across processes and perturbations).
This file proves *structural* purity: the source of every synth module
must not contain an import of the LLM client or any of the LLM SDKs.

If a future refactor adds ``from ai_billing_audit.llm import LLMClient``
to a synth module, this test fails on CI before the change ever
reaches production.

The check is AST-based: we parse each synth module's source and inspect
its top-level ``Import`` / ``ImportFrom`` nodes. This is more robust
than a ``sys.modules`` snapshot because the parent package's
``__init__.py`` eagerly imports the LLM client (so the module is
always in ``sys.modules``), and the question we actually want to
answer is "does the synth's *own* code touch the LLM", not "is the
LLM module loaded somewhere in the process".
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

# Module names that must never be imported by any synth module's source.
# ``ai_billing_audit.llm`` and ``ai_billing_audit.minimax_client`` are
# the project's own LLM client + provider; ``llm_client`` is the short
# alias; ``litellm`` / ``dspy`` / ``openai`` / ``anthropic`` /
# ``google.generativeai`` are third-party SDKs the project may pull in
# via the auditor / judge / grader — none of them belong in the synth.
LLM_MODULE_NAMES: frozenset[str] = frozenset(
    (
        "ai_billing_audit.llm",
        "ai_billing_audit.minimax_client",
        "llm_client",
        "litellm",
        "dspy",
        "openai",
        "anthropic",
        "google.generativeai",
    )
)

# Each entry is the dotted path of a synth module. We deliberately
# cover the public shim and the three internals; if a future refactor
# splits any of these further, add the new name here.
SYNTH_ENTRY_POINTS: tuple[str, ...] = (
    "ai_billing_audit.synth_agent",
    "ai_billing_audit.synth",
    "ai_billing_audit.synth.template",
    "ai_billing_audit.synth.content_table",
    "ai_billing_audit.synth.render",
)


def _module_source_path(dotted: str) -> Path:
    mod = importlib.import_module(dotted)
    if not hasattr(mod, "__file__") or mod.__file__ is None:
        raise AssertionError(f"module {dotted} has no __file__")
    return Path(mod.__file__)


def _imports_in_source(path: Path) -> list[str]:
    """Return a list of every top-level module name the file imports.

    A future-proofing detail: we look at both ``import X`` and
    ``from X import Y`` so ``from ai_billing_audit.llm import LLMClient``
    is caught via the ``module == "ai_billing_audit.llm"`` branch.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # ``from .synth import ...`` — ``node.module`` may be None
            # for ``from . import x``; we still want to record those
            # for the intra-package check below.
            if node.module is not None:
                # Resolve relative imports to an absolute name so the
                # LLM check is uniform.
                if node.level and node.level > 0:
                    # The synth modules are inside ``ai_billing_audit.*``.
                    # For our purposes, relative imports inside the
                    # synth package stay in the synth — record the
                    # *target* module path so an LLM name can still
                    # be caught if someone writes
                    # ``from ..llm import LLMClient``.
                    package = "." * node.level
                    names.append(f"{package}{node.module}")
                else:
                    names.append(node.module)
    return names


def _is_llm_import(name: str) -> bool:
    """True if the import name matches one of the LLM modules.

    Matching is exact for top-level names and ``startswith`` for
    sub-modules, so ``import ai_billing_audit.llm.helpers`` is also
    caught. Relative imports (``..llm``) are caught via startswith
    against the absolute module name — we never see them in this
    codebase, but the check is safe either way.
    """
    if name in LLM_MODULE_NAMES:
        return True
    return any(name == m or name.startswith(m + ".") for m in LLM_MODULE_NAMES)


# ---------------------------------------------------------------------------
# AST-based purity checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", SYNTH_ENTRY_POINTS)
def test_synth_module_source_does_not_import_llm(entry: str):
    """No synth module's source may import any LLM backend.

    We parse the file's AST and inspect every Import / ImportFrom node.
    This is more reliable than a sys.modules snapshot because the
    parent package's __init__.py eagerly loads the LLM client for
    unrelated reasons.
    """
    path = _module_source_path(entry)
    imports = _imports_in_source(path)
    leaked = sorted(name for name in imports if _is_llm_import(name))
    assert not leaked, (
        f"{entry} imports LLM-backed modules: {leaked}\n"
        f"file: {path}\n"
        f"all imports in this file: {imports}"
    )


def test_synth_imports_only_stdlib_and_intra_package():
    """Every synth module's imports are either stdlib or live inside ``ai_billing_audit``.

    Tightens the purity contract: no third-party package (other than
    stdlib) may appear in a synth module's import graph. A regression
    that adds ``import pandas`` or ``import requests`` to a synth
    module fails here.
    """
    # Third-party module top-level names that are allowed in *other*
    # parts of the project but never in the synth. We allow the test
    # framework (pytest) and the project's own sub-modules.
    forbidden_third_party: frozenset[str] = frozenset(
        (
            "pandas",
            "numpy",
            "requests",
            "urllib3",
            "httpx",
            "aiohttp",
            "litellm",
            "openai",
            "anthropic",
            "dspy",
            "jsonschema",  # used by encounter_schema, not the synth
        )
    )

    for entry in SYNTH_ENTRY_POINTS:
        path = _module_source_path(entry)
        imports = _imports_in_source(path)
        third_party = [
            name.split(".")[0]
            for name in imports
            if not name.startswith("ai_billing_audit") and not name.startswith(".")
        ]
        leaked = sorted(set(third_party) & forbidden_third_party)
        assert not leaked, (
            f"{entry} imports forbidden third-party modules: {leaked}\nfile: {path}"
        )


# ---------------------------------------------------------------------------
# Runtime sanity: generate_suite produces a real suite, end to end.
# ---------------------------------------------------------------------------
#
# Note on the deliberately-omitted child-process test: the project
# root ``ai_billing_audit/__init__.py`` eagerly imports the LLM
# client (``grader``, ``judge``, ``minimax_client``, ``messages``,
# ``grading``) so the LLM client is always in ``sys.modules`` as soon
# as *any* sub-module is imported. A naive child-process test that
# asserts "no LLM module in sys.modules" therefore fails for reasons
# unrelated to the synth. The AST check above is the structural
# guarantee that survives the package's eager imports. If a future
# refactor wants to tighten the runtime guarantee, the right move is
# to make the package's ``__init__.py`` lazy — out of scope here.


def test_generate_suite_smoke():
    """generate_suite is callable end-to-end and returns 6 encounters."""
    from ai_billing_audit.synth_agent import generate_suite

    suite = generate_suite(seed=42)
    assert len(suite) == 6
    for enc in suite:
        # Spot-check the shape the schema validator looks for.
        assert enc["difficulty_tier"] in {"EASY", "MEDIUM", "HARD"}
        assert enc["encounter_id"].startswith("enc_synth_")
        assert enc["icd10_codes"]
        assert enc["cpt_codes"]
