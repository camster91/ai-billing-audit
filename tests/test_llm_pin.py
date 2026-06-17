"""Tests for the pinned default model in ``ai_billing_audit.llm``.

These tests enforce the acceptance criteria for t_35eae361:
* The pinned model id is a specific, non-empty, non-``"latest"`` string.
* ``default_model()`` falls back to the pinned id when ``LLM_MODEL``
  is unset.
* The pinned id is exported on the public ``llm`` module surface so
  downstream code can introspect it without re-defining a constant.
* Setting an explicit ``LLM_MODEL`` overrides the pin (so a deployment
  can opt out without editing the source).
"""

from __future__ import annotations

import importlib
import os


def _reload_llm(monkeypatch=None) -> None:
    """Reload the ``llm`` module so env-var reads happen at test time."""
    import ai_billing_audit.llm as llm_mod

    importlib.reload(llm_mod)


def test_pinned_default_model_is_exported() -> None:
    from ai_billing_audit.llm import PINNED_DEFAULT_MODEL

    assert isinstance(PINNED_DEFAULT_MODEL, str)
    assert PINNED_DEFAULT_MODEL, "PINNED_DEFAULT_MODEL must be a non-empty string"
    # Acceptance criterion (1): the pin must never be the literal "latest".
    # "latest" silently swaps models and is exactly the failure mode the
    # pin exists to prevent.
    assert PINNED_DEFAULT_MODEL.strip().lower() != "latest"
    # No bare "MiniMax-M3" or "minimax-m3" string either — those are
    # version-floating aliases that defeat deterministic builds.
    assert "MiniMax-m3" not in PINNED_DEFAULT_MODEL
    assert "minimax-m3" not in PINNED_DEFAULT_MODEL


def test_default_model_falls_back_to_pin(monkeypatch) -> None:
    monkeypatch.delenv("LLM_MODEL", raising=False)
    _reload_llm()

    from ai_billing_audit import llm

    assert llm.default_model() == llm.PINNED_DEFAULT_MODEL


def test_explicit_llm_model_env_overrides_pin(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-3-5-sonnet-20241022")
    _reload_llm()

    from ai_billing_audit import llm

    assert llm.default_model() == "anthropic/claude-3-5-sonnet-20241022"


def test_resolve_model_uses_pin_when_nothing_set(monkeypatch) -> None:
    monkeypatch.delenv("LLM_MODEL", raising=False)
    _reload_llm()

    from ai_billing_audit.llm import LLMClient

    client = LLMClient()
    # No explicit override, no LLM_MODEL, no kwargs["model"] → pin wins.
    assert client._resolve_model({}) == client._resolve_model.__globals__["PINNED_DEFAULT_MODEL"]


def test_pinned_id_is_the_only_default_in_source() -> None:
    """No duplicate hard-coded model id may live in llm.py.

    Acceptance criterion (2): the pinned id must appear in exactly the
    documented location (``PINNED_DEFAULT_MODEL``) — no other module
    constant or string literal may re-declare it.
    """
    from pathlib import Path

    llm_src = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ai_billing_audit"
        / "llm.py"
    ).read_text(encoding="utf-8")

    from ai_billing_audit.llm import PINNED_DEFAULT_MODEL

    occurrences = llm_src.count(PINNED_DEFAULT_MODEL)
    # Exactly one: the assignment ``PINNED_DEFAULT_MODEL = "<id>"``.
    # The constant name (identifier) is referenced many times — the
    # assertion is about the string LITERAL appearing only in the
    # declaration. Any second occurrence of the literal means someone
    # re-declared the id instead of importing the constant.
    assert occurrences == 1, (
        f"PINNED_DEFAULT_MODEL literal appears {occurrences} times in llm.py; "
        "expected exactly 1 (the declaration). Re-declaring the id defeats "
        "the pin — import the constant instead."
    )


def test_no_latest_alias_in_llm_source() -> None:
    """The literal string ``"latest"`` must not appear in llm.py.

    Acceptance criterion (1): grep for ``"latest"`` in model-id
    positions returns no production matches.
    """
    from pathlib import Path

    llm_src = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ai_billing_audit"
        / "llm.py"
    ).read_text(encoding="utf-8")

    # Strip docstrings + comments so the assertion is about code, not
    # prose. A docstring explaining why we don't use "latest" is fine.
    lines = [ln for ln in llm_src.splitlines() if not ln.lstrip().startswith("#")]
    code_only = "\n".join(lines)

    # Count "latest" only when it appears as a quoted string literal.
    # Docstrings (triple-quoted) are excluded by the comment-strip above
    # only if they live on a line that started with a comment, which is
    # not how docstrings are written; instead, look for it as a token
    # inside double-quoted strings.
    import re

    matches = re.findall(r"""['\"]\s*latest\s*['\"]""", code_only)
    assert not matches, (
        f"Found 'latest' as a string literal in llm.py: {matches}. "
        "The pinned default model must never be 'latest'."
    )
