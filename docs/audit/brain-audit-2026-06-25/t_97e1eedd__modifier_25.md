# t_97e1eedd — Modifier-25 deep-dive

**Audit claim:** Modifier -25 (separately identifiable E/M) is the #1
denial reason. Audit must catch missing -25 on E/M + procedure same day,
and overused -25 on E/M that isn't separately identifiable.

**Evidence:**
- `grep -c "modifier" rules/seed_rules.json` → **31 hits**
- Rules referencing modifier -25 specifically:
  - "second visit is typically reported with modifier -25 on the E/M code when a separately identifiable service is performed on the same day as a procedure" (EM bundle rule)
  - "Preventive medicine codes ... append modifier -25 to the preventive code"
  - "An E/M code (99202-99215) reported on the same date of service as a procedure ... is generally not separately payable without modifier -25"
- `prompts/v12/auditor_prompt.txt`: 14 hits for "25" but **none are
  specifically framed as a -25 modifier rule with positive AND negative
  examples**.
- No file: `prompts/v0/modifier25_examples.txt` (does not exist).

**Verdict:** **partial** — modifier -25 IS in seed rules and referenced in
the prompt, but no dedicated 30-example set, no overused-25 detector, and
no 20-encounter test set.

**Recommended follow-up:** Create `prompts/v0/modifier25_examples.txt`
with 30 labeled examples (10 missing-25, 10 overused-25, 10 correct-25),
add a test fixture, and add a per-clinic metric for -25 denials.