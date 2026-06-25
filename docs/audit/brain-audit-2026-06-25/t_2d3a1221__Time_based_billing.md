# t_2d3a1221 — Time_based_billing

**Audit claim:** Time-based billing (critical care, prolonged services, psychotherapy)

**Evidence:**
- `rules/seed_rules.json` EM-003: time ranges for 99202-99215
- v12 prompt mentions 08.19A (psychotherapy 45-min) and 08.19B (30-min)
- No critical-care-specific rules (99291/99292) in v12
- No prolonged-services (99417/G2212) rule in seed

**Verdict:** **partial** — E/M time ranges ARE present (EM-003); AHCIP psychotherapy time codes ARE in v12; missing: critical care time thresholds, US prolonged-services codes, and a time-tracking assertion in the prompt that ties documentation time-statement to the chosen level.

**Recommended follow-up:** Add critical-care (99291/99292, ≥30/≥74 min) and prolonged-services (99417, G2212) rules to `rules/seed_rules.json` and add a 'time statement required when billing by time' assertion.
