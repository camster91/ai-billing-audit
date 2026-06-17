"""Synth package — pure template + RNG encounter generation.

This package splits the original monolithic ``synth_agent.py`` into:

- ``template`` — ``Scenario`` and ``Template`` frozen dataclasses.
- ``content_table`` — the bundled 9-scenario content table.
- ``render`` — pure per-tier render functions (no I/O, no LLM).

The public shim at ``ai_billing_audit.synth_agent`` re-exports the
public API (``generate``, ``generate_suite``, ``generate_encounter``,
``tier_variants``, ``TIERS``, ``VARIANTS``, ``Scenario``, ``Template``,
``ContentTable``, ``DEFAULT_CONTENT``) so legacy imports keep working.

The package must stay pure: it imports only stdlib + intra-package.
``tests/test_synth_purity.py`` enforces that.
"""

from __future__ import annotations

from .content_table import DEFAULT_CONTENT
from .render import _build_easy, _build_hard, _build_medium, _enc_id, _rng_for
from .template import ContentTable, Scenario, Template, TemplateSequence

__all__ = [
    "ContentTable",
    "DEFAULT_CONTENT",
    "Scenario",
    "Template",
    "TemplateSequence",
]
