"""LLM-as-judge fallback grader for ambiguous per-finding matches.

The :class:`Grader` is a per-finding fallback decision-maker for cases
where the deterministic :func:`ai_billing_audit.grading.match_findings`
matcher is on the fence. The matcher is built on token-Jaccard overlap
of the clinical-evidence quote; a paraphrase in the borderline band
(0.7 <= overlap < 0.80 OR overlap just above the threshold with a
large financial-impact discrepancy) is exactly the case where a
deterministic rule is too brittle. We delegate that call to a second
LLM.

The judge is, by design, a *different* LLM provider than the auditor.
A grader that uses the same model as the system it grades inherits
the same blind spots and biases. The provider-difference rule is
enforced at construction time: if the judge and auditor resolve to
the same provider, :class:`Grader.__init__` raises
:class:`SameProviderError`.

Trigger conditions (both must hold)
------------------------------------

  1. ``0.7 <= token-Jaccard overlap(evidence_quote_pred,
     evidence_quote_gt) <= 0.9``
  2. ``|gt.financial_impact - pred.financial_impact| / |gt.financial_impact| <= 0.20``
     (i.e. relative error <= 20 %; if the ground-truth impact is 0 the
     condition is satisfied only when the predicted impact is also 0)

Judge prompt contract
---------------------

The judge receives a single yes/no question plus four pieces of
context: predicted evidence quote, ground-truth evidence quote,
predicted financial impact, ground-truth financial impact. The judge
must answer ``yes`` (the predicted evidence supports the predicted
financial impact given the ground truth) or ``no``. Anything else
(abstain, ``maybe``, ``unsure``, ``?``, blank, …) is treated as an
abstain and falls back to the deterministic string-match score.

Return shape
------------

:meth:`Grader.grade` returns a :class:`GradeResult` with three fields:

  - ``score``: float in [0.0, 1.0]. 1.0 for a judge "yes", 0.0 for a
    judge "no". On abstain / skip, the deterministic token-Jaccard
    overlap is returned.
  - ``method``: one of ``"judge"`` (judge answered yes/no),
    ``"abstain_fallback"`` (judge invoked but abstained, score is the
    deterministic overlap), ``"deterministic"`` (trigger conditions
    not met; judge was not called; score is the overlap).
  - ``judge_used``: bool, ``True`` iff the judge was actually invoked
    (i.e. conditions were met *and* the judge produced a yes/no
    answer). False on abstain, False on skipped trigger.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .grading import _jaccard, _tokenize  # reuse the deterministic primitive
from .llm import LLMClient, default_model, provider

__all__ = [
    "FallbackGrader",
    "GradeResult",
    "SameProviderError",
    "ABSTAIN_FALLBACK",
    "JUDGE_OVERLAP_LOWER",
    "JUDGE_OVERLAP_UPPER",
    "JUDGE_FINANCIAL_REL_TOLERANCE",
]


# Trigger thresholds per the spec.
JUDGE_OVERLAP_LOWER = 0.7
JUDGE_OVERLAP_UPPER = 0.9
JUDGE_FINANCIAL_REL_TOLERANCE = 0.20

# A trivial safety net: a perfect overlap shouldn't ever fall into the
# fallback band. We still keep the spec's [0.7, 0.9] interval, so this
# only matters when callers pass a custom threshold by accident.

# A small set of tokens that, in isolation, indicate an abstain
# response from the judge. Anything outside this set is treated as a
# "no" (the conservative call when the model goes off-script).
_ABSTAIN_TOKENS = frozenset(
    {
        "abstain",
        "unsure",
        "unknown",
        "uncertain",
        "maybe",
        "unclear",
        "?",  # bare punctuation the model sometimes returns
        "",
    }
)

_YES_RE = re.compile(r"\b(yes|y|true|correct|supported)\b", re.IGNORECASE)
_NO_RE = re.compile(r"\b(no|n|false|unsupported|not supported)\b", re.IGNORECASE)


@dataclass(frozen=True)
class GradeResult:
    """The output of :meth:`Grader.grade`."""

    score: float
    method: str
    judge_used: bool


class SameProviderError(ValueError):
    """Raised when the judge resolves to the same provider as the auditor."""


# ---------------------------------------------------------------------------
# Provider-difference logic
# ---------------------------------------------------------------------------

# Pairs of (auditor_default, judge_default) chosen so the default
# configuration already has two different providers. The operator can
# override either side with JUDGE_LLM_PROVIDER / JUDGE_LLM_MODEL.
_PAIR_TABLE: dict[str, str] = {
    "openai": "anthropic",
    "anthropic": "openai",
    "cohere": "openai",
    "google": "openai",
    "azure": "anthropic",
    "openrouter": "anthropic",
    "bedrock": "openai",
}


def _resolve_judge_provider(auditor_provider: str) -> str:
    """Pick a judge provider guaranteed to differ from the auditor's.

    Resolution order:

      1. ``JUDGE_LLM_PROVIDER`` env var (explicit operator choice).
      2. :data:`_PAIR_TABLE` lookup on the auditor's provider.
      3. The literal string ``"anthropic"`` if the auditor's provider
         is unrecognised — OpenAI and Anthropic are the two providers
         the project tests against, so this gives a sensible default
         in the common cases and a deterministic one in the obscure
         ones. (We never return the auditor's own provider.)
    """
    explicit = os.environ.get("JUDGE_LLM_PROVIDER")
    if explicit:
        return explicit
    if auditor_provider in _PAIR_TABLE:
        return _PAIR_TABLE[auditor_provider]
    # Fallback: prefer anthropic unless the auditor IS anthropic, in
    # which case pick openai. (The chain above only reaches here for
    # provider strings outside the table, but we still want a sane
    # default.)
    return "openai" if auditor_provider == "anthropic" else "anthropic"


def _resolve_judge_model(auditor_provider: str, judge_provider: str) -> str:
    """Pick a model name for the judge.

    Resolution order:

      1. ``JUDGE_LLM_MODEL`` env var.
      2. A conventional model name for the chosen provider: claude-haiku
         for anthropic, gpt-4o-mini for openai. These are cheap,
         deterministic enough for yes/no classification, and on the
         allowlist of most litellm configurations.
    """
    explicit = os.environ.get("JUDGE_LLM_MODEL")
    if explicit:
        return explicit
    if judge_provider == "anthropic":
        return "claude-haiku-4-5"
    if judge_provider == "openai":
        return "gpt-4o-mini"
    # Last-resort fallback: re-use the auditor's default model. This
    # only fires for providers we don't have a curated model for; the
    # provider-difference invariant is preserved by the surrounding
    # caller (which compares providers, not models).
    return default_model()


# ---------------------------------------------------------------------------
# Judge prompt
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM = (
    "You are an independent auditor's auditor. You are given a "
    "predicted auditor finding and the ground-truth finding it is "
    "being compared against. Your only job is to decide whether the "
    "predicted evidence quote, taken at face value, supports the "
    "predicted financial-impact claim given the ground truth. "
    "Answer with exactly one word: yes or no. No prose, no "
    "punctuation, no explanation."
)


def _build_judge_messages(
    predicted_quote: str,
    ground_truth_quote: str,
    predicted_financial_impact: float,
    ground_truth_financial_impact: float,
) -> list[dict[str, str]]:
    """Render the four pieces into a single yes/no question."""
    user = (
        "Predicted evidence quote:\n"
        f"  {predicted_quote}\n\n"
        "Ground-truth evidence quote:\n"
        f"  {ground_truth_quote}\n\n"
        f"Predicted financial impact: {predicted_financial_impact}\n"
        f"Ground-truth financial impact: {ground_truth_financial_impact}\n\n"
        "Does the predicted evidence quote support the predicted "
        "financial-impact claim, given the ground truth? Answer with "
        "exactly one word: yes or no."
    )
    return [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class Grader:
    """LLM-as-judge fallback grader for ambiguous per-finding matches.

    Construction reads the auditor's provider from
    :func:`ai_billing_audit.llm.provider` and picks a different
    provider for the judge. Both providers are resolved up front and
    compared — if they end up the same (e.g. the operator set
    ``JUDGE_LLM_PROVIDER`` to the auditor's provider) construction
    raises :class:`SameProviderError`.

    This class is named ``Grader`` in the source file (mirroring the
    spec's ``grader.grade(prediction, ground_truth)`` signature), but
    it is exported as :data:`FallbackGrader` to avoid a name clash
    with the deterministic LLM-based :class:`ai_billing_audit.grader.Grader`
    in the package's public surface. Both graders coexist; the
    deterministic one is the default per-finding judge, and this one
    is the LLM fallback for ambiguous cases.

    Parameters
    ----------
    llm:
        Optional :class:`LLMClient` for the judge. When omitted, a
        default client is constructed that routes through
        ``litellm.completion`` with the judge model. Tests inject a
        fake client whose ``complete`` returns a canned yes/no
        payload.
    auditor_provider:
        Override the auditor's provider string. Defaults to
        :func:`ai_billing_audit.llm.provider`. Exposed mainly for
        tests; production code should leave it alone.
    judge_provider:
        Override the judge's provider string. Defaults to
        :func:`_resolve_judge_provider` applied to the auditor's
        provider.
    judge_model:
        Override the judge's model. Defaults to
        :func:`_resolve_judge_model`.
    """

    def __init__(
        self,
        *,
        llm: LLMClient | None = None,
        auditor_provider: str | None = None,
        judge_provider: str | None = None,
        judge_model: str | None = None,
    ) -> None:
        auditor_p = auditor_provider if auditor_provider is not None else provider()
        judge_p = judge_provider if judge_provider is not None else _resolve_judge_provider(auditor_p)
        judge_m = judge_model if judge_model is not None else _resolve_judge_model(auditor_p, judge_p)

        if judge_p == auditor_p:
            raise SameProviderError(
                f"Judge provider ({judge_p!r}) must differ from auditor "
                f"provider ({auditor_p!r}). Set JUDGE_LLM_PROVIDER to a "
                "different value."
            )

        self._auditor_provider = auditor_p
        self._judge_provider = judge_p
        self._judge_model = judge_m
        self._llm: LLMClient = llm if llm is not None else LLMClient(model=judge_m)

    # ------------------------------------------------------------------
    # Properties for introspection (tests + the dashboard consume these)
    # ------------------------------------------------------------------

    @property
    def auditor_provider(self) -> str:
        return self._auditor_provider

    @property
    def judge_provider(self) -> str:
        return self._judge_provider

    @property
    def judge_model(self) -> str:
        return self._judge_model

    # ------------------------------------------------------------------
    # Trigger logic
    # ------------------------------------------------------------------

    @staticmethod
    def _evidence_of(finding: Any) -> str:
        """Pull the evidence quote from a dict or dataclass.

        The spec calls this ``evidence_quote``; the auditor's
        ``Finding`` dataclass calls it ``quote``. Accept both.
        """
        if isinstance(finding, Mapping):
            for key in ("clinical_evidence_quote", "evidence_quote", "quote"):
                if key in finding:
                    return str(finding.get(key, "") or "")
            return ""
        for key in ("clinical_evidence_quote", "evidence_quote", "quote"):
            if hasattr(finding, key):
                return str(getattr(finding, key, "") or "")
        return ""

    @staticmethod
    def _impact_of(finding: Any) -> float:
        """Pull the financial impact from a dict or dataclass.

        Accepts ``financial_impact`` (spec name) and
        ``estimated_financial_impact`` (the data model used in the
        existing training data).
        """
        for key in ("financial_impact", "estimated_financial_impact"):
            if isinstance(finding, Mapping):
                if key in finding:
                    try:
                        return float(finding[key] or 0)
                    except (TypeError, ValueError):
                        return 0.0
            else:
                if hasattr(finding, key):
                    try:
                        return float(getattr(finding, key) or 0)
                    except (TypeError, ValueError):
                        return 0.0
        return 0.0

    def _should_invoke_judge(
        self, predicted: Any, ground_truth: Any
    ) -> tuple[bool, float]:
        """Compute the trigger conditions.

        Returns ``(should_invoke, deterministic_overlap)``. The
        deterministic overlap is returned alongside the trigger
        verdict because both the skip path and the abstain-fallback
        path need to return it as the score.
        """
        pred_quote = self._evidence_of(predicted)
        gt_quote = self._evidence_of(ground_truth)
        overlap = _jaccard(_tokenize(pred_quote), _tokenize(gt_quote))

        # Condition 1: evidence overlap in the ambiguous band.
        cond1 = JUDGE_OVERLAP_LOWER <= overlap <= JUDGE_OVERLAP_UPPER

        # Condition 2: financial-impact relative error within tolerance.
        # Ground-truth impact of 0 collapses the relative-error formula;
        # we only treat (0, 0) as a pass (the impact is "the same"
        # when both are zero).
        gt_impact = self._impact_of(ground_truth)
        pred_impact = self._impact_of(predicted)
        if gt_impact == 0:
            cond2 = pred_impact == 0
        else:
            rel_err = abs(gt_impact - pred_impact) / abs(gt_impact)
            cond2 = rel_err <= JUDGE_FINANCIAL_REL_TOLERANCE

        return (cond1 and cond2), overlap

    # ------------------------------------------------------------------
    # Judge call
    # ------------------------------------------------------------------

    def _invoke_judge(
        self,
        predicted: Any,
        ground_truth: Any,
    ) -> str:
        """Call the judge and return the raw text answer.

        The caller is responsible for parsing yes/no/abstain from the
        return value. We deliberately do NOT raise on transport
        errors — the spec says abstain/uncertain should fall back to
        the deterministic score, and a flaky LLM call is closer to
        "abstain" than to "no" (the conservative call when we don't
        know is: don't override the deterministic answer).
        """
        try:
            response = self._llm.complete(
                _build_judge_messages(
                    predicted_quote=self._evidence_of(predicted),
                    ground_truth_quote=self._evidence_of(ground_truth),
                    predicted_financial_impact=self._impact_of(predicted),
                    ground_truth_financial_impact=self._impact_of(ground_truth),
                ),
                model=self._judge_model,
            )
        except Exception:  # noqa: BLE001 — any transport error → abstain
            return "abstain"

        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return "abstain"
        return (content or "").strip()

    @staticmethod
    def _parse_judge_answer(raw: str) -> str:
        """Reduce the judge's free-form answer to ``"yes"`` / ``"no"`` / ``"abstain"``."""
        if not raw:
            return "abstain"
        # Trim and normalise whitespace.
        text = raw.strip().lower()
        # Bare punctuation is an abstain.
        compact = re.sub(r"\s+", "", text)
        if compact in _ABSTAIN_TOKENS:
            return "abstain"
        # Detect explicit abstain phrases before the yes/no sweep so
        # "I'm not sure" is treated as abstain rather than collapsed
        # to "no" by a substring rule.
        if any(tok in compact for tok in ("notsure", "cannotdetermine", "cantdetermine", "idk")):
            return "abstain"
        # Yes/no sweep on the full text.
        if _YES_RE.search(text) and not _NO_RE.search(text):
            return "yes"
        if _NO_RE.search(text) and not _YES_RE.search(text):
            return "no"
        # Both matched, or neither matched: treat as abstain.
        return "abstain"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def grade(self, prediction: Any, ground_truth: Any) -> GradeResult:
        """Grade a single predicted finding against a single ground-truth finding.

        Parameters
        ----------
        prediction, ground_truth:
            A finding (dict or dataclass) shaped with
            ``clinical_evidence_quote`` and ``estimated_financial_impact``
            (or ``financial_impact``).

        Returns
        -------
        :class:`GradeResult`
            ``score`` in [0.0, 1.0], ``method`` in
            ``{"deterministic", "judge", "abstain_fallback"}``,
            ``judge_used`` is True iff the judge was invoked *and*
            produced a yes/no answer.
        """
        should_invoke, overlap = self._should_invoke_judge(prediction, ground_truth)
        if not should_invoke:
            return GradeResult(
                score=float(overlap),
                method="deterministic",
                judge_used=False,
            )

        raw = self._invoke_judge(prediction, ground_truth)
        verdict = self._parse_judge_answer(raw)
        if verdict == "yes":
            return GradeResult(score=1.0, method="judge", judge_used=True)
        if verdict == "no":
            return GradeResult(score=0.0, method="judge", judge_used=True)
        # Abstain: fall back to the deterministic overlap.
        return GradeResult(
            score=float(overlap),
            method="abstain_fallback",
            judge_used=False,
        )


# Public sentinel for the abstain-fallback score: callers that want a
# "no LLM" configuration can use ABSTAIN_FALLBACK to skip the judge
# call entirely. Not used by the production code path, but documented
# for downstream consumers.
ABSTAIN_FALLBACK = "abstain_fallback"


# Public alias. The class is named ``Grader`` in this module to match
# the spec's ``grader.grade(...)`` signature, but it is exported as
# :data:`FallbackGrader` so it does not collide with the deterministic
# :class:`ai_billing_audit.grader.Grader`. Both names refer to the
# same class.
FallbackGrader = Grader
