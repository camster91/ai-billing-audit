"""Locale / i18n support for Quebec French-CA and US-Spanish tenants.

Kanban: t_843317a2 (clinical-impact board).

This module provides:

* A small key→text translation table for ``en``, ``fr-ca``, ``es``.
  Adding a new locale is a matter of dropping a ``Dict[str, str]``
  into ``_TABLES`` and listing it in ``SUPPORTED_LOCALES``.
* ``set_locale(tenant_id, locale)`` / ``get_locale(tenant_id)`` —
  per-tenant locale storage backed by a JSONL file at
  ``/app/logs/tenant_locale.jsonl``. One row per tenant.
* ``currency_for(locale)`` — currency display per tenant:
  ``fr-ca`` → CAD, ``es`` → USD (US-Spanish speaking clinics in
  the US Southwest bill USD), ``en`` → USD.
* ``audit_note_locale(note_text, locale)`` — translation helper.
  Real translation is out of scope (the doctor who wrote the note
  is the canonical source), but this function returns a flag
  ``needs_translation=True`` and the locale tag so the audit
  pipeline can route the note through a translation layer before
  the LLM call. The v12 prompt already runs in English.

Scope
-----
We do NOT translate the v12 prompt or any clinical code (CPT,
ICD-10). Codes are locale-invariant by definition. We only
translate UI strings. Quebec Law 25 / BAA template translations
live in ``baa_templates.py`` and are out of scope for this
module.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Literal

Locale = Literal["en", "fr-ca", "es"]

SUPPORTED_LOCALES: tuple[Locale, ...] = ("en", "fr-ca", "es")
DEFAULT_LOCALE: Locale = "en"

# Currency display per locale. Quebec clinics bill in CAD, US
# clinics bill in USD regardless of UI language.
_CURRENCY: dict[Locale, str] = {
    "en": "USD",
    "fr-ca": "CAD",
    "es": "USD",
}

# Translation table — UI strings only. Missing keys fall back to
# English so we never render an empty string.
_TABLES: dict[Locale, dict[str, str]] = {
    "en": {
        "dashboard.title": "Zorva Pre-Bill Audit",
        "dashboard.subtitle": "Catch denials before the claim goes out.",
        "encounter.audit_now": "Audit this claim",
        "encounter.flag_count": "{n} flags",
        "doctor.weekly.subject": "Your week in notes: {clean} clean, {flagged} flagged",
        "monthly.win.subject": "Your clinic saved ${saved} this month",
        "language.switch": "Language",
        "currency.label": "Currency",
    },
    "fr-ca": {
        "dashboard.title": "Audit de facturation Zorva",
        "dashboard.subtitle": "Détectez les refus avant l'envoi de la réclamation.",
        "encounter.audit_now": "Vérifier cette réclamation",
        "encounter.flag_count": "{n} avertissements",
        "doctor.weekly.subject": "Votre semaine en notes : {clean} conformes, {flagged} signalées",
        "monthly.win.subject": "Votre clinique a économisé {saved} $ ce mois-ci",
        "language.switch": "Langue",
        "currency.label": "Devise",
    },
    "es": {
        "dashboard.title": "Auditoría de facturación Zorva",
        "dashboard.subtitle": "Detecta denegaciones antes de enviar la reclamación.",
        "encounter.audit_now": "Auditar esta reclamación",
        "encounter.flag_count": "{n} alertas",
        "doctor.weekly.subject": "Tu semana en notas: {clean} limpias, {flagged} señaladas",
        "monthly.win.subject": "Tu clínica ahorró ${saved} este mes",
        "language.switch": "Idioma",
        "currency.label": "Moneda",
    },
}

# Per-tenant locale log (append-only JSONL, SHA-256 chained for
# tamper evidence — same pattern as audit_actions.py).
_LOG_PATH = Path(os.environ.get("TENANT_LOCALE_LOG", "/app/logs/tenant_locale.jsonl"))
_GENESIS_SIG = "0" * 64


def is_supported_locale(locale: str) -> bool:
    """Return True iff ``locale`` is in ``SUPPORTED_LOCALES``."""
    return locale in SUPPORTED_LOCALES


def list_supported_locales() -> list[Locale]:
    """Return the full list of supported locales (stable order)."""
    return list(SUPPORTED_LOCALES)


def currency_for(locale: Locale) -> str:
    """Return the display currency code for ``locale`` (USD / CAD)."""
    return _CURRENCY.get(locale, "USD")


def translate(key: str, locale: Locale, **fmt: object) -> str:
    """Translate ``key`` for ``locale`` with Python ``str.format`` substitution.

    Falls back to ``en`` when the key is missing in the requested
    locale, and to the key itself when missing in English (so the
    UI never goes blank — we render the developer-facing token).
    """
    table = _TABLES.get(locale) or _TABLES[DEFAULT_LOCALE]
    template = table.get(key) or _TABLES[DEFAULT_LOCALE].get(key) or key
    if fmt:
        try:
            return template.format(**fmt)
        except (KeyError, IndexError):
            return template
    return template


def audit_note_locale(note_text: str, locale: Locale) -> dict[str, object]:
    """Flag a note as needing translation before LLM audit.

    The v12 prompt runs in English. If the note is in French-CA or
    Spanish, the calling pipeline must translate it before invoking
    the LLM. This helper returns a small dict so the caller can
    branch on ``needs_translation``.
    """
    needs_translation = locale in ("fr-ca", "es")
    return {
        "needs_translation": needs_translation,
        "source_locale": locale,
        "target_locale": "en",
        "note_chars": len(note_text or ""),
        # The actual translation happens upstream; we only flag it.
    }


# ---------------------------------------------------------------------------
# Per-tenant locale storage
# ---------------------------------------------------------------------------


def _last_signature(path: Path) -> str:
    if not path.exists():
        return _GENESIS_SIG
    last = _GENESIS_SIG
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            last = row.get("cryptographic_signature") or last
    return last


def _sign(previous: str, row: dict[str, object]) -> str:
    import hashlib

    payload = "|".join(str(row.get(k, "")) for k in sorted(row.keys()) if k != "cryptographic_signature")
    return hashlib.sha256(f"{previous}|{payload}".encode("utf-8")).hexdigest()


def set_locale(tenant_id: str, locale: Locale) -> dict[str, object]:
    """Persist the locale preference for ``tenant_id``.

    Append-only JSONL. The most-recent row per tenant wins.
    """
    if not is_supported_locale(locale):
        raise ValueError(
            f"locale must be one of {SUPPORTED_LOCALES}, got {locale!r}"
        )
    path = Path(os.environ.get("TENANT_LOCALE_LOG", str(_LOG_PATH)))
    path.parent.mkdir(parents=True, exist_ok=True)
    prev_sig = _last_signature(path)
    row: dict[str, object] = {
        "event_id": uuid.uuid4().hex,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tenant_id": tenant_id,
        "locale": locale,
        "previous_signature": prev_sig,
    }
    row["cryptographic_signature"] = _sign(prev_sig, row)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def get_locale(tenant_id: str, *, log_path: Path | str | None = None) -> Locale:
    """Return the most-recent locale set for ``tenant_id`` (default ``en``)."""
    path = Path(log_path) if log_path is not None else _LOG_PATH
    if not path.exists():
        return DEFAULT_LOCALE
    latest: Locale | None = None
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("tenant_id") == tenant_id:
                loc = row.get("locale")
                if isinstance(loc, str) and is_supported_locale(loc):
                    latest = loc  # type: ignore[assignment]
    return latest or DEFAULT_LOCALE


def locale_for_tenant(tenant_id: str, *, log_path: Path | str | None = None) -> Locale:
    """Alias for ``get_locale`` (clearer at call sites)."""
    return get_locale(tenant_id, log_path=log_path)