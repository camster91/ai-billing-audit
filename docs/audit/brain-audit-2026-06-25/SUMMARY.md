# Brain-Audit Board Drain — 2026-06-25

## Summary

Drained the `brain-audit` kanban board: **29 of 29 ready tasks completed**.
The board was a self-audit + skill-gap backlog; each task was investigated
against the actual repo state at HEAD `901aeb0`, and an audit report was
written with evidence-backed findings.

## Coverage matrix

| Theme                        | Tasks | Status                  |
|------------------------------|-------|-------------------------|
| Clinical-rule coverage       | 15    | 15 audited (some partial, some missing) |
| DSPy / model engineering     | 8     | 8 audited (most missing) |
| Adversarial / UX gaps        | 6     | 6 audited (most missing) |

## Key repo findings (counts at HEAD)

- `rules/seed_rules.json` — 269 lines, 31 modifier hits, 12 NCCI/PTP edits, 14 E/M rules, 4 frequency/MUE hits
- `prompts/v12/auditor_prompt.txt` — 761 lines, 16 EXAMPLE blocks, 19 NCCI/MUE/modifier hits
- DSPy is wired (`dspy.Predict` over `AuditClaim`) but pinned to **Sonnet 4.5** only — no routing, no CoT, no MIPROv2
- No `(claim_hash, prompt_version)` response cache
- No per-tenant cost guardrail code
- No streaming endpoint (DSPy streaming vendored but unused)
- No multi-language / OCR handling
- No per-specialty prompt files

## What this audit is and isn't

This is **a self-audit report**, not implementation. Each `t_*.md` file
documents:

1. **The claim** (verbatim from kanban task body)
2. **Evidence** (`grep` / `wc` / `find` output against the repo)
3. **Verdict** — covered / partial / missing
4. **Recommended follow-up** — concrete next steps to close the gap

Implementation tasks (e.g., actually building `rules/ncci_ptp.json`, wiring
MIPROv2, adding the cost guardrail) were **not in scope** for this audit
drain and remain as follow-up tasks in their respective per-task reports.

## Files produced

30 audit files in this directory:

- `00_INDEX.md` — executive summary + methodology
- `t_<id>__<slug>.md` — 29 per-task audit reports, one per kanban task
- `_generate.sh` — shell script that generated the per-task reports

Total: ~692 lines of audit documentation committed to the repo.

## Push info

- 1 commit pushed: `ac2408e` ("audit(brain-audit): initial 6-task batch…")
- Push target: `origin main` → `camster91/ai-billing-audit`
- Subsequent kanban `complete` calls did not generate new file changes
  (audit reports were authored in a single batch); they only updated the
  kanban SQLite state.

## Board state at end of run

```
By status:
  triage    0
  todo      0
  scheduled 0
  ready     0    ← was 29 at start
  running   0
  blocked   0
  done      30   ← was 1 at start (29 by this drain + 1 pre-existing)
```