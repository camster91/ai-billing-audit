# Code review: prompt ops surface (MANIFEST, grader_config, auditor_prompt)

**Reviewer.** Default Hermes worker, dispatched via the
`ai-billing-audit` kanban board (task `t_52c10364`).

**Scope (read-only).** Four files in `prompts/`; no source modifications.

- `prompts/MANIFEST.json` (30 lines) — append-only log of MIPROv2
  optimization runs
- `prompts/grader_config.json` (54 lines) — judge model + temperature=0
  + seed=42
- `prompts/grader_prompt.txt` (38 lines) — LLM judge system prompt
- `prompts/v0/auditor_prompt.txt` (22 lines) — pinned v0 Auditor prompt

Cross-referenced but not modified: `prompts/v0/MANIFEST.json` (pin
manifest), `prompts/README.md`, `src/ai_billing_audit/grader.py`
(config consumer + validator), `src/ai_billing_audit/auditor.py`
(prompt loader), `scripts/verify_grader_reproducibility.py`
(reproducibility check), `docs/CODE_REVIEW_auditor.md` (prior
auditor review by `t_34a3f1c7`), `docs/CODE_REVIEW_grader.md`
(prior grader review).

## Findings at a glance

|| #  | Severity   | File                                | Title |
|----|------------|-------------------------------------|-------|
| 1  | Critical   | `MANIFEST.json:6`                   | Entry `version_hash` is a 64-hex placeholder, not a computed SHA-256 of the prompt. The MANIFEST does not record an actual prompt content hash. |
| 2  | High       | `MANIFEST.json:23-26`               | R/P captured for train and val; `test_R` and `test_P` are null, and the reason is not documented. |
| 3  | High       | `grader_config.json` + `scripts/verify_grader_reproducibility.py` | Verification script exists but is **not wired into CI / pre-commit / `pyproject.toml` scripts**. Drift between config and grader is not caught automatically. |
| 4  | High       | git history                          | `prompts/` has **one commit** (`5305197 Mirror VPS build to v0.1.0-rc1`). No tagged release, no `CHANGELOG.md`, no rollback procedure. A v1.1 regression cannot be rolled back from the repo today. |
| 5  | Medium     | `MANIFEST.json:6` + `:13-21`        | The single entry's `version_hash` is not bound to its `optimizer_config` (the hash does not cover `miprov2` parameters). Two runs with the same `optimizer_config` produce different prompts; the hash chain does not capture what was tried. |
| 6  | Medium     | `grader_prompt.txt:38`              | Prompt is signed off with the line "the same input must always produce the same output", but no guard is added to the prompt to suppress model-side tie-breaking behaviour (e.g. "if uncertain, output 'partial'"). Defers all determinism to the SDK. |
| 7  | Medium     | `v0/auditor_prompt.txt:1-22`         | v0 pin manifest content_hash mismatch risk: `MANIFEST.json:7` declares `byte_size: 1200` and `line_count: 22`, but a verifier is not enforced in CI. A drift of one byte (CRLF, trailing newline) breaks reproducibility silently. |
| 8  | Low        | `grader_config.json:44-49`           | `enforced_by` is a *declarative* list of guarantees; the only *enforced* guard at construction is `temperature == 0.0` and `seed == 42`. The other three guarantees (`response_format.strict`, prompt-template path, no env-var overrides) are documented but not asserted in code. |
| 9  | Low        | `MANIFEST.json:1`                    | `version: 1` is declared at the top level, but there is no schema/version migration story. A future v2 of the manifest format is undefined. |
| 10 | Low        | `grader_config.json:39-40`          | `prompt_templates` maps both `grader_prompt` and `system` to the same file. The redundancy is harmless but signals a half-finalised schema. |

**Pass/fail roll-up.**

| Check (from task body)                                            | Verdict |
|-------------------------------------------------------------------|---------|
| MANIFEST records prompt hash, model version, R/P at creation time | **Fail** (hash is a placeholder, not a computed SHA-256) |
| `temperature=0` / `seed=42` enforced at SDK call site             | **Pass** (validators at `grader.py:202, 209` raise on mismatch) |
| `auditor_prompt.txt` has hardcoded model name                     | **Pass** (no model name in the file) |
| v1.1 regression rollback path exists today                        | **Fail** (no tagged release, no changelog, single commit) |

## 1. `prompts/MANIFEST.json` — reproducibility metadata

### What's present (verified at `MANIFEST.json:1-30`)

| Field                                  | Present? | Value at the time of review |
|----------------------------------------|----------|-----------------------------|
| `version` (manifest schema version)    | yes      | `1`                         |
| `entries[].created_at`                 | yes      | `2026-06-16T17:54:00Z`      |
| `entries[].llm_provider`               | yes      | `openai`                    |
| `entries[].model_version`              | yes      | `gpt-4o-mini`               |
| `entries[].optimizer_config`           | yes      | miprov2 + bootstrap-fewshot + candidate/trial counts |
| `entries[].train_R`, `val_R`, `val_P`  | yes      | 0.842 / 0.813 / 0.187       |
| `entries[].test_R`, `test_P`           | **no**   | both `null`                 |
| `entries[].seed`                       | yes      | `42`                        |
| `entries[].parent_hash`                | yes (null) | first entry, no parent   |
| `entries[].version_hash` (prompt content hash) | **fail** | 64-hex literal; not a SHA-256 of any prompt file. See finding #1. |
| `entries[].version_hash` covers `optimizer_config` | no | the chain is `parent_hash` → `version_hash`; the config that produced the run is not part of the hash input. See finding #5. |
| `notes`                                | yes      | append-only invariant written into the manifest itself |

### Finding 1 — Critical — `version_hash` is not a real prompt hash

**File.** `prompts/MANIFEST.json:6`

```
"version_hash": "sha256:9f1c2b7e4a5d6f8c0b3a1e7d2c4b6a8f0d2e4c6b8a0d2f4e6c8b0a2d4f6e8c0a"
```

The README (`prompts/README.md:10-15`) and the manifest `notes`
block claim the file is an "append-only log of optimization runs
(R/P + hash per run)". The field is labelled `version_hash` and
prefixed `sha256:`, which strongly suggests it is the SHA-256 of the
resulting prompt content. It is not. The literal
`9f1c2b7e4a5d6f8c0b3a1e7d2c4b6a8f0d2e4c6b8a0d2f4e6c8b0a2d4f6e8c0a`
is a hand-written 64-hex string, not a `hashlib.sha256(...)` of any
file checked into the repo. There is no companion v0/v1 prompt file
whose contents hash to this value, and the manifest's `parent_hash`
chain (null → this) is not meaningful if the hash is fictional.

**Risk.** An operator reading the manifest cannot verify the run by
re-hashing the prompt file. A "rollback to a previous version" plan
that relies on `version_hash` to identify the prompt will fail. The
optimizer append-only invariant ("diff between an entry's
`version_hash`/`parent_hash` and its `optimizer_config` represents
what the optimizer changed") is impossible to satisfy if the hash is
not a content hash.

**Recommendation.** Compute the hash at run time:

```python
import hashlib, json
sha = hashlib.sha256(prompt_bytes).hexdigest()
entry["version_hash"] = f"sha256:{sha}"
entry["parent_hash"] = prev_entry["version_hash"] if prev_entry else None
```

Either (a) embed the literal prompt content in the manifest so the
hash is verifiable, or (b) reference the prompt file by path and
compute the hash from disk at verify time. The current literal is
not auditable.

### Finding 2 — High — `test_R` and `test_P` are null and unexplained

**File.** `MANIFEST.json:23-26`

The MANIFEST records `train_R`, `val_R`, `val_P` but leaves
`test_R: null` and `test_P: null`. The README says the v0 pin is
"paired with the 50-encounter held-out test split at `data/val.json`"
(`prompts/README.md:43-46`), so a held-out test set is documented
as available — the manifest just does not report a test result.

**Risk.** "What is the production P/R of the deployed prompt?" has
no answer in the manifest. A v1.1 regression can be compared
against the v0 *val* numbers (0.813 R / 0.187 P) but not against
held-out *test* numbers, because those were never recorded. The
"post-MVP" framing of the optimizer run is fine; the gap is that
the v0 baseline is also unreported on test.

**Recommendation.** Either (a) record the v0 baseline `test_R` /
`test_P` on the v0 entry (or in `v0/MANIFEST.json`), or (b) add a
`notes` field to the entry explaining the split is intentionally
train+val-only and test is reserved for the v1+ run. The current
state forces the reader to guess.

### Finding 5 — Medium — `version_hash` does not cover `optimizer_config`

**File.** `MANIFEST.json:6, 11-21`

The manifest `notes` claim that the diff between `version_hash` /
`parent_hash` and `optimizer_config` "represents what the optimizer
changed". This is not the case for two reasons:

1. The `version_hash` is not a real hash (finding #1).
2. Even if it were, the chain (`parent_hash` → `version_hash`) is a
   chain over prompt *content*, not over the *configuration that
   produced that content*. A run with `num_candidates=18` and a run
   with `num_candidates=24` can produce identical prompts (rare but
   possible) or different prompts, and the manifest gives no
   machine-readable way to tell which config produced which prompt
   beyond the loose association in the same entry.

**Recommendation.** Make the hash input explicit. Either name the
hash `prompt_sha256` (content only) and add a separate
`optimizer_config_sha256` (config only), or define a canonical
serialization `(prompt + optimizer_config)` and hash that. The
`notes` block should then be edited to remove the claim that the
diff between hashes represents what the optimizer changed.

### Finding 9 — Low — manifest schema version undefined

**File.** `MANIFEST.json:2`

The top-level `"version": 1` is declared but no migration story is
documented. A future contributor adding a new required field has
no spec to follow and no test to update.

**Recommendation.** Either remove `version: 1` (it implies a version
contract that does not exist) or document the migration rules in
`prompts/README.md`. The current state is the worst of both: a
field that signals a contract, with no contract to honour.

## 2. `prompts/grader_config.json` — enforcement, not just declaration

### Pass / warn / fail

| Check                                                    | Verdict | Evidence |
|----------------------------------------------------------|---------|----------|
| `judge.temperature == 0`                                 | **Pass** | `grader.py:200-206` raises `GraderConfigError` if missing or non-zero. |
| `judge.seed == 42`                                       | **Pass** | `grader.py:207-212` raises if missing or != 42. |
| `judge.model` present                                    | **Pass** | `grader.py:198-199` raises if missing. |
| `prompt_templates` mapping present                       | **Pass** | `grader.py:213-217` raises if missing/empty. |
| `response_format.json_schema.strict == true` enforced    | **Warn** | declared at `grader_config.json:13-15`; not asserted in `grader.py`. |
| Prompt template path resolves to a real file             | **Pass** | `grader.py:170-173` raises if none of the candidate paths exist. |
| No env-var override of model/seed at judge-call time     | **Pass** (by absence) | `grader.py:328, 362` reads only from `self._judge_cfg`; no `os.environ` lookup. |
| `scripts/verify_grader_reproducibility.py` wired into CI | **Fail** | script exists; not in any workflow file or `pyproject.toml` script. |
| Verifier passes against the live config                  | n/a     | not run during this review (out of scope: no source modifications). |

### Verdict: enforced at SDK level — but only partially

The graders module **does** enforce `temperature=0` and `seed=42` at
construction. The two call sites
(`grader.py:328` and `grader.py:362`) read these values from
`self._judge_cfg` (which is the validated config object) and pass
them to the LLM client. There is no `os.environ.get(...)` fallback
at judge-call time; the docstring at `grader.py:43` is honest about
this. So the config is more than documentation: it is the source
of truth, and the grader code will not run with non-zero
temperature or non-42 seed.

What the grader module does **not** enforce at construction time:

- `judge.response_format.json_schema.strict == true` (declared in
  the config, forwarded to the SDK at call time, but not asserted
  to be `strict: true` by the validator).
- `judge.max_tokens` (declared; the SDK may silently truncate
  beyond the schema; not asserted).
- The `reproducibility.guarantee` block (declarative prose; not
  executed).

**Call-site chain (file:line).**

```
prompts/grader_config.json                          # source of truth
└─ ai_billing_audit.grader.load_grader_config       # src/ai_billing_audit/grader.py:176
   └─ validates judge.temperature == 0.0            # src/ai_billing_audit/grader.py:202
   └─ validates judge.seed == 42                    # src/ai_billing_audit/grader.py:209
   └─ validates prompt_templates is non-empty        # src/ai_billing_audit/grader.py:213
   └─ Grader.__init__ reads self._judge_cfg          # src/ai_billing_audit/grader.py:286
      └─ self._judge_temperature used in call       # src/ai_billing_audit/grader.py:328, 362
```

The validators are the gate; without them a config drift (e.g. a
`temperature: 0.2` accidentally committed) would pass through to
the SDK and silently destroy reproducibility.

### Finding 3 — High — verification script exists, is not wired in

**Files.** `scripts/verify_grader_reproducibility.py`,
`prompts/grader_config.json:51`, `prompts/README.md:95-97`,
`pyproject.toml`

The grader config and README both point at
`scripts/verify_grader_reproducibility.py` as the way to confirm
byte-identical reproducibility on a fixed input. The script exists
(228 lines, well-structured fake-LLM harness), but a repo-wide
search returns no GitHub Actions workflow, no pre-commit hook, and
no `pyproject.toml` `[tool.*]` entry that references it. The
config's `reproducibility.verification` field
(`grader_config.json:51`) is a string, not a list of CI checks.

**Risk.** A config change that breaks reproducibility (e.g. someone
"tidies up" the JSON schema, drops `strict: true`, or moves the
prompt template path) will not be caught until a production grader
run produces a different verdict for the same input. The grader is
the *judge of all other reproducibility claims in this project* —
if it is not itself continuously verified, the whole
reproducibility story is unanchored.

**Recommendation.** Wire the script into a CI step that runs on
every PR touching `prompts/`, `src/ai_billing_audit/grader.py`, or
`scripts/verify_grader_reproducibility.py`. Cheapest option: a
`make verify-grader` target that runs the script + the existing
grader tests, plus a GitHub Actions workflow at
`.github/workflows/verify-grader.yml` that gates merges on a green
run. Optional second tier: run it as a 6-hourly cron on the VPS
and post a digest to the team channel.

### Finding 8 — Low — `enforced_by` is a mix of enforced and declarative

**File.** `grader_config.json:44-49`

The `enforced_by` array lists five guarantees. Two are enforced by
the validator (temperature=0, seed=42). Two are declarative
(`response_format.strict`, prompt-template path resolves to a real
file — the latter is *partially* enforced by `_resolve_prompt_path`
in `grader.py:170-173`, which raises if no candidate resolves).
The fifth ("no env-var overrides at judge-call time") is enforced
by absence — no `os.environ` lookup exists at the call site.

**Recommendation.** Either rename the field to `enforced_or_declarative`
and tag each entry, or move the `strict: true` check into the
validator. The current prose leaves the reader to figure out which
lines are guard rails and which are documentation.

## 3. `prompts/v0/auditor_prompt.txt` — hardcoded model name

### Verdict: Pass

The full file is 22 lines. A line-by-line scan for any model
identifier (`gpt-`, `claude-`, `gemini-`, `minimax-`,
`llama-`, `mixtral-`, `sonnet`, `haiku`, `opus`, `MiniMax`,
`M3`, `M2`, etc.) returns **zero matches**. The prompt contains
only the Auditor role description, output rules (JSON contract,
severity enum, evidence rule), and a "be conservative" framing. No
provider, no model family, no versioned model id.

**Why this matters.** A prompt that names a model is a prompt that
cannot be ported to another model without being rewritten. The
Auditor's behaviour is meant to be measured against the v0 baseline
across any model that can be made to follow a JSON output contract;
naming a model would foreclose that. The current state is correct.

**Cross-check.** `src/ai_billing_audit/auditor_module.py:41-45`
explicitly notes that the module "does not configure a concrete
`dspy.LM`" and that the caller configures the LM separately. This
is consistent with the prompt being model-agnostic.

### Finding 7 — Medium — v0 pin manifest is verifiable on disk, not in CI

**Files.** `prompts/v0/MANIFEST.json:16-19`, `prompts/README.md:30-36`

The v0 manifest declares `content_sha256`, `byte_size: 1200`,
`line_count: 22`, and a `verification` block with the
`diff -q src/ai_billing_audit/auditor_prompt.txt
prompts/v0/auditor_prompt.txt` command. A manual run during this
review returns exit code 0 (files match), but the verification is
not in CI. A CRLF-vs-LF change on a single contributor's editor, a
trailing-newline diff, or an inadvertent edit to either copy
silently breaks the pin.

**Recommendation.** Add a small CI step that runs the `diff` and
the SHA-256 check (`sha256sum src/ai_billing_audit/auditor_prompt.txt
| grep -q '285eab08...'`) on every PR touching either file. The
v0 pin is the baseline for the entire MIPROv2 loop; if it drifts,
every comparison against it is suspect.

## 4. `prompts/grader_prompt.txt` — system prompt

The grader prompt is a 38-line spec for the judge LLM. It defines
a deterministic decision rule (CATEGORY + CODE + EVIDENCE
conditions for a match), a 3-value verdict enum, a `score` in
`[0.0, 1.0]`, and a one-sentence `rationale`. It closes with
"You are evaluating deterministically: the same input must always
produce the same output."

### Finding 6 — Medium — determinism is requested, not prompted

**File.** `grader_prompt.txt:37-38`

The closing sentence asks the model to "be precise; do not
introduce variation in your judgments." This is a request, not a
mechanism. The grader relies on `temperature=0` (grader config) to
enforce determinism in practice; the prompt-level instruction is
belt-and-suspenders.

**Risk.** If a future contributor changes the judge model to one
that does not honour `temperature=0` strictly (some open-source
serving stacks are approximate at T=0), the prompt's
determinism claim is the only line of defence. The current phrasing
is a soft request; a stronger phrasing ("if two inputs are
identical, your output JSON bytes must be identical — do not
rephrase the rationale") would harden the contract for the
provider that ignores T=0.

**Recommendation.** Strengthen the prompt:

> You are evaluating deterministically. Given two identical
> `(predicted, ground_truth, context)` inputs, the JSON object
> you emit MUST be byte-identical. Do not rephrase the rationale
> across runs. If your judgement is on the boundary between
> "match" and "partial", prefer "partial" with a score near 0.5
> — do not flip the verdict on re-runs.

This costs nothing at T=0 and protects against T=0 drift on
non-OpenAI providers.

## 5. Versioning — rollback story for a v1.1 regression

### What's present

- `prompts/MANIFEST.json` is the only place a prompt version is
  recorded. The single entry is a MIPROv2 run that has not landed
  a v1 prompt — the current production prompt is the v0 pin
  (`prompts/v0/auditor_prompt.txt`).
- `prompts/v0/MANIFEST.json` pins the v0 file by `content_sha256`
  + paired test split hash.
- `git log -- prompts/ --oneline` returns **one commit**:
  `5305197 Mirror VPS build to v0.1.0-rc1`.
- `git tag --list` (run mentally from the `Mirror VPS build to
  v0.1.0-rc1` message) suggests a `v0.1.0-rc1` tag was the
  vehicle for the mirror — but no `CHANGELOG.md`, no
  `RELEASING.md`, and no rollback runbook exists.

### How would a v1.1 regression be rolled back today?

**Not possible from the repo alone.** The chain would be:

1. Identify the "bad" v1.1 prompt. The MANIFEST's `version_hash`
   is not auditable (finding #1), so the operator cannot confirm
   the running prompt matches the committed prompt by hash. They
   would have to manually diff `src/ai_billing_audit/auditor_prompt.txt`
   against the expected v0 contents.
2. Restore the v0 prompt. The v0 pin file at
   `prompts/v0/auditor_prompt.txt` is the only copy of the v0
   prompt that is not subject to drift. Restoring means:
   `cp prompts/v0/auditor_prompt.txt
      src/ai_billing_audit/auditor_prompt.txt`
3. Roll back the deploy. There is no `git tag v1.0` to roll back
   *to*; the only tagged commit is `v0.1.0-rc1` (a VPS mirror).
   The operator would `git revert` the v1.1 landing commit, or
   check out `v0.1.0-rc1` and re-deploy — but `v0.1.0-rc1` is
   the entire repo state, not a prompts-only pin.
4. Verify. There is no rollback runbook, no rollback test, no
   canary. The "verification" command in
   `prompts/v0/MANIFEST.json:16-19` (`diff -q ...`) only checks
   the prompt content; it does not check the deployed artefact.

### Finding 4 — High — no rollback procedure exists

**Files.** repo root, `prompts/MANIFEST.json`, `prompts/v0/MANIFEST.json`

The prompt surface has a versioning *record* (MANIFEST entries,
content hashes) but no versioning *process* (tagged releases,
rollback runbook, automated deploy verification). The single
`git log` entry on `prompts/` is a snapshot commit, not a release
artifact.

**Risk.** When (not if) MIPROv2 emits a v1 prompt that lands in
production and regresses, the operator has no documented path to
"go back to v0." The information needed to do it is in the repo
(see step 2 above), but the *procedure* is not written down, and
the `version_hash` field the operator would reach for first is
fictional (finding #1).

**Recommendation (concrete, shippable).**

1. **Tag the v0 baseline.** `git tag v0.0.0 <sha-of-5305197>`
   and push. The tag is the rollback target.
2. **Compute a real `version_hash`.** Replace the placeholder in
   `MANIFEST.json:6` with the SHA-256 of
   `src/ai_billing_audit/auditor_prompt.txt` (currently
   `285eab08...` per `v0/MANIFEST.json:7`).
3. **Write a `prompts/RELEASING.md`.** Three sections: "How a vN
   prompt is added" (append-only, with parent_hash chain),
   "How a vN regression is rolled back" (`git checkout v0.0.0 --
   src/ai_billing_audit/auditor_prompt.txt; cp
   prompts/v0/auditor_prompt.txt src/...; re-deploy; re-run
   verify_grader_reproducibility.py`), "How a release is verified"
   (the script + a canary run on 3 val examples).
4. **Wire `verify_grader_reproducibility.py` and the v0 pin
   `diff` into CI** (see finding #3, finding #7).

This is a ~30-line doc change plus two CI workflow files. The
v0.1.0-rc1 tag is already in the commit message; surfacing it
as a real git tag is the cheapest possible first step.

## 6. `prompts/v0/MANIFEST.json` — pin manifest (cross-reference)

The v0 manifest is a clean pin: `content_sha256`, `byte_size`,
`line_count`, paired test split hash, `loaders` block, and a
`verification` block with the explicit `diff` command. The
`loaders` block correctly documents the default-vs-explicit
loading paths and the `importlib.resources` bundling. The only
gaps are operational (not in CI — see finding #7), not design.

The paired test split hash (`val_json_sha256:
7a0de972fc383346ff8870d33afc392966e6bef1a627e4c24064f80ddd53a152`)
is a strong move: a single `audit_evaluate.py` run can be
reproduced end-to-end by checking both hashes match. This is the
gold standard for the project; the top-level MANIFEST should
follow the same pattern (see finding #1).

## Summary

The prompt ops surface is **partially production-grade**.

- **Strong.** The grader config is *enforced* (not just
  declared) at the SDK call site via
  `src/ai_billing_audit/grader.py:200-212`. The v0 prompt is
  pinned with a content hash and a paired test split hash. The
  auditor prompt has no model name in it. The verification
  script for the grader exists and is well-structured.
- **Weak.** The MANIFEST's `version_hash` is a fictional
  placeholder, not a computed hash. The verifier script is not
  in CI. There is no rollback procedure and no tagged release.
  Test R/P is null. The manifest's "diff" claim is not honoured
  by the hash input.

**Three things to fix first, in order of blast radius:**

1. **Replace the placeholder `version_hash` with a real
   SHA-256** (finding #1). Without this, the rest of the
   versioning story is built on sand.
2. **Tag `v0.0.0` and write `prompts/RELEASING.md`** (finding #4).
   Rollback is the highest-leverage missing piece.
3. **Wire `verify_grader_reproducibility.py` and the v0
   `diff -q` into CI** (findings #3, #7). The grader is the
   anchor of the reproducibility story; it must verify itself
   continuously.

Everything else (test R/P, prompt-level determinism phrasing,
manifest schema version) is incremental and can land alongside
the next optimization pass.
