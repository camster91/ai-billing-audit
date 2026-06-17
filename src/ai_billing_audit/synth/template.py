"""Synth template primitives.

The synth is a pure function of ``(template, seed)``. This module
defines the *data* side of that contract — the ``Template`` key that
selects which (tier, variant, schema_version) the caller wants, and the
``Scenario`` value type that the content table holds.

Both are ``@dataclass(frozen=True)``: they are pure data, hashable, and
immutable. The renderer (``synth.render``) consumes them.

No I/O, no randomness, no LLM call. Importing this module must not pull
the LLM client into ``sys.modules`` — that is the property the
``tests/test_synth_purity.py`` suite enforces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

__all__ = [
    "ContentTable",
    "Scenario",
    "Template",
]


# A ``ContentTable`` maps a (tier, variant) key to the ordered tuple of
# ``Scenario`` objects the synth may sample for that key. It is a
# ``Mapping`` (not a ``dict``) so tests can inject smaller or partial
# tables without copying the full bundled content.
ContentTable = Mapping[tuple[str, str], tuple["Scenario", ...]]


@dataclass(frozen=True)
class Scenario:
    """One concrete clinical scenario the synth can sample.

    Pure data: no I/O, no RNG state, no LLM, no network. The renderer
    reads the fields below and threads them into the encounter dict.

    The shape is tier-dependent: EASY uses ``icd10`` (a single code) and
    an optional ``benign_flag`` for the flagged variant; MEDIUM uses
    ``icd10`` as a list of two distinct codes; HARD uses
    ``icd10_chronic_a/b`` and ``icd10_acute`` plus ``cpt_em`` /
    ``cpt_surgery`` / ``global_period_days``. The dataclass carries the
    union and the renderer knows which fields to consult for which tier.
    Carrying the union keeps the content table flat and the
    ``@dataclass(frozen=True)`` invariant simple.
    """

    # EASY + MEDIUM share these.
    hpi: str
    exam: str
    mdm: str
    icd10: str | list[str]
    cpts: tuple[dict[str, Any], ...]
    benign_flag: str | None = None

    # HARD-only fields. ``None`` for non-HARD scenarios.
    icd10_chronic_a: str | None = None
    icd10_chronic_b: str | None = None
    icd10_acute: str | None = None
    cpt_em: str | None = None
    cpt_surgery: str | None = None
    global_period_days: int | None = None


@dataclass(frozen=True)
class Template:
    """A template = (tier, variant, schema_version). Pure data.

    ``schema_version`` is the version of ``encounter_schema`` the
    renderer should target. Today only version 1 exists; the field is
    additive so a future schema migration does not break the API.
    """

    tier: str  # "EASY" | "MEDIUM" | "HARD"
    variant: str  # "clean" | "flagged"
    schema_version: int = 1


# Type alias re-exported for callers that want to spell out the suite's
# input type. Keeping the alias here (rather than in the public shim)
# means downstream code that imports ``Template`` from
# ``ai_billing_audit.synth_agent`` still picks it up via the re-export.
TemplateSequence = Sequence[Template]
