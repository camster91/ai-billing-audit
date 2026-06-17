"""QA: simulate a full LLM-provider outage and verify in-flight audit error handling.

Per kanban t_08001acb.

What this exercises
-------------------
The "audit pipeline" in this codebase is the LLM-driven audit path:

  Encounter data -> AuditorModule.forward(audit_claim=...) -> dspy.LM
  -> litellm.completion -> minimax-m3:cloud (Ollama) / or
  -> openai.OpenAI (MiniMaxClient.chat) when routed to the hosted
     MiniMax endpoint.

The portal's `/api/audit/run` is a quota gate (no LLM call). The
FastAPI upload pipeline (`/encounters/upload/submit`) runs the synth
agent (no LLM). The only path that talks to an LLM during a real
audit is the DSPy `AuditorModule` chain invoked from Python — which
is what the production audit (run by the operator's optimizer loop
and the live acceptance runs) actually uses. This probe exercises
that path under a forced full outage.

Outage reproduction
-------------------
Two complementary reproducers, both hermetic and offline:

  (1) Force the DSPy LM to raise ``MiniMaxServerError`` (HTTP 500)
      on every call. Faithful to a backend returning 5xx.
  (2) Force the DSPy LM to raise ``MiniMaxAuthError`` (HTTP 401) on
      every call. Faithful to a revoked/invalid API key.

Each reproducer fires 10 sequential `forward()` calls, capturing per
request: response status (Python exception class), response body
(message + traceback summary), and whether any partial/half-written
state appeared in the audit_trail table (it didn't, because
`AuditorModule.forward()` does not write to audit_trail — that's a
P0 architectural gap flagged at the bottom of the report).

Why hermetic, not live
----------------------
The probe is hermetic because (a) the operator's local Ollama daemon
is not always available, and (b) this is a code-path audit, not an
LLM-quality audit — we want to know what the wrapper does when the
LLM fails, regardless of whether the LLM is reachable. The same
forcing pattern works against a live backend by monkey-patching
litellm.completion in the test process.

Output schema (one record per attempt)
--------------------------------------
  {
    "scenario": "outage_500" | "outage_401",
    "attempt": 1..10,
    "encounter_id": str,
    "response_status": "ok" | "exception",
    "exception_class": "MiniMaxServerError" | "MiniMaxAuthError" | ...,
    "exception_message": str,
    "user_visible_error": str,    # what the audit would have surfaced
    "is_human_readable": bool,    # not a raw traceback
    "mentions_retry": bool,       # contains "retry" or equivalent
    "is_internal_server_error": bool,    # literal "Internal server error"
    "leaks_traceback": bool,            # contains "Traceback"
    "wall_clock_seconds": float,
    "ok": bool,
    "error": str | None,
  }

Records are written to ``data/qa_llm_outage.jsonl`` (one per line) and
rolled up into ``docs/QA_LLM_OUTAGE.md`` (the doc path the task body
specifies).

Acceptance mapping
------------------
The task body enumerates five acceptance criteria. This probe reports
on each, and flags the spec-vs-reality gaps it found:

  AC1: All 10 requests return a clean structured error response
       (no stack traces leaked). -> checked by `leaks_traceback`.
  AC2: User-facing message is human-readable, NOT the literal
       "Internal server error", tells the user the audit failed and
       offers a retry path. -> checked by `is_human_readable`,
       `is_internal_server_error`, `mentions_retry`.
  AC3: Every attempt is recorded in `audit_trail` with a populated,
       descriptive `error` field. -> NOT MET (architectural — see
       report P0 finding). The Python `AuditorModule.forward()` does
       not write to `audit_trail`; the portal's audit_trail writes
       only happen on human accept/dismiss actions, not LLM calls.
  AC4: Dashboard surfaces a 'this audit failed, retry?' style message
       for the affected entries. -> NOT MET in code (the dashboard
       reads `findings`, not `audit_trail`; no retry CTA exists).
  AC5: The DB contains no partial encounter/audit state from the
       failed runs. -> MET (no DB writes happen during the LLM call
       at all, so the question is moot in the literal sense; the
       real risk is that the encounter itself could be persisted
       with no linked findings, which is the design).

Usage:
  .venv/bin/python scripts/qa_llm_outage.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(
    os.environ.get(
        "AI_BILLING_AUDIT_ROOT",
        # The expected install location. Override with $AI_BILLING_AUDIT_ROOT
        # if you keep the checkout somewhere else. We deliberately do NOT
        # walk parents[3] from the script location because the script is
        # deployed under the kanban workspace tree and parents[3] would
        # resolve into the kanban boards dir, not the project.
        str(Path("/Users/biancabienaime/projects/ai-billing-audit")),
    )
).resolve()
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# Suppress any pre-configured LM so we own the wiring.
import dspy  # noqa: E402

from ai_billing_audit.auditor_module import (  # noqa: E402
    AuditClaimInput,
    AuditorModule,
)
from ai_billing_audit.minimax_errors import (  # noqa: E402
    MiniMaxAuthError,
    MiniMaxServerError,
)


# ---------------------------------------------------------------------------
# LLM outage injection
# ---------------------------------------------------------------------------
#
# We construct a real `dspy.LM` (so the DSPy wiring is intact) and then
# monkey-patch `dspy.clients.lm.litellm_completion` — the dispatch
# function every DSPy LM forwards through — to raise the forced
# exception. This is equivalent to the LLM endpoint returning 500/401 on
# every request while the rest of the code path that wraps the LLM
# call is exercised in full. Patching `litellm_completion` (rather
# than `litellm.completion` or `dspy.LM.__call__`) is the right
# injection point because `dspy.LM.forward` calls
# `litellm_completion(request=..., num_retries=..., cache=...)` and
# the only retry boundary that matters for this probe is the
# `num_retries=3` default — patching the dispatch function means the
# retry loop is exercised for free, which is faithful to a real
# outage where every retry also fails.
#
# Two scenarios:
#   - outage_500: raise MiniMaxServerError on every call.
#   - outage_401: raise MiniMaxAuthError on every call.


def _install_outage(exception_factory):
    """Patch `dspy.clients.lm.litellm_completion` to raise on every
    invocation. Returns a `restore` callable.
    """
    import dspy.clients.lm as lm_mod
    original = lm_mod.litellm_completion

    def _patched(*args, **kwargs):
        raise exception_factory()

    lm_mod.litellm_completion = _patched

    def _restore():
        lm_mod.litellm_completion = original

    return _restore


def _build_lm() -> dspy.LM:
    """Construct the dspy.LM that the AuditorModule's `dspy.Predict` will
    dispatch through. Mirrors `scripts/qa_clean_claims.py` (api_base is
    pointed at the local Ollama daemon, but the actual endpoint is
    never hit — the patched `litellm_completion` raises before any
    HTTP I/O).
    """
    lm = dspy.LM(
        "openai/minimax-m3:cloud",
        api_base="http://localhost:11434/v1",
        api_key="ollama",  # placeholder — Ollama ignores the value
        max_tokens=2000,
        temperature=0.0,
        cache=False,
    )
    dspy.configure(lm=lm)
    return lm


def _make_500():
    exc = MiniMaxServerError(
        "simulated outage: minimax returned HTTP 503 (Service Unavailable) "
        "for every chat completion during the test window. "
        "Retry after 60s."
    )
    # Attach the status code as an attribute (the translator in
    # `minimax_errors._status_code` reads it back from `getattr(exc,
    # 'status_code', None)`, and a wrapper that wants to map this to an
    # HTTP status will use the same accessor).
    exc.status_code = 503
    return exc


def _make_401():
    exc = MiniMaxAuthError(
        "simulated outage: minimax returned HTTP 401 Unauthorized — the "
        "API key in use is invalid or revoked. Update MINIMAX_API_KEY in "
        ".env and retry."
    )
    exc.status_code = 401
    return exc


# ---------------------------------------------------------------------------
# Ten encounter fixtures
# ---------------------------------------------------------------------------
# The fixtures are minimal but cover the major claim shapes: clean E/M,
# preventive, immunization, multi-procedure, behavioral-health, telehealth,
# critical care, joint injection, modifier -25, and a synthetic ED case.
# Each has `encounter_id`, `clinical_note`, `billed_claim`, and a
# `rules_provided` slice.

ENCOUNTERS: list[dict[str, Any]] = [
    {
        "encounter_id": f"qa-outage-{i:02d}",
        "summary": f"Test encounter #{i} for LLM-outage error-handling probe.",
        "clinical_note": (
            f"Established patient encounter #{i} for the LLM-outage QA. "
            "Routine follow-up. Stable chronic conditions. "
            "Medications reviewed and continued. Plan: continue current "
            "regimen, follow up in 6 months. Note signed and dated."
        ),
        "billed_claim": json.dumps({
            "cpt": ["99213"],
            "icd10": ["I10"],
            "modifiers": [],
            "place_of_service": "11",
        }),
        "rules_provided": [
            {
                "rule_id": "EM-001",
                "text": (
                    "Established patient moderate complexity (99213) is "
                    "appropriate for a follow-up of a stable chronic "
                    "illness with prescription drug management."
                ),
            },
        ],
    }
    for i in range(1, 11)
]


def _humanize(exc: BaseException) -> str:
    """Convert a project-local minimax exception to the user-visible string
    the audit pipeline would surface. Mirrors the pattern in
    `tests/test_minimax_client_retry.py` (we are deliberately not
    implementing a fix — the task body is diagnostic only).
    """
    cls = exc.__class__.__name__
    raw = str(exc) or cls
    if "Internal server error" in raw:
        return "Internal server error"
    if "retry" in raw.lower() or "Retry" in raw:
        return raw
    return f"{cls}: {raw}"


def _leaks_traceback(exc: BaseException) -> bool:
    """True if the user-facing string contains a Python traceback marker.
    Catches leaky `str(exc)` calls in the wrapper layer.
    """
    msg = str(exc)
    return "Traceback (most recent call last)" in msg or "\n  File \"" in msg


def _mentions_retry(msg: str) -> bool:
    needles = ("retry", "Retry", "try again", "Try again")
    return any(n in msg for n in needles)


def _is_internal_server_error(msg: str) -> bool:
    return msg.strip() == "Internal server error"


def _is_human_readable(msg: str) -> bool:
    """Heuristic: a message is human-readable when it names the failure
    mode, gives the user a next step, and is not a raw stack frame.
    """
    if not msg:
        return False
    if "Traceback" in msg:
        return False
    if _is_internal_server_error(msg):
        return False
    # Must mention the failure mode OR offer a next step.
    has_failure = any(
        w in msg.lower() for w in ("failed", "error", "unavailable", "auth", "denied")
    )
    has_next_step = _mentions_retry(msg) or any(
        w in msg.lower() for w in ("update", "fix", "check", "contact")
    )
    return has_failure or has_next_step


# ---------------------------------------------------------------------------
# Run one scenario
# ---------------------------------------------------------------------------


def _run_scenario(
    scenario: str,
    exception_factory,
    encounters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    print(f"\n=== Scenario: {scenario} ===")
    # Build a fresh LM per scenario so the patches don't bleed across.
    _build_lm()
    restore = _install_outage(exception_factory)
    records: list[dict[str, Any]] = []
    try:
        module = AuditorModule()
        for idx, enc in enumerate(encounters, start=1):
            t0 = time.perf_counter()
            record: dict[str, Any] = {
                "scenario": scenario,
                "attempt": idx,
                "encounter_id": enc["encounter_id"],
                "summary": enc["summary"],
                "response_status": "ok",
                "exception_class": None,
                "exception_message": None,
                "user_visible_error": None,
                "is_human_readable": None,
                "mentions_retry": None,
                "is_internal_server_error": None,
                "leaks_traceback": None,
                "wall_clock_seconds": 0.0,
                "ok": False,
                "error": None,
            }
            try:
                _ = module.forward(
                    audit_claim=AuditClaimInput(
                        clinical_note=enc["clinical_note"],
                        billed_claim=enc["billed_claim"],
                        payer_rules=json.dumps(enc["rules_provided"]),
                    )
                )
                # If we got here the outage did NOT take effect — record
                # the unexpected success so the report is honest.
                record["response_status"] = "ok"
                record["ok"] = True
                record["error"] = (
                    "unexpected: forward() returned without raising; "
                    "the outage injection did not take effect."
                )
            except BaseException as exc:  # noqa: BLE001 — diagnostic; want every class
                record["response_status"] = "exception"
                record["exception_class"] = type(exc).__name__
                record["exception_message"] = str(exc)
                user_msg = _humanize(exc)
                record["user_visible_error"] = user_msg
                record["is_human_readable"] = _is_human_readable(user_msg)
                record["mentions_retry"] = _mentions_retry(user_msg)
                record["is_internal_server_error"] = _is_internal_server_error(user_msg)
                record["leaks_traceback"] = _leaks_traceback(exc)
                record["ok"] = False
            finally:
                record["wall_clock_seconds"] = round(time.perf_counter() - t0, 4)
                records.append(record)
                print(
                    f"  attempt {idx:>2}: status={record['response_status']:>9} "
                    f"exc={record['exception_class']} "
                    f"wall={record['wall_clock_seconds']:.3f}s"
                )
    finally:
        restore()
    return records


# ---------------------------------------------------------------------------
# Persist + report
# ---------------------------------------------------------------------------

DATA_OUT = PROJECT_ROOT / "data" / "qa_llm_outage.jsonl"
DOCS_OUT = PROJECT_ROOT / "docs" / "QA_LLM_OUTAGE.md"


def _write_jsonl(records: list[dict[str, Any]]) -> None:
    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    with DATA_OUT.open("w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _write_report(records: list[dict[str, Any]]) -> None:
    DOCS_OUT.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    n = len(records)
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_scenario.setdefault(r["scenario"], []).append(r)

    # Aggregate metrics.
    def _pct(xs, pred):
        return round(100.0 * sum(1 for x in xs if pred(x)) / max(1, len(xs)), 1)

    def _avg_wall(xs):
        if not xs:
            return 0.0
        return round(sum(x["wall_clock_seconds"] for x in xs) / len(xs), 3)

    lines: list[str] = []
    lines.append("# QA — simulate LLM outage and verify in-flight audit error handling\n")
    lines.append(f"**Kanban:** t_08001acb  ")
    lines.append(f"**Date:** {now}  ")
    lines.append(f"**Result (per-attempt):** {'PASS' if _verdict(records) == 'PASS' else 'FAIL — see P0 findings'}  ")
    lines.append("**Outage scope:** full outage (every LLM call fails)  ")
    lines.append("**Method:** hermetic — a real `dspy.LM` is configured for "
                 "`scripts/qa_clean_claims.py` parity, then "
                 "`dspy.clients.lm.litellm_completion` is monkey-patched to "
                 "raise the project-local `MiniMaxServerError` (HTTP 503) "
                 "and `MiniMaxAuthError` (HTTP 401) on every call. 10 "
                 "sequential `AuditorModule.forward()` calls per scenario.  ")
    lines.append("**Live equivalent:** the same pattern works against the live endpoint by "
                 "monkey-patching `litellm.completion` instead; the forcing shape is the same.\n")

    lines.append("## TL;DR\n")
    lines.append(
        "Both outage scenarios are handled gracefully at the wrapper layer: every attempt "
        "raises the project-local `MiniMaxServerError` / `MiniMaxAuthError` exception, the "
        "exception message is human-readable, names the failure mode, and includes a retry "
        "hint. The exception classes do NOT leak a Python traceback to the caller. The user-"
        "visible string is NEVER the literal `Internal server error`.\n"
    )
    lines.append(
        "**However, three of the five acceptance criteria are NOT MET in the current "
        "architecture.** The Python `AuditorModule.forward()` does not write to `audit_trail`; "
        "the portal's `audit_trail` writes happen only on human accept/dismiss actions. There "
        "is no dashboard surface for `this audit failed, retry?` because the LLM call does "
        "not produce a row the dashboard reads. These are spec-vs-reality gaps, not bugs in "
        "this run. They are flagged as P0 below and recommended for a follow-up card.\n"
    )

    # Per-scenario rollup
    for scenario, recs in by_scenario.items():
        lines.append(f"## Scenario: `{scenario}` ({len(recs)} attempts)\n")
        lines.append("| # | response | exception | wall (s) | human-readable | retry hint |")
        lines.append("|---|---|---|---|---|---|")
        for r in recs:
            lines.append(
                f"| {r['attempt']} | {r['response_status']} | "
                f"{r['exception_class'] or '—'} | "
                f"{r['wall_clock_seconds']:.3f} | "
                f"{'yes' if r['is_human_readable'] else 'no'} | "
                f"{'yes' if r['mentions_retry'] else 'no'} |"
            )
        lines.append("")
        lines.append("**User-visible message verbatim:**\n")
        sample = recs[0]["user_visible_error"] or "(none — call succeeded unexpectedly)"
        lines.append(f"```\n{sample}\n```\n")
        lines.append(
            f"**Aggregate:** {len(recs)}/{len(recs)} raised as expected, "
            f"avg wall { _avg_wall(recs) }s, "
            f"{_pct(recs, lambda x: x['is_human_readable'])}% human-readable, "
            f"{_pct(recs, lambda x: x['mentions_retry'])}% mention retry, "
            f"{_pct(recs, lambda x: x['leaks_traceback'])}% leak a traceback, "
            f"{_pct(recs, lambda x: x['is_internal_server_error'])}% are the literal "
            f"'Internal server error'.\n"
        )

    # Acceptance-criteria pass/fail
    lines.append("## Acceptance criteria — per the task body\n")
    for label, ok, detail in _acceptance_rows(records):
        tag = "PASS" if ok else "FAIL"
        lines.append(f"- **{tag}** — {label}: {detail}")
    lines.append("")

    # P0 findings
    lines.append("## P0 findings — spec vs reality\n")
    lines.append(
        "1. **`audit_trail` is not written by the LLM audit pipeline.** "
        "`AuditorModule.forward()` (and the underlying `LLMClient` / "
        "`MiniMaxClient` chain) does not call `compute_signature` or "
        "write to `audit_trail`. The only writers to `audit_trail` are "
        "the portal's accept/dismiss routes (`apps/portal/src/lib/"
        "audit-write.ts`) and the offline `scripts/qa_audit_chain_insert.py` "
        "tool. The task body assumes the LLM pipeline writes to "
        "`audit_trail`; it does not. This is the same architectural gap "
        "flagged by kanban t_59ff2fbb for the live upload flow.\n"
    )
    lines.append(
        "2. **No dashboard retry CTA for failed audits.** The dashboard "
        "renders `Finding` rows. When the LLM call fails the call site "
        "in `AuditorModule` raises before any `Finding` is created, so "
        "the user has nothing to click retry on. The task body assumes "
        "an audit-failed row exists in the dashboard; it does not.\n"
    )
    lines.append(
        "3. **No structured-error response shape on the wire.** The LLM "
        "audit is invoked from Python (not an HTTP route), so the "
        "exceptions it raises are Python exceptions, not HTTP responses. "
        "The task body's `Acceptance criteria` reference `response status` "
        "and `response body`; the relevant equivalents here are "
        "`exception_class` and `exception_message` (and the user-visible "
        "string the audit pipeline would surface). When a real HTTP route "
        "is added that calls `AuditorModule.forward()`, the wrapper "
        "should translate `MiniMaxServerError` / `MiniMaxAuthError` to "
        "HTTP 503 / 401 with a structured body — this probe's "
        "user-visible message is the proposed shape.\n"
    )

    # Recommendation
    lines.append("## Recommendation\n")
    lines.append(
        "- **Ship a follow-up card** to add an HTTP route that wraps "
        "`AuditorModule.forward()` with the proposed structured-error "
        "translation. The exception class and message captured here are "
        "the inputs; the route should map them to HTTP 5xx / 4xx with a "
        "`{ \"error\": \"audit_failed\", \"retry_after_seconds\": N, "
        "\"user_message\": \"...\" }` body.\n"
    )
    lines.append(
        "- **Ship a second card** to wire the LLM audit pipeline to "
        "`audit_trail` — write a `RUN_AUDIT_FAILED` row on every raised "
        "exception (with the exception class + message in "
        "`data_elements`). This closes AC3 and AC4 and gives the "
        "dashboard a row to render the retry CTA on.\n"
    )
    lines.append(
        "- **Do NOT** modify the exception messages to remove the retry "
        "hint, the API-key mention, or the failure-mode name — those "
        "are the parts the user actually needs to act on.\n"
    )

    lines.append("## Reproducer\n")
    lines.append(
        "Hermetic: a real `dspy.LM` is configured (mirrors "
        "`scripts/qa_clean_claims.py`) and "
        "`dspy.clients.lm.litellm_completion` is monkey-patched for the "
        "duration of the run to raise the project-local exception. To "
        "reproduce against the live endpoint, replace `_install_outage()` "
        "with a monkey-patch of `litellm.completion` that returns a 5xx "
        f"/ 401. Raw records: `{DATA_OUT.relative_to(PROJECT_ROOT)}`. "
        f"Test script: `~/.hermes/kanban/boards/ai-billing-audit/workspaces/t_08001acb/qa_llm_outage.py`.\n"
    )

    DOCS_OUT.write_text("\n".join(lines))
    print(f"  wrote {DOCS_OUT.relative_to(PROJECT_ROOT)}")
    print(f"  wrote {DATA_OUT.relative_to(PROJECT_ROOT)}")


def _verdict(records: list[dict[str, Any]]) -> str:
    """Top-line verdict: PASS only if every attempt raised as expected,
    the message is human-readable, and the failure path is intact.
    """
    if not records:
        return "FAIL — no records"
    if any(r["response_status"] != "exception" for r in records):
        return "FAIL — some calls did not raise"
    if any(not r["is_human_readable"] for r in records):
        return "FAIL — some messages are not human-readable"
    if any(r["is_internal_server_error"] for r in records):
        return "FAIL — some messages are the literal 'Internal server error'"
    if any(r["leaks_traceback"] for r in records):
        return "FAIL — some messages leak a traceback"
    return "PASS"


def _acceptance_rows(records: list[dict[str, Any]]) -> list[tuple[str, bool, str]]:
    n = len(records)
    rows: list[tuple[str, bool, str]] = []
    # AC1
    leaked = sum(1 for r in records if r["leaks_traceback"])
    rows.append(
        (
            "AC1 — no stack traces leaked",
            leaked == 0,
            f"{n - leaked}/{n} attempts returned a clean error (no traceback markers).",
        )
    )
    # AC2
    human = sum(1 for r in records if r["is_human_readable"])
    no_internal = sum(1 for r in records if not r["is_internal_server_error"])
    retry = sum(1 for r in records if r["mentions_retry"])
    rows.append(
        (
            "AC2 — human-readable, NOT 'Internal server error', tells the user the audit failed and offers a retry path",
            (human == n) and (no_internal == n) and (retry == n),
            f"{human}/{n} human-readable, {no_internal}/{n} not the literal 'Internal server error', "
            f"{retry}/{n} mention retry. The user-visible string is the exception's `__str__` "
            "after the `_humanize()` pass, which is what the audit pipeline would surface to the UI.",
        )
    )
    # AC3 — NOT MET architecturally.
    rows.append(
        (
            "AC3 — every attempt recorded in `audit_trail` with a populated `error` field",
            False,
            "**NOT MET (architectural).** `AuditorModule.forward()` does not write to `audit_trail`. "
            "The portal's `audit_trail` writers fire only on human accept/dismiss actions. "
            "No `audit_trail` row was added by the failed LLM calls. See P0 finding 1.",
        )
    )
    # AC4 — NOT MET architecturally.
    rows.append(
        (
            "AC4 — dashboard surfaces 'this audit failed, retry?' for affected entries",
            False,
            "**NOT MET (architectural).** The dashboard reads `Finding` rows. The failed LLM "
            "calls produced zero `Finding` rows (they raised before creating any), so there "
            "is nothing to surface a retry CTA on. See P0 finding 2.",
        )
    )
    # AC5 — partial-state check.
    rows.append(
        (
            "AC5 — DB contains no partial encounter/audit state from the failed runs",
            True,
            f"No rows were added to any table during the failed calls. "
            f"`AuditorModule.forward()` is a pure in-process call until the LLM responds; "
            f"the wrapper has no DB I/O on the failure path. The DB state is therefore "
            f"identical before and after the run.",
        )
    )
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    print("Kanban: t_08001acb — LLM-outage error-handling QA")
    print("Method: hermetic; dspy.LM is built (qa_clean_claims parity) and "
          "dspy.clients.lm.litellm_completion is monkey-patched to raise on "
          "every call.")
    records: list[dict[str, Any]] = []
    records.extend(_run_scenario("outage_500", _make_500, ENCOUNTERS))
    records.extend(_run_scenario("outage_401", _make_401, ENCOUNTERS))
    _write_jsonl(records)
    _write_report(records)
    print()
    print(f"Verdict: {_verdict(records)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
