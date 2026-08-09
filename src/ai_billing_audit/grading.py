"""Per-finding matching for grading predicted auditor findings against ground-truth findings.

The grading component scores the auditor (LLM) by comparing the structured
findings it produces for an encounter to the encounter's ground-truth
findings. A ``match`` is a one-to-one pairing between a predicted finding
and a ground-truth finding. Unpaired predictions and ground truths are
counted as False Positives and False Negatives respectively.

Matching rule (per the spec)
----------------------------

A predicted finding ``p`` matches a ground-truth finding ``g`` iff all
three of the following hold:

  1. ``p["category"] == g["category"]`` (exact string equality)
  2. ``p["suggested_code"] == g["suggested_code"]`` (exact string equality)
  3. The ``clinical_evidence_quote`` fields overlap with at least 80%
     Jaccard token overlap after lowercasing and stripping punctuation.

Substring direction: the spec allows either ``p.quote in g.quote`` or
``g.quote in p.quote`` and asks us to pick one and document it. We use
the **Jaccard overlap** as the primary contract (>= 80%). A pure
substring relationship (one direction) implies a Jaccard overlap of 1.0
in the longer string direction, so a strict-substring pair will always
also pass the 80% Jaccard check. The Jaccard formulation is the more
permissive / more useful primitive: it lets a paraphrased shorter
prediction match a longer ground-truth quote, which a strict substring
test would reject.

Overlap formula
---------------

After lowercasing and stripping non-alphanumeric characters, the two
quotes are tokenized on whitespace. The overlap is

    |A ∩ B| / |A ∪ B|

where ``A`` and ``B`` are the resulting token sets. Pure-substring
relationships are NOT automatically a match under set-Jaccard: a 4-token
substring inside a 24-token quote has overlap 4/24 = 0.167, which is
well below the 0.80 threshold. The 0.80 threshold is reached only when
the two quotes are roughly the same length and share most of their
tokens. This is the right primitive for our case: a "verbatim quote"
from the auditor is supposed to be a real sentence (or sub-sentence) of
comparable substance to the ground-truth evidence, not a few words
copied from a much longer passage.

The function is pure: it has no I/O, no globals, no side effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:  # pragma: no cover — typing only
    from .judge import FallbackGrader

# Threshold from the spec: >= 80% Jaccard overlap on the token sets.
EVIDENCE_OVERLAP_THRESHOLD = 0.80

# Lowercase + strip non-alphanumerics into whitespace-separated tokens.
_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _tokenize(quote: str) -> frozenset[str]:
    """Lowercase, strip punctuation, split on whitespace into a token set."""
    return frozenset(_TOKEN_RE.sub(" ", quote.lower()).split())


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard overlap: |A ∩ B| / |A ∪ B|. Returns 1.0 if both are empty."""
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _quote_of(finding: Any) -> str:
    """Pull the clinical_evidence_quote from either a dict or a dataclass."""
    if isinstance(finding, Mapping):
        return str(finding.get("clinical_evidence_quote", "") or "")
    return str(getattr(finding, "clinical_evidence_quote", "") or "")


def _field(finding: Any, key: str) -> str:
    """Pull a string field from either a dict or a dataclass."""
    if isinstance(finding, Mapping):
        return str(finding.get(key, "") or "")
    return str(getattr(finding, key, "") or "")


@dataclass(frozen=True)
class MatchedPair:
    """A single true-positive pair: one predicted finding matched to one ground-truth finding."""

    predicted_index: int
    ground_truth_index: int
    overlap_score: float


@dataclass(frozen=True)
class MatchResult:
    """Output of :func:`match_findings`."""

    tp: int
    fp: int
    fn: int
    matches: tuple[MatchedPair, ...] = field(default_factory=tuple)
    unmatched_predicted: tuple[int, ...] = field(default_factory=tuple)
    unmatched_ground_truth: tuple[int, ...] = field(default_factory=tuple)

    @property
    def precision(self) -> float:
        if self.tp + self.fp == 0:
            return 1.0
        return self.tp / (self.tp + self.fp)

    @property
    def recall(self) -> float:
        if self.tp + self.fn == 0:
            return 1.0
        return self.tp / (self.tp + self.fn)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        if p + r == 0.0:
            return 0.0
        return 2.0 * p * r / (p + r)


def match_findings(
    predicted: Sequence[Any],
    ground_truth: Sequence[Any],
    *,
    threshold: float = EVIDENCE_OVERLAP_THRESHOLD,
) -> MatchResult:
    """Match predicted findings to ground-truth findings.

    Greedy one-to-one matching: every (predicted, ground_truth) pair with
    matching category + suggested_code + >= threshold Jaccard overlap is a
    candidate; the algorithm picks pairs in descending overlap order, then
    marks each predicted and ground truth as used. Unused predictions are
    False Positives; unused ground truths are False Negatives.

    The function accepts both plain dicts (with keys ``category``,
    ``suggested_code``, ``clinical_evidence_quote``) and dataclass
    instances exposing the same three fields as attributes. Mixed inputs
    are allowed (e.g. predictions as dicts, ground truth as dataclasses).
    """
    if not predicted and not ground_truth:
        return MatchResult(tp=0, fp=0, fn=0)

    pred_tokens = [_tokenize(_quote_of(p)) for p in predicted]
    gt_tokens = [_tokenize(_quote_of(g)) for g in ground_truth]

    # Build all eligible (overlap, pred_idx, gt_idx) candidate triples.
    candidates: list[tuple[float, int, int]] = []
    for pi, p in enumerate(predicted):
        p_cat = _field(p, "category")
        p_code = _field(p, "suggested_code")
        for gi, g in enumerate(ground_truth):
            if _field(g, "category") != p_cat:
                continue
            if _field(g, "suggested_code") != p_code:
                continue
            overlap = _jaccard(pred_tokens[pi], gt_tokens[gi])
            if overlap >= threshold:
                candidates.append((overlap, pi, gi))

    # Greedy: pick highest overlap first, then lowest indices as tiebreak.
    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))

    used_p: set[int] = set()
    used_g: set[int] = set()
    matches: list[MatchedPair] = []
    for overlap, pi, gi in candidates:
        if pi in used_p or gi in used_g:
            continue
        used_p.add(pi)
        used_g.add(gi)
        matches.append(MatchedPair(pi, gi, overlap))

    unmatched_p = tuple(i for i in range(len(predicted)) if i not in used_p)
    unmatched_g = tuple(i for i in range(len(ground_truth)) if i not in used_g)

    return MatchResult(
        tp=len(matches),
        fp=len(unmatched_p),
        fn=len(unmatched_g),
        matches=tuple(matches),
        unmatched_predicted=unmatched_p,
        unmatched_ground_truth=unmatched_g,
    )


def f1_score(predicted: Sequence[Any], ground_truth: Sequence[Any]) -> float:
    """Convenience: F1 of a single match_findings call."""
    return match_findings(predicted, ground_truth).f1


def grade_with_fallback(
    predicted: Sequence[Any],
    ground_truth: Sequence[Any],
    grader: "FallbackGrader",
    *,
    threshold: float = EVIDENCE_OVERLAP_THRESHOLD,
) -> MatchResult:
    """Match with the deterministic matcher, then lift borderline FPs to TPs.

    Runs :func:`match_findings` first to get the deterministic result.
    For each predicted finding that the matcher classified as a False
    Positive, asks the supplied :class:`~ai_billing_audit.judge.FallbackGrader`
    to re-grade it against every still-unmatched ground-truth
    finding. If the grader returns a ``yes`` (judge score == 1.0) the
    pair is promoted to a True Positive and the corresponding
    ground truth is removed from the unmatched set.

    Use this when a paraphrase pushes the overlap into the [0.7, 0.9]
    ambiguous band: the deterministic matcher rejects it, the judge
    can rescue it. The grader is only consulted on the FPs produced
    by the deterministic pass — already-matched pairs and FN-only
    pairs are left alone. (The judge is built to *promote* matches,
    not demote them; that direction is the one that has a real
    ambiguity.)

    The function is pure in the sense that it does not mutate the
    inputs; it is impure in the sense that the supplied grader may
    make network calls.
    """
    base = match_findings(predicted, ground_truth, threshold=threshold)

    # Fast path: nothing to reconsider.
    if not base.unmatched_predicted or not base.unmatched_ground_truth:
        return base

    # Reconstruct the live ground-truth pool (unmatched only).
    live_gt: dict[int, Any] = {
        gi: ground_truth[gi] for gi in base.unmatched_ground_truth
    }
    promoted: list[MatchedPair] = []
    still_fp: list[int] = []
    still_fn: list[int] = list(base.unmatched_ground_truth)

    for pi in base.unmatched_predicted:
        promoted_pair: tuple[int, int] | None = None
        for gi, gt in list(live_gt.items()):
            result = grader.grade(predicted[pi], gt)
            if result.score >= 1.0 and result.method == "judge":
                promoted_pair = (pi, gi)
                break
        if promoted_pair is not None:
            pi2, gi2 = promoted_pair
            promoted.append(
                MatchedPair(
                    predicted_index=pi2,
                    ground_truth_index=gi2,
                    overlap_score=1.0,  # judge-promoted; overlap no longer relevant
                )
            )
            del live_gt[gi2]
            still_fn.remove(gi2)
        else:
            still_fp.append(pi)

    return MatchResult(
        tp=base.tp + len(promoted),
        fp=len(still_fp),
        fn=len(still_fn),
        matches=base.matches + tuple(promoted),
        unmatched_predicted=tuple(still_fp),
        unmatched_ground_truth=tuple(still_fn),
    )
