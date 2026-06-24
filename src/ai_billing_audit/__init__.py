"""ai-billing-audit: vendor-neutral LLM usage and billing audit."""

from __future__ import annotations

# Pre-imports that prevent the typing_extensions/litellm import-order bug
# on Python 3.11 + litellm 1.x + typing_extensions 4.15. Without these,
# the first transitive import of litellm raises:
#   AttributeError: module 'inspect' has no attribute 'signature'
# at typing_extensions.py:1060. Importing these first ensures `inspect.signature`
# is fully bound in sys.modules before litellm's chain reaches it.
import inspect as _inspect  # noqa: F401
import typing as _typing  # noqa: F401
import typing_extensions as _typing_extensions  # noqa: F401

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
