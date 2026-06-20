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

import re
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