"""Tests for the NPI Registry email lookup.

The NPI Registry (https://npiregistry.cms.hhs.gov/api/) is a public
REST API. The lookup function calls it once per provider, caches the
result on disk, and returns the email.

What's pinned
-------------
* Malformed NPI -> None without an API call (already tested)
* Cache hit -> no HTTP call, returns cached value
* Network error -> None, caches None
* Not-found (empty results) -> None
* Found -> email returned, cache populated
* Cache file is corrupted -> treated as empty cache
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock


from ai_billing_audit.doctor_email import doctor_email_for_provider


def _mock_response(payload: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_cache_hit_no_http_call(tmp_path, monkeypatch):
    """If the NPI is in the cache, no HTTP call is made."""
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    cache_path = tmp_path / "npi_email_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "1234567890": "dr.cached@example.com",
            }
        )
    )

    # Mock urlopen — if it's called, the test fails.
    mock_urlopen = MagicMock()
    with patch("urllib.request.urlopen", mock_urlopen):
        result = doctor_email_for_provider("1234567890")
    assert result == "dr.cached@example.com"
    mock_urlopen.assert_not_called()


def test_network_error_returns_none(tmp_path, monkeypatch):
    """Network errors don't crash; we get None."""
    import urllib.error

    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    mock_urlopen = MagicMock(side_effect=urllib.error.URLError("connection refused"))
    with patch("urllib.request.urlopen", mock_urlopen):
        result = doctor_email_for_provider("1234567890")
    assert result is None


def test_not_found_returns_none(tmp_path, monkeypatch):
    """NPI not in registry -> None."""
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    payload = {"results": []}
    mock_urlopen = MagicMock(return_value=_mock_response(payload))
    with patch("urllib.request.urlopen", mock_urlopen):
        result = doctor_email_for_provider("1234567890")
    assert result is None


def test_found_returns_email(tmp_path, monkeypatch):
    """Found NPI -> email returned and cached for next time."""
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    payload = {
        "results": [
            {
                "addresses": [
                    {
                        "address_purpose": "MAILING",
                        "email": "dr.smith@example.com",
                    },
                    # Non-mailing addresses should be skipped
                    {"address_purpose": "LOCATION", "email": "ignored@example.com"},
                ],
            }
        ]
    }
    mock_urlopen = MagicMock(return_value=_mock_response(payload))
    with patch("urllib.request.urlopen", mock_urlopen):
        result = doctor_email_for_provider("1234567890")
    assert result == "dr.smith@example.com"

    # Cached for next call (no second HTTP request)
    cache_path = tmp_path / "npi_email_cache.json"
    assert cache_path.is_file()
    cache = json.loads(cache_path.read_text())
    assert cache["1234567890"] == "dr.smith@example.com"


def test_no_mailing_address_returns_none(tmp_path, monkeypatch):
    """Provider has addresses but none are MAILING -> None."""
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    payload = {
        "results": [
            {
                "addresses": [
                    {"address_purpose": "LOCATION", "email": "ignored@example.com"},
                ],
            }
        ]
    }
    mock_urlopen = MagicMock(return_value=_mock_response(payload))
    with patch("urllib.request.urlopen", mock_urlopen):
        result = doctor_email_for_provider("1234567890")
    assert result is None


def test_corrupt_cache_treated_as_empty(tmp_path, monkeypatch):
    """A corrupt cache file shouldn't crash the lookup."""
    monkeypatch.setattr("ai_billing_audit.doctor_email._LOGS_DIR", tmp_path)
    cache_path = tmp_path / "npi_email_cache.json"
    cache_path.write_text("not valid json {")

    # Should fall back to making the HTTP call
    payload = {
        "results": [
            {"addresses": [{"address_purpose": "MAILING", "email": "dr.x@example.com"}]}
        ]
    }
    mock_urlopen = MagicMock(return_value=_mock_response(payload))
    with patch("urllib.request.urlopen", mock_urlopen):
        result = doctor_email_for_provider("1234567890")
    assert result == "dr.x@example.com"
