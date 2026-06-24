"""Per-clinic rule adjustment based on biller dismissal patterns.

When a biller repeatedly dismisses the same rule for the same encounter
pattern at the same clinic, that is a signal: the model is overcalling
that rule for this clinic's specific pattern. This module groups feedback
log entries into (clinic, rule, pattern) buckets, computes a dismissal
rate, and returns a weight multiplier (< 1.0) for any bucket that
crosses a configured threshold.

The output is a ``clinic_pattern_adjustment`` mapping suitable for the
auditor to consult before scoring findings:

    {
        "clinic_a": {
            "rule_ahcip_em_level_upcode": 0.5,
            "rule_ahcip_modifier_25": 0.7,
        },
        "clinic_b": {},  # not enough data
    }

A weight of 1.0 means "no adjustment". A weight < 1.0 means "down-weight
or suppress". The auditor can choose its own mapping (e.g. drop findings
whose weight is below a hard floor).

Configuration
-------------
Two parameters control the thresholding. They are passed as a
``PatternAdjustmentConfig`` so tests can pin them and production can
tune them via env vars / CLI args.

* ``min_occurrences`` (default 5): the bucket must have at least this
  many total feedback entries (any action) before any adjustment is
  emitted. Below this we have no signal.
* ``min_dismissal_rate`` (default 0.6): of those occurrences, at least
  this fraction must be ``dismiss`` actions to trigger an adjustment.
  The rationale: a 50% dismissal rate is "controversial"; we adjust
  only when the biller is clearly rejecting the rule.

The weight itself is a linear ramp: at the threshold it equals
``min_weight`` (default 0.5); at 100% dismissal rate it equals 0.0.
Formula: ``weight = max(min_weight, 1.0 - dismissal_rate)``.

Note on data
------------
The ``FeedbackEntry`` schema in :mod:`ai_billing_audit.feedback` does
not currently carry a ``clinic_id`` field — biller is the proxy. This
module accepts a ``clinic_for_biller`` callback so callers that *do*
have a clinic mapping (the API, the dashboard) can inject it; default
falls back to ``biller_id`` so the module still works without one.

"Encounter pattern signature" today is ``(category, severity)`` — the
two FeedbackEntry fields that describe the finding shape. This is a
deliberate, conservative signature: the future direction (when
encounter-level features are exposed via the feedback log) is to swap
in a richer signature without changing the module's surface.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping

from .feedback import FeedbackEntry


@dataclass
class PatternAdjustmentConfig:
    """Threshold parameters for the per-clinic pattern adjustment.

    Defaults are conservative: a bucket must have at least 5 feedback
    entries AND at least 60% dismissals to be down-weighted. These
    numbers come from the original ``zorva-learning-loop`` task spec
    (see ``scripts/load_scope_kanbans.py``).

    Fields
    ------
    min_occurrences:
        Minimum total feedback entries (any action) in a bucket before
        any adjustment is emitted. Below this the signal is too thin.
    min_dismissal_rate:
        Minimum fraction of entries in a bucket that must be ``dismiss``
        for the bucket to qualify as "over-called".
    min_weight:
        Floor for the weight multiplier. 0.0 = full suppression,
        0.5 = at most 50% down-weight, 1.0 = no adjustment. Default 0.5
        keeps the rule alive in the auditor output but visibly de-prioritised.
    """

    min_occurrences: int = 5
    min_dismissal_rate: float = 0.6
    min_weight: float = 0.5

    def __post_init__(self) -> None:
        if self.min_occurrences < 1:
            raise ValueError(
                f"min_occurrences must be >= 1, got {self.min_occurrences}"
            )
        if not 0.0 <= self.min_dismissal_rate <= 1.0:
            raise ValueError(
                f"min_dismissal_rate must be in [0, 1], got {self.min_dismissal_rate}"
            )
        if not 0.0 <= self.min_weight <= 1.0:
            raise ValueError(
                f"min_weight must be in [0, 1], got {self.min_weight}"
            )


@dataclass
class _BucketStats:
    total: int = 0
    dismiss: int = 0

    @property
    def dismissal_rate(self) -> float:
        return (self.dismiss / self.total) if self.total else 0.0


@dataclass
class PatternAdjustmentReport:
    """Output of :func:`compute_clinic_pattern_adjustments`.

    Fields
    ------
    weights:
        ``{clinic_id: {rule_id: weight_multiplier}}`` — weight 1.0 means
        "no change", weight < 1.0 means "down-weight". Empty dict for a
        clinic means the clinic had no qualifying over-call patterns.
    adjusted:
        ``[(clinic_id, rule_id, signature, dismissal_rate, weight)]`` —
        a flat list of every bucket that crossed the threshold, useful
        for logging and dashboards.
    """

    weights: dict[str, dict[str, float]] = field(default_factory=dict)
    adjusted: list[tuple[str, str, tuple[str, str], float, float]] = field(
        default_factory=list
    )


def _bucket_key(entry: FeedbackEntry, clinic_for_biller: Callable[[str], str]) -> tuple[str, str, tuple[str, str]]:
    """Reduce a feedback entry to a (clinic, rule, signature) tuple.

    The signature is ``(category, severity)`` today. When richer
    encounter features are added to ``FeedbackEntry``, swap this out
    for a hashable composite (e.g. ``(category, severity, line_item_set)``).
    """
    clinic = clinic_for_biller(entry.biller_id)
    signature = (entry.category or "", entry.severity or "")
    return (clinic, entry.rule_id or "", signature)


def _compute_weight(dismissal_rate: float, cfg: PatternAdjustmentConfig) -> float:
    """Linear ramp from 1.0 (no dismissals) to ``min_weight`` (at the threshold).

    Above the threshold (i.e. dismissal_rate >= min_dismissal_rate) the
    weight is allowed to drop linearly toward 0.0 as the rate approaches
    1.0, but it is floored at ``min_weight`` so the rule never fully
    disappears — the auditor may still want to surface it for human
    review.
    """
    if dismissal_rate <= 0.0:
        return 1.0
    if dismissal_rate < cfg.min_dismissal_rate:
        return 1.0
    # Above the threshold: weight drops linearly from min_weight (at the
    # threshold) toward 0.0 (at 100% dismissal rate).
    span = 1.0 - cfg.min_dismissal_rate
    if span <= 0.0:
        return cfg.min_weight
    fraction_above_threshold = (dismissal_rate - cfg.min_dismissal_rate) / span
    weight = cfg.min_weight * (1.0 - fraction_above_threshold)
    return max(0.0, min(1.0, weight))


def compute_clinic_pattern_adjustments(
    entries: Iterable[FeedbackEntry],
    *,
    config: PatternAdjustmentConfig | None = None,
    clinic_for_biller: Callable[[str], str] | None = None,
) -> PatternAdjustmentReport:
    """Group feedback entries and return per-clinic per-rule weights.

    Parameters
    ----------
    entries:
        Feedback log entries (typically from ``FeedbackStore.read_all()``).
    config:
        Threshold parameters. Defaults to :class:`PatternAdjustmentConfig`
        with conservative numbers (5 occurrences, 60% dismissal rate).
    clinic_for_biller:
        Optional mapping from ``biller_id`` to ``clinic_id``. When
        omitted, the module falls back to using ``biller_id`` as the
        clinic key (which is the only fully-correct behaviour until
        ``FeedbackEntry`` gains a ``clinic_id`` field).

    Returns
    -------
    :class:`PatternAdjustmentReport`
    """
    cfg = config or PatternAdjustmentConfig()
    clinic_lookup: Callable[[str], str] = clinic_for_biller or (lambda b: b)

    buckets: dict[tuple[str, str, tuple[str, str]], _BucketStats] = defaultdict(_BucketStats)
    for entry in entries:
        key = _bucket_key(entry, clinic_lookup)
        buckets[key].total += 1
        if entry.action == "dismiss":
            buckets[key].dismiss += 1

    report = PatternAdjustmentReport()
    for (clinic, rule, signature), stats in buckets.items():
        if stats.total < cfg.min_occurrences:
            continue
        if stats.dismissal_rate < cfg.min_dismissal_rate:
            continue
        weight = _compute_weight(stats.dismissal_rate, cfg)
        report.weights.setdefault(clinic, {})[rule] = weight
        report.adjusted.append(
            (clinic, rule, signature, stats.dismissal_rate, weight)
        )
    return report


def apply_weights(
    findings: Iterable[Mapping[str, object]],
    weights: Mapping[str, float],
    *,
    min_weight_to_emit: float = 0.0,
) -> list[dict[str, object]]:
    """Apply per-rule weights to a list of findings, optionally suppressing.

    Parameters
    ----------
    findings:
        Iterable of finding dicts. Each must have a ``rule_id`` field.
    weights:
        Per-rule weight map (as emitted by
        :func:`compute_clinic_pattern_adjustments` for one clinic).
    min_weight_to_emit:
        Findings whose effective weight falls below this floor are
        dropped. Default 0.0 keeps all findings (with their weight
        attached); a value of 0.5 (matching ``min_weight``) drops
        findings the clinic has effectively rejected.

    Returns
    -------
    A new list of finding dicts. Each emitted finding gains a
    ``pattern_weight`` field (in [0, 1]). Dropped findings are not
    returned; the caller cannot distinguish "dropped by weight" from
    "dropped by other rules" without re-checking the weight map.
    """
    out: list[dict[str, object]] = []
    for f in findings:
        rule_id = str(f.get("rule_id", ""))
        weight = float(weights.get(rule_id, 1.0))
        if weight < min_weight_to_emit:
            continue
        new_f = dict(f)
        new_f["pattern_weight"] = weight
        out.append(new_f)
    return out
