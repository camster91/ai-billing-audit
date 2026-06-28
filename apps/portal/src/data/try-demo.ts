// apps/portal/src/data/try-demo.ts
//
// Canned data for the public /try demo page (research/P0-PRODUCT-ROADMAP.md
// W1.1, Gap #9 in research/P6-product-gaps.md).
//
// Why static + canned (no FastAPI auditor call):
// - /try is a marketing surface, not a real tool. Cold-outreach prospects need
//   to see Zorva's output in <30s without uploading PHI. A real auditor call
//   takes 40s+ per encounter + requires Ollama up.
// - Deterministic: same canned findings every render. Lets us A/B test
//   page copy without auditor variance.
// - Decoupled from FastAPI production: demo works even if FastAPI is down.
// - Compliance: HIA s.64 doesn't apply because no real PHI crosses the wire.
//
// Source provenance:
// - Encounter data: data/synth/val_ca.json (encounter_id ca_ahcip_002 — chosen
//   because it has 3 v12 predictions: 1 informational + 2 medium-severity
//   findings, the most-compelling single-encounter demo)
// - Predicted findings: runs/recall/v12_ahcip_clean.json
//   (per-encounter predictions from a real v12 run on 2026-06-22)
// - Encounter id, clinical_note, claim, and the 3 findings match the v12
//   output verbatim. No cherry-picking.

export interface CannedFinding {
  rule_id: string;
  category: string;
  severity: "info" | "low" | "medium" | "high" | "critical";
  quote: string;
  explanation: string;
}

export interface CannedDemoEncounter {
  encounter_id: string;
  market: string;
  province: string;
  compliance_law: string;
  clinical_note: string;
  claim: {
    som_b_codes: string[];
    diagnosis_codes: string[];
    modifier: string | null;
    patient_health_number: string;
    referring_provider_npi: string | null;
    date_of_service: string;
  };
}

export interface CannedDemo {
  source: "synthetic";
  pick_rationale: string;
  encounter: CannedDemoEncounter;
  findings: CannedFinding[];
}

export const TRY_DEMO: CannedDemo = {
  source: "synthetic",
  pick_rationale:
    "Ca_ahcip_002 has 3 v12 predicted findings (1 informational, 2 medium-severity) — the most-compelling single-encounter demo in the val_ca set.",
  encounter: {
    encounter_id: "ca_ahcip_002",
    market: "CA",
    province: "AB",
    compliance_law: "PIPEDA",
    clinical_note:
      "New patient consultation, referred by Dr. Smith for hypertension management. BP 168/102, HR 84. No end-organ damage. Started amlodipine 5mg daily. Follow-up in 4 weeks.",
    claim: {
      som_b_codes: ["03.04A"],
      diagnosis_codes: ["I10"],
      modifier: null,
      patient_health_number: "987654321",
      referring_provider_npi: null,
      date_of_service: "2026-05-18",
    },
  },
  findings: [
    {
      rule_id: "rule_ahcip_em_level",
      category: "evaluation",
      severity: "info",
      quote:
        "New patient consultation, referred by Dr. Smith for hypertension management. BP 168/102, HR 84. No end-organ damage. Started amlodipine 5mg daily. Follow-up in 4 weeks.",
      explanation:
        "The note documents a new patient encounter with a single chronic problem (hypertension), focused exam, medication initiation, and a follow-up plan. The note does not use brief/minor/limited/quick language, so 03.04A comprehensive assessment is consistent with the documentation. No change to the E/M level is required.",
    },
    {
      rule_id: "rule_ahcip_referring_npi",
      category: "consultation",
      severity: "medium",
      quote: "referred by Dr. Smith for hypertension management",
      explanation:
        "The clinical note explicitly documents a referral from Dr. Smith, but the claim has referring_provider_practitioner_id = null. Because the visit is described as a 'consultation' for a referred new patient, this is both a data-population issue and a possible code-choice opportunity: if the visit is intended as a formal specialist consultation, it should be billed as 03.03A (which requires the referring provider's practitioner ID on the claim) rather than 03.04A. Populate Dr. Smith's Alberta practitioner ID on the claim, and confirm with the physician whether the service was a one-time consultation opinion (03.03A) or an assumption-of-care comprehensive assessment (03.04A).",
    },
    {
      rule_id: "rule_ahcip_cmgp",
      category: "modifier",
      severity: "medium",
      quote:
        "referred by Dr. Smith for hypertension management. BP 168/102, HR 84. No end-organ damage. Started amlodipine 5mg daily.",
      explanation:
        "The patient has documented essential hypertension (I10), a qualifying chronic condition for the CMGP (chronic disease management general premium), with active medication management (amlodipine 5mg daily initiated at this visit). 03.04A is billed and the modifier field is null. Append the CMGP modifier to the 03.04A claim to capture the chronic disease management premium.",
    },
  ],
};
