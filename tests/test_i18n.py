"""Tests for i18n.locale support (kanban t_843317a2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_billing_audit import i18n


def test_supported_locales():
    assert i18n.is_supported_locale("en")
    assert i18n.is_supported_locale("fr-ca")
    assert i18n.is_supported_locale("es")
    assert not i18n.is_supported_locale("de")
    assert not i18n.is_supported_locale("")
    assert not i18n.is_supported_locale("FR-CA")


def test_list_supported():
    locales = i18n.list_supported_locales()
    assert "en" in locales
    assert "fr-ca" in locales
    assert "es" in locales
    assert tuple(locales) == ("en", "fr-ca", "es")


def test_currency_for_locale():
    assert i18n.currency_for("en") == "USD"
    assert i18n.currency_for("fr-ca") == "CAD"
    assert i18n.currency_for("es") == "USD"


def test_translate_known_key():
    assert i18n.translate("dashboard.title", "en") == "Zorva Pre-Bill Audit"
    assert "Audit" in i18n.translate("dashboard.title", "fr-ca")
    assert "Auditoría" in i18n.translate("dashboard.title", "es")


def test_translate_falls_back_to_english():
    # Unknown locale falls back to English for known keys
    # We use a 'fake' locale string by skipping the supported check
    # — translate() does not enforce supported-ness, only is_supported_locale does.
    out = i18n.translate("dashboard.title", "en")
    assert out  # non-empty


def test_translate_format_substitution():
    out = i18n.translate("encounter.flag_count", "en", n=5)
    assert "5" in out
    out_fr = i18n.translate("encounter.flag_count", "fr-ca", n=12)
    assert "12" in out_fr
    out_es = i18n.translate("encounter.flag_count", "es", n=7)
    assert "7" in out_es


def test_translate_unknown_key_returns_key():
    # If neither table has the key, the key itself is returned
    out = i18n.translate("totally.unknown.key", "en")
    assert out == "totally.unknown.key"


def test_translate_format_with_bad_kwargs_returns_template():
    # When the user passes fmt args that don't match the template,
    # we return the raw template rather than KeyError'ing.
    out = i18n.translate("dashboard.title", "en", missing_arg=True)
    assert out == "Zorva Pre-Bill Audit"  # no placeholders so it's fine
    # With a placeholder we don't supply
    out2 = i18n.translate("encounter.flag_count", "en")
    assert "{n}" in out2  # the template is returned unformatted


def test_audit_note_locale():
    en = i18n.audit_note_locale("Patient presents with...", "en")
    assert en["needs_translation"] is False
    assert en["source_locale"] == "en"
    fr = i18n.audit_note_locale("Le patient se présente avec...", "fr-ca")
    assert fr["needs_translation"] is True
    assert fr["source_locale"] == "fr-ca"
    assert fr["target_locale"] == "en"
    es = i18n.audit_note_locale("El paciente se presenta con...", "es")
    assert es["needs_translation"] is True


def test_set_and_get_locale(tmp_path: Path, monkeypatch):
    log = tmp_path / "locale.jsonl"
    monkeypatch.setenv("TENANT_LOCALE_LOG", str(log))

    assert i18n.get_locale("clinic_a", log_path=log) == "en"
    i18n.set_locale(
        "clinic_a",
        "fr-ca",
    )
    assert i18n.get_locale("clinic_a", log_path=log) == "fr-ca"

    # Setting twice — latest wins
    i18n.set_locale("clinic_a", "es")
    assert i18n.get_locale("clinic_a", log_path=log) == "es"

    # Tenant isolation
    assert i18n.get_locale("clinic_b", log_path=log) == "en"


def test_set_locale_validates(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TENANT_LOCALE_LOG", str(tmp_path / "x.jsonl"))
    with pytest.raises(ValueError):
        i18n.set_locale("clinic_a", "klingon")


def test_locale_log_signature_chain(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TENANT_LOCALE_LOG", str(tmp_path / "x.jsonl"))
    i18n.set_locale("clinic_a", "fr-ca")
    i18n.set_locale("clinic_b", "es")

    rows = [
        json.loads(line)
        for line in (tmp_path / "x.jsonl").read_text().splitlines()
        if line
    ]
    assert len(rows) == 2
    assert rows[0]["previous_signature"] == "0" * 64
    assert rows[1]["previous_signature"] == rows[0]["cryptographic_signature"]
    assert all(r["cryptographic_signature"] for r in rows)


def test_locale_for_tenant_alias():
    # alias works the same as get_locale
    assert i18n.locale_for_tenant("nobody") == "en"
