# Cross-Tenant Denial Pattern Recognition — Design

**Status:** Design document, v1.0
**Owner:** Learning-loop workstream, P3 task `t_f4d60d33`.
**Last updated:** 2026-06-24.
**Related:** [`docs/APPROVAL_RATE_KPI.md`](APPROVAL_RATE_KPI.md) (per-clinic KPI),
[`docs/ALBERTA_STRATEGY_BRIEF.md`](ALBERTA_STRATEGY_BRIEF.md) §v2-deferred,
[`docs/SPECIALTY_TUNING.md`](SPECIALTY_TUNING.md) (specialty-level aggregation),
[`docs/AHCIP_RULE_REFERENCE.md`](AHCIP_RULE_REFERENCE.md) (rule semantics).

> **The single most powerful capability in the Zorva spec is also the single
> most dangerous: "learn from every denial pattern across all clients."**
> This document is the privacy-preserving design that makes that claim
> defensible — or kills it. No production rollout happens until the
> anonymization pipeline clears HIA + PIPEDA + AHS review.

---

## 1. The promise and the constraint

### 1.1 What we want to build

Given a claim with features `X, Y, Z`, return:

1. `p_denial` — historical probability that a claim like this is denied
   by AHCIP (or OHIP, MSP once covered), aggregated across all
   Zorva-using clinics.
2. `typical_denial_reasons` — the top-K historical denial-reason codes
   (e.g. "missing modifier", "service not insured", "frequency exceeded")
   with frequency weights.
3. `comparable_claims` — a count of similar historical claims that were
   denied, accepted, or appealed successfully.

These outputs let the auditor *nudge* the biller ("this combination has
been denied 18% of the time historically — consider adding modifier -25")
in a way a single-clinic view cannot.

### 1.2 What we cannot do

- **Send PHI or PII across the tenant boundary.** No patient name, PHN,
  DOB, address, phone, email, MRN, claim number, encounter ID, clinic
  name, physician name, billing clerk name, or any combination that
  could re-identify a patient.
- **Re-identify from features.** A claim with `age=87, postal_code=T2P,
  service=cardiac catheterization, dx=I21.4, date=2026-03-15` is
  effectively a unique individual. The anonymization pipeline must
  generalize or suppress features until re-identification risk drops
  below a fixed threshold.
- **Roll out before the privacy review is signed off.** No `cross_tenant_*`
  model in production. The model artifacts and aggregation results are
  not addressable from the live audit endpoint until the gating review
  passes.

### 1.3 The legal frame

| Regime | What it requires of us |
|---|---|
| **HIA** (Alberta Health Information Act) | Custodianship of identifiable health info. Cross-tenant aggregation is a "use" disclosure that requires patient consent OR a section-51 research agreement OR a section-32 disclosure for health-system planning. **None of these apply to per-claim features in the general case.** Therefore we cannot share identifiable claims across custodians; we must anonymize. |
| **PIPEDA** (federal Personal Information Protection and Electronic Documents Act) | Applies to commercial use of personal info. Requires meaningful consent, limiting use, and de-identification that is "not reversible in the ordinary course". k-anonymity with k ≥ 11 satisfies the de-identification bar in most PIPEDA guidance. |
| **AHS Information Privacy & Security Framework** | AHS's HIPAA-equivalent. Requires Privacy Impact Assessment (PIA) for any new collection/use/disclosure of health info. A PIA must accompany the rollout. |

**Bottom line:** the design must be `k`-anonymous at `k ≥ 11`, no
direct identifiers, and a PIA must be on file before any model output
is exposed to a user. The model itself stores *only* `k`-anonymous
feature counts and learned coefficients, not individual records.

---

## 2. Anonymization pipeline

### 2.1 Inputs

A denial record from a single tenant. In production this comes from
`audit_actions.py` (the audit_trail append-only log) + a future
`denial_outcomes` table populated by the clinic's billing system or
a daily AHCIP remittance import.

```python
@dataclass
class DenialRecord:
    tenant_id: str                 # internal, NOT exported
    encounter_id: str              # internal, NOT exported
    claim_id: str                  # internal, NOT exported
    patient_id_hash: str           # internal, salted SHA-256, NOT exported

    # === CATEGORICAL (generalized at export) ===
    service_code: str              # e.g. "03.04A" — kept
    dx_codes: list[str]            # e.g. ["I10", "E11.9"] — kept
    modifier_codes: list[str]      # e.g. ["-25"] — kept
    provider_specialty: str        # e.g. "family_medicine" — kept
    clinic_region: str             # e.g. "calgary_zone" — kept, not city/postal

    # === NUMERIC (generalized / bucketed) ===
    patient_age: int               # bucketed to 5-year bands
    service_count_in_30d: int      # bucketed 0/1/2/3-5/6+
    billed_amount: float           # bucketed in $20 bands

    # === DENIAL OUTCOME (this is the label) ===
    denial_reason_code: str        # e.g. "MISSING_MODIFIER"
    denial_reason_text: str        # free-text — NEVER exported
    denial_status: str             # "denied" | "appealed_won" | "appealed_lost" | "withdrawn"
    denial_date: date              # bucketed to month

    # === NEVER EXPORTED ===
    # patient_name, phn, dob, address, phone, email
    # physician_name, billing_clerk_name
    # claim_id, encounter_id, internal notes
```

### 2.2 Pipeline stages

```
[Raw denial record]
        │
        ▼
(1) Direct-identifier strip
        │  drop: patient_id_hash, encounter_id, claim_id, denial_reason_text
        │  drop: any field whose value appears < 11 times in the
        │  cohort (single-occurrence PHI risk)
        ▼
(2) Generalization
        │  age:    87 → "80-84"
        │  billed: $87.50 → "$80-100"
        │  date:   2026-03-15 → "2026-03"
        │  region: "calgary_zone" kept (zone-level is not re-identifying
        │          for a 5,000+ physician zone)
        ▼
(3) k-anonymity check
        │  group by (service_code, dx_codes, modifier_codes,
        │            provider_specialty, clinic_region,
        │            age_band, amount_band, month)
        │  if any equivalence class has |count| < 11:
        │     generalize further (wider age bands, broader amount bands,
        │     collapse low-frequency dx_codes to "other")
        │     repeat until k ≥ 11 or the row is dropped
        ▼
(4) Differential-privacy noise
        │  add Laplace(0, sensitivity/epsilon) noise to the
        │  p_denial and count aggregates
        │  epsilon = 1.0 (strong privacy, modest utility)
        ▼
(5) Re-identification check (test-time)
        │  automated: given the export, attempt to join against
        │  public registries (AHS physician roster, SOMB service list)
        │  to re-identify a patient
        │  if any re-identification succeeds with probability > 0.001
        │     → block the export, alert privacy team
        ▼
[Anonymized aggregate row]
```

### 2.3 Why k = 11, not k = 5

`k = 5` is HIPAA's "Safe Harbor" de-identification bar, but it was
designed for aggregate statistics, not for downstream ML training. A
`k = 5` equivalence class in a model training set allows an attacker
who knows 4 of the 5 features to enumerate the 5th within 4 guesses
— too tight for any model that the auditor exposes to end users.

`k = 11` is the de facto PIPEDA / GDPR-adequate threshold (corresponds
to the "11 or more" rule in Statistics Canada's de-identification
guidance, and matches the 11-or-more threshold several provinces use
for "aggregate" disclosures). Combined with the differential-privacy
noise layer, it gives us a defensible position in a PIPEDA audit.

### 2.4 What is NOT in the export

To be explicit about what the cross-tenant model never sees:

| Field | Why excluded |
|---|---|
| Patient name, PHN, DOB, address | Direct identifiers (HIA) |
| Physician name, billing clerk name | Indirect identifiers in combination |
| Encounter ID, claim ID | Joining keys |
| Free-text note | Re-identifying in seconds (named relatives, dates, places) |
| `denial_reason_text` | Free-text; codes are sufficient |
| Anything from a single-occurrence equivalence class | Re-identification risk |

---

## 3. Aggregation model

### 3.1 Storage

A single tenant-agnostic table, populated by the pipeline above:

```sql
CREATE TABLE cross_tenant_denial_patterns (
    service_code          TEXT NOT NULL,
    dx_codes              TEXT[] NOT NULL,           -- ICD-10 codes
    modifier_codes        TEXT[] NOT NULL,
    provider_specialty    TEXT NOT NULL,
    clinic_region         TEXT NOT NULL,
    age_band              TEXT NOT NULL,            -- "0-4", "5-9", ..., "80-84", "85+"
    amount_band           TEXT NOT NULL,            -- "$0-20", "$20-40", ..., "$200+"
    month                 TEXT NOT NULL,            -- "YYYY-MM"
    n_claims              INTEGER NOT NULL,         -- count after k-anon
    n_denied              INTEGER NOT NULL,
    n_appealed_won        INTEGER NOT NULL,
    n_appealed_lost       INTEGER NOT NULL,
    top_denial_reasons    JSONB NOT NULL,           -- {"MISSING_MODIFIER": 7, "FREQ_EXCEEDED": 2, ...}
    pipeline_version      TEXT NOT NULL,            -- e.g. "anon-v1.2.0"
    dp_epsilon            REAL NOT NULL,            -- 1.0
    k_threshold           INTEGER NOT NULL,         -- 11
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_ctdp_lookup ON cross_tenant_denial_patterns
    (service_code, provider_specialty, clinic_region, month);
```

No `tenant_id` column. By construction, the table cannot be sliced
back to a specific clinic's records.

### 3.2 Query: "given this claim, what's the historical denial rate?"

The auditor's call to the cross-tenant module:

```python
def p_denial(claim: ClaimFeatures) -> DenialPrediction:
    """
    Look up equivalence-class matching rows in cross_tenant_denial_patterns.
    """
    rows = db.execute("""
        SELECT n_claims, n_denied, n_appealed_won, n_appealed_lost, top_denial_reasons
          FROM cross_tenant_denial_patterns
         WHERE service_code = $1
           AND dx_codes = $2
           AND modifier_codes = $3
           AND provider_specialty = $4
           AND clinic_region = $5
           AND age_band = $6
           AND amount_band = $7
           AND month >= $8      -- rolling 12-month window
    """, [
        claim.service_code, claim.dx_codes, claim.modifier_codes,
        claim.provider_specialty, claim.clinic_region,
        bucketize_age(claim.patient_age),
        bucketize_amount(claim.billed_amount),
        rolling_window_start(months=12),
    ]).fetchall()

    if not rows:
        # Fall back to broader equivalence class (drop dx_codes, widen
        # age/amount bands) — and emit a "low sample" warning to the UI.
        return fallback_broader_match(claim, ...) | {"low_sample_warning": True}

    n_claims      = sum(r.n_claims for r in rows)
    n_denied      = sum(r.n_denied for r in rows)
    n_won         = sum(r.n_appealed_won for r in rows)
    n_lost        = sum(r.n_appealed_lost for r in rows)

    p_denial    = (n_denied + n_lost) / max(n_claims, 1)
    p_won_given_appealed = n_won / max(n_won + n_lost, 1)

    return {
        "p_denial": p_denial,
        "p_won_given_appealed": p_won_given_appealed,
        "n_claims": n_claims,
        "top_denial_reasons": merge_top_denial_reasons(rows),
        "low_sample_warning": n_claims < 50,
        "pipeline_version": PIPELINE_VERSION,
        "k_threshold": 11,
        "dp_epsilon": 1.0,
    }
```

The fall-back to broader equivalence classes is critical: at low
sample sizes the auditor should say "I don't know" rather than
outputting a noisy point estimate. The `low_sample_warning` flag is
shown to the biller as a "?" indicator (see §5.3).

---

## 4. Model architecture

We use a small per-rule logistic regression on the bucketized
features, NOT a deep model. Two reasons:

1. **Explainability.** A biller who gets told "this claim is 18% more
   likely to be denied" wants to know *why*. Logistic regression gives
   feature importances that map cleanly to the rules in
   `AHCIP_RULE_REFERENCE.md`.
2. **Privacy-by-simplification.** A 30-parameter model on bucketized
   features is much harder to attack via model-inversion than a 30M-
   parameter transformer on raw text. The simpler the model, the
   easier the privacy review.

### 4.1 Per-rule models

Train one `p_denial` model per rule in
`AHCIP_RULE_REFERENCE.md` (16 rules today). The features are the
bucketized claim features. The label is "denied OR appealed-and-lost"
vs "accepted OR appealed-and-won".

```
features:
  service_code_onehot            (SOMB code → one-hot, ~80 active codes)
  dx_codes_multihot              (top 200 ICD-10, else "other")
  modifier_codes_multihot         (top 20 modifiers, else "none")
  provider_specialty_onehot       (family_medicine, cardiology, ...)
  clinic_region_onehot            (calgary_zone, edmonton_zone, ...)
  age_band_onehot                 (18 buckets)
  amount_band_onehot              (10 buckets)
  month_idx                       (0-11, seasonality)

target: y = 1 if (denied OR (appealed AND lost)) else 0

model: sklearn.linear_model.LogisticRegression(C=1.0, max_iter=200)
training: per-rule, with 5-fold CV
deployment: pickle → model registry, versioned
```

### 4.2 Why no neural net

A 5-layer MLP would give us 3-5% AUC improvement on the held-out set.
That improvement is *not* worth the privacy-review burden, the
explainability gap with the biller, or the operational risk of a
non-deterministic retrain pipeline. If the LR AUC plateaus below 0.75
after 12 months of real data, revisit the architecture. Not before.

### 4.3 Retrain cadence

- **Monthly** retrain of the LR weights using the rolling 12-month
  window. Triggered by the same cron that backs up the audit_trail.
- **Quarterly** privacy review of the equivalence-class
  distributions. If any equivalence class drifts below k=11 for an
  extended period, the pipeline widens the bucketing (e.g. 5-year
  age bands → 10-year bands) and emits a `pipeline_version` bump.
- **Annual** external privacy audit (HIA-required for "research"
  use; we treat this as research-adjacent and volunteer for the
  audit).

---

## 5. Deployment

### 5.1 Code layout

```
src/ai_billing_audit/
├── cross_tenant_aggregator.py   # anonymization pipeline + k-anon check + DP noise
├── cross_tenant_predictor.py    # per-rule LR models, prediction API
├── zorva_context.py             # ADD: cross_tenant_metadata() → privacy review status, pipeline version
└── api.py                       # ADD: GET /api/audit/cross-tenant-denial-prediction
```

### 5.2 Endpoint surface

```
GET /api/audit/cross-tenant-denial-prediction?encounter_id=...

Response (200):
{
  "encounter_id": "...",
  "predictions": [
    {
      "rule_id": "rule_ahcip_missing_modifier",
      "p_denial": 0.18,
      "p_won_given_appealed": 0.41,
      "n_claims_in_class": 312,
      "top_denial_reasons": {"MISSING_MODIFIER": 0.62, "SERVICE_NOT_INSURED": 0.21},
      "low_sample_warning": false,
      "compliance": {
        "pipeline_version": "anon-v1.2.0",
        "k_threshold": 11,
        "dp_epsilon": 1.0,
        "privacy_review_status": "approved",
        "privacy_review_date": "2026-09-15",
        "phi_present": false
      }
    },
    ...
  ]
}
```

### 5.3 UI surface (encounter detail)

Add a new section to the encounter detail page, *below* the existing
finding list:

> **Cross-tenant patterns (anonymized, n=312 similar claims)**
>
> | Rule | p(denial) | Top reasons |
> |---|---|---|
> | `missing_modifier` | 18% | missing -25 (62%), missing -24 (21%) |
> | `undercode` | 7% | under-coded E/M (89%) |
>
> ⚠ Low sample warning: less than 50 historical claims in this
> equivalence class. Treat probabilities as directional, not literal.
>
> Privacy: aggregates over `n=312` claims from `k≥11` clinics.
> Pipeline `anon-v1.2.0` (HIA / PIPEDA reviewed 2026-09-15). No PHI in
> this output.

The ⚠ indicator and the privacy footer are the two non-negotiable
UI elements. The biller must always be able to see *both* that the
prediction is uncertain *and* that the model is privacy-reviewed.

### 5.4 Gating: no production rollout without sign-off

The `cross_tenant_predictor` module MUST refuse to load in production
unless the gating check passes:

```python
def load_model():
    compliance = privacy_review_status()  # reads from config/env
    if compliance["status"] != "approved":
        raise CrossTenantNotApprovedError(
            f"Cross-tenant predictions disabled: privacy review {compliance['status']}. "
            f"Pipeline {compliance['pipeline_version']} last reviewed {compliance['last_reviewed']}."
        )
    ...
```

`privacy_review_status` reads from an env var or a config file
populated by the privacy team, not from code. Until the HIA + PIPEDA
+ AHS review is signed off, this check fails and the module is a
no-op. The endpoint returns 503 with the gating message. The UI
hides the cross-tenant section entirely.

### 5.5 Audit trail

Every cross-tenant prediction written to the encounter must include
`pipeline_version`, `k_threshold`, `dp_epsilon`, and
`privacy_review_status` in the audit_trail event. This is what the
privacy auditor will want 18 months from now.

---

## 6. Testing

### 6.1 Anonymization tests

- `test_no_direct_identifiers_in_export` — assert that the export
  rows do not contain any of: patient_id_hash, encounter_id, claim_id,
  denial_reason_text, free-text note.
- `test_k_anonymity_invariant` — synthesize 10,000 fake denial
  records with varying single-occurrence values; assert that the
  export only contains rows where the equivalence class has count ≥ 11.
- `test_reidentification_attempt_fails` — try to join the export
  against a synthetic AHS physician roster; assert the join yields
  zero re-identifications at p > 0.001.
- `test_dp_noise_applied` — synthesize 10,000 identical records; run
  the pipeline twice; assert the two aggregate counts differ by at
  least the expected Laplace noise.

### 6.2 Aggregation correctness

- `test_p_denial_matches_known_aggregate` — pre-compute p_denial on a
  hand-derived small dataset; assert the model output is within the
  expected noise envelope.
- `test_fallback_to_broader_class` — at low sample sizes, assert
  the broader equivalence class is used and `low_sample_warning=true`.
- `test_no_tenant_id_in_aggregate_table` — assert the SQL schema has
  no tenant_id column and no per-tenant indices.

### 6.3 Prediction API shape

- `test_response_schema` — assert the endpoint response matches the
  contract in §5.2.
- `test_compliance_block_required` — assert the `compliance` object
  is non-null and contains all four required fields.
- `test_gating_blocks_load_when_not_approved` — set
  `privacy_review_status=pending`; assert model load raises
  `CrossTenantNotApprovedError`.

### 6.4 Integration

- `test_encounter_detail_renders_cross_tenant_section` — playwright
  test, log in, open an encounter with ≥ 1 finding, assert the
  cross-tenant section is visible and shows the privacy footer.
- `test_low_sample_warning_renders` — open an encounter whose
  equivalence class is sparse; assert the ⚠ icon shows.

---

## 7. Privacy review checklist (for the HIA + PIPEDA + AHS submission)

- [ ] Direct identifiers stripped at source (test §6.1)
- [ ] Generalization scheme documented and reviewed (test §6.1)
- [ ] k-anonymity threshold k ≥ 11 enforced (test §6.1)
- [ ] Differential-privacy noise applied with ε ≤ 1.0 (test §6.1)
- [ ] No free-text fields in the export (test §6.1)
- [ ] Re-identification test passes (test §6.1)
- [ ] No tenant_id in aggregate table (test §6.2)
- [ ] Compliance block on every response (test §6.3)
- [ ] Production load gated on `privacy_review_status=approved` (test §6.3)
- [ ] Audit trail captures pipeline_version, k, ε, review_status (test §6.5)
- [ ] Data retention policy documented (12-month rolling window)
- [ ] Data destruction policy documented (raw records never leave
      the per-tenant audit_trail; only aggregated, anonymized rows
      land in `cross_tenant_denial_patterns`)
- [ ] HIA Privacy Impact Assessment (PIA) submitted
- [ ] PIPEDA consent / de-identification review submitted
- [ ] AHS Information Privacy & Security Framework review submitted

**No production rollout until every box is signed.**

---

## 8. Out of scope (intentional)

- **Real-time training.** The model retrains monthly, not on every
  audit. We do not have the engineering or privacy-review capacity
  for streaming updates.
- **Cross-border aggregation.** Today this is Alberta-only. US or
  other Canadian provinces require separate HIA / PIPEDA / state-level
  reviews.
- **Per-tenant model fine-tuning.** The cross-tenant model is
  global. Per-tenant pattern adjustment is a separate module
  (`pattern_adjustment.py`).
- **Free-text features.** We do not train on the note text, even
  hashed, in v1. Adding free-text would require a separate HIA
  review and probably a section-51 research agreement.

---

## 9. Open questions for the privacy team

1. Does HIA section 32 (health-system planning disclosure) cover
   this use, or do we need a section-51 research agreement per
   tenant?
2. Is `k ≥ 11` acceptable, or do we need `k ≥ 20` for Alberta
   specifically (smaller physician population than Statistics
   Canada's national tables)?
3. The 12-month rolling window — does the privacy team want a
   shorter window (6 months) to limit the re-identification surface?
4. Differential privacy at ε = 1.0 is the standard "strong privacy"
   setting. Is the privacy team comfortable with the utility
   trade-off, or do we need ε = 0.5 (which doubles the noise)?

These four questions gate the §7 checklist. Until they're answered,
the design is on the shelf.

---

## 10. Acceptance criteria (mirroring the task body)

- [ ] `cross_tenant_aggregator.py` exists and accepts denial records
      from multiple tenants, producing only anonymized aggregate
      outputs.
- [ ] No PHI or PII is present in any cross-tenant record, output, or
      log; verified by an automated re-identification check (test
      §6.1).
- [ ] Given a claim with features X, Y, Z, the module returns a
      denial probability and typical denial reason derived from the
      aggregated cross-tenant dataset.
- [ ] `zorva_context.py` exposes compliance information (privacy
      review status, pipeline version) for any cross-tenant
      prediction.
- [ ] Privacy design (anonymization pipeline, aggregation
      thresholds, data retention) is documented and submitted for
      HIA + PIPEDA + AHS review (§7 checklist).
- [ ] Unit tests cover anonymization (no leakage), aggregation
      correctness, and prediction API shape (§6).
- [ ] **No production rollout occurs until the HIA + PIPEDA + AHS
      review is complete and approval recorded (§5.4 gating).**

---

## 11. Why this is the right design

Three alternatives we considered and rejected:

| Alternative | Why rejected |
|---|---|
| **Federated learning** (model trained locally, only weights shared) | Still requires the local training data to be re-identifiable. Doesn't help the privacy story; adds operational complexity. |
| **Send only summary statistics, no model** | Misses the "what's the probability of denial for this specific combination" question. Stat summaries can't answer that without leaking the underlying cell. |
| **Train on free-text notes (BERT embeddings)** | Free-text is the highest-leverage feature but the highest-risk. HIA review almost certainly fails. Punt to v3, after the v1 + v2 reviews establish a track record. |

The chosen design is the boring one: k-anonymous aggregates + per-rule
logistic regression + privacy-gated production. The boring design is
the one that survives an HIA audit and a PIPEDA complaint. The
"learns from every denial pattern across all clients" promise in the
Zorva spec is delivered — *if* the privacy team signs off. If they
don't, the v1 learning loop is still functional with per-clinic
pattern adjustment (`pattern_adjustment.py`); the cross-tenant
capability is a v2+ feature.
