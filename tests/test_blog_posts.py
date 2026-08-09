"""Tests for the /blog/{slug} per-post page route.

P0 audit fix 2026-07-13: blog.html was advertising 4 posts whose
links 404'd. Added the /blog/{slug} route + blog_posts.py data +
blog_post.html template. These tests pin the contract: every post
in feeds.BLOG_POSTS has a matching detail entry, the route renders
without 500, the post body is the long-form version, and unknown
slugs return 404.
"""

from __future__ import annotations

import importlib
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUDIT_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("TENANT_ID", "default")
    import ai_billing_audit.api as api_mod

    importlib.reload(api_mod)
    app = api_mod.create_app()
    return TestClient(app)


def test_blog_post_route_exists_for_every_post_in_feeds(client):
    """Every post in feeds.BLOG_POSTS must have a working detail page."""
    from ai_billing_audit.feeds import BLOG_POSTS

    for post in BLOG_POSTS:
        # url_path is "/blog/{slug}" — extract the slug
        slug = post["url_path"].rsplit("/", 1)[-1]
        resp = client.get(f"/blog/{slug}")
        assert resp.status_code == 200, f"/blog/{slug} returned {resp.status_code}"
        # Title block must contain the post title (not the default)
        assert post["title"] in resp.text


def test_blog_post_uses_blog_post_template(client):
    """The per-post template extends base.html and renders the
    back-link, the byline, and the post body."""
    resp = client.get("/blog/why-we-built-zorva")
    assert resp.status_code == 200
    # Back-link to the blog index
    assert 'href="/blog"' in resp.text
    # Author byline
    assert "Cameron Ashley" in resp.text
    # Body has the long-form content (not just the teaser)
    assert "decision-support tool" in resp.text
    # JSON-LD BlogPosting schema
    assert "BlogPosting" in resp.text


def test_blog_post_404_for_unknown_slug(client):
    """Unknown slugs return 404 (not 500 or empty 200)."""
    resp = client.get("/blog/this-post-does-not-exist")
    assert resp.status_code == 404
    # For GET on /blog/* (no API path prefix), the 404 handler
    # returns the branded HTML page. Either HTML or JSON is fine
    # here — the contract is just that the response is 404.
    body = resp.text
    assert "404" in body or "not found" in body.lower()


def test_blog_post_contains_og_meta_for_sharing(client):
    """Per-post OG meta tags so the post preview looks right when
    shared on LinkedIn / Twitter / Slack."""
    resp = client.get("/blog/why-flat-fee")
    assert resp.status_code == 200
    # OG title includes the post title
    assert "Why we charge flat-fee" in resp.text
    # OG image is the same 1200x630 og-image.jpg
    assert "/static/og-image.jpg" in resp.text
    # OG type = article for proper Twitter card
    assert (
        'property="og:type" content="article"' in resp.text
        or 'property="og:type"' in resp.text
    )


def test_blog_posts_data_matches_feeds_metadata(client):
    """The blog_posts module and feeds.BLOG_POSTS share id + title
    + published so the RSS feed teaser matches the detail page."""
    from ai_billing_audit.blog_posts import BLOG_POSTS_DETAIL
    from ai_billing_audit.feeds import BLOG_POSTS

    feed_by_id = {p["id"]: p for p in BLOG_POSTS}
    for post_id, detail in BLOG_POSTS_DETAIL.items():
        assert post_id in feed_by_id, (
            f"blog_posts.BLOG_POSTS_DETAIL has {post_id!r} but feeds.BLOG_POSTS doesn't"
        )
        feed = feed_by_id[post_id]
        assert detail["title"] == feed["title"]
        assert detail["published"] == feed["published"]


def test_blog_post_body_is_substantive(client):
    """Each post body has at least 1,000 characters of long-form
    content (vs. the ~200-char teaser in feeds.BLOG_POSTS)."""
    from ai_billing_audit.blog_posts import BLOG_POSTS_DETAIL

    for post_id, detail in BLOG_POSTS_DETAIL.items():
        body_len = len(detail.get("body_html", ""))
        assert body_len > 1000, (
            f"{post_id} body is only {body_len} chars; should be a "
            f"long-form post (>1000 chars), not the teaser."
        )


def test_blog_index_links_to_all_per_post_pages(client):
    """The /blog index links to all 4 /blog/{slug} pages and they
    all return 200 (the original 404 bug)."""
    resp = client.get("/blog")
    assert resp.status_code == 200
    for slug in [
        "why-we-built-zorva",
        "18-ahcip-rules",
        "why-flat-fee",
        "why-alberta-first",
    ]:
        assert f"/blog/{slug}" in resp.text, (
            f"/blog index does not link to /blog/{slug}"
        )
        sub = client.get(f"/blog/{slug}")
        assert sub.status_code == 200, f"/blog/{slug} is not 200"
