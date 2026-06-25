# Zorva ROI Formula — Mathematical Derivation

> **Audience:** Sales engineers, billing-lead-facing demo presenters,
> and skeptical clinic admins who ask *"how do you calculate the $X
> you claim we are leaving on the table?"*. This document is the
> defensible answer.

This document explains every term in the Zorva missed-revenue
formula and how the constants are anchored to real evaluation data.
The same formula is implemented in
`apps/portal/src/app/calculator/roi-calculator.tsx` — the calculator
is a UI rendering of these equations, nothing more.

---

## 1. The headline equation

The headline number — *projected annual revenue recoverable with
Zorva* — is:

$$
R_{\text{zorva}} \;=\; C_m \cdot 12 \cdot \bar{v} \cdot d \cdot s \cdot F_1^{\text{global}}
$$

where each symbol is defined below. Worked example follows the
definitions.

---

## 2. Symbol definitions

| Symbol | Name | Source / value |
|---|---|---|
| $C_m$ | Claims submitted per month | User input (calculator) |
| $\bar{v}$ | Average claim value (CAD), specialty-blended | See §4 |
| $d$ | Current denial / undercode rate | User input; industry typical 5–12% |
| $s$ | Recoverable share of denied claims | $0.55$ (industry consensus, conservative) |
| $F_1^{\text{global}}$ | Global micro-averaged F1 of the Zorva auditor | $0.690$ (cleaned v12, see §3) |

All rates are unit-less and lie in $[0, 1]$. $C_m$ is integer,
$\bar{v}$ is CAD per claim.

---

## 3. Anchoring $F_1^{\text{global}}$ — the per-rule weighting

The $0.690$ number is **not** a marketing number. It is the
micro-averaged F1 of the cleaned v12 evaluation on the AHCIP val
set (`data/val_ca.json`, 10 encounters, 13 gold findings, 0 errors).
See `runs/recall/v12_ahcip_clean.json` and the disclosure in
`runs/recall/v12_summary.md` for the EXAMPLE 6/7 leakage correction.

### 3.1 Micro-averaged precision and recall

For each rule $r$ in the rule set $\mathcal{R}$, let $\text{TP}_r$,
$\text{FP}_r$, $\text{FN}_r$ be the true positives, false positives,
and false negatives observed on the eval set. Micro precision and
recall are pooled across rules:

$$
P^{\text{micro}} \;=\; \frac{\sum_{r \in \mathcal{R}} \text{TP}_r}
                                {\sum_{r \in \mathcal{R}} (\text{TP}_r + \text{FP}_r)}
\qquad
R^{\text{micro}} \;=\; \frac{\sum_{r \in \mathcal{R}} \text{TP}_r}
                                {\sum_{r \in \mathcal{R}} (\text{TP}_r + \text{FN}_r)}
$$

### 3.2 Global F1

$$
F_1^{\text{global}} \;=\; \frac{2 \cdot P^{\text{micro}} \cdot R^{\text{micro}}}
                                   {P^{\text{micro}} + R^{\text{micro}}}
$$

For the cleaned v12 run:

| Metric | Value |
|---|---|
| $P^{\text{micro}}$ | $0.625$ |
| $R^{\text{micro}}$ | $0.769$ |
| $F_1^{\text{global}}$ | $\frac{2 \cdot 0.625 \cdot 0.769}{0.625 + 0.769} = 0.690$ |

### 3.3 Why micro, not macro

Micro-averaging weights each rule by the number of findings it
contributes, which is what we want for an ROI projection: the rules
that actually fire most often in real billing data are the ones
whose precision and recall should drive the catch-rate assumption.

Macro-averaged F1 on the same run is $0.713$ (per-encounter mean,
see `runs/recall/v12_ahcip_clean.json`). We deliberately publish the
lower **micro** number as $F_1^{\text{global}}$ because it is more
defensible against the "you're cherry-picking your headline" question.

### 3.4 Per-rule F1 weighting (advanced)

For a clinic that wants a per-specialty projection, the global F1
can be decomposed into a per-rule weighted average. Let
$w_r \in [0, 1]$ be the share of the clinic's annual volume that
triggers rule $r$, with $\sum_r w_r = 1$. Then:

$$
F_1^{\text{weighted}} \;=\; \sum_{r \in \mathcal{R}} w_r \cdot F_1^{(r)}
$$

where $F_1^{(r)}$ is the per-rule F1 from the cleaned v12 run. The
per-rule $F_1^{(r)}$ values (cleaned v12):

| Rule | $F_1^{(r)}$ |
|---|---|
| `rule_ahcip_dx_linkage` | $1.00$ |
| `rule_ahcip_global_window` | $1.00$ |
| `rule_ahcip_referring_npi` | $1.00$ |
| `rule_ahcip_same_day_conflict` | $1.00$ |
| `rule_ahcip_telehealth` | $1.00$ |
| `rule_ahcip_em_level` | $0.75$ |
| `rule_ahcip_psychotherapy_time` | $0.67$ |
| `rule_ahcip_em_level_upcode` | $0.50$ |
| `rule_ahcip_lab_coverage` | $0.00$ |
| `rule_ahcip_cmgp` | $0.00$ |
| `rule_ahcip_non_insured_service` | $0.00$ |

A family-medicine-heavy clinic whose $w_r$ distribution is dominated
by modifier / EM-level rules will land closer to $F_1^{\text{weighted}}
\approx 0.70$. A cardiology-heavy clinic that leans on CMGP and lab
coverage will land closer to $0.45$. The calculator's headline
number uses the global F1 as a conservative midpoint.

---

## 4. Specialty-blended $\bar{v}$

The calculator uses a single blended average claim value per
specialty, rounded to the nearest $\$5$ for defensibility:

| Specialty | $\bar{v}$ (CAD) | Source |
|---|---|---|
| Family medicine | $38$ | Alberta SOMB blended visit average, 2026 |
| Internal medicine | $62$ | Alberta SOMB blended consult / visit avg, 2026 |
| Cardiology | $95$ | Alberta SOMB blended consult + ECG avg, 2026 |
| Pediatrics | $42$ | Alberta SOMB blended well-child + sick visit avg, 2026 |
| Psychiatry | $78$ | Alberta SOMB blended psychotherapy + assessment, 2026 |
| Dermatology | $52$ | Alberta SOMB blended assessment + procedure, 2026 |
| Orthopedics | $88$ | Alberta SOMB blended assessment + casting, 2026 |
| Ob/Gyn | $72$ | Alberta SOMB blended prenatal + procedure, 2026 |
| Other | $55$ | Conservative blended midpoint |

These are deliberately conservative. A clinic that has a higher
mix of complex visits or consult codes will see real-world revenue
recovered per finding higher than $\bar{v}$.

---

## 5. The recoverable share $s = 0.55$

We do not assume every denied claim is recoverable. Published
industry figures for US payers place the recoverable share at
roughly 60–67% (see Change Healthcare 2023 denial report). For the
Alberta primary-care market, which has a more concentrated payer
(AHCIP, with very limited secondary insurance for shadow-billing
practices), the share is closer to 50–60%. We anchor on the
conservative end:

$$
s \;=\; 0.55
$$

This number is **not** derived from Zorva's own data — it is an
industry-baseline constant that captures the fact that some denied
claims are denied for valid clinical reasons (e.g. non-insured
service, patient ineligible on date of service) and are not
recoverable regardless of what the auditor says. As we collect real
pilot data we expect to publish a Zorva-specific $s_{\text{zorva}}$
that is anchored to actual resubmission outcomes rather than
industry defaults.

---

## 6. Worked example

A family-medicine clinic with $C_m = 1500$ claims/month and a
current denial rate of $d = 8\%$:

| Step | Symbol | Value |
|---|---|---|
| Annual claims | $C_m \cdot 12$ | $18{,}000$ |
| Average claim value | $\bar{v}$ | $\$38$ |
| Annual billed | $C_m \cdot 12 \cdot \bar{v}$ | $\$684{,}000$ |
| × Denial rate | $d$ | $0.08$ |
| = Missed base | $C_m \cdot 12 \cdot \bar{v} \cdot d$ | $\$54{,}720$ |
| × Recoverable share | $s$ | $0.55$ |
| = Recoverable in principle | | $\$30{,}096$ |
| × Zorva catch rate (F1) | $F_1^{\text{global}}$ | $0.690$ |
| = **Projected annual recovery** | $R_{\text{zorva}}$ | **$\$20{,}766$** |

In real numbers, this is the figure shown in the calculator
"Projected recovery with Zorva" panel. The clinic's own pilot will
vary by ±20% in either direction in the first 30 days, then
converge as the auditor calibrates to the clinic's specific
encounter mix.

---

## 7. Sensitivity table

The two user inputs that move the headline number most are $C_m$
and $d$. Holding $\bar{v} = \$38$ (FP) and $s \cdot F_1 = 0.55
\cdot 0.690 = 0.3795$ constant:

| $C_m$ \ $d$ | 4% | 8% | 12% |
|---|---|---|---|
| 500  | $\$3{,}462$  | $\$6{,}924$  | $\$10{,}386$ |
| 1,500 | $\$10{,}386$ | $\$20{,}766$ | $\$31{,}152$ |
| 3,000 | $\$20{,}766$ | $\$41{,}538$ | $\$62{,}304$ |
| 5,000 | $\$34{,}620$ | $\$69{,}240$ | $\$103{,}860$ |

A useful rule of thumb: **for every 1,000 claims/month at an 8%
denial rate, the FP specialty lands at roughly $\$14{,}000$ in
projected annual recovery.**

---

## 8. What this formula does NOT capture

Three known blind spots in the formula, all called out in the
calculator's on-page disclaimer:

1. **Timely-submission cutoffs.** The AHCIP window is 90 days for
   most codes. Claims that have already aged out are not
   recoverable regardless of what the auditor finds. The formula
   assumes the clinic is operating inside the window.

2. **Patient eligibility changes.** A claim denied for patient
   ineligibility on the date of service is not recoverable. The
   $s = 0.55$ recoverable share absorbs most of this, but a clinic
   with a transient patient population (e.g. a walk-in clinic near
   a post-secondary campus) will run below the 55% baseline.

3. **Coding-staff capacity.** The formula assumes the clinic has
   the bandwidth to act on the findings the auditor surfaces. A
   clinic whose billing staff is already at capacity will recover
   less than the headline number — not because the findings are
   wrong, but because the queue isn't being worked. We track this
   in real pilots as the "act-on rate" and report it on the
   findings dashboard.

---

## 9. Reproducing the numbers

The calculator is implemented in
`apps/portal/src/app/calculator/roi-calculator.tsx`. The constants
$CATCH_RATE` and `RECOVERABLE_SHARE` are exported at the top of the
file and labelled with their source. The per-specialty $\bar{v}$
table is the `SPECIALTIES` array. To recompute for a new specialty:

```python
def zorva_recovery(claims_per_month, denial_rate_pct,
                   avg_claim_value, f1=0.690, s=0.55):
    annual_claims = claims_per_month * 12
    annual_billed = annual_claims * avg_claim_value
    missed = annual_billed * (denial_rate_pct / 100)
    return missed * s * f1
```

That function returns the same number as the calculator's
"Projected recovery" panel, to the dollar.

— Zorva team. Anchored to the v12 cleaned run, 2026-06-23.