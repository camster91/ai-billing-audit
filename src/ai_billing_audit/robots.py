"""Static /robots.txt for Zorva.

Allow all well-behaved crawlers (Google, Bing, DuckDuckGo, the
common social-card fetchers for Open Graph). Explicitly disallow
a small set of paths that exist for product or admin purposes
and should not be indexed:

- /admin            - admin console (when present)
- /api/             - all API endpoints (auth required; no SEO value)
- /audits           - the dashboard; auth-gated; no SEO value
- /encounters/      - per-encounter audit results
- /encounter/       - same, singular

The User-agent section is permissive by default. The
social-card fetchers (Slack, Twitter, Facebook, LinkedIn, Discord)
hit /, /pricing, etc. with no rate limit; for Zorva's current
traffic this is fine. If we ever need to gate specific bots,
add their User-agent token to the disallow block.
"""
ROBOTS_TXT = """# Zorva &mdash; https://ai-billing-audit.ashbi.ca

User-agent: *
Allow: /

# Block internal-tool paths from search engines
Disallow: /api/
Disallow: /audits
Disallow: /encounters/
Disallow: /encounter/
Disallow: /admin

# Point crawlers at the sitemap
Sitemap: https://ai-billing-audit.ashbi.ca/sitemap.xml
"""
