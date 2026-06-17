"""Smoke test: package imports and version is exposed."""

from __future__ import annotations


def test_version_is_string() -> None:
    import ai_billing_audit

    assert isinstance(ai_billing_audit.__version__, str)
    # PEP 440 dev/release segments are allowed; we just require two
    # numeric components to catch a blank version being shipped.
    parts = ai_billing_audit.__version__.split(".")
    assert len(parts) >= 2
    assert all(p.isdigit() for p in parts[:2])


def test_auditor_module_imports() -> None:
    from ai_billing_audit import auditor  # noqa: F401

    assert hasattr(auditor, "run_audit")
    assert hasattr(auditor, "build_messages")
    assert hasattr(auditor, "load_prompt")
    assert hasattr(auditor, "validate_findings")


def test_grading_module_imports() -> None:
    from ai_billing_audit import grading  # noqa: F401

    assert hasattr(grading, "match_findings")
    assert hasattr(grading, "MatchResult")
    assert hasattr(grading, "MatchedPair")
    assert hasattr(grading, "EVIDENCE_OVERLAP_THRESHOLD")
    assert hasattr(grading, "grade_with_fallback")


def test_judge_module_imports() -> None:
    from ai_billing_audit import judge  # noqa: F401

    assert hasattr(judge, "FallbackGrader")
    assert hasattr(judge, "GradeResult")
    assert hasattr(judge, "SameProviderError")
    assert hasattr(judge, "JUDGE_OVERLAP_LOWER")
    assert hasattr(judge, "JUDGE_OVERLAP_UPPER")
    assert hasattr(judge, "JUDGE_FINANCIAL_REL_TOLERANCE")
