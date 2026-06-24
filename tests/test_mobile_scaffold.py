"""Smoke tests for the Capacitor mobile scaffold (kanban t_7004415a).

This is a SCAFFOLD — there are no native builds, no LLM calls,
and no servers. The test is structural validation: the manifest
files exist, are valid JSON, declare the required Capacitor
dependencies, and the WebView target points at the live
dashboard URL.

What's NOT tested here
----------------------

* iOS / Android builds (require Xcode / Android Studio on a
  developer machine, not in CI).
* The actual WebView behaviour (it's the dashboard's
  responsibility, not the scaffold's).
* Push notifications / secure storage / biometric auth — those
  are out of scope for the v1 scaffold.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# apps/mobile/ is a sibling of tests/ at the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MOBILE_DIR = PROJECT_ROOT / "apps" / "mobile"
PACKAGE_JSON = MOBILE_DIR / "package.json"
CAPACITOR_CONFIG = MOBILE_DIR / "capacitor.config.json"
WWW_INDEX = MOBILE_DIR / "www" / "index.html"
README = MOBILE_DIR / "README.md"

# The five Capacitor deps the kanban card calls out. Keeping the
# list as a module-level constant so the assertion is one line
# and a missing dep shows up as a clear diff.
REQUIRED_CAPS = (
    "@capacitor/core",
    "@capacitor/ios",
    "@capacitor/android",
    "@capacitor/app",
    "@capacitor/preferences",
)

EXPECTED_DASHBOARD_URL = "https://ai-billing-audit.ashbi.ca/"


# --- 1. scaffold files exist ------------------------------------------


def test_mobile_dir_exists() -> None:
    assert MOBILE_DIR.is_dir(), f"{MOBILE_DIR} is missing — the scaffold wasn't created"


def test_package_json_exists() -> None:
    assert PACKAGE_JSON.is_file()


def test_capacitor_config_exists() -> None:
    assert CAPACITOR_CONFIG.is_file()


def test_www_index_html_exists() -> None:
    assert WWW_INDEX.is_file()


def test_readme_exists() -> None:
    assert README.is_file()


# --- 2. JSON is well-formed --------------------------------------------


def test_package_json_is_valid_json() -> None:
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


def test_capacitor_config_is_valid_json() -> None:
    data = json.loads(CAPACITOR_CONFIG.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


# --- 3. package.json declares the required deps ------------------------


@pytest.mark.parametrize("dep", REQUIRED_CAPS)
def test_package_json_declares_required_capacitor_dep(dep: str) -> None:
    """The kanban card calls out the five Capacitor packages the
    scaffold must depend on. Each one is required (no
    equivalent substitute) — assert each is present in
    ``dependencies``.
    """
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    deps = data.get("dependencies", {}) or {}
    assert dep in deps, (
        f"{dep!r} is missing from apps/mobile/package.json "
        f"dependencies; required by kanban t_7004415a. Found: "
        f"{sorted(deps.keys())}"
    )


def test_package_json_has_capacitor_cli_in_dev_deps() -> None:
    """`cap` CLI is required for `cap add ios` / `cap add android` /
    `cap sync`. It can live in devDependencies (the build pipeline
    needs it but the runtime app does not).
    """
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    dev = data.get("devDependencies", {}) or {}
    assert "@capacitor/cli" in dev


# --- 4. capacitor.config.json points at the live dashboard ------------


def test_capacitor_config_app_id_is_set() -> None:
    data = json.loads(CAPACITOR_CONFIG.read_text(encoding="utf-8"))
    assert data.get("appId"), "appId is required for `cap add ios/android`"
    # Reverse-DNS style: reverse the Java-package convention.
    assert "." in data["appId"], (
        f"appId {data['appId']!r} should be a reverse-DNS string"
    )


def test_capacitor_config_app_name_is_set() -> None:
    data = json.loads(CAPACITOR_CONFIG.read_text(encoding="utf-8"))
    assert data.get("appName"), "appName is required so the App Store label isn't 'My App'"


def test_capacitor_config_web_dir_is_www() -> None:
    data = json.loads(CAPACITOR_CONFIG.read_text(encoding="utf-8"))
    assert data.get("webDir") == "www"


def test_capacitor_config_server_url_is_live_dashboard() -> None:
    """The WebView target must be the live dashboard URL. The
    kanban card scopes the wrap to the Next.js marketing site at
    https://ai-billing-audit.ashbi.ca/.
    """
    data = json.loads(CAPACITOR_CONFIG.read_text(encoding="utf-8"))
    server = data.get("server", {}) or {}
    assert server.get("url") == EXPECTED_DASHBOARD_URL, (
        f"server.url {server.get('url')!r} != expected "
        f"{EXPECTED_DASHBOARD_URL!r}"
    )


def test_capacitor_config_does_not_allow_cleartext() -> None:
    """A WebView wrap of a remote HTTPS dashboard must not
    silently allow HTTP fallbacks. The dashboard is HTTPS-only
    (Cloudflare in front), so cleartext traffic would be a
    downgrade attack vector.
    """
    data = json.loads(CAPACITOR_CONFIG.read_text(encoding="utf-8"))
    server = data.get("server", {}) or {}
    assert server.get("cleartext") is False


# --- 5. www/index.html is a real splash, not a stub -------------------


def test_www_index_html_has_doctype() -> None:
    body = WWW_INDEX.read_text(encoding="utf-8").lstrip()
    assert body.lower().startswith("<!doctype html"), (
        "www/index.html should start with a DOCTYPE"
    )


def test_www_index_html_references_dashboard_url() -> None:
    """Even though Capacitor's server.url is what the WebView
    actually loads, www/index.html ships as a fallback and must
    point at the same dashboard URL so a cached / offline launch
    doesn't go to a 404.
    """
    body = WWW_INDEX.read_text(encoding="utf-8")
    assert EXPECTED_DASHBOARD_URL in body, (
        f"www/index.html should mention {EXPECTED_DASHBOARD_URL}"
    )


def test_www_index_html_has_viewport_meta() -> None:
    """Without a viewport meta, the WebView falls back to a
    980px-wide desktop layout — useless on a phone.
    """
    body = WWW_INDEX.read_text(encoding="utf-8")
    assert "name=\"viewport\"" in body


# --- 6. README documents the build path -------------------------------


def test_readme_documents_cap_add_ios() -> None:
    body = README.read_text(encoding="utf-8")
    assert "cap add ios" in body


def test_readme_documents_cap_add_android() -> None:
    body = README.read_text(encoding="utf-8")
    assert "cap add android" in body


def test_readme_documents_cap_sync() -> None:
    body = README.read_text(encoding="utf-8")
    assert "cap sync" in body


def test_readme_documents_cap_open_ios() -> None:
    body = README.read_text(encoding="utf-8")
    assert "cap open ios" in body


def test_readme_mentions_kanban_card_id() -> None:
    """The README ties the scaffold back to the kanban card so a
    future contributor can find the original requirements
    without grepping git history.
    """
    body = README.read_text(encoding="utf-8")
    assert "t_7004415a" in body
