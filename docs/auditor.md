# Auditor agent

The auditor is the LLM-driven component of the ai-billing-audit
pipeline. Given a clinical encounter, a billed claim, and the payer
rules retrieved for the encounter, it returns a structured
discrepancy report.

The agent is implemented as a thin DSPy wrapper,
`ai_billing_audit.auditor_module.AuditorModule`, that composes a
single `dspy.Predict` step over the `AuditClaim` signature and
pins the global adapter to `dspy.JSONAdapter` so the LM is asked
to emit JSON matching the signature's typed outputs.

This page is the entry point for a new contributor wiring the
auditor into a pipeline. The module-level docstring in
`src/ai_billing_audit/auditor_module.py` is the in-repo API
reference; this page is the long-form, linkable version.

## Canonical call

```python
import dspy
from ai_billing_audit.auditor_module import AuditClaimInput, AuditorModule
dspy.configure(lm=dspy.LM("anthropic/claude-sonnet-4-5"))
auditor = AuditorModule()  # pins dspy.JSONAdapter() globally
result = auditor.forward(AuditClaimInput(
    clinical_note=note_text, billed_claim=claim_json, payer_rules=rules_text,
))
# result.has_discrepancy: bool  /  confidence_score: float  /  findings: list[str]
```

Two things to notice:

1. `dspy.configure(lm=...)` is called **before** `AuditorModule()`.
   The auditor does not configure a concrete LM; it expects the
   caller to do that at application startup so the same wrapper
   can be used in tests (with `dspy.utils.DummyLM`) and in
   production (with the real provider).
2. `AuditorModule()` pins `dspy.JSONAdapter` globally via
   `dspy.configure(adapter=...)`. You don't need to wire the
   adapter yourself; the constructor does it.

## Inputs and outputs

The wrapper's `forward` takes a single `AuditClaimInput` and
returns a `dspy.Prediction`.

### Inputs (on `AuditClaimInput`)

| Field           | Type  | Description                                                                                          |
| --------------- | ----- | ---------------------------------------------------------------------------------------------------- |
| `clinical_note` | `str` | The full clinical encounter note, as written by the provider. Verbatim.                              |
| `billed_claim`  | `str` | The claim being submitted (CPT/HCPCS + ICD-10-CM + modifiers + place of service + any other fields). |
| `payer_rules`   | `str` | The retrieved payer rules for this encounter, formatted as one rule per block.                       |

`AuditClaimInput` is a frozen dataclass; instances are immutable
and safe to share between threads.

### Outputs (attributes on the returned `dspy.Prediction`)

| Attribute           | Type        | Description                                                                       |
| ------------------- | ----------- | --------------------------------------------------------------------------------- |
| `has_discrepancy`   | `bool`      | `True` if the claim is not supported by the documentation under the rules.         |
| `confidence_score`  | `float`     | Calibrated confidence in `[0.0, 1.0]`.                                            |
| `findings`          | `list[str]` | One concise discrepancy statement per problem; empty list when no discrepancy.    |

## How `dspy.JSONAdapter` is configured

The adapter is pinned in `AuditorModule.__init__`:

```python
dspy.configure(adapter=dspy.JSONAdapter())
```

`dspy.configure` is idempotent — it replaces whichever adapter
was previously configured, so constructing two `AuditorModule`
instances in the same process is safe.

`dspy.JSONAdapter` accepts two optional kwargs:

- `callbacks` (`list[BaseCallback] | None`) — adapter event hooks.
  Default `None`.
- `use_native_function_calling` (`bool`) — `True` (default) asks
  providers that support tool/function calling to emit a structured
  call rather than a raw JSON string; `False` falls back to
  prompt-then-parse. Override only if a specific provider produces
  malformed function calls. The default works for Claude, OpenAI,
  Gemini, and the project's primary MiniMax-M3 backend.

## Migration: `dspy.Predict` to `dspy.ChainOfThought`

The wrapper uses `dspy.Predict` for speed. To trade latency for
higher-quality reasoning, change the `self.predict = ...` line in
`__init__`:

```python
class AuditorModule(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        dspy.configure(adapter=dspy.JSONAdapter())
        # Swap this:
        #   self.predict = dspy.Predict(AuditClaim)
        # For reasoning:
        self.predict = dspy.ChainOfThought(AuditClaim)
```

`dspy.ChainOfThought` adds a `reasoning` output field on top of
the signature's declared outputs, so the returned
`dspy.Prediction` gains a `reasoning` (`str`) attribute that
downstream code can log for audit trails. The three `AuditClaim`
outputs are unchanged.

### Perf/quality tradeoff

| Predict (default)            | ChainOfThought                                                   |
| ---------------------------- | ---------------------------------------------------------------- |
| 1 LM call per `forward`      | 1 LM call per `forward` (still one round-trip)                   |
| No reasoning preamble        | LM emits a reasoning block before the JSON outputs               |
| ~1x prompt token cost        | ~2x prompt token cost                                            |
| Lower latency                | ~1.5-2x latency                                                  |
| Weaker on ambiguous notes    | Stronger on borderline encounters (rule conflicts, partial docs) |
| Effect on clean-cut cases: small | Effect on clean-cut cases: small                              |

The wrapper is `Predict` by default because the auditor is the
slowest step in the pipeline and the cost of `ChainOfThought`
compounds across every encounter. Switch it on when
per-encounter quality matters more than throughput (e.g. on a
held-out eval run, or for high-stakes encounters flagged by a
pre-screen).

### Test impact

The contract tests in `tests/test_auditor_module.py` pin the
`Predict` shape. After swapping to `ChainOfThought`:

- `test_forward_returns_dspy_prediction_instance` still passes
  (CoT also returns a `dspy.Prediction`).
- The `test_forward_populates_*` tests still pass for the three
  declared `AuditClaim` outputs.
- `test_init_builds_a_predict_over_audit_claim` will **fail** —
  rename or relax it to assert `dspy.Predict.__mro__`-membership
  via `isinstance(module.predict, (dspy.Predict, dspy.ChainOfThought))`,
  or split it into two tests, one per strategy.
- `test_forward_passes_inputs_through_to_predict` will still pass
  (CoT also accepts the three input kwargs by name).
- `test_module_can_be_reimported_and_reinstantiated` will still
  pass.

## Testing

The wrapper is covered by 19 hermetic tests in
`tests/test_auditor_module.py`. They run against
`dspy.utils.DummyLM` with the `JSONAdapter` wired, so the full
DSPy `Predict -> JSONAdapter -> Prediction` round-trip is
exercised with no network calls and no API keys.

```bash
.venv/bin/pytest tests/test_auditor_module.py -v
```

## See also

- `src/ai_billing_audit/auditor_module.py` — module-level API
  reference (the docstring is the authoritative version of this
  page; this file mirrors it in long form).
- `src/ai_billing_audit/auditor_signature.py` — the `AuditClaim`
  signature that defines the inputs and outputs.
- `tests/test_auditor_module.py` — contract tests that pin the
  wrapper's behaviour.
- `prompts/auditor_v0.txt` — the bundled default system prompt
  used by the v0 baseline runner.
