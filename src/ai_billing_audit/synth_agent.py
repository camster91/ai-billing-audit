"""Synthetic encounter generator — pure function of (template, seed).

The synth agent emits clinical-encounter fixtures that match the schema
in ``ai_billing_audit.encounter_schema``. It is intentionally rule-based
(no LLM, no network) so the optimizer loop, the grader, and any other
downstream consumer can rely on byte-identical output given the same
seed.

The implementation is split into the ``ai_billing_audit.synth`` package:

- ``synth.template`` — the ``Template`` and ``Scenario`` frozen dataclasses.
- ``synth.content_table`` — the bundled 9-scenario content table.
- ``synth.render`` — per-tier pure render functions.

This module is the thin public-API shim. It owns:

- the canonical ``TIERS`` / ``VARIANTS`` lists,
- the legacy ``generate_encounter(tier, variant, *, seed)`` entry point,
- the new ``generate(template, *, seed, content=...)`` entry point,
- the ``generate_suite`` and ``tier_variants`` helpers.

Two entry points, one underlying pipeline. The legacy
``generate_encounter`` is a one-line wrapper that builds a ``Template``
and delegates. Both produce the same byte-equal output given the same
seed.

Tier spec (unchanged from the pre-refactor version):

- EASY
    * single problem focus (1 ICD-10)
    * NO prescription drug management
    * NO modifier flags
    * clean + flagged (flag must be benign: demographic variance only)
- MEDIUM
    * dual problems (2 distinct ICD-10 codes)
    * prescription drug management present (this combination triggers
      MDM Moderate, per the E/M 2021 guidelines)
    * clean + flagged
- HARD
    * chronic + acute (2 ICD-10 with chronicity)
    * surgery with a global period present
    * clean variant: modifier -25 correctly applied to the E/M
    * flagged variant: modifier -25 missing or wrong

The generator threads one ``random.Random`` instance per call so two
calls with the same seed always produce identical output. The
determinism contract is enforced by ``tests/test_synth_determinism.py``;
the purity contract (no LLM / network / time imports) is enforced by
``tests/test_synth_purity.py``.
"""

from __future__ import annotations

from typing import Any

from .synth import (
    DEFAULT_CONTENT,
    ContentTable,
    Scenario,
    Template,
    TemplateSequence,
    _build_easy,
    _build_hard,
    _build_medium,
    _rng_for,
)

__all__ = [
    "CONTENT",
    "DEFAULT_CONTENT",
    "Scenario",
    "Template",
    "TIERS",
    "VARIANTS",
    "generate",
    "generate_encounter",
    "generate_suite",
    "tier_variants",
]


TIERS: tuple[str, ...] = ("EASY", "MEDIUM", "HARD")
VARIANTS: tuple[str, ...] = ("clean", "flagged")

# Convenience alias: ``CONTENT`` is the default content table; tests may
# import this and override locally.
CONTENT: ContentTable = DEFAULT_CONTENT


# ---------------------------------------------------------------------------
# Internal dispatch — picks the right builder for a template's tier.
# ---------------------------------------------------------------------------


_BUILDERS = {
    "EASY": _build_easy,
    "MEDIUM": _build_medium,
    "HARD": _build_hard,
}


def _validate_tier_variant(tier: str, variant: str) -> None:
    if tier not in TIERS:
        raise ValueError(f"tier must be one of {TIERS}, got {tier!r}")
    if variant not in VARIANTS:
        raise ValueError(f"variant must be one of {VARIANTS}, got {variant!r}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate(
    template: Template,
    *,
    seed: int,
    content: ContentTable | None = None,
) -> dict[str, Any]:
    """Generate one encounter from a ``Template`` and a seed.

    Pure function: given the same ``template``, ``seed``, and
    ``content`` table, the returned dict is byte-identical.

    Args:
        template: a ``Template(tier, variant, schema_version)``. The
            schema version is informational for now; only version 1
            exists.
        seed: any integer; output is deterministic given the same seed.
        content: optional content table. Defaults to the bundled
            ``DEFAULT_CONTENT``. Tests inject a smaller table to cover
            specific scenarios without copying the full set.

    Returns:
        A dict that validates against ``encounter_schema.ENCOUNTER_SCHEMA``.

    Raises:
        ValueError: if ``template.tier`` or ``template.variant`` is not
            one of the canonical values, or if ``content`` does not
            contain the requested (tier, variant) key.
    """
    _validate_tier_variant(template.tier, template.variant)
    table = content if content is not None else DEFAULT_CONTENT
    try:
        scenarios = table[(template.tier, template.variant)]
    except KeyError as exc:
        raise ValueError(
            f"content table has no entry for (tier={template.tier!r}, "
            f"variant={template.variant!r})"
        ) from exc
    rng = _rng_for(template.tier, template.variant, seed)
    scenario = rng.choice(scenarios)
    return _BUILDERS[template.tier](rng, scenario, template.variant)


def generate_encounter(
    tier: str, variant: str, *, seed: int
) -> dict[str, Any]:
    """Generate a single encounter. Thin wrapper around ``generate``.

    Kept for backwards compatibility with the pre-refactor API
    (``optimize.py`` and the stratified-sampler task both call this
    signature). The new ``generate(Template(...), *, seed)`` form is
    preferred for new code.

    Args:
        tier: one of ``"EASY"``, ``"MEDIUM"``, ``"HARD"``.
        variant: one of ``"clean"``, ``"flagged"``.
        seed: any integer; output is deterministic given the same seed.

    Returns:
        A dict that validates against ``encounter_schema.ENCOUNTER_SCHEMA``.
    """
    return generate(Template(tier=tier, variant=variant), seed=seed)


def tier_variants() -> list[tuple[str, str]]:
    """Canonical ordered list of (tier, variant) pairs the suite covers."""
    return [(tier, variant) for tier in TIERS for variant in VARIANTS]


def generate_suite(
    *,
    seed: int,
    content: ContentTable | None = None,
    templates: TemplateSequence | None = None,
) -> list[dict[str, Any]]:
    """Generate the canonical encounter suite.

    Default templates = 3 tiers × 2 variants (6 encounters). Pass
    ``templates`` to override the suite's shape; pass ``content`` to
    override the content table.

    The suite is deterministic given the seed: each (tier, variant)
    pair draws from its own seeded RNG so reordering the pairs would
    not change the encounter contents, but the encounter IDs embed
    the RNG draw so they remain unique per pair.

    Args:
        seed: master seed. Each (tier, variant) pair derives a per-pair
            RNG so all encounters are reproducible.
        content: optional content table override.
        templates: optional list of ``Template`` objects to render in
            order. Defaults to the canonical 3 × 2 grid.

    Returns:
        A list of encounter dicts, one per template, in the order
        given by ``templates`` (or the canonical order if omitted).
    """
    if templates is None:
        return [
            generate(Template(tier=tier, variant=variant), seed=seed, content=content)
            for tier, variant in tier_variants()
        ]
    return [generate(t, seed=seed, content=content) for t in templates]
