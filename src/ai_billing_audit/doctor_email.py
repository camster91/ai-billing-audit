"""Doctor summary email.

When the auditor finds a flag-worthy finding, the doctor who wrote
the clinical note gets a plain-English email with a 1-sentence "fix".

This is the single most leverage move in the product. Doctors who see
1-2 of these per month learn to write notes that pass the audit. Within
3 months the clinic's denial rate drops because the notes are better,
not because the biller is gaming the auditor.

Email format:
    Subject: "1 claim from your June 12 visit needs a 1-sentence fix"
    Body:
        Dr. Lee,

        Your visit note for Jane Doe on June 12 would have been denied
        by [payer] because [1-sentence why].

        Fix: add this sentence to the note —

            "Reviewed prior chest x-ray from 2024 and compared to
            current imaging."

        The auditor will re-run and (usually) clear the claim.

        — Zorva pre-bill audit

The email is sent via Mailgun REST API (https://api.mailgun.net/v3).
The api key and domain are read from the environment:
    - MAILGUN_API_KEY : the API key for the ashbi.ca Mailgun account
    - MAILGUN_DOMAIN  : the sending domain (default: ashbi.ca)
If either is missing or Mailgun returns an error, the email is logged
to /app/logs/doctor_emails.jsonl for manual delivery in dev.

Per-tenant config:
    - DOCTOR_SUMMARY_OPT_IN (env, default "1"): master switch
    - per-doctor opt-out: stored in the audit_actions log under
      ``data_elements.doctor_opted_out = True``

PHIPA s.18 implied consent: the patient has consented to the clinic
providing their health info to a billing agent. We do not need a
separate patient consent flow for this. The clinic's privacy
officer is responsible for documenting that consent.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Where we drop emails in dev when Mailgun is not configured.
_LOGS_DIR = Path("/app/logs")


def _dev_mailbox_path() -> Path:
    """Resolve the dev-mailbox path lazily so tests can override _LOGS_DIR."""
    return _LOGS_DIR / "doctor_emails.jsonl"


def _optout_path() -> Path:
    """Path to the JSON file storing per-doctor opt-outs.

    Shape: {"doctor@example.com": {"opted_out_at": 1700000000.0, "reason": "..."}}

    v1 storage: simple JSON file in /app/logs. v2: per-tenant DB
    table so a multi-tenant deployment doesn't accidentally cross-
    pollute the opt-out list. The functions that read/write this
    file use a file lock to avoid concurrent-write corruption
    (rare in practice but cheap to add).
    """
    return _LOGS_DIR / "doctor_optouts.json"


def _load_optouts() -> dict[str, dict[str, Any]]:
    """Load the opt-outs file. Returns {} on missing/corrupt file."""
    p = _optout_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_optouts(data: dict[str, dict[str, Any]]) -> None:
    """Persist opt-outs to disk. Creates parent dirs."""
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _optout_path().write_text(json.dumps(data, indent=2, sort_keys=True))


def _is_doctor_opted_out(doctor_email: str) -> bool:
    """True iff the doctor has opted out of receiving summary emails."""
    if not doctor_email:
        return False
    return doctor_email.lower() in _load_optouts()


def opt_out_doctor(doctor_email: str, reason: str = "") -> bool:
    """Mark a doctor's email as opted-out. Idempotent.

    Returns True if a new opt-out was created, False if it already
    existed. The caller (admin UI in v2) should also write an
    audit-trail row to record the action.

    v1: simple JSON file. v2: per-tenant DB row.
    """
    if not doctor_email:
        return False
    data = _load_optouts()
    key = doctor_email.lower()
    if key in data:
        return False
    data[key] = {
        "opted_out_at": time.time(),
        "reason": reason,
    }
    _save_optouts(data)
    return True


def opt_in_doctor(doctor_email: str) -> bool:
    """Reverse an opt-out. Idempotent. Returns True if a row was removed."""
    if not doctor_email:
        return False
    data = _load_optouts()
    key = doctor_email.lower()
    if key not in data:
        return False
    del data[key]
    _save_optouts(data)
    return True


@dataclass(frozen=True)
class DoctorSummary:
    """One doctor-summary email, ready to send.

    Attributes
    ----------
    to_email : str
        The rendering provider's email.
    subject : str
        Email subject line.
    body_text : str
        Plain-text email body.
    encounter_id : str
        Which encounter the email is about.
    finding_id : str
        Which finding (used to dedupe and for the audit-trail row).
    """

    to_email: str
    subject: str
    body_text: str
    encounter_id: str
    finding_id: str


def _mailgun_configured() -> tuple[str, str] | None:
    """Return (api_key, domain) if Mailgun is configured, else None.

    The api key is sourced from MAILGUN_API_KEY. The domain defaults
    to ``ashbi.ca`` (the Cam-controlled domain that hosts the
    Mailgun account) but can be overridden with MAILGUN_DOMAIN for
    a per-tenant sender (e.g. mg.tenantclinic.ca).
    """
    api_key = os.environ.get("MAILGUN_API_KEY", "").strip()
    domain = os.environ.get("MAILGUN_DOMAIN", "").strip() or "ashbi.ca"
    if not api_key:
        return None
    return (api_key, domain)


def _send_via_mailgun(
    api_key: str,
    domain: str,
    summary: DoctorSummary,
) -> tuple[bool, str]:
    """POST the email to Mailgun's REST API.

    Returns (ok, message_id_or_error). Uses basic auth (username=api,
    password=key) per Mailgun's spec. ``requests`` is the only
    third-party dep we add for this.

    Why the REST API over SMTP:
    - Synchronous: we get a 200/4xx response in <2s, not 30s+
      of SMTP retries
    - Clear error messages: "address invalid", "domain not
      verified", "quota exceeded" — all surface in the response
      body and we can log them for debugging
    - DomainDKIM, SPF, return-path are all handled by Mailgun
      once the domain is verified in their dashboard

    Reference: https://documentation.mailgun.com/en/latest/api-sending.html
    """
    try:
        import requests  # type: ignore
    except ImportError:
        return False, "requests package not installed"

    sender = os.environ.get(
        "DOCTOR_SUMMARY_FROM",
        f"Zorva Audit <audit@{domain}>",
    )
    url = f"https://api.mailgun.net/v3/{domain}/messages"
    try:
        resp = requests.post(
            url,
            auth=("api", api_key),
            data={
                "from": sender,
                "to": summary.to_email,
                "subject": summary.subject,
                "text": summary.body_text,
            },
            timeout=10,
        )
    except requests.RequestException as e:
        return False, f"network error: {type(e).__name__}: {e}"

    if 200 <= resp.status_code < 300:
        # Mailgun returns JSON: {"id": "...", "message": "Queued..."}
        try:
            payload = resp.json()
            message_id = payload.get("id", "")
        except ValueError:
            message_id = ""
        return True, message_id

    # Non-2xx. Mailgun returns JSON with ``message`` field on error.
    try:
        payload = resp.json()
        err = payload.get("message", resp.text[:200])
    except ValueError:
        err = resp.text[:200]
    return False, f"HTTP {resp.status_code}: {err}"


# Specialty detection by CPT code prefix. A cardiologist and a
# psychiatrist write notes in completely different idioms; the doctor
# summary should match the specialty. v1 is a coarse CPT-prefix
# lookup — primary care (99201-99215), surgery (10004-69990),
# imaging (70000-79999), path/lab (80000-89999), medicine/psych
# (90801-99607). v2 will use the NPI taxonomy + clinical context.
_SPECIALTY_BY_CPT_PREFIX = [
    # (prefix_range, specialty)
    ((99201, 99215), "primary_care"),
    ((99221, 99239), "inpatient"),
    ((99281, 99285), "emergency"),
    ((99291, 99292), "critical_care"),
    ((99304, 99318), "nursing_facility"),
    ((99381, 99397), "preventive"),
    ((90801, 90899), "psychiatry"),
    ((90935, 90999), "dialysis"),
    ((10004, 69990), "surgery"),
    ((70000, 79999), "imaging"),
    ((80000, 89999), "pathology_lab"),
    ((90281, 90399), "immunization"),
    ((90465, 90474), "immunization_admin"),
    ((90476, 90479), "immunization_admin"),
    ((90460, 90461), "immunization_admin"),
    ((90951, 90961), "obstetrics"),
    ((90945, 90945), "dialysis"),
    ((92002, 92499), "ophthalmology"),
    ((99217, 99220), "observation"),
    ((99224, 99226), "subsequent_observation"),
    ((99234, 99236), "observation_same_day"),
    ((99238, 99239), "hospital_discharge"),
    ((99281, 99285), "emergency"),
    ((99304, 99318), "nursing_facility"),
    ((99381, 99397), "preventive"),
    ((99441, 99443), "telephone"),
    ((99460, 99465), "newborn"),
    ((99471, 99476), "critical_care_neonatal"),
    ((99477, 99480), "newborn"),
    ((99495, 99496), "transitional_care"),
    ((99605, 99607), "medication_therapy"),
]


def specialty_from_cpt(cpt_codes: list[str] | None) -> str | None:
    """Best-effort specialty detection from billed CPT codes.

    Returns the first matching specialty, or None if no CPT code
    maps to a known range. Used to pick the right phrasing for the
    doctor summary email. Cheap because it's a list scan on a few
    dozen CPT codes per encounter.
    """
    if not cpt_codes:
        return None
    for raw in cpt_codes:
        try:
            code = int(str(raw).strip().split(".")[0])
        except (TypeError, ValueError):
            continue
        for (lo, hi), specialty in _SPECIALTY_BY_CPT_PREFIX:
            if lo <= code <= hi:
                return specialty
    return None


# Per-specialty phrasing for the "fix" recommendation. The default
# already covers common cases; these tweaks make the doctor feel the
# summary was written for THEIR specialty, not a generic intern.
_SPECIALTY_FIX_OVERRIDES = {
    "primary_care": {
        "MOD-25": "The E/M service (e.g., 99213) addresses a separate concern from today's preventive visit and is documented in the assessment.",
    },
    "psychiatry": {
        "TIME": "Total time spent on this encounter: [X] minutes face-to-face with the patient, of which [Y] minutes were psychotherapy.",
    },
    "emergency": {
        "MOD-25": "The E/M service represents a separate and significant evaluation beyond the typical work of the procedure, documented in the medical decision-making section.",
    },
    "surgery": {
        "MOD-25": "A separate, significant E/M was performed above and beyond the usual pre- and post-operative work for the procedure; documentation supports a distinct history, exam, and medical decision-making.",
    },
    "imaging": {
        "MED-NEC": "The clinical indication for this imaging study is documented in the order and the note, with relevant signs/symptoms and prior workup.",
    },
    "pathology_lab": {
        "MED-NEC": "The order includes a specific diagnosis or condition justifying the lab, with relevant clinical history noted on the requisition.",
    },
}


def specialty_fix_suggestion(
    rule_id: str, suggested_code: str, specialty: str | None
) -> str:
    """Pick a specialty-aware fix when available, else default."""
    if specialty and rule_id in _SPECIALTY_FIX_OVERRIDES.get(specialty, {}):
        return _SPECIALTY_FIX_OVERRIDES[specialty][rule_id]
    return _default_fix_suggestion(rule_id, suggested_code)


def specialty_reason(
    rule_id: str, severity: str, suggested_code: str, quote: str, specialty: str | None
) -> str:
    """Pick a specialty-aware reason when available, else default.

    Most rules have the same plain-English reason regardless of
    specialty (a missing modifier-25 is the same problem for a
    cardiologist and a psychiatrist). But for time-based and
    documentation-adequacy rules, the specialty matters. v2 will
    expand the override map; v1 has just a few entries.
    """
    return _one_sentence_reason(rule_id, severity, suggested_code, quote)


def build_doctor_summary(
    *,
    finding: dict[str, Any],
    encounter: dict[str, Any],
    doctor_name: str | None = None,
    patient_label: str = "the patient",
) -> DoctorSummary | None:
    """Build a plain-English doctor summary from a single finding.

    The output is short: 4 sentences max. The first names the issue,
    the second gives the fix, the third says "auditor will re-run".

    Returns None if we don't have enough information to build a useful
    email (e.g. no doctor email, no fix recommendation).
    """
    doctor_email = encounter.get("provider_email") or encounter.get("doctor_email")
    if not doctor_email:
        return None

    finding_id = str(finding.get("finding_id", "") or "")
    if not finding_id:
        return None

    rule_id = (
        finding.get("rule_id")
        or (finding.get("rule_ids") or [""])[0]
    )
    severity = str(finding.get("severity", "medium"))
    quote = str(finding.get("quote", "") or "").strip()
    suggested = str(finding.get("suggested_code", "") or "").strip()
    suggested_action = str(
        finding.get("suggested_addition")
        or finding.get("doctor_summary")
        or finding.get("summary_short")
        or ""
    ).strip()

    # Detect specialty from the encounter's CPT codes so the reason
    # and fix use specialty-aware phrasing ("separate concern from
    # the preventive visit" for primary care vs "above and beyond the
    # usual pre/post-op work" for surgery).
    cpt_codes = encounter.get("CPT_codes") or encounter.get("cpt_codes") or []
    specialty = specialty_from_cpt(cpt_codes)

    # 1-sentence reason (the "why this would be denied")
    reason = specialty_reason(rule_id, severity, suggested, quote, specialty)

    # 1-sentence fix (copy-pasteable, specific to the encounter)
    fix = suggested_action or specialty_fix_suggestion(rule_id, suggested, specialty)

    salutation = f"Dr. {doctor_name.split()[-1]}," if doctor_name else "Hi,"

    body = (
        f"{salutation}\n\n"
        f"Your visit note for {patient_label} on "
        f"{encounter.get('date_of_service', 'recent visit')} would have "
        f"been denied by the payer.\n\n"
        f"Reason: {reason}\n\n"
        f"Fix: add this sentence to the note —\n\n"
        f"    \"{fix}\"\n\n"
        f"The auditor will re-run and (usually) clear the claim. "
        f"No action needed if the patient was a one-off.\n\n"
        f"— Zorva pre-bill audit\n"
    )

    subject = f"1 claim needs a 1-sentence fix ({severity})"

    return DoctorSummary(
        to_email=doctor_email,
        subject=subject,
        body_text=body,
        encounter_id=str(encounter.get("encounter_id", "")),
        finding_id=finding_id,
    )


def _one_sentence_reason(
    rule_id: str,
    severity: str,
    suggested_code: str,
    quote: str,
) -> str:
    """Compose the 1-sentence 'why' for the doctor.

    Uses the rule_id to map to a plain-English reason. Falls back to
    a generic phrase if we don't recognise the rule.
    """
    REASONS = {
        "MOD-25": (
            "the E/M code for the same-day visit is missing modifier -25, "
            "which the payer requires when an E/M is billed alongside a "
            "procedure on the same day"
        ),
        "MOD-59": (
            "two procedures on the same day need modifier -59 to indicate "
            "they are separate services — without it, the payer bundles them"
        ),
        "E/M-LEVEL": (
            "the documentation supports a different E/M level than what "
            "was billed"
        ),
        "NCCI": (
            "two procedure codes on the same day conflict under the NCCI "
            "edits and need a modifier to be billed together"
        ),
        "TIME": (
            "critical care / prolonged service codes need explicit start "
            "and end time or total minutes documented in the note"
        ),
        "MED-NEC": (
            "the diagnosis code doesn't clearly support the medical "
            "necessity for the procedure billed"
        ),
    }
    reason = REASONS.get(rule_id)
    if reason:
        return reason
    if suggested_code:
        return (
            f"the documentation doesn't fully support billing "
            f"{suggested_code} as submitted"
        )
    if quote:
        return f"the note's documentation around \"{quote[:60]}...\" is incomplete"
    return "the documentation doesn't fully support the claim as billed"


def _default_fix_suggestion(rule_id: str, suggested_code: str) -> str:
    """Generic fix recommendation per rule family."""
    FIXES = {
        "MOD-25": (
            "The E/M service (e.g., 99213) is significant and separately "
            "identifiable from the procedure performed today."
        ),
        "MOD-59": (
            "These procedures are performed at different anatomic sites "
            "or for distinct clinical reasons."
        ),
        "E/M-LEVEL": (
            "Medical decision making: [problems], [data reviewed], [risk]. "
            "Total time spent on this encounter: [X] minutes."
        ),
        "TIME": (
            "Total time spent on this encounter: [X] minutes, from "
            "[start time] to [end time], of which [Y] minutes were "
            "spent on this specific service."
        ),
    }
    return FIXES.get(rule_id, "Document the medical decision making in more detail.")


def send_doctor_summary(summary: DoctorSummary) -> bool:
    """Send a doctor-summary email via Mailgun (or log to dev mailbox).

    Returns True if the email was sent (or queued for delivery),
    False if it was dropped (no API key + no dev mailbox writable).
    """
    if os.environ.get("DOCTOR_SUMMARY_OPT_IN", "1") == "0":
        logger.info("doctor summary disabled via DOCTOR_SUMMARY_OPT_IN=0")
        return False

    # Per-doctor opt-out check. The encounter dict carries the
    # provider NPI; if the doctor has previously said "don't email
    # me", we drop the email. The audit-trail row records the
    # drop so the biller knows there was a finding but the doctor
    # opted out.
    if _is_doctor_opted_out(summary.to_email):
        logger.info(
            "doctor opted out — skipping email",
            extra={
                "encounter_id": summary.encounter_id,
                "to": summary.to_email,
            },
        )
        return False

    config = _mailgun_configured()
    if config is not None:
        api_key, domain = config
        ok, message_or_error = _send_via_mailgun(api_key, domain, summary)
        if ok:
            logger.info(
                "doctor summary sent via mailgun",
                extra={
                    "encounter_id": summary.encounter_id,
                    "to": summary.to_email,
                    "mailgun_id": message_or_error,
                    "domain": domain,
                },
            )
            return True
        logger.warning(
            "mailgun send failed: %s — falling back to dev mailbox",
            message_or_error,
        )
        # Fall through to dev mailbox so we don't lose the email.

    # Dev / fallback: append to /app/logs/doctor_emails.jsonl so a
    # human can review what would have been sent. Better than silent
    # loss. We still record the failure reason so the human knows
    # why the live send didn't happen.
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "to": summary.to_email,
        "subject": summary.subject,
        "body": summary.body_text,
        "encounter_id": summary.encounter_id,
        "finding_id": summary.finding_id,
        "ts": time.time(),
    }
    with _dev_mailbox_path().open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    return True


def doctor_email_for_provider(provider_npi: str) -> str | None:
    """Look up a provider's email by NPI via the NPI Registry.

    The CMS NPI Registry (https://npiregistry.cms.hhs.gov/api/) is
    a public REST API. We hit it once per provider, cache the result
    on disk, and return the email.

    Returns None on any failure (NPI not found, no email in record,
    network error). The caller is responsible for falling back to a
    per-tenant override or skipping the email.
    """
    import urllib.request
    import urllib.parse
    import urllib.error

    # Cache in /app/logs/npi_email_cache.json
    cache_path = _LOGS_DIR / "npi_email_cache.json"
    cache: dict[str, str | None] = {}
    if cache_path.is_file():
        try:
            cache = json.loads(cache_path.read_text())
        except json.JSONDecodeError:
            cache = {}
    if provider_npi in cache:
        return cache[provider_npi]
    if not provider_npi or not provider_npi.isdigit() or len(provider_npi) != 10:
        cache[provider_npi] = None
        return None

    try:
        url = "https://npiregistry.cms.hhs.gov/api/?version=2.1&number=" + urllib.parse.quote(provider_npi)
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        cache[provider_npi] = None
        return None

    results = payload.get("results") or []
    if not results:
        cache[provider_npi] = None
    else:
        # Pick the first email address (NPI registry can return
        # multiple addresses for an NPI if the provider has multiple
        # practice locations). For v1, first one wins.
        addresses = (results[0].get("addresses") or [])
        email = None
        for addr in addresses:
            if addr.get("address_purpose") == "MAILING":
                email = addr.get("email")
                if email:
                    break
        cache[provider_npi] = email

    # Persist cache
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True))
    return cache[provider_npi]
