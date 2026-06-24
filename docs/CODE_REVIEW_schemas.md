# Code review: `encounter_schema.py` + `demo_entries.py` + `demo_registry.py`

**Reviewer.** Default Hermes worker, dispatched via the
`ai-billing-audit` kanban board (task `t_783eb181`).

**Scope (read-only).** Three source files, no source modifications:

- `src/ai_billing_audit/encounter_schema.py` (217 lines) — JSON-schema
  for synth-agent-emitted encounters + the `validate_encounter` function
- `src/ai_billing_audit/demo_entries.py` (91 lines) — three
  `register_demo_encounter(...)` calls, one per difficulty tier
- `src/ai_billing_audit/demo_registry.py` (113 lines) — the
  in-process registry, JSON loader, and `DemoEncounter` dataclass

Cross-referenced but not modified: `src/ai_billing_audit/synth/render.py:1-179`,
`src/ai_billing_audit/synth/template.py:1-87`, `src/ai_billing_audit/synth/content_table.py`,
`src/ai_billing_audit/api.py:46-49, 61, 180-268`, `data/val.json:1-50`,
`data/train.json:1-100`, `tests/test_dashboard.py`, `tests/test_synth_purity.py`,
`docs/CODE_REVIEW_tests.md:339-345`.

## Spec basis — what these three files are meant to do

The three files are not a self-contained triad; they form one
corner of a two-shape data architecture the rest of the pipeline
already commits to:

1. **Synth-agent emission shape** — every encounter produced by
   `synth_agent.generate_encounter(tier, variant, seed)` matches
   `encounter_schema.ENCOUNTER_SCHEMA` (the
   `encounter_id / difficulty_tier / flagged / trigger_reason /
   provider_note / icd10_codes / cpt_codes` dict).
2. **Training-data shape** — every record in `data/train.json` and
   `data/val.json` matches the training-data shape
   (`encounter_id / is_flagged / clinical_note / claim / rules /
   ground_truth`).

`encounter_schema.py` is the format spec for shape 1 and only shape 1.
`demo_entries.py` + `demo_registry.py` operate on shape 2 — they
register three training-data records (enc_10032, enc_0007, enc_0000)
and the dashboard (`api.py:180-268`) reads them straight from
`data/*.json` via `load_encounter_record(...)` and renders them.
`validate_encounter()` is **never called by any consumer in the
codebase** (verified by `rg "validate_encounter\("` — only the
defining module and a passing reference in
`docs/CODE_REVIEW_tests.md:344`); the auditor, the smoke tests, the
dashboard, and the synth renderers all rely on the synth renderer
producing the right shape by hand and on the training-data records
being pre-validated at generation time.

This is the most important thing to understand before the findings
below: many of the questions the brief asks about "the demo fixtures
validating against the schema" have a negative answer by design, not
by accident. The brief, however, asks us to flag the drift, so
finding 1 below does.

## Findings at a glance

| #  | Sev      | File:line                                 | Finding                                                                                                                                                                                  |
|----|----------|-------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1  | Critical | `encounter_schema.py:55-125`              | The three registered demos (enc_10032, enc_0007, enc_0000) are training-data records (`is_flagged`/`clinical_note`/`claim`/`rules`/`ground_truth`) and **do not validate** against `ENCOUNTER_SCHEMA`. The schema targets a different shape (synth-agent output) than what the dashboard renders. Brief asks us to flag this; the broader question of whether the dashboard *should* render training-data records vs. synth-agent-emitted ones is out of scope. |
| 2  | Major    | `encounter_schema.py:55-217`              | `validate_encounter()` is defined and exported but **has zero call sites anywhere in the application code, the test suite, or the synth pipeline** (verified by repo-wide ripgrep). It is dead-on-arrival in the current code path: a future schema regression would be caught by nothing. |
| 3  | Major    | `synth/render.py:135` + `synth/content_table.py` | The third HARD scenario has `icd10_chronic_a == icd10_acute == "M17.11"`. The renderer emits `[chronic_codes[0], acute_code]` = `["M17.11", "M17.11"]` — duplicate ICD-10 codes — for **17/50 HARD/clean seeds and 13/50 HARD/flagged seeds**. The schema does not enforce `uniqueItems` (it only enforces `minItems: 1`), so this passes; the spec contract at `render.py:129-135` says "two distinct ICD-10 codes," and there is no test enforcing that ("test_hard_dual_problems_with_chronicity" is referenced in a code comment but does not exist in the suite). |
| 4  | Major    | `encounter_schema.py:61-69`               | `difficulty_tier` is `required` and must be `EASY`/`MEDIUM`/`HARD`, but the regex/pattern checks (lines 166-191) live in the post-schema Python validator. The two-tier split (schema for shape, validator for codes) is intentional, but several *schema-level* invariants are also enforced only in Python (e.g. `prescription_drug_management` for MEDIUM, the `surgery_with_global_period`/E/M cross-check at line 201) — the comment at line 193-200 admits the modifier-25/global-period audit rule is *not* enforced by the schema at all. |
| 5  | Major    | `encounter_schema.py:55-125`              | `additionalProperties: False` is set on the root and on `cpt_codes` items, but `provider_note` is missing the `pattern`/`format` on `hpi`/`exam`/`mdm` — a single whitespace string passes `minLength: 1`. A "HPI: ." encounter would validate. |
| 6  | Minor    | `encounter_schema.py:182-191`             | The validator only complains about *unknown* modifiers when `modifier` is non-null; a *missing* modifier on a HARD-tier post-op window is the *actual* modifier-25 audit error the brief calls out (line 193-200 admits this is not the schema's job), and is correctly delegated to the auditor — but the schema-level message is misleading ("Modifier -25 / global period audit rule is NOT enforced by the schema" lives in a code comment, not the docstring). |
| 7  | Minor    | `encounter_schema.py:74`                  | `encounter_id` regex `^enc_[a-zA-Z0-9_]+$` allows trailing-underscore ids like `enc_foo_`. Most synthesizers emit `enc_synth_<tier>_<variant>_<8hex>` so this is theoretical, but no anchor at end forces a non-empty suffix. |
| 8  | Minor    | `encounter_schema.py:46-52`               | The `_KNOWN_MODIFIERS` set is a closed allow-list at the time of writing (82 entries). New CMS modifiers added after 2024 will be silently rejected by the validator. There is no version stamp and no source-of-truth link to the CMS HCPCS quarterly update. |
| 9  | Minor    | `encounter_schema.py:128-138`             | `EncounterValidationError.errors` is `list[str]` (human-readable strings), not structured (`{path, code, message}` dicts). A future `auditor_agent` that wants to programmatically map each error to a fix-up action (e.g. "auto-add a default E/M 99213 if missing") will have to re-parse the strings. |
| 10 | Minor    | `encounter_schema.py:160-162`             | `validator.iter_errors(payload)` is collected with `key=lambda e: e.path`, but `e.path` is a `deque` — comparison is element-by-element, which works but is non-obvious. A future maintainer sorting on `e.absolute_path` (a `deque` of strings) would get a different ordering. |
| 11 | Minor    | `demo_entries.py:31-39`                   | `enc_10032` (EASY) has `claim.cpt_codes: []` and `claim.icd10_codes: []` — empty claim arrays. The dashboard's encounter-detail page passes `record.get("claim", {})` to the template (api.py:241); an empty `{"cpt_codes": [], "icd10_codes": []}` may render as "(none)" or a blank panel depending on the template's defensive default. |
| 12 | Minor    | `demo_entries.py:1-91`                    | The EASY summary ("single rule, evidence quote appears verbatim in the clinical note") describes the audit-panel UX, not the encounter itself. A reader using these summaries to triage a multi-finding audit will get the right answer; a reader using them to understand the underlying encounter won't. Cosmetic. |
| 13 | Minor    | `demo_registry.py:91-113`                 | `load_encounter_record(...)` is **not** deterministic by user/session — it returns the first matching record by encounter_id from `val.json` then `train.json`. There is no user-facing selection function at all (the index page at `api.py:185-207` calls `list_demo_encounters()` and emits whatever was registered at import time, in registration order). For a 3-entry demo this is the right shape; if the registry ever grows past ~6 entries, an "I want a random EASY one" or "I want the third HARD one" UX request will need a separate selection surface. |
| 14 | Minor    | `demo_registry.py:51-75`                  | `_REGISTRY` is a module-level list mutated by `register_demo_encounter(...)`. Concurrent registration (e.g. two sibling workers racing at import time) is not protected. Today's callers all run at app-import time, single-threaded, so this is theoretical; a future async registrar or test that calls `register_demo_encounter` from two threads would race. |
| 15 | Minor    | `demo_registry.py:99-110`                 | The lazy-load cache (`getattr(load_encounter_record, "_cache", {})`) pins the JSON file mtime to "first read." If a staff user drops a new `train.json` while the dashboard is running (the live deploy does not, but the dev flow does), the in-process cache will not pick it up until restart. No cache-invalidation hook. |
| 16 | Minor    | `demo_registry.py:35`                     | `_DATA_DIR = (Path(__file__).resolve().parent.parent.parent / "data").resolve()` — three levels up assumes a fixed install layout. If the package is ever vendored or installed in editable mode with a non-standard `src/` depth, the loader will silently return no records (every record lookup returns `None`, every encounter-detail page 404s, no error in the log). |
| 17 | Minor    | `encounter_schema.py:1-18`                | Module docstring says "consumed by the rest of the audit pipeline" — `validate_encounter` is **never called by the rest of the audit pipeline** (finding 2). The docstring is out of date. |
| 18 | Nit      | `encounter_schema.py:89`                  | `patient.age` is bounded `[0, 130]`. Newborns are `0`; a 131-year-old patient is rejected. 130 is generous; could be 125 (oldest verified human lifespan). Cosmetic. |
| 19 | Nit      | `encounter_schema.py:90`                  | `patient.sex` enum is `["M", "F", "O"]` — `"O"` for "other" / "non-binary" is non-standard; the HL7 FHIR `AdministrativeGender` code is `male / female / other / unknown`. `"U"` (unknown) is missing. Cosmetic; depends on jurisdiction (US payers use `M`/`F`/`U`, Canadian provinces allow `X` for health card). |
| 20 | Nit      | `demo_entries.py:19`                     | The module imports `register_demo_encounter` from `demo_registry` but also re-exports nothing via `__all__`. Cosmetic; matches a deliberate "side-effect import only" pattern the module docstring spells out. |
| 21 | Nit      | `demo_registry.py:46`                    | `_Difficulty = str  # "EASY" | "MEDIUM" | "HARD"` — the type alias is a bare `str`; the real constraint is enforced at runtime in `register_demo_encounter` (line 64). A typed enum (`class Difficulty(str, Enum)`) would give mypy a chance to flag a typo at a sibling-worker's call site. |
| 22 | Nit      | `demo_registry.py:68-70`                 | Idempotency check is O(n) per call (`for existing in _REGISTRY`). For 3 entries this is fine; for 1000+ entries (a "scaled" demo would be the use case) a `dict[encounter_id, DemoEncounter]` would be O(1). The brief calls this a "registry" not a "ledger," so linear is acceptable, but worth a note. |

Severity legend: **Critical** = incorrect behaviour on common
inputs / data-flow misalignment; **Major** = correctness gap on a
documented spec contract or materially incomplete coverage;
**Minor** = maintainability issue that does not break the happy
path; **Nit** = style/clarity.

## Brief questions, answered directly

### Q1. Which required fields are enforced at the JSON-schema level vs. only at the validator-function level, with file:line references?

**JSON-schema level (enforced by `ENCOUNTER_SCHEMA` at
`encounter_schema.py:55-125`):**

- `encounter_id` — string, `minLength: 1`, pattern `^enc_[a-zA-Z0-9_]+$` (line 71-75)
- `difficulty_tier` — string, enum `EASY|MEDIUM|HARD` (line 76-79)
- `flagged` — boolean (line 80)
- `trigger_reason` — string, `minLength: 1` (line 81-84)
- `provider_note` — object, `additionalProperties: False`, `required: [hpi, exam, mdm]`, each with `minLength: 1` (line 93-102)
- `icd10_codes` — array, `minItems: 1`, items `string` (line 103-107)
- `cpt_codes` — array, `minItems: 1`, items `{code: string, modifier?: string, global_period_days?: integer}` (line 108-121)
- `patient.age` — integer `[0, 130]` (line 89)
- `patient.sex` — enum `M|F|O` (line 90)

**Validator-function level (enforced by `validate_encounter(...)` at
`encounter_schema.py:146-217`):**

- ICD-10 code regex `_ICD10_RE` (line 37, applied at line 168-171) —
  the JSON schema only requires the value to be a string; the
  ICD-10 shape check lives in Python
- CPT/HCPCS code regex `_CPT_RE` (line 41, applied at line 178-181)
  — JSON schema only requires the value to be a string
- CPT modifier allow-list `_KNOWN_MODIFIERS` (line 46-52, applied at
  line 188-191) — JSON schema allows any string
- Modifier type check (line 184-187) — JSON schema allows any value
  for `modifier` (not even a `type: string` constraint)
- Cross-field check `surgery_with_global_period → at least one 992xx
  E/M line` (line 201-211) — not expressible in JSON schema

**Deliberately NOT enforced anywhere (the comment at
`encounter_schema.py:193-200` is explicit):**

- The HIGH-severity finding the brief calls out — modifier 25 missing
  on a HARD fixture with surgery in a global period. The comment
  says: "the modifier-25 / global-period audit rule is NOT enforced
  by the schema. The schema validates the structural shape of the
  encounter; whether a flagged HARD fixture has the modifier
  correctly applied or not is the auditor's job to detect, not the
  schema's."

The split is reasonable: shape constraints go in the JSON schema;
code-format constraints (regex-enforced codes, modifier allow-lists)
go in Python because the regex is awkward to embed in a JSON-schema
`pattern`. The cross-field surgery/E/M check is genuinely
cross-field, and JSON-schema 2020-12 supports `if/then/else` for
exactly this — it would be cleaner to lift it into the schema than
keep it in the validator. The modifier-25 rule is the auditor's
business, but the comment should move from `validate_encounter` to
the module docstring so a future maintainer looking at the schema
for "what rules does this enforce?" gets the right answer without
scrolling.

### Q2. Per-demo assessment of whether it is real-looking clinical content or a placeholder stub

All three demos load from `data/val.json` / `data/train.json` and
are real-looking, hand-authored clinical content — none are
placeholder stubs:

**enc_10032 (EASY, `demo_entries.py:31-39`, source
`data/val.json`):**

- Clinical note (117 chars): `"Duplicate service on same date. Patient seen for annual wellness visit and a separate sick visit billed the same day."`
- Plausible real-world scenario (AWV + sick-visit same-day billing
  is a Medicare-targeted duplicate flag, exactly the kind of
  finding an audit tool would surface).
- Claim `cpt_codes: []`, `icd10_codes: []` — empty. The
  "duplicate service" semantics do not require a specific code
  to be billed; the rule fires on *both* visits being billed on
  the same date, and the suggested action is `DENY`. The empty
  arrays are a faithful representation of "the claim-as-billed
  is the duplicate set," but a dashboard reading
  `record.get("claim", {})` and rendering `claim.cpt_codes`
  may show an empty list. See finding 11.
- 1 ground-truth finding (`gt0`), severity `high`, evidence quote
  `"duplicate service on same date"` is a verbatim substring of
  the clinical note. Highlight will work.

**enc_0007 (MEDIUM, `demo_entries.py:52-61`, source
`data/train.json`):**

- Clinical note (118 chars): `"Type 2 diabetes follow-up. HbA1c drawn; result pending. Influenza vaccine administered. Essential hypertension stable."`
- Plausible. Two chronic problems (T2DM, essential HTN), one
  acute procedure (flu vaccine), one lab (HbA1c).
- Claim: CPT `83036` (HbA1c), `90686` (quadrivalent IIV4
  preservative-free flu vaccine — actually, 90686 is the
  cell-culture IIV4, which is correct for a 2024+ encounter);
  ICD `E11.9` (T2DM without complications), `I10` (essential
  HTN). All codes are real, currently billable, and consistent
  with the note.
- 4 ground-truth findings, severities (1 medium, 3 low), 4
  distinct categories. All 4 evidence quotes are verbatim
  substrings.

**enc_0000 (HARD, `demo_entries.py:81-91`, source
`data/train.json`):**

- Clinical note (250 chars): `"Patient presents for established patient moderate complexity. ECG performed in office due to palpitations reported. Documentation supports a separately identifiable E/M; modifier 25 applied. Lipid panel ordered for cardiovascular risk stratification."`
- Plausible. Moderate-complexity established-patient E/M with an
  in-office ECG, palpitations (R00.2), modifier 25 applied
  correctly (this is the clean variant), and a lipid panel.
- Claim: CPT `99214` (established patient, moderate complexity),
  `93000` (12-lead ECG, complete), `80061` (lipid panel). ICD
  `R00.2` (palpitations). All codes are real, billable, and
  consistent with the note.
- 5 ground-truth findings, severities (1 high, 2 medium, 1 low,
  1 info), 5 distinct categories. The HIGH finding is the
  modifier-25 rule (`rule_modifier_25_001`) with the evidence
  quote `"separately identifiable E/M"` — a verbatim substring.
  All other 4 quotes are also verbatim substrings.

**No placeholders or lorem-ipsum strings were detected** in any of
the three clinical notes (verified by scanning for `TODO`, `TBD`,
`TBA`, `lorem`, `ipsum`, `placeholder`, `FIXME`, `XXX`, `???`,
`null`, `N/A`).

**No timestamps or provider names** appear in the data shape (no
`date`, `timestamp`, `provider`, `clinician`, or `physician` keys
in any of the three records). The brief asks about "plausible
… providers, timestamps" — the data shape does not carry them.
This is a property of the training-data shape, not a defect in
`demo_entries.py` (which only registers the encounter_id /
difficulty / summary triple, and the actual record is loaded from
disk at request time).

### Q3. The selection mechanism in `demo_registry.py` — is it deterministic (hash of user/session), random, round-robin, or fixed?

**Fixed / registration-order, with deterministic load-by-id.**

- The `_REGISTRY` list (`demo_registry.py:51`) is appended to in
  `register_demo_encounter(...)` at line 71-75. The
  `list_demo_encounters()` accessor (line 78-80) returns
  `list(_REGISTRY)` — i.e. a copy in registration order. There is
  no shuffle, no sort, no hash, no user input, no time input.
- The dashboard's index page (`api.py:185-207`) calls
  `list_demo_encounters()` and renders the cards in that order.
  With the current 3 entries (EASY registered first, MEDIUM
  second, HARD third) the page always shows EASY → MEDIUM → HARD
  in that order on every request.
- `get_demo_encounter(encounter_id)` (line 83-88) is a linear
  scan by `encounter_id` — also fully deterministic.
- `load_encounter_record(encounter_id)` (line 91-113) looks up
  the record in `val.json` first, then `train.json`, and returns
  the first match. The lookup is by `encounter_id` only — no
  user/session/timestamp/seed input.

**UX recommendation.** For a 3-entry demo, registration-order
fixed is the correct choice: the index page is meant to teach a
new user what each difficulty band looks like, and the EASY →
MEDIUM → HARD ordering is the natural reading order. If the
registry ever grows past ~6 entries, the right next step is to
add a `Difficulty` filter (so the index page becomes "show me
EASY encounters" / "show me HARD encounters") rather than
introduce randomness — a random selection would break the
teaching/eval use case the current ordering supports. A
"surprise me" or "random encounter" UX would be a *separate*
selector function, not a change to `list_demo_encounters()`.

### Q4. Schema-vs-demo mismatches (demos that would fail validation)

The three registered demos would **all fail** `validate_encounter()`
on the synth-agent's schema. This is by design, not by accident
— the data files are a different shape from the schema. The
schema validates the synth-agent's *emitted fixture*; the
registry's `load_encounter_record(...)` returns the raw
training-data record (the *input* the audit pipeline consumes,
not the output the synth-agent produces).

Concretely, the validation errors for each demo (run locally with
the schema code):

- `enc_10032` (data shape): missing required field `difficulty_tier`
  (it's a difficulty tag in the registry, not a field on the
  record). Missing required fields `flagged`, `trigger_reason`,
  `provider_note`, `icd10_codes`, `cpt_codes`. Has unknown
  fields `is_flagged`, `clinical_note`, `claim`, `rules`,
  `ground_truth` (rejected by `additionalProperties: False` at
  the root).
- `enc_0007`, `enc_0000`: same as above.

The brief explicitly asks us to call this out. The deeper
question — *should* the dashboard render training-data records
or synth-agent-emitted records? — is out of scope per the
brief. But two things follow from the answer:

1. The relationship between "the demos" and "the schema" is
   indirect. The schema is a *test fixture shape* the synth
   pipeline validates its own output against (and currently
   nobody — see finding 2). The demos are *production data
   records* the dashboard renders directly. A reader of the
   review who is looking for "is there a drift between the
   data we render and the schema we validate against?" will
   reasonably say "yes, but they're different things."
2. The `encounter_id` pattern at `encounter_schema.py:74`
   (`^enc_[a-zA-Z0-9_]+$`) would *not* match the data-file
   ids (`enc_10032`, `enc_0007`, `enc_0000`) by accident — the
   patterns do happen to match in this case. If a future
   demo wants an id like `enc_2025-01-15-001`, the dash will
   fail the regex (no dash in `[a-zA-Z0-9_]`). Worth knowing
   for the next sibling worker.

## Detailed findings

### 1. Critical — Training-data demos do not validate against the synth-agent schema

The three registered demos (`enc_10032`, `enc_0007`, `enc_0000`)
are training-data records loaded by `load_encounter_record(...)`
from `data/val.json` and `data/train.json`. Their shape is
`{encounter_id, is_flagged, clinical_note, claim, rules,
ground_truth}`. The synth-agent's `ENCOUNTER_SCHEMA` requires
`{encounter_id, difficulty_tier, flagged, trigger_reason,
provider_note, icd10_codes, cpt_codes, ...}`. The two shapes
have only `encounter_id` in common.

This is **by design** — the schema is a format spec for the
synth-agent's emitted fixtures (see `synth/render.py:7-9` and
`synth/template.py:69-80`), and the training-data records are a
different shape consumed by a different layer of the pipeline.
The brief asks us to flag the drift, so it is flagged here.

**Suggested fix (out-of-scope per brief, recorded for the next
sibling):** Either (a) document the two-shape architecture
explicitly in `encounter_schema.py`'s module docstring and in
`demo_registry.py`'s module docstring, so the next reader
doesn't have to deduce it from the call sites, or (b) write a
*separate* schema for the training-data shape (e.g.
`training_data_schema.py`) and have
`load_encounter_record(...)` validate each record against it at
load time. Option (a) is one paragraph; option (b) closes a
real gap (no test asserts the training-data records match the
shape the auditor assumes).

### 2. Major — `validate_encounter()` is dead-on-arrival

Repo-wide search for `validate_encounter(` returns only the
defining module and a passing reference in
`docs/CODE_REVIEW_tests.md:344`. It is not called by:

- The synth-agent renderer (`synth/render.py:1-179`). The
  module docstring at line 9-12 *says* "validation is the
  consumer's job" — and the only consumer in
  `synth/render.py:11-12` is the auditor and the cross-provider
  smoke tests, neither of which actually invokes it.
- The auditor (`auditor.py`, `auditor_module.py`,
  `auditor_signature.py`). Verified by ripgrep.
- The dashboard (`api.py:46-49, 180-268`). The dashboard
  reads the *training-data shape* via
  `load_encounter_record(...)` and never touches the synth
  shape.
- The test suite (`tests/test_dashboard.py`,
  `tests/test_synth_purity.py`). `test_synth_purity.py:211`
  asserts `enc["encounter_id"].startswith("enc_synth_")` —
  this is a *prefix check*, not a schema validation.

The module docstring at `encounter_schema.py:1-18` says
"consumed by the rest of the audit pipeline." It is not.
The function is exported, well-documented, and untested in
the running application.

**Suggested fix (out-of-scope per brief, recorded for the next
sibling):** Add a single integration test in
`tests/test_dashboard.py` (or a new `test_synth_validation.py`)
that calls `generate_suite()` (3 tiers × 2 variants × N seeds)
and asserts every emitted encounter passes
`validate_encounter()`. The CODE_REVIEW_tests review at
`docs/CODE_REVIEW_tests.md:339-345` already identified this gap
as G-3 (Low); the current review bumps it to Major because the
gap is wider than the earlier review estimated — there is no
test, but there is also no consumer. The dead code is harmless
in the happy path (the synth renderers do produce the right
shape by hand) and silently wrong in the regression path
(someone refactors the renderer to add a new field without
updating the schema, and no test catches it).

### 3. Major — Third HARD scenario emits duplicate ICD-10 codes for 17/50 clean and 13/50 flagged seeds

The third entry in `_HARD_SCENARIOS` has
`icd10_chronic_a == icd10_acute == "M17.11"` (left knee OA in
both slots, with `icd10_chronic_b = "E11.9"` for T2DM). The
renderer at `synth/render.py:135` sets
`icd10 = [chronic_codes[0], acute_code]` = `["M17.11",
"M17.11"]`. Verified locally across 50 seeds each: 17 HARD/clean
seeds and 13 HARD/flagged seeds produce this duplicate.

The schema at `encounter_schema.py:103-107` enforces only
`minItems: 1` and `items: string` — it does not enforce
`uniqueItems`. The comment at `synth/render.py:129-135` is
explicit that the intent is "two distinct ICD-10 codes" and
that the renderer should "list one chronic + the acute" — but
the third scenario's data contradicts the comment because
`chronic_a == acute`.

**Suggested fix (out-of-scope per brief, recorded for the next
sibling):** Add `uniqueItems: True` to the
`icd10_codes` schema entry — that closes it at the schema
level and is the right place to enforce it. Alternatively,
change the third scenario to use a different acute code (e.g.
`M17.11` for chronic_a, `S83.511A` for acute — a knee sprain
that coexists with chronic knee OA is a more realistic
combo anyway). The "test_hard_dual_problems_with_chronicity"
test referenced in the `synth/render.py:130` comment does not
exist in the test suite; that test, if added, would catch the
regression.

### 4. Major — Multiple cross-field invariants enforced in Python instead of JSON-schema `if/then/else`

The validator function enforces at least one cross-field
invariant (the `surgery_with_global_period → at least one 992xx
E/M` check at `encounter_schema.py:201-211`). JSON Schema 2020-12
supports `if/then/else` natively, so the same check would be
cleaner in the schema than in the post-schema Python loop. A
reader who reads only the JSON schema will not realise the
E/M check exists.

**Suggested fix (out-of-scope per brief):** Move the
`if surgery_with_global_period then at least one cpt_codes[*].code
starts with "992"` check into the JSON schema as an `if/then`
clause. The validator can keep the post-schema check as a
defensive duplicate if you want belt-and-suspenders, but the
schema is the spec — the spec should be self-describing.

### 5. Major — `provider_note.hpi` / `exam` / `mdm` accept single-whitespace strings

`encounter_schema.py:98-100` sets `minLength: 1` on each of
`hpi`, `exam`, `mdm` and the parent `provider_note` is
`additionalProperties: False`. A provider note of
`{"hpi": " ", "exam": ".", "mdm": ""}` would fail on `mdm`
(empty), but `{"hpi": " ", "exam": " . ", "mdm": "x"}` would
pass — and would render as a one-character clinical note. The
dashboard would highlight nothing, the auditor would have no
evidence to work with, and the smoke tests would treat the
encounter as a valid one.

**Suggested fix (out-of-scope per brief):** Add a `minLength: 8`
(or whatever the realistic minimum for an HPI sentence is)
on each of `hpi`, `exam`, `mdm`. JSON Schema also supports
`"pattern": "\\S"` (a non-whitespace character) for the
"must have real content" case. Choose one, not both, and
document the choice.

### 6. Minor — The "modifier-25 / global period" comment is in the wrong place

`encounter_schema.py:193-200` contains a six-line comment in
the middle of `validate_encounter(...)` explaining that the
modifier-25 audit rule is not the schema's job. This is
correctly delegated, but a future maintainer looking at the
schema for "what rules does this enforce?" will not see this
comment — they will see the `ENCOUNTER_SCHEMA` dict and the
`__all__` list and assume the schema is self-describing.

**Suggested fix (out-of-scope per brief):** Move the comment
from `validate_encounter` to the module docstring at
`encounter_schema.py:1-18`, where the cross-reference to the
auditor lives. The current docstring does not mention the
modifier-25 rule at all.

### 7. Minor — `encounter_id` regex allows trailing-underscore ids

`encounter_schema.py:74` defines the pattern as
`^enc_[a-zA-Z0-9_]+$` — the `+` quantifier allows one or more
characters. The synth renderer at `synth/render.py:48` emits
`enc_synth_<tier>_<variant>_<8hex>`, so the empirical pattern
in production is fine. But the regex does not anchor the
suffix to be non-empty after the last underscore, so `enc_`
or `enc_foo_` would technically pass (the second matches
`foo` + a trailing underscore). Theoretical; not a real bug
today.

**Suggested fix:** Change the pattern to
`^enc_[a-zA-Z0-9_]+[a-zA-Z0-9]$` to require the final
character to be alphanumeric. Cosmetic.

### 8. Minor — `_KNOWN_MODIFIERS` is a closed allow-list with no version stamp

`encounter_schema.py:46-52` lists 82 CPT modifiers. New CMS
modifiers (e.g. the post-2024 telehealth modifiers, or any
jurisdiction-specific modifier a Canadian billing tool might
emit) will be silently rejected by the validator at line
188-191 with `"cpt_codes[i].modifier: 'XX' is not a
recognised CPT modifier"`.

**Suggested fix (out-of-scope per brief):** Add a
`# last reviewed: YYYY-MM-DD` comment to the set and a
`__version__ = "2024-Q4"` (or similar) module constant. For
the MVP this is fine; for a real billing product the allow-
list needs a refresh cadence tied to the CMS HCPCS quarterly
update.

### 9. Minor — `EncounterValidationError.errors` is `list[str]`, not structured

`encounter_schema.py:128-138` defines the error type with a
plain `list[str]` for `errors`. Each string is a
human-readable `f"{path}: {message}"`. A programmatic
consumer that wants to map each error to a fix-up action
(e.g. "auto-add a default E/M 99213 if missing") will have
to regex-parse the strings.

**Suggested fix (out-of-scope per brief):** Change the
attribute to `list[dict[str, str]]` with a stable shape like
`{"path": "/cpt_codes/0/code", "code": "pattern", "message":
"..."}`. Backward-incompatible for any current consumer; but
finding 2 above says there are no current consumers, so the
break is free.

### 10. Minor — `validator.iter_errors(payload)` sort key is on `e.path` (a `deque`)

`encounter_schema.py:161` sorts with
`key=lambda e: e.path`. `e.path` is a `deque`; deque
comparison is element-by-element and works, but the
comparison is not the same as a path-string comparison. A
future maintainer who reads this and "improves" it to
`key=lambda e: list(e.path)` or `key=lambda e:
"/".join(e.path)` will get a different ordering, which will
break a snapshot test that depends on the order (none
exists today, so this is theoretical).

**Suggested fix (out-of-scope per brief):** Add a comment
explaining the deque comparison, or sort on `e.absolute_path`
(the deque of path components, which compares the same way
and is the more commonly used attribute in `jsonschema`
recipes).

### 11. Minor — `enc_10032` has empty `claim.cpt_codes` and `claim.icd10_codes`

`data/val.json:1-10` (the enc_10032 record) has
`"claim": {"cpt_codes": [], "icd10_codes": []}`. The
dashboard's encounter-detail page at
`api.py:232-246` passes `record.get("claim", {})` to the
template verbatim. The template's behaviour for an empty
`cpt_codes` list is not visible from this review (out of
scope), but a reader will see "no codes billed" alongside a
"Duplicate service billed" rule — which is *correct* for a
duplicate flag (the rule fires on two visits being billed,
not on a specific code), but may look like a data error to a
new dashboard user. The `summary` string in
`demo_entries.py:34-38` already says "Duplicate service
billed same day as annual wellness visit," which is a good
disambiguator.

**Suggested fix (out-of-scope per brief):** No code change;
the dashboard template's empty-list handling is the right
place to add a "(no codes billed — claim is the duplicate
set)" sub-line. The summary string already covers it.

### 12. Minor — `demo_entries.py` summaries describe the audit-panel UX, not the encounter

`demo_entries.py:34-38, 56-60, 84-90` each describe what the
*dashboard* will show ("evidence quote appears verbatim in
the clinical note," "highlight renders on all 4 findings").
A reader using these summaries to triage a multi-finding
audit will get the right answer; a reader using them to
understand the underlying encounter (e.g. "what diagnosis
does this EASY encounter represent?") will not.

**Suggested fix (out-of-scope per brief):** Reframe the
summaries to lead with the clinical scenario ("AWV +
same-day sick visit, flagged as duplicate") and demote the
audit-panel UX to a second sentence. Cosmetic; both
readers will get the right answer, just with different
cognitive loads.

### 13. Minor — `load_encounter_record(...)` is deterministic by encounter_id, not by user/session

`demo_registry.py:91-113` is a linear scan by encounter_id
across `val.json` then `train.json`. There is no user/
session/seed input, so the selection is fully deterministic
and fixed (within the lifetime of the in-process cache —
see finding 15).

**Recommendation (per brief Q3):** Keep the fixed
registration-order + load-by-id design. The current 3-entry
demo benefits from "the page is the same every time I
refresh" (a teaching surface, not a discovery surface). If
the demo ever grows past ~6 entries, add a `Difficulty`
filter rather than a random shuffle. Random would break the
"use this demo to teach a new user what each band looks
like" use case.

### 14. Minor — `_REGISTRY` is a module-level list with no concurrency guard

`demo_registry.py:51-75`. The current call sites
(`demo_entries.py:31, 52, 81`) are all at app-import time,
single-threaded. A future test or async registrar that calls
`register_demo_encounter` from two threads would race.

**Suggested fix (out-of-scope per brief):** Add a
`threading.Lock` around the `_REGISTRY.append` (or accept
the limit and document it). Today's callers are safe; this
is a maintainability note for the next sibling.

### 15. Minor — Lazy JSON cache has no invalidation hook

`demo_registry.py:99-110`. The `_cache` is populated on
first read of each split and never invalidated. A dev
workflow that drops a fresh `train.json` while the dashboard
is running (the live deploy doesn't, but local dev with
`uvicorn --reload` and a side-channel JSON edit might) will
not see the change until restart.

**Suggested fix (out-of-scope per brief):** Add a
`reload_demo_registry()` function that clears the cache and
re-loads. Wire it to a `/dev/reload` endpoint guarded by
debug mode. For the live deploy, the current behaviour is
correct (the JSON is committed and frozen at deploy time).

### 16. Minor — `_DATA_DIR` assumes a fixed install layout

`demo_registry.py:35`. `(Path(__file__).resolve().parent.
parent.parent / "data")` is three levels up from the source
file. If the package is ever vendored (e.g. `pip install
ai-billing-audit` from a wheel) without the `data/`
directory at the expected location, every
`load_encounter_record` call returns `None` and the
encounter-detail page 404s on every record. No log message;
silent failure mode.

**Suggested fix (out-of-scope per brief):** Make the data
directory an install-time config (e.g. env var
`AI_BILLING_AUDIT_DATA_DIR` with the current default), or
log a single warning at import time if the directory does
not exist. The current code's comment at line 32-35 is
helpful for code-readers but does not help at runtime.

### 17. Minor — Module docstring is out of date

`encounter_schema.py:1-18` says the schema is "consumed by
the rest of the audit pipeline." Per finding 2, it is not.
Update the docstring to reflect the actual contract
("the format spec for synth-agent-emitted fixtures; consumed
by the synth renderers and the cross-provider smoke tests"
— and the smoke-test consumer claim should also be
verified, since I did not run the smoke tests).

**Suggested fix (out-of-scope per brief):** Update the
docstring to match the actual consumer list. The
cross-provider smoke test claim should be verified
(`scripts/smoke_dashboard.py` is in the search hits — read
it before editing the docstring).

### 18. Nit — `patient.age` upper bound of 130

`encounter_schema.py:89`. Generous; the oldest verified
human lifespan is ~122. A 131-year-old patient would be
rejected. Cosmetic; no real-world data will hit this
boundary.

### 19. Nit — `patient.sex` enum is `M | F | O`

`encounter_schema.py:90`. `O` is the JSON-schema-style
"other" / "non-binary" placeholder. HL7 FHIR uses
`male | female | other | unknown`; CMS uses `M | F | U`;
some Canadian provinces use `X` on the health card.
Jurisdiction-dependent. For an MVP, the current enum is
fine; for a multi-jurisdiction product, it should be
configurable per tenant.

### 20. Nit — `demo_entries.py` has no `__all__`

`demo_entries.py:21`. The module is imported for
side-effects only (`from ai_billing_audit import demo_entries
# noqa: F401` at `api.py:61`), so the absence of `__all__` is
deliberate. The module docstring at line 8-15 spells this
out. Cosmetic.

### 21. Nit — `_Difficulty` is a bare `str` type alias

`demo_registry.py:38`. The runtime check at line 64-67
makes the constraint discoverable at call time, but a typed
enum would let mypy flag a typo at a sibling-worker's
registration call site. Cosmetic; sibling workers will
get the wrong-difficulty rejection at runtime anyway.

### 22. Nit — `register_demo_encounter` idempotency is O(n)

`demo_registry.py:68-70`. For 3 entries this is fine; for
1000+ entries a `dict[encounter_id, DemoEncounter]` would
be O(1). The brief calls this a "registry" not a "ledger,"
so linear is acceptable. Note for the next sibling.

## Out-of-scope (recorded for the next sibling, not acted on per the brief)

- Refactoring the schema, demos, or registry code (the brief
  is review-only, no code changes).
- Reviewing files outside `encounter_schema.py`,
  `demo_entries.py`, and `demo_registry.py`. Cross-
  references to `synth/render.py`, `synth/template.py`,
  `api.py`, `data/*.json`, and the test files were made
  only to ground the findings.
- Performance benchmarking, security audit, or test-
  coverage analysis beyond the schema-and-registry surface.
  The `CODE_REVIEW_tests.md` (findings G-3) and
  `SEC_REVIEW_phi.md` (lines 71-74) reviews already cover
  those surfaces.
- Rewriting clinical content of the demo fixtures. The
  three demos are clinically plausible and consistent with
  their summaries; no rewriting needed.

## Verification

This review was produced by reading the three target files
end-to-end, running 18 calls to `validate_encounter()`
against `generate_encounter(tier, variant, seed)` for
3 tiers × 2 variants × 3 seeds, and verifying the
selection mechanism in `demo_registry.py` is the
registration-order + load-by-id design described above.
No source files were modified.
