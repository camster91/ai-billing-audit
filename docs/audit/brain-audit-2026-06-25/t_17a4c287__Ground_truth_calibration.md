# t_17a4c287 — Ground_truth_calibration

**Audit claim:** Ground-truth review: 20 hand-verified encounters for calibration

**Evidence:**
- `src/ai_billing_audit/ground_truth.py` exists (13 references found via grep)
- No `data/ground_truth/hand_verified.jsonl` (`find data -name '*.jsonl'` → only demo registries)
- `docs/CALIBRATION.md` exists but its date/scope unclear

**Verdict:** **missing** — ground_truth.py module exists but the 20 hand-verified encounter set is not committed to the repo. Calibration claims cannot be reproduced from HEAD.

**Recommended follow-up:** Author the 20-encounter hand-verified set as `data/ground_truth/hand_verified_v1.jsonl` with schema {encounter_id, billed_codes, correct_codes, modifier_set, expected_findings} and wire it into the calibration harness.
