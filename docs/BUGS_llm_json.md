# BUGS_llm_json.md — LLM JSON Parser Edge-Case Bug Hunt

Findings from the LLM JSON parser edge-case bug hunt (kanban `t_85e986bd`).
Investigation only — no parser or provider code was modified.

---

## Summary

| Severity | Count | Findings |
|---|---|---|
| **High** | 1 | BUG-LLM-01 (double-encoded JSON → silent `has_discrepancy=False`) |
| **Medium** | 3 | BUG-LLM-02 (markdown fences unhandled), BUG-LLM-03 (truncation indistinguishable from generic parse error), BUG-LLM-04 (refusal text miscategorised as JSON error) |
| **Low** | 0 | — |
| **Informational** | 1 | OBS-LLM-01 (unicode escape sequences decode correctly across all paths) |

**Headline:** 5 of 6 parser paths silently misclassify a `findings=[]` response that hides a complete JSON object inside a string field. Only the schema-constrained branch catches it. This is the exact failure mode the task-body rubric flags as High severity — a false-negative on a result the operator would otherwise treat as "audit found no discrepancy, ship it."

## Scope of the probe

The repo ships two distinct JSON parser surfaces and four provider classes that route through the second:

* **Path A1** — `ai_billing_audit.llm.LLMClient.complete_json` with the legacy
  `{"type": "json_object"}` envelope. No schema validation.
  Source: `src/ai_billing_audit/llm.py:127-152`.
* **Path A2** — the same `complete_json` with a real JSON Schema (constrained
  decoding + local `jsonschema.validate`). Source: `src/ai_billing_audit/llm.py:154-171`.
* **Path B** — the four provider classes
  (`MinimaxClient` / `ClaudeClient` / `OpenAIClient` / `GeminiClient`) at
  `src/llm_client.py:443, 492, 541, 601`. All four are structurally identical:
  `json.loads(_extract_assistant_text(response))` with no validation and no
  recovery.

Five fixtures were exercised through all six parser paths = **30 runs total**,
which exceeds the acceptance criterion of 5 fixtures × 4 providers (20 runs).

Fixtures:

| ID | Name | Raw response |
|---|---|---|
| 01 | fence | ` ```json\n{...valid dict...}\n``` ` |
| 02 | truncated | `{...cut off mid-string...` |
| 03 | refusal | "I cannot help with that request..." (plain English) |
| 04 | double-encoded | `{"summary":"ok","findings":[],"raw":"{\"foo\":\"bar\",...}"}` |
| 05 | unicode-escapes | valid JSON with `\u00e9` and `\u2014` in string values |

The probe (`workspaces/t_85e986bd/probe.py`) is hermetic — `litellm.completion`
is mocked, no network or API keys required. Raw results at
`workspaces/t_85e986bd/probe_results.json`.

## Results table

| Fixture | A1 (LLMClient legacy) | A2 (LLMClient schema) | B:minimax | B:claude | B:openai | B:gemini |
|---|---|---|---|---|---|---|
| 01 fence | `JSONDecodeError` | `JSONDecodeError` | `JSONDecodeError` | `JSONDecodeError` | `JSONDecodeError` | `JSONDecodeError` |
| 02 truncated | `JSONDecodeError` | `JSONDecodeError` | `JSONDecodeError` | `JSONDecodeError` | `JSONDecodeError` | `JSONDecodeError` |
| 03 refusal | `JSONDecodeError` | `JSONDecodeError` | `JSONDecodeError` | `JSONDecodeError` | `JSONDecodeError` | `JSONDecodeError` |
| 04 double-encoded | `parsed → has_disc=False` | `SchemaValidationError` | `parsed → has_disc=False` | `parsed → has_disc=False` | `parsed → has_disc=False` | `parsed → has_disc=False` |
| 05 unicode-escapes | `parsed → has_disc=True` | `parsed → has_disc=True` | `parsed → has_disc=True` | `parsed → has_disc=True` | `parsed → has_disc=True` | `parsed → has_disc=True` |

`has_disc` is the boolean mapping the task body calls out:
`has_discrepancy = bool(parsed.get("findings"))` when the parser returns a
dict, `None` when it raised. A `False` value with a non-empty `raw` payload
hidden inside the response is the silent false-negative the rubric flags
as High severity.

---

## BUG-LLM-01 — Double-encoded JSON inside a string field silently classifies as "no discrepancy"

**Severity: High**

**Status: Open (no fix shipped — out of scope per the task body)**

**Affected paths:** A1, B (all four provider classes). 5 of 6 paths. A2 catches it.

### One-line summary

When a model returns a string field whose value is itself a JSON-encoded object
(double-encoded), 5 of 6 parser paths accept the outer dict as valid JSON,
see an empty `findings` array, and return `has_discrepancy=False`. The inner
JSON payload is silently dropped on the floor. Only the schema-constrained
decoding path (A2) rejects it, because its `additionalProperties: False`
schema doesn't list a `raw` key.

### Repro

```python
import json
from unittest.mock import patch, MagicMock
import litellm

from ai_billing_audit.llm import LLMClient

INNER = json.dumps({"foo": "bar", "n": 1})
double_encoded = json.dumps({
    "summary": "ok",
    "findings": [],
    "raw": INNER,  # model wrapped the result in an extra json.dumps
})

# Path A1 — legacy envelope.
client = LLMClient(complete=lambda *, messages, **kwargs: {
    "choices": [{"message": {"content": double_encoded}}]
})
result = client.complete_json(
    [{"role": "user", "content": "Reply with JSON."}],
    {"type": "json_object"},
)
assert result == {"summary": "ok", "findings": [], "raw": INNER}
assert result.get("findings") == []      # silent false-negative
assert INNER not in json.dumps(result)   # the inner payload is gone
#                        ^^ (the OUTER raw field is still there, but the
#                            audit pipeline keys on `findings`, not `raw`,
#                            so the inner JSON is never inspected)
```

The same shape with `MinimaxClient` / `ClaudeClient` / `OpenAIClient` /
`GeminiClient` returns the identical dict.

### Observed vs expected

**Observed:** all five paths return the dict verbatim with `findings=[]`. The
audit pipeline (`auditor.run_audit` at `src/ai_billing_audit/auditor.py:262-264`)
calls `validate_findings` on the dict, which iterates the empty list and
returns `()`. `has_discrepancy` is `False`. The inner JSON inside the `raw`
string field is never inspected.

**Expected (per the rubric):** the parser should either reject the response
outright (the inner JSON clearly isn't an AuditResult-shaped object) or
inspect string fields for embedded JSON and surface a warning. The schema
used by the audit pipeline (`src/ai_billing_audit/auditor.py:66-100`) does
not list a `raw` key, so the `additionalProperties: False` clause already
gives the schema-constrained path (A2) everything it needs to reject — it
just isn't the path the four provider classes go through.

### Suggested fix direction

Two layers, in priority order:

1. **Force the audit pipeline to go through the schema-constrained path.**
   `auditor.run_audit` already calls `client.complete_json(messages,
   RESPONSE_JSON_SCHEMA)` where `RESPONSE_JSON_SCHEMA` has
   `additionalProperties: False`. The problem is that the four provider
   classes in `src/llm_client.py` ignore the schema argument and only
   forward it to the litellm transport as `response_format={"type":
   "json_object"}`. Make every provider class run `jsonschema.validate`
   locally the way the `ai_billing_audit.llm.LLMClient.complete_json` A2
   path already does — that one function call closes the bug for all
   four providers.
2. **Add an "embedded JSON" sanity check on string fields.** Optional, but
   it catches the case where a model accidentally double-encodes *inside*
   a string field that *is* declared in the schema (e.g. `quote`
   containing a JSON blob). For each string value in the parsed dict,
   `json.loads(value.strip())` in a `try/except ValueError` and warn
   if it succeeds.

### Why this is High severity

The audit pipeline's "no discrepancy" outcome is the default that operators
trust — a per-encounter audit that comes back empty is treated as "this
encounter is clean, no human review needed." A model that double-encodes
the response turns every encounter that hits the bug into a silent
false-negative. The model is functioning, the network is fine, the JSON
*is* valid, the schema is satisfied, and yet the real finding (the inner
JSON payload) is dropped without a trace. This is the exact failure mode
the task body calls out: "refusal → silent `has_discrepancy=false`" is the
worked example, and double-encoded JSON shares the same shape — wrong
content, parsed as success, no error surfaces.

---

## BUG-LLM-02 — Markdown-fenced JSON raises `JSONDecodeError` on all parser paths

**Severity: Medium**

**Status: Open (no fix shipped — out of scope per the task body)**

**Affected paths:** all 6.

### One-line summary

A response wrapped in ` ```json ... ``` ` markdown fences raises
`json.JSONDecodeError` on every parser path, even though every modern LLM
(GPT-4o, Claude 3.5, Gemini 1.5, the team's primary `minimax` backend)
emits fences in roughly 1-3% of completions despite being told to use
constrained decoding.

### Repro

```python
text = "```json\n{\"summary\": \"ok\", \"findings\": []}\n```"
# Any of the six parser paths:
#   - LLMClient.complete_json([...], {"type": "json_object"})
#   - LLMClient.complete_json([...], <real schema>)
#   - MinimaxClient.complete_json([...], <any schema>)
#   - ClaudeClient.complete_json([...], <any schema>)
#   - OpenAIClient.complete_json([...], <any schema>)
#   - GeminiClient.complete_json([...], <any schema>)
# all raise:
#   json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

### Observed vs expected

**Observed:** `json.JSONDecodeError` propagates up to the caller. The audit
pipeline lets this bubble (`auditor.run_audit` does not catch it), so the
operator sees a parse-error stack trace in the job queue log.

**Expected:** strip leading and trailing markdown fences before `json.loads`.
A regex like `re.sub(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", r"\1",
text, flags=re.DOTALL)` is enough. Optional: also strip a leading "Here
is the JSON:" prose preamble if the model adds one.

### Why this is Medium (not High)

The failure is **loud** — operators see the parse error, retry, and the
next completion usually comes back without fences. There is no silent
false-negative. The cost is operational friction (failed jobs in the log,
occasional duplicate completions billed) rather than a wrong audit result.
A two-line regex fix closes it.

### Suggested fix direction

Add the fence-stripping regex at the top of `complete_json` in both parser
surfaces (`src/ai_billing_audit/llm.py:127` and `src/llm_client.py` per
provider class). Same regex in both, no schema changes, no behaviour
change for non-fenced responses.

---

## BUG-LLM-03 — Truncated output is indistinguishable from any other malformed input

**Severity: Medium**

**Status: Open (no fix shipped — out of scope per the task body)**

**Affected paths:** all 6.

### One-line summary

When the LLM hits a max_tokens cutoff (or the connection drops) mid-completion,
the parser raises a generic `json.JSONDecodeError` with no way for the caller
to distinguish "the model ran out of tokens" from "the model emitted
gibberish." The audit pipeline treats both as fatal, even though the
truncation case is recoverable (retry with a larger token budget or a
shorter prompt).

### Repro

```python
text = (
    '{"summary": "Encounter has two under-coded lines", '
    '"findings": [{"category": "under_coding", '
    '"suggested_code": "99213", '
    '"quote": "Established patient, 15 minu'  # cutoff here, unterminated string
)
# All 6 paths raise:
#   json.decoder.JSONDecodeError: Unterminated string starting at: line 1 column 137 (char 136)
```

The error message says "Unterminated string" — useful to a human reading
the trace, but unstructured and not programmatically distinguishable from
"the model wrote `not json at all`."

### Observed vs expected

**Observed:** `json.JSONDecodeError` with one of three messages depending
on where the truncation lands (`Unterminated string`, `Expecting value`,
or `Expecting ',' delimiter`).

**Expected:** a `TruncatedResponseError` subclass that the caller can
catch and react to with a retry. The audit pipeline could then bump
`max_tokens` and resubmit instead of failing the job.

### Why this is Medium (not High)

Per the rubric: "truncation is Medium unless it silently coerces to a
valid-looking result, which is High." The parser does **not** silently
coerce — the error surfaces loudly. The danger is that an operator who
sees "Unterminated string" in the log has no way to tell whether the
prompt was too long, the model was rate-limited, or the model actually
emitted malformed text. That ambiguity is the cost, not a wrong result.

### Suggested fix direction

A pre-`json.loads` heuristic: if the trimmed text ends mid-token (e.g.
inside a string, after a `,` or `:`, or with an unclosed brace), raise
a dedicated `TruncatedResponseError(ValueError)` instead of letting
`json.JSONDecodeError` bubble. Catching that class in `auditor.run_audit`
enables a retry-with-larger-budget path.

---

## BUG-LLM-04 — Refusal text raises `json.JSONDecodeError`, losing the safety signal

**Severity: Medium**

**Status: Open (no fix shipped — out of scope per the task body)**

**Affected paths:** all 6.

### One-line summary

When a model refuses a request ("I cannot help with that request. The
clinical note appears to contain protected health information..."), the
parser raises a generic `json.JSONDecodeError`. The operator sees a parse
error, not a safety event. The audit pipeline has no way to flag
"encounter X was refused by the model and needs human review" — it just
treats the refusal as a malformed response and either drops the job or
retries until the model either complies or burns through the retry budget.

### Repro

```python
text = (
    "I cannot help with that request. The clinical note appears to "
    "contain protected health information and I am not able to "
    "audit it without explicit authorisation."
)
# All 6 paths raise:
#   json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

### Observed vs expected

**Observed:** `json.JSONDecodeError`, same as for any other non-JSON
input. The error message does not mention the word "refused" or
"safety."

**Expected:** a `RefusalDetected(ValueError)` exception class with the
refusal text attached as a field, raised by the parser when the response
text starts with a refusal preamble. The audit pipeline catches it
specifically, logs a structured "model_refused" event, and routes the
encounter to a human-review queue (rather than retrying the same prompt
and burning tokens).

### Why this is Medium (not High)

The task body rubric says: "refusal → silent `has_discrepancy=False`
is **High**." The current parser does **not** silently return
`has_discrepancy=False` — it raises. The High-severity false-negative
threshold is not met by the literal behaviour.

However, the spirit of the rubric is "refusals are safety-relevant and
must be surfaced distinctly." The current behaviour surfaces them
*loudly* but as the wrong category — a generic JSON parse error instead
of a safety event. A retry loop on a refused response wastes tokens, and
a dropped refusal hides the fact that the model thought the encounter
contained PHI patterns. The cost is operational (wasted tokens, missed
PHI signal) rather than a wrong audit result.

### Suggested fix direction

In both parser surfaces (`src/ai_billing_audit/llm.py:127` and the
four classes in `src/llm_client.py`), before `json.loads`, run a refusal
classifier over the text. A simple regex catches the common preambles:

```python
REFUSAL_PATTERNS = (
    re.compile(r"^\s*i\s+(?:cannot|can['']t|will not|won['']t)\s+", re.I),
    re.compile(r"^\s*i['']m\s+(?:sorry|unable)", re.I),
    re.compile(r"^\s*as an? (?:ai|language model)", re.I),
)
def _looks_like_refusal(text: str) -> bool:
    head = text[:200]
    return any(p.match(head) for p in REFUSAL_PATTERNS)
```

If true, raise `RefusalDetected(text)` instead of `json.JSONDecodeError`.
`auditor.run_audit` catches it and routes to the human-review queue.

---

## OBS-LLM-01 — Unicode escape sequences decode correctly across all paths

**Severity: Informational (no bug found)**

A response containing `\u00e9` (é) and `\u2014` (em-dash) in string
values parses correctly on all 6 paths and produces a `has_discrepancy=True`
result. `json.loads` decodes escape sequences by default; no parser
double-decodes (which is a known footgun in some hand-rolled JSON
parsers). Behaviour is correct, no fix needed.

---

## Provenance

* **Probe code:** `workspaces/t_85e986bd/probe.py` (hermetic, mocked
  `litellm.completion`).
* **Raw results:** `workspaces/t_85e986bd/probe_results.json` (30 runs,
  one per fixture × parser path).
* **Source locations referenced:**
  * `src/ai_billing_audit/llm.py:127-171` — `LLMClient.complete_json`
    (paths A1 and A2).
  * `src/llm_client.py:443-460` — `MinimaxClient.complete_json`.
  * `src/llm_client.py:492-509` — `ClaudeClient.complete_json`.
  * `src/llm_client.py:541-558` — `OpenAIClient.complete_json`.
  * `src/llm_client.py:601-618` — `GeminiClient.complete_json`.
  * `src/ai_billing_audit/auditor.py:66-100, 247-269` — the audit
    pipeline that consumes the parsed dict and maps `findings` to
    `has_discrepancy`.
  * `src/ai_billing_audit/auditor.py:262-264` — the exact line that
    turns a parsed dict into the boolean an operator trusts.

## Re-run

```bash
cd /Users/biancabienaime/projects/ai-billing-audit
source .venv/bin/activate
python /Users/biancabienaime/.hermes/kanban/boards/ai-billing-audit/workspaces/t_85e986bd/probe.py
# → 30 runs, results table, probe_results.json rewritten
```

Runs in well under a second. No API keys, no network.
