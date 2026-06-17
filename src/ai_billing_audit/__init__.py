"""ai-billing-audit: vendor-neutral LLM usage and billing audit."""

from __future__ import annotations

from ai_billing_audit.grader import (
    Grader,
    GraderConfigError,
    GraderVerdict,
    build_messages as build_grader_messages,
    load_grader_config,
)
from ai_billing_audit.minimax_client import (
    MINIMAX_BASE_URL,
    MINIMAX_DEFAULT_MODEL,
    MiniMaxClient,
)
from ai_billing_audit.minimax_errors import (
    MINIMAX_BACKOFF_BASE_SECONDS,
    MINIMAX_BACKOFF_CAP_SECONDS,
    MINIMAX_BACKOFF_FACTOR,
    MINIMAX_MAX_ATTEMPTS,
    MiniMaxAuthError,
    MiniMaxError,
    MiniMaxRateLimitError,
    MiniMaxServerError,
    compute_backoff,
    should_retry,
    translate_sdk_exception,
)
from ai_billing_audit.grading import (
    EVIDENCE_OVERLAP_THRESHOLD,
    MatchedPair,
    MatchResult,
    grade_with_fallback,
    match_findings,
)
from ai_billing_audit.judge import (
    FallbackGrader,
    GradeResult,
    SameProviderError,
)
from ai_billing_audit.messages import (
    ChatMessage,
    ChatRequest,
    MessageValidationError,
    Role,
    assistant,
    system,
    user,
    validate_chat_request,
    validate_messages,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "ChatMessage",
    "ChatRequest",
    "EVIDENCE_OVERLAP_THRESHOLD",
    "FallbackGrader",
    "Grader",
    "GraderConfigError",
    "GradeResult",
    "GraderVerdict",
    "MatchedPair",
    "MatchResult",
    "MINIMAX_BACKOFF_BASE_SECONDS",
    "MINIMAX_BACKOFF_CAP_SECONDS",
    "MINIMAX_BACKOFF_FACTOR",
    "MINIMAX_BASE_URL",
    "MINIMAX_DEFAULT_MODEL",
    "MINIMAX_MAX_ATTEMPTS",
    "MessageValidationError",
    "MiniMaxAuthError",
    "MiniMaxClient",
    "MiniMaxError",
    "MiniMaxRateLimitError",
    "MiniMaxServerError",
    "Role",
    "SameProviderError",
    "assistant",
    "build_grader_messages",
    "compute_backoff",
    "grade_with_fallback",
    "load_grader_config",
    "match_findings",
    "should_retry",
    "system",
    "translate_sdk_exception",
    "user",
    "validate_chat_request",
    "validate_messages",
]
