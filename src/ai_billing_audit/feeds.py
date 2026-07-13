"""RSS / Atom feed for Zorva blog + changelog.

`/rss.xml` returns an Atom 1.0 feed (Atom is the modern standard
and renders fine in every reader that supports RSS). The feed
combines the blog index and the changelog index so subscribers
get a single source of "what's new on the Zorva site."

For now this is a static feed built from the in-template post
list. When a real blog backend is added (kanban card mentioned
in /blog h2), the feed moves to read from the same source.
"""
from __future__ import annotations

import datetime
from xml.etree import ElementTree as ET
from xml.dom import minidom

from fastapi import Request
from fastapi.responses import Response


ATOM_NS = "http://www.w3.org/2005/Atom"


# Source-of-truth entries: matches the /blog and /changelog
# page bodies. Keep these in sync when either page changes.
BLOG_POSTS: list[dict] = [
    {
        "id": "why-we-built-zorva",
        "title": "Why we built Zorva (and not a billing service)",
        "published": datetime.datetime(2026, 7, 13, 9, 0, 0, tzinfo=datetime.timezone.utc),
        "summary": (
            "Most AHCIP billing software falls into one of two "
            "categories: a managed submission service, or an EMR "
            "billing module. Neither of them reads the clinical "
            "note against the AHCIP fee schedule. We built one that does."
        ),
        "url_path": "/blog/why-we-built-zorva",
    },
    {
        "id": "18-ahcip-rules",
        "title": "The 18 AHCIP rules in v12",
        "published": datetime.datetime(2026, 7, 8, 9, 0, 0, tzinfo=datetime.timezone.utc),
        "summary": (
            "v12 of the Zorva prompt ships with 18 AHCIP rules "
            "covering the highest-yield patterns Alberta billers see "
            "on every claim."
        ),
        "url_path": "/blog/18-ahcip-rules",
    },
    {
        "id": "why-flat-fee",
        "title": "Why we charge flat-fee, not per-claim",
        "published": datetime.datetime(2026, 7, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
        "summary": (
            "Per-claim pricing punishes the clinics that need the "
            "most help. We picked flat-fee because the alternative "
            "rewards us for not running the auditor on the trickiest claims."
        ),
        "url_path": "/blog/why-flat-fee",
    },
    {
        "id": "why-alberta-first",
        "title": "Why Alberta first",
        "published": datetime.datetime(2026, 6, 22, 9, 0, 0, tzinfo=datetime.timezone.utc),
        "summary": (
            "Zorva started as an Ontario-pivot idea. Then we looked "
            "at the Alberta AHCIP fee schedule, talked to six "
            "Alberta billers, and realized the entire competitive "
            "landscape was different."
        ),
        "url_path": "/blog/why-alberta-first",
    },
]


CHANGELOG_RELEASES: list[dict] = [
    {
        "id": "v0.5.0",
        "title": "v0.5.0 \u2014 Marketing site + pre-submit pilot ready",
        "published": datetime.datetime(2026, 7, 4, 18, 0, 0, tzinfo=datetime.timezone.utc),
        "summary": (
            "Live marketing site at ai-billing-audit.ashbi.ca. "
            "Per-finding Accept/Dismiss. Shadow runner CLI for the "
            "100-claim no-cost pilot. Privacy Officer Brief. "
            "First Alberta prospect list (12 clinics)."
        ),
        "url_path": "/changelog#v0-5-0",
    },
    {
        "id": "v0.4.0",
        "title": "v0.4.0 \u2014 v12 prompt + 18 AHCIP rules",
        "published": datetime.datetime(2026, 6, 15, 18, 0, 0, tzinfo=datetime.timezone.utc),
        "summary": (
            "v12 auditor prompt with 18 AHCIP rules covering "
            "modifier-25, telehealth, CMGP, lab coverage, "
            "most-common AHCIP denial codes. F1=0.690 baseline on "
            "the cleaned AHCIP val set."
        ),
        "url_path": "/changelog#v0-4-0",
    },
    {
        "id": "v0.3.0",
        "title": "v0.3.0 \u2014 Dashboard + hash-chained audit trail",
        "published": datetime.datetime(2026, 5, 1, 18, 0, 0, tzinfo=datetime.timezone.utc),
        "summary": (
            "Audits dashboard, hash-chained audit trail (every "
            "state-changing click signs the prior row), re-verify "
            "offline tool, RBAC roles."
        ),
        "url_path": "/changelog#v0-3-0",
    },
    {
        "id": "v0.2.0",
        "title": "v0.2.0 \u2014 Multi-tenant + auth",
        "published": datetime.datetime(2026, 4, 1, 18, 0, 0, tzinfo=datetime.timezone.utc),
        "summary": (
            "Multi-tenant data model with per-tenant audit chain. "
            "Bearer token auth. Stripe Checkout for tier subscriptions."
        ),
        "url_path": "/changelog#v0-2-0",
    },
    {
        "id": "v0.1.0",
        "title": "v0.1.0 \u2014 First deployment",
        "published": datetime.datetime(2026, 2, 15, 18, 0, 0, tzinfo=datetime.timezone.utc),
        "summary": (
            "First deployment to ai-billing-audit.ashbi.ca. "
            "837P / CSV / paste-form ingest. v8 prompt with 8 AHCIP "
            "rules. Single-user demo account."
        ),
        "url_path": "/changelog#v0-1-0",
    },
]


def _atom_entry(entry: dict, host: str) -> ET.Element:
    """Build a single <entry> for an Atom feed."""
    e = ET.Element("entry")
    ET.SubElement(e, "title").text = entry["title"]
    full_url = f"{host}{entry['url_path']}"
    ET.SubElement(e, "id").text = full_url
    ET.SubElement(e, "link", href=full_url, rel="alternate")
    ET.SubElement(e, "updated").text = entry["published"].isoformat()
    ET.SubElement(e, "published").text = entry["published"].isoformat()
    author = ET.SubElement(e, "author")
    ET.SubElement(author, "name").text = "Cameron Ashley"
    ET.SubElement(e, "summary", type="text").text = entry["summary"]
    return e


def build_atom_feed(host: str) -> str:
    """Build the Atom 1.0 XML feed combining blog + changelog."""
    feed = ET.Element("feed", xmlns=ATOM_NS)
    ET.SubElement(feed, "title").text = "Zorva \u2014 blog + changelog"
    ET.SubElement(feed, "subtitle").text = (
        "Build notes, AHCIP observations, and release notes from Zorva."
    )
    ET.SubElement(feed, "id").text = f"{host}/rss.xml"
    ET.SubElement(feed, "link", href=f"{host}/rss.xml", rel="self")
    ET.SubElement(feed, "link", href=f"{host}/", rel="alternate")
    author = ET.SubElement(feed, "author")
    ET.SubElement(author, "name").text = "Cameron Ashley"
    ET.SubElement(author, "email").text = "cameron@ashbi.ca"
    ET.SubElement(feed, "updated").text = (
        max(
            (e["published"] for e in BLOG_POSTS + CHANGELOG_RELEASES),
            default=datetime.datetime.now(datetime.timezone.utc),
        ).isoformat()
    )
    ET.SubElement(feed, "generator", uri="https://github.com/camster91/ai-billing-audit", version="0.5.0").text = (
        "Zorva (custom)"
    )
    # Newest first
    entries = sorted(
        BLOG_POSTS + CHANGELOG_RELEASES,
        key=lambda e: e["published"],
        reverse=True,
    )
    for entry in entries:
        feed.append(_atom_entry(entry, host))
    raw = ET.tostring(feed, encoding="utf-8", xml_declaration=True)
    # Pretty-print for human readability
    return minidom.parseString(raw).toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")


def build_sitemap(host: str, public_paths: list[str]) -> str:
    """Build sitemap.xml for all public marketing routes."""
    # 1.0.0 is the earliest sitemap format; 0.9 is the latest
    urlset = ET.Element(
        "urlset",
        xmlns="http://www.sitemaps.org/schemas/sitemap/0.9",
    )
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    for path in public_paths:
        url = ET.SubElement(urlset, "url")
        ET.SubElement(url, "loc").text = f"{host}{path}"
        ET.SubElement(url, "lastmod").text = now
        # Marketing pages update at human speed; changelog at
        # human speed; everything else at the same rate.
        priority = "0.8" if path in ("/", "/pricing", "/try") else "0.5"
        ET.SubElement(url, "priority").text = priority
        ET.SubElement(url, "changefreq").text = "weekly"
    raw = ET.tostring(urlset, encoding="utf-8", xml_declaration=True)
    return minidom.parseString(raw).toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")


# The list of public marketing paths for the sitemap. Keep in
# sync with the route definitions in api.py + the public_read
# whitelist in _bearer_auth_middleware.
PUBLIC_MARKETING_PATHS = [
    "/",
    "/about",
    "/blog",
    "/careers",
    "/changelog",
    "/compare",
    "/contact",
    "/demo-request",
    "/faq",
    "/for/family-medicine",
    "/glossary",
    "/how-it-works",
    "/legal/privacy",
    "/legal/terms",
    "/pilot",
    "/press",
    "/pricing",
    "/roi",
    "/case-studies",
    "/security",
    "/status",
    "/trust",
    "/try",
    "/what-zorva-finds",
    "/audits",  # dashboard
]
