"""Tests for the RSS feed and sitemap.

The feeds module is the source of truth for the public
marketing feed and sitemap. Pin the contract here so a
template change doesn't silently drop an entry.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest
from starlette.testclient import TestClient

from ai_billing_audit.api import app
from ai_billing_audit.feeds import (
    BLOG_POSTS,
    CHANGELOG_RELEASES,
    PUBLIC_MARKETING_PATHS,
    build_atom_feed,
    build_sitemap,
)


def test_blog_post_count_pinned() -> None:
    """If the count changes, the test reminds the author to
    update the /blog template to match."""
    assert len(BLOG_POSTS) == 4, (
        f"BLOG_POSTS count is {len(BLOG_POSTS)}; /blog page "
        f"renders 4 launch posts. Add or remove both."
    )


def test_changelog_release_count_pinned() -> None:
    """Same pin for /changelog."""
    assert len(CHANGELOG_RELEASES) == 5, (
        f"CHANGELOG_RELEASES count is {len(CHANGELOG_RELEASES)}; "
        f"/changelog page renders 5 releases. Add or remove both."
    )


def test_blog_post_required_fields() -> None:
    """Every blog post has the 5 fields the feed needs."""
    required = {"id", "title", "published", "summary", "url_path"}
    for post in BLOG_POSTS:
        missing = required - set(post.keys())
        assert not missing, f"Blog post {post.get('id')!r} missing: {missing}"


def test_changelog_release_required_fields() -> None:
    required = {"id", "title", "published", "summary", "url_path"}
    for release in CHANGELOG_RELEASES:
        missing = required - set(release.keys())
        assert not missing, f"Changelog {release.get('id')!r} missing: {missing}"


def test_blog_post_published_is_aware_datetime() -> None:
    """A naive datetime would be ambiguous in the Atom feed
    (RFC 3339 with no offset is invalid)."""
    for post in BLOG_POSTS:
        assert post["published"].tzinfo is not None, (
            f"Blog post {post['id']!r} has naive datetime; must be tz-aware"
        )


def test_changelog_release_published_is_aware_datetime() -> None:
    for release in CHANGELOG_RELEASES:
        assert release["published"].tzinfo is not None, (
            f"Changelog {release['id']!r} has naive datetime; must be tz-aware"
        )


def test_build_atom_feed_returns_valid_xml() -> None:
    xml = build_atom_feed("https://example.com")
    # Should parse as valid XML.
    root = ET.fromstring(xml)
    assert root.tag.endswith("}feed") or root.tag == "feed"
    # Atom namespace check.
    assert root.tag.startswith("{http://www.w3.org/2005/Atom}")


def test_build_atom_feed_includes_all_entries() -> None:
    """Every blog post + every changelog release must appear
    in the feed (no silent drops)."""
    xml = build_atom_feed("https://example.com")
    root = ET.fromstring(xml)
    ns = "{http://www.w3.org/2005/Atom}"
    titles = {e.findtext(f"{ns}title") for e in root.findall(f"{ns}entry")}
    for post in BLOG_POSTS:
        assert post["title"] in titles, f"Blog post {post['title']!r} missing from feed"
    for release in CHANGELOG_RELEASES:
        assert release["title"] in titles, (
            f"Changelog {release['title']!r} missing from feed"
        )


def test_build_atom_feed_entries_newest_first() -> None:
    """Readers expect newest-first ordering."""
    xml = build_atom_feed("https://example.com")
    root = ET.fromstring(xml)
    ns = "{http://www.w3.org/2005/Atom}"
    updated_times = [e.findtext(f"{ns}updated") for e in root.findall(f"{ns}entry")]
    assert updated_times == sorted(updated_times, reverse=True), (
        f"Feed is not newest-first: {updated_times}"
    )


def test_build_sitemap_returns_valid_xml() -> None:
    xml = build_sitemap("https://example.com", ["/foo", "/bar"])
    root = ET.fromstring(xml)
    assert root.tag.endswith("}urlset") or root.tag == "urlset"


def test_build_sitemap_includes_every_path() -> None:
    paths = ["/", "/pricing", "/try", "/security"]
    xml = build_sitemap("https://example.com", paths)
    root = ET.fromstring(xml)
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    locs = {
        u.findtext(f"{ns}loc").removeprefix("https://example.com")
        for u in root.findall(f"{ns}url")
    }
    for path in paths:
        assert path in locs, f"Path {path!r} missing from sitemap"


def test_public_marketing_paths_no_trailing_slash_duplicates() -> None:
    """Sitemap entries must be canonical. If /about and /about/
    both show up, search engines will index them as separate
    URLs."""
    for path in PUBLIC_MARKETING_PATHS:
        assert not path.endswith("/") or path == "/", (
            f"Path {path!r} has trailing slash; use the canonical form"
        )


# --- HTTP-level tests (require the auth-middleware to allow
# /rss.xml + /sitemap.xml through) ---


def test_rss_endpoint_returns_200(client: TestClient) -> None:
    r = client.get("/rss.xml")
    assert r.status_code == 200
    assert "application/atom+xml" in r.headers["content-type"]


def test_sitemap_endpoint_returns_200(client: TestClient) -> None:
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "application/xml" in r.headers["content-type"]


def test_rss_endpoint_includes_recent_blog_title(client: TestClient) -> None:
    r = client.get("/rss.xml")
    # The most recent blog post's title should be in the body.
    most_recent = max(BLOG_POSTS, key=lambda p: p["published"])
    assert most_recent["title"] in r.text


def test_sitemap_includes_high_priority_paths(client: TestClient) -> None:
    """Home / pricing / try get priority 0.8 in the sitemap.
    Other paths get 0.5. Pin the high-priority set."""
    r = client.get("/sitemap.xml")
    # The test client uses 'testserver' as host. We just check
    # the path appears; the host is constructed from
    # request.headers['host'] in the route handler.
    import re

    high_priority = ["/", "/pricing", "/try"]
    for path in high_priority:
        # Match <loc>...<path>...</loc> (path is '/' for home)
        pattern = rf"<loc>[^<]+{re.escape(path)}</loc>"
        if path == "/":
            pattern = r"<loc>[^<]+/</loc>"
        assert re.search(pattern, r.text), (
            f"High-priority path {path!r} missing from sitemap"
        )
        # Verify the priority is 0.8 for these specific paths.
        # Find the <url> block that contains this path.
        url_match = re.search(
            rf"<url>\s*<loc>[^<]+{re.escape(path)}</loc>.*?</url>",
            r.text,
            re.DOTALL,
        )
        assert url_match, f"<url> block for {path!r} not found"
        assert "<priority>0.8</priority>" in url_match.group(0), (
            f"Path {path!r} should have priority 0.8"
        )


@pytest.fixture
def client():
    return TestClient(app)
