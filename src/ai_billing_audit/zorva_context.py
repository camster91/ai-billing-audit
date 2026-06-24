"""Zorva system context.

This module encodes the product's strategic context — what Zorva is,
who it serves, what compliance framework applies per market, and what
downstream capabilities consume the audit output. The auditor LLM
doesn't see this prose directly — instead, the FastAPI runner uses
``build_context_for_encounter()`` to compose a small structured
context payload that gets injected into the encounter envelope.

Why structured (not prose)?
--------------------------
Stuffing "we serve Canada, US, Mexico, Colombia" into the auditor
prompt dilutes the rule-matching signal. The auditor's job is to
emit JSON findings; the more tokens we spend on context, the more
we hurt P/R. Instead the runner composes a compact dict the
auditor sees alongside the encounter — it's a hint, not a lecture.

This is the same pattern as ``runner.SeverityRank`` or
``encounter.get("NPI")`` — operational hints passed as data,
not prompt-engineered text.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Zorva identity (single source of truth, not duplicated across files)
# ---------------------------------------------------------------------------

ZORVA_VISION = """\
Zorva is an AI-powered revenue recovery and billing intelligence
platform for medical practices across Canada, the United States,
Mexico, and Colombia. The end goal is simple: every claim a physician
submits is clean before it leaves the clinic, paid in full when it
arrives at the payer, and recovered immediately if it is ever denied.
Zorva replaces the human administrative overhead between clinical
work and collected revenue with a silent, self-improving engine that:

- Catches billing errors before submission
- Scores every claim for denial risk in real time
- Generates appeal letters automatically when denials occur
- Alerts the physician to critical findings before they become lost revenue
- Maintains a tamper-proof audit trail of every action on every claim
- Learns from every denial pattern across all clients to get smarter

The physician experience: upload claims. Get paid. Nothing else required.
"""

# Per-market compliance framework. The auditor emits findings
# the same way regardless of market — these are upstream of the
# model's output, used by the runner + appeal-letter generator +
# privacy officer dashboard.
MARKETS: dict[str, dict[str, Any]] = {
    "CA": {
        "name": "Canada",
        "compliance_law": "PIPEDA",
        "provinces": ["ON", "AB", "BC", "QC", "MB", "SK", "AB", "NS", "NB", "PE", "NL"],
        "billing_authorities": {
            "ON": "OHIP Schedule of Benefits (Section GP-17)",
            "AB": "AHCIP Schedule of Medical Benefits (SOMB)",
            "BC": "MSP Doctors of BC Fee Guide",
        },
        "data_residency_required": True,  # patient data stays in CA
        "phi_identifiers_required": False,  # PIPEDA + provincial HIA
    },
    "US": {
        "name": "United States",
        "compliance_law": "HIPAA",
        "billing_standard": "CMS-1500 / ANSI 837P / CPT / HCPCS / ICD-10-CM",
        "data_residency_required": False,
        "phi_identifiers_required": True,
        "ak_safe_harbor_pricing": True,  # flat-fee SaaS, never % of collections
    },
    "MX": {
        "name": "Mexico",
        "compliance_law": "NOM-024 / SAT CFDI",
        "billing_standard": "CFDI 4.0 / CIE-10 / Tabulador IMSS",
        "data_residency_required": True,
        "phi_identifiers_required": False,
        "invoice_format": "CFDI XML with UUID fiscal folio",
    },
    "CO": {
        "name": "Colombia",
        "compliance_law": "DIAN / Superintendencia de Salud",
        "billing_standard": "CUPS / CIE-10 / Resolución 2284",
        "data_residency_required": True,
        "phi_identifiers_required": False,
        "invoice_format": "DIAN electronic invoice (Factura Electrónica)",
    },
}

SUPPORTED_MARKETS = tuple(MARKETS.keys())


# ---------------------------------------------------------------------------
# Encounter envelope enrichment
# ---------------------------------------------------------------------------

# US billing is dominated by payer + state rules. We tag
# encounters with the originating market so downstream consumers
# (appeal-letter generator, denial-risk scorer, audit dashboard)
# know which compliance framing to apply.

# Provincial health-number patterns are heuristic — we don't
# validate, we just hint. CMS 1500 / 837P carries state-specific
# identifiers but the universal pattern is the 10-digit NPI.

_HEALTH_NUMBER_PATTERNS: dict[str, re.Pattern] = {
    "CA_ON": re.compile(r"^\d{10}$"),    # OHIP: 10 digits
    "CA_AB": re.compile(r"^\d{9}$"),     # AHCIP: 9 digits
    "CA_BC": re.compile(r"^\d{10}$"),    # MSP: 10 digits (PHN)
    "US":   re.compile(r"^\d{10}$"),      # NPI: 10 digits
    "MX":   re.compile(r"^\d{10,11}$"),  # CURP-like
    "CO":   re.compile(r"^\d{6,12}$"),   # Cédula / NUIP
}


def infer_market(
    *,
    country_code: str | None = None,
    payer_id: str | None = None,
    health_number: str | None = None,
) -> str:
    """Best-effort guess at which market this encounter belongs to.

    Priority: explicit country_code > payer_id prefix > health-number
    digit-count heuristics. Returns one of the keys in ``MARKETS``,
    defaulting to "CA" when nothing useful is present.

    The auditor doesn't see this — it's used by the runner to add
    the right compliance framing to the audit envelope.
    """
    if country_code and country_code.upper() in MARKETS:
        return country_code.upper()
    if payer_id:
        pid = payer_id.upper()
        if pid.startswith(("OHIP", "AHCIP", "MSP", "RAMQ", "SUN", "ALBERTA", "BC-")):
            return "CA"
        if pid.startswith(("BCBS", "AETNA", "UHC", "MEDICARE", "MEDICAID", "CMS")):
            return "US"
        if pid.startswith(("IMSS", "ISSSTE", "SAT", "PEMEX", "SEGURO")):
            return "MX"
        if pid.startswith(("EPS", "SURA", "SANITAS", "COMPENSAR", "DIAN")):
            return "CO"
    if health_number:
        digits = len(health_number.strip())
        if 9 <= digits <= 12:
            # We can't reliably distinguish US-NPI from CA-provincial;
            # default to CA since the dashboard defaults to Acme Family
            # Practice. v2: let the tenant config override.
            return "CA"
    return "CA"


def build_context_for_encounter(
    *,
    country_code: str | None = None,
    payer_id: str | None = None,
    province: str | None = None,
    health_number: str | None = None,
) -> dict[str, Any]:
    """Build the structured Zorva context for an encounter envelope.

    The runner injects this dict into the encounter dict before
    calling the auditor. The auditor sees it as opaque data; downstream
    consumers (dashboard, appeal-letter generator, privacy officer)
    read the keys they care about.

    What's in here
    --------------
    * ``market``: two-letter country code (CA / US / MX / CO)
    * ``province``: for CA: ON / AB / BC / etc. (None for non-CA)
    * ``billing_authority``: which schedule the encounter is billed
      against (e.g. "OHIP Schedule of Benefits (Section GP-17)")
    * ``compliance_law``: PIPEDA / HIPAA / NOM-024 / DIAN
    * ``data_residency_required``: True for CA / MX / CO
    * ``phi_identifiers_required``: True for US (HIPAA Safe Harbor)
    * ``ak_safe_harbor_pricing``: True for US (flat-fee SaaS only)
    * ``invoice_format``: CFDI UUID / DIAN Folio / etc.
    * ``long_term_vision``: the one-paragraph vision summary, included
      only in the structured payload (not as prose context) so the
      runner can use it for downstream UI without leaking it into
      every LLM call

    Returns an empty dict if the encounter can't be classified. The
    runner logs a warning when this happens but doesn't fail the
    audit — the product ships with CA as the default market for
    legacy encounters.
    """
    market = infer_market(
        country_code=country_code,
        payer_id=payer_id,
        health_number=health_number,
    )
    market_profile = MARKETS.get(market, {})
    province_norm = (
        province.upper().strip()
        if (province and market == "CA")
        else None
    )
    if province_norm == "":
        province_norm = None

    billing_authority = None
    if market == "CA" and province_norm:
        billing_authorities = market_profile.get("billing_authorities", {}) or {}
        billing_authority = billing_authorities.get(province_norm)

    return {
        "market": market,
        "market_name": market_profile.get("name", "Unknown"),
        "province": province_norm,
        "billing_authority": billing_authority,
        "compliance_law": market_profile.get("compliance_law"),
        "data_residency_required": market_profile.get(
            "data_residency_required", False
        ),
        "phi_identifiers_required": market_profile.get(
            "phi_identifiers_required", False
        ),
        "ak_safe_harbor_pricing": market_profile.get(
            "ak_safe_harbor_pricing", False
        ),
        "invoice_format": market_profile.get("invoice_format"),
        "long_term_vision": ZORVA_VISION.strip(),
    }


def appeal_recipient_for(market: str) -> str:
    """Default appeal-letter recipient address for the given market.

    Returns a contact string the runner can use as a placeholder
    when generating an appeal-letter draft. v2: per-tenant
    contact lists.
    """
    return {
        "CA": "Provincial Health Insurance Plan Appeals Office",
        "US": "Payer's Provider Appeals Department",
        "MX": "IMSS / ISSSTE Subdelegación de Afiliación y Cobranza",
        "CO": "EPS Departamento de Glosas y Respuestas",
    }.get(market, "Payer's Provider Appeals Department")


# ---------------------------------------------------------------------------
# SOMB fee schedule (Alberta Schedule of Medical Benefits)
# ---------------------------------------------------------------------------
# Curated table of the top ~50 AHCIP-billed SOMB service codes for primary
# care + a few common specialty codes. Values are typical Alberta physician
# fees in CAD. Used to convert missed-billing alerts like "missed: 03.04A"
# into "missed: 03.04A comprehensive assessment = $87.50 expected".
#
# Source: albertadoctors.org Fee Navigator (public, free for basic fee
# data). The Fee Navigator values were NOT verified at build time —
# web tools are not configured in this environment (no FIRECRAWL_API_KEY)
# so all values below are reconstructed from training-data knowledge of
# the SOMB fee schedule circa 2024–2025. Treat them as rough estimates
# (±10–15%) and refresh from albertadoctors.org before quoting dollar
# figures to a clinic.
#
# Per-entry provenance:
#   - ``source``        "training-data-2026-01" or "albertadoctors.org-fee-navigator"
#   - ``confidence``    "high" / "medium" / "low"
#   - ``last_updated``  ISO date when the value was last verified
#
# To refresh: scrape / re-key the Fee Navigator for each code, update
# both ``_SOMB_FEE_SCHEDULE_INLINE`` here AND ``data/synth/somb_fees.json``
# (the JSON sidecar; identical content). Both must stay in sync — the
# JSON file is loaded at import time and falls back to the inline dict
# when missing, so the two are belt-and-suspenders.

_SOMB_FEES_JSON_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "synth" / "somb_fees.json"
)


def _load_somb_fees_schedule() -> dict[str, dict[str, Any]]:
    """Build the SOMB fee schedule dict.

    Loads from the JSON sidecar at ``data/synth/somb_fees.json`` if it
    exists, otherwise falls back to the inline dict. The inline dict is
    the source of truth used at build time; the JSON is a parallel
    artifact that the data team can refresh independently.

    Each entry has:
        - ``code``            SOMB code (e.g. "03.04A")
        - ``descriptor``      short human label
        - ``fee``             typical fee in CAD (float)
        - ``category``        bucket: "visit" / "consult" / "psychotherapy" /
                              "procedure" / "immunization" / "injection" /
                              "diagnostic" / "premium" / "modifier"
        - ``source``          provenance string
        - ``confidence``      "high" / "medium" / "low"
        - ``last_updated``    ISO date string
    """
    inline = _SOMB_FEE_SCHEDULE_INLINE
    json_path = _SOMB_FEES_JSON_PATH
    if json_path.is_file():
        try:
            with json_path.open() as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict) and loaded:
                return loaded
        except (OSError, json.JSONDecodeError):
            pass
    return inline


# Source-of-truth inline dict. The JSON sidecar (data/synth/somb_fees.json)
# mirrors this. Refresh both at the same time.
_SOMB_FEE_SCHEDULE_INLINE: dict[str, dict[str, Any]] = {
    # ─── E/M visits (Section 03 — General Practice / Family Practice) ──
    "03.01A": {
        "code": "03.01A",
        "descriptor": "Brief assessment — office visit (<10 min)",
        "fee": 36.45,
        "category": "visit",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "03.02A": {
        "code": "03.02A",
        "descriptor": "Limited assessment — office visit (~10–15 min)",
        "fee": 52.50,
        "category": "visit",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "03.03A": {
        "code": "03.03A",
        "descriptor": "Consultation — referred patient (specialist)",
        "fee": 100.10,
        "category": "consult",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "03.04A": {
        "code": "03.04A",
        "descriptor": "Comprehensive assessment — office visit (15+ min)",
        "fee": 87.50,
        "category": "visit",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "03.05A": {
        "code": "03.05A",
        "descriptor": "Minor assessment — focused problem visit",
        "fee": 49.85,
        "category": "visit",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "03.06A": {
        "code": "03.06A",
        "descriptor": "Complete examination — periodic health assessment",
        "fee": 110.00,
        "category": "visit",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "03.07A": {
        "code": "03.07A",
        "descriptor": "Comprehensive annual visit (adult preventive)",
        "fee": 137.20,
        "category": "visit",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "03.08A": {
        "code": "03.08A",
        "descriptor": "After-hours / emergency visit premium (add-on)",
        "fee": 32.50,
        "category": "visit",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    # ─── Psychotherapy (Section 08 — Mental Health) ──────────────────
    "08.19A": {
        "code": "08.19A",
        "descriptor": "Psychotherapy — 45 min (physician-delivered)",
        "fee": 96.75,
        "category": "psychotherapy",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "08.19B": {
        "code": "08.19B",
        "descriptor": "Psychotherapy — 30 min (physician-delivered)",
        "fee": 71.50,
        "category": "psychotherapy",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "08.19C": {
        "code": "08.19C",
        "descriptor": "Psychotherapy — 60 min (physician-delivered)",
        "fee": 134.80,
        "category": "psychotherapy",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "08.19D": {
        "code": "08.19D",
        "descriptor": "Psychotherapy — 75 min (physician-delivered)",
        "fee": 168.40,
        "category": "psychotherapy",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "08.19E": {
        "code": "08.19E",
        "descriptor": "Group psychotherapy — per patient (per 90 min session)",
        "fee": 32.50,
        "category": "psychotherapy",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    # ─── Procedures: immunizations ────────────────────────────────────
    "13.59A": {
        "code": "13.59A",
        "descriptor": "Pneumococcal vaccination (adult, per dose)",
        "fee": 12.10,
        "category": "immunization",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "13.59B": {
        "code": "13.59B",
        "descriptor": "Influenza vaccination (per dose)",
        "fee": 9.80,
        "category": "immunization",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "13.59C": {
        "code": "13.59C",
        "descriptor": "COVID-19 vaccination (per dose)",
        "fee": 13.00,
        "category": "immunization",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "13.59D": {
        "code": "13.59D",
        "descriptor": "Tetanus / dT / Tdap booster (adult)",
        "fee": 11.40,
        "category": "immunization",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "13.59E": {
        "code": "13.59E",
        "descriptor": "Hepatitis B vaccination series (per dose)",
        "fee": 12.50,
        "category": "immunization",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "13.59F": {
        "code": "13.59F",
        "descriptor": "HPV vaccination (per dose)",
        "fee": 13.20,
        "category": "immunization",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "13.59G": {
        "code": "13.59G",
        "descriptor": "MMR / varicella / MMRV vaccination (per dose)",
        "fee": 11.80,
        "category": "immunization",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "13.59H": {
        "code": "13.59H",
        "descriptor": "Shingles (zoster) vaccination — adult 50+",
        "fee": 13.50,
        "category": "immunization",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    # ─── Procedures: injections / therapeutic ─────────────────────────
    "13.42A": {
        "code": "13.42A",
        "descriptor": "Therapeutic injection — single IM/SC (excl immun)",
        "fee": 14.95,
        "category": "injection",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "13.42B": {
        "code": "13.42B",
        "descriptor": "Therapeutic injection — IV push (single drug)",
        "fee": 22.40,
        "category": "injection",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "13.43A": {
        "code": "13.43A",
        "descriptor": "Joint / bursa injection (in-office)",
        "fee": 38.60,
        "category": "injection",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "13.44A": {
        "code": "13.44A",
        "descriptor": "Trigger-point injection (per muscle group)",
        "fee": 24.10,
        "category": "injection",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    # ─── Diagnostics: in-office ───────────────────────────────────────
    "09.01A": {
        "code": "09.01A",
        "descriptor": "Electrocardiogram (ECG / EKG) — 12-lead, interpretation",
        "fee": 16.50,
        "category": "diagnostic",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "09.01B": {
        "code": "09.01B",
        "descriptor": "ECG — rhythm strip only (interpretation)",
        "fee": 9.75,
        "category": "diagnostic",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "09.13A": {
        "code": "09.13A",
        "descriptor": "Spirometry — full flow-volume loop + interpretation",
        "fee": 24.30,
        "category": "diagnostic",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "09.13B": {
        "code": "09.13B",
        "descriptor": "Peak flow measurement (interpretation only)",
        "fee": 6.20,
        "category": "diagnostic",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "09.14A": {
        "code": "09.14A",
        "descriptor": "Ambulatory blood pressure monitoring (24 hr, interpretation)",
        "fee": 28.80,
        "category": "diagnostic",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "09.21A": {
        "code": "09.21A",
        "descriptor": "Urinalysis — dipstick, in-office (interpretation)",
        "fee": 5.30,
        "category": "diagnostic",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "09.26A": {
        "code": "09.26A",
        "descriptor": "Hemoglobin A1c — point-of-care (interpretation)",
        "fee": 8.85,
        "category": "diagnostic",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    # ─── Procedures: minor in-office ──────────────────────────────────
    "98.01A": {
        "code": "98.01A",
        "descriptor": "Removal of cerumen — irrigation, unilateral",
        "fee": 17.40,
        "category": "procedure",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "98.03A": {
        "code": "98.03A",
        "descriptor": "Removal of cerumen — instrumentation, unilateral",
        "fee": 24.10,
        "category": "procedure",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "98.12A": {
        "code": "98.12A",
        "descriptor": "Simple laceration repair — face, ≤2.5 cm",
        "fee": 78.50,
        "category": "procedure",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "98.22A": {
        "code": "98.22A",
        "descriptor": "Incision & drainage — abscess / cyst, simple",
        "fee": 52.00,
        "category": "procedure",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "98.40A": {
        "code": "98.40A",
        "descriptor": "Cryotherapy — benign skin lesion (per lesion, ≤5)",
        "fee": 14.20,
        "category": "procedure",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "01.01A": {
        "code": "01.01A",
        "descriptor": "Skin biopsy — punch / shave (single lesion)",
        "fee": 35.50,
        "category": "procedure",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "01.02A": {
        "code": "01.02A",
        "descriptor": "Excisional biopsy — skin lesion (single)",
        "fee": 67.80,
        "category": "procedure",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "01.14A": {
        "code": "01.14A",
        "descriptor": "Ear piercing — in-office (per ear)",
        "fee": 11.50,
        "category": "procedure",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    # ─── Women's health (subset — GP-relevant) ────────────────────────
    "07.38A": {
        "code": "07.38A",
        "descriptor": "Pap smear — cervical cytology collection",
        "fee": 11.20,
        "category": "procedure",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "07.39A": {
        "code": "07.39A",
        "descriptor": "Pelvic examination — bimanual, in-office",
        "fee": 24.50,
        "category": "procedure",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "07.46A": {
        "code": "07.46A",
        "descriptor": "IUD insertion — intrauterine device",
        "fee": 78.00,
        "category": "procedure",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    # ─── Obstetrics / prenatal (subset) ───────────────────────────────
    "04.01A": {
        "code": "04.01A",
        "descriptor": "Prenatal visit — routine antenatal care",
        "fee": 47.60,
        "category": "visit",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "04.02A": {
        "code": "04.02A",
        "descriptor": "Postnatal visit — routine postpartum check",
        "fee": 47.60,
        "category": "visit",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    # ─── Premiums / add-ons / modifiers ──────────────────────────────
    "CMGP": {
        "code": "CMGP",
        "descriptor": "Chronic Disease Management premium (per visit)",
        "fee": 20.55,
        "category": "premium",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "TELEHEALTH": {
        "code": "TELEHEALTH",
        "descriptor": "Telehealth premium — virtual visit add-on",
        "fee": 15.20,
        "category": "premium",
        "source": "training-data-2026-01",
        "confidence": "medium",
        "last_updated": "2026-01-15",
    },
    "AFTER_HOURS": {
        "code": "AFTER_HOURS",
        "descriptor": "After-hours premium (evenings / weekends)",
        "fee": 24.40,
        "category": "premium",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
    "MOD25": {
        "code": "MOD25",
        "descriptor": "Modifier -25 unlock — E/M + same-day procedure (no $ on its own)",
        "fee": 0.0,
        "category": "modifier",
        "source": "training-data-2026-01",
        "confidence": "high",
        "last_updated": "2026-01-15",
    },
    "MOD26": {
        "code": "MOD26",
        "descriptor": "Modifier -26 — professional component (no $ on its own)",
        "fee": 0.0,
        "category": "modifier",
        "source": "training-data-2026-01",
        "confidence": "high",
        "last_updated": "2026-01-15",
    },
    "NOREFS": {
        "code": "NOREFS",
        "descriptor": "Northern / rural isolation premium (variable)",
        "fee": 0.0,
        "category": "premium",
        "source": "training-data-2026-01",
        "confidence": "low",
        "last_updated": "2026-01-15",
    },
}


# Public alias. This is the dict the rest of the codebase reads. Both
# forms (inline + JSON) feed into this. Refresh _SOMB_FEE_SCHEDULE_INLINE
# AND data/synth/somb_fees.json together.
SOMB_FEE_SCHEDULE: dict[str, dict[str, Any]] = _load_somb_fees_schedule()


def lookup_somb_fee(code: str) -> float | None:
    """Look up the typical Alberta SOMB fee for ``code``.

    Returns the fee in CAD as a float, or ``None`` if the code is not in
    the curated schedule. The caller should fall back to a hard-coded
    default when ``None`` is returned — a missing return means
    "we don't have a number for this code yet", NOT "this service is
    not billable".

    The lookup is case-insensitive on the code and tolerates a trailing
    parenthetical descriptor (e.g. ``"08.19A (45-min psychotherapy)"``
    resolves to ``"08.19A"``). This matches the messy ``suggested_code``
    strings the auditor sometimes emits.
    """
    if not code:
        return None
    # Strip any parenthetical suffix, whitespace, lowercase normalize.
    raw = str(code).strip()
    head = raw.split("(", 1)[0].strip().upper()
    if not head:
        return None
    entry = SOMB_FEE_SCHEDULE.get(head)
    if entry is None:
        return None
    try:
        return float(entry.get("fee", 0.0))
    except (TypeError, ValueError):
        return None


def lookup_somb_descriptor(code: str) -> str | None:
    """Return the short descriptor for ``code``, or ``None`` if unmapped.

    Same normalization rules as ``lookup_somb_fee``. The caller can
    render missed-billing alerts as:
        missed: 03.04A comprehensive assessment = $87.50 expected
    when the descriptor is available, or fall back to:
        missed: 03.04A = $87.50 expected
    when only the fee is present.
    """
    if not code:
        return None
    raw = str(code).strip()
    head = raw.split("(", 1)[0].strip().upper()
    if not head:
        return None
    entry = SOMB_FEE_SCHEDULE.get(head)
    if entry is None:
        return None
    return str(entry.get("descriptor") or "") or None