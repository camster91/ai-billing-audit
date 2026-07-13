"""Per-release body content for /changelog/{version}.

The marketing changelog at templates/changelog.html lists 5
releases (v0.5.0, v0.4.0, v0.3.0, v0.2.0, v0.1.0) with
their titles + summaries. The detail page at
/changelog/{version} shows the full body + what shipped +
what changed.

The release metadata (id, title, published, summary) is
duplicated in :mod:`ai_billing_audit.feeds` as
``CHANGELOG_RELEASES`` for the RSS feed. The full body
content lives here so the RSS feed stays compact.
"""
from __future__ import annotations

import datetime
from typing import Any


def _body_v050() -> str:
    return (
        "<p>The first public release of Zorva. Live marketing "
        "site, per-finding Accept/Dismiss, shadow runner CLI, "
        "and the Privacy Officer Brief are all live.</p>"
        "<h2>Added</h2>"
        "<ul>"
        "<li>Live marketing site at "
        "<code>https://ai-billing-audit.ashbi.ca</code></li>"
        "<li>Per-finding Accept / Dismiss on the dashboard "
        "(was previously encounter-level only)</li>"
        "<li>Shadow runner CLI "
        "(<code>scripts/shadow_audit.py</code>) for the "
        "100-claim no-cost pilot</li>"
        "<li>Privacy Officer Brief at "
        "<code>/legal/privacy</code></li>"
        "<li>First Alberta prospect list (12 clinics, "
        "prioritized in research/P5)</li>"
        "</ul>"
        "<h2>Changed</h2>"
        "<ul>"
        "<li>Engagement letter pricing copy updated to "
        "PHIPA-aligned audit-trail wording</li>"
        "</ul>"
        "<h2>Fixed</h2>"
        "<ul>"
        "<li><code>re</> import bug in <code>api.py</code> "
        "that crashed the encounter-detail page on cold start</li>"
        "</ul>"
    )


def _body_v040() -> str:
    return (
        "<p>The 18 AHCIP rules ship in this release. v12 of "
        "the auditor prompt with F1=0.690 baseline on the "
        "cleaned AHCIP val set.</p>"
        "<h2>Added</h2>"
        "<ul>"
        "<li>18 AHCIP rules covering modifier-25, telehealth, "
        "CMGP, lab coverage, most-common AHCIP denial codes</li>"
        "<li>v12 prompt tuning with shadow-audit harness</li>"
        "</ul>"
        "<h2>Known limitations</h2>"
        "<ul>"
        "<li>No per-finding accept/dismiss — encounter-level "
        "only (fixed in v0.5.0)</li>"
        "<li>No public marketing site (fixed in v0.5.0)</li>"
        "</ul>"
    )


def _body_v030() -> str:
    return (
        "<p>The dashboard ships. Hash-chained audit trail, "
        "offline re-verify tool, and RBAC roles.</p>"
        "<h2>Added</h2>"
        "<ul>"
        "<li>Audits dashboard at <code>/audits</code></li>"
        "<li>Hash-chained audit trail (every state-changing "
        "click signs the prior row)</li>"
        "<li>Offline re-verify tool "
        "(<code>scripts/verify_audit_chain.py</code>)</li>"
        "<li>RBAC roles (admin / biller / read-only)</li>"
        "</ul>"
    )


def _body_v020() -> str:
    return (
        "<p>Multi-tenant data model. Per-tenant audit chain. "
        "Bearer token auth. Stripe Checkout.</p>"
        "<h2>Added</h2>"
        "<ul>"
        "<li>Multi-tenant data model with per-tenant audit chain</li>"
        "<li>Bearer token auth "
        "(<code>AUDIT_BEARER_TOKEN</code> env var)</li>"
        "<li>Stripe Checkout for tier subscriptions</li>"
        "</ul>"
    )


def _body_v010() -> str:
    return (
        "<p>First deployment to <code>ai-billing-audit.ashbi.ca</code>. "
        "837P / CSV / paste-form ingest. v8 prompt with 8 AHCIP "
        "rules. Single-user demo account.</p>"
        "<h2>Added</h2>"
        "<ul>"
        "<li>837P / CSV / paste-form ingest</li>"
        "<li>v8 prompt with 8 AHCIP rules</li>"
        "<li>Single-user demo account</li>"
        "<li>Traefik HTTPS front, in-stack Caddy reverse proxy</li>"
        "</ul>"
    )


_RELEASE_BODIES: dict[str, str] = {
    "v0.5.0": _body_v050(),
    "v0.4.0": _body_v040(),
    "v0.3.0": _body_v030(),
    "v0.2.0": _body_v020(),
    "v0.1.0": _body_v010(),
}


def get_release(version: str) -> dict[str, Any] | None:
    """Look up a single release by version (e.g. 'v0.5.0')."""
    from .feeds import CHANGELOG_RELEASES
    for r in CHANGELOG_RELEASES:
        if r["id"] == version:
            return {
                **r,
                "body_html": _RELEASE_BODIES.get(version, ""),
            }
    return None


def list_releases() -> list[dict[str, Any]]:
    """All releases with their bodies, newest first."""
    from .feeds import CHANGELOG_RELEASES
    out: list[dict[str, Any]] = []
    for r in CHANGELOG_RELEASES:
        out.append({
            **r,
            "body_html": _RELEASE_BODIES.get(r["id"], ""),
        })
    return out
