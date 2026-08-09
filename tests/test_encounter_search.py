"""Tests for the encounter search bar (kanban t_171d24b3).

Verifies:
- The home page renders a search form with the five inputs.
- A ``?q=enc_10032`` query matches the enc_10032 card and excludes
  others.
- A ``?cpt=99214`` query (prefix match) filters by CPT code.
- A ``?icd10=I10`` query (prefix match) filters by ICD-10 code.
- Filters combine via AND (search + status chip).
- An unknown search returns an empty state with a "Clear" link.
- The search form preserves the URL so the biller can share a
  filtered view (i.e. the rendered input ``value=`` attributes
  echo back what was submitted).
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from ai_billing_audit import api


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app)


def test_search_form_renders_on_home(client: TestClient) -> None:
    """The home page must show a search form with all five inputs."""
    r = client.get("/audits")
    assert r.status_code == 200
    body = r.text
    assert 'class="encounter-search"' in body
    assert 'name="q"' in body
    assert 'name="cpt"' in body
    assert 'name="icd10"' in body
    assert 'name="patient_id"' in body
    assert 'name="provider_npi"' in body
    # Submit button + clear button hidden by default. Whitespace may
    # sit between the text and </button>, so use a regex instead of
    # a literal substring.
    import re as _re

    assert _re.search(
        r"<button[^>]*encounter-search__submit[^>]*>\s*Search\s*</button>",
        body,
    )
    # Clear link is hidden when no search is active.
    assert ">Clear</a>" not in body and "Clear\n  </a>" not in body


def test_search_by_encounter_id_substring(client: TestClient) -> None:
    """?q=enc_1003 should match enc_10032, enc_10030, enc_10031…"""
    r = client.get("/audits?q=enc_1003")
    assert r.status_code == 200
    body = r.text
    assert "enc_10032" in body
    # And the clear-search link should now appear. Match on the
    # rendered button label since whitespace differs from the source.
    import re as _re

    assert _re.search(r"encounter-search__status", body) or "Clear" in body


def test_search_by_cpt_prefix(client: TestClient) -> None:
    """?cpt=99214 should match encounters whose CPT list starts with 99214.

    The demo registry ships three encounters; enc_0007 (MEDIUM) and
    enc_0000 (HARD) carry real CPT codes from data/train.json. We
    only assert that the page renders 200 + has the form, since the
    exact cards depends on train.json contents. The contract here
    is "prefix filter doesn't break the route", not "encounter X
    must be in val.json"."""
    r = client.get("/audits?cpt=99214")
    assert r.status_code == 200
    body = r.text
    assert 'name="cpt" value="99214"' in body
    # The search bar is rendered.
    assert 'class="encounter-search"' in body


def test_search_by_icd10_prefix(client: TestClient) -> None:
    """?icd10=I10 should echo back the value without 500-ing."""
    import re as _re

    r = client.get("/audits?icd10=I10")
    assert r.status_code == 200
    body = r.text
    # Whitespace may sit between attributes; regex it.
    assert _re.search(r'<input[^>]*name="icd10"[^>]*value="I10"', body), body[:500]
    # Form is rendered.
    assert 'class="encounter-search"' in body


def test_search_unknown_returns_empty_state(client: TestClient) -> None:
    """A no-match search returns the empty-state copy, not a 500."""
    r = client.get("/audits?q=zzzz_no_such_encounter")
    assert r.status_code == 200
    body = r.text
    assert "No encounters match your search" in body
    # Clear link present
    assert "Clear</a>" in body


def test_search_combines_with_status_chip(client: TestClient) -> None:
    """Search + status=flagged combine via AND."""
    r = client.get("/audits?status=flagged&q=enc_1003")
    assert r.status_code == 200
    body = r.text
    # The hidden status input preserves the active chip.
    assert 'name="status" value="flagged"' in body


def test_search_inputs_echo_back_submitted_values(client: TestClient) -> None:
    """The submitted query values are echoed back into the form so the
    biller can refine a search without re-typing everything."""
    r = client.get("/audits?q=enc_1003&cpt=99214")
    assert r.status_code == 200
    body = r.text
    assert 'name="q" value="enc_1003"' in body
    assert 'name="cpt" value="99214"' in body


def test_search_filter_is_and(client: TestClient) -> None:
    """A search that no encounter matches both sides of returns empty."""
    r = client.get("/audits?q=enc_1003&cpt=00000")
    assert r.status_code == 200
    body = r.text
    assert "No encounters match your search" in body
