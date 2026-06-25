# influencers-link — DNS follow-up: 2 subdomains still on dead VPS

**Task:** `t_35a685d4` (blocked)
**Owner:** Cam (DNS control panel access)
**Context:** Cam just fixed `app.influencerslink.com` (was 187.77.26.99, now 88.223.82.6). Two related subdomains still point at the dead VPS — needs the same fix.

## Subdomains to fix

| Subdomain | Current (dead VPS) | Target |
|---|---|---|
| `influencer-link.ashbi.ca` | A 187.77.26.99 | A 88.223.82.6 |
| `link.ashbi.ca` | A 187.77.26.99 | A 88.223.82.6 |

## DNS change (Cam)

Both are subdomains of `ashbi.ca`, managed in Cloudflare (assuming
Cam kept the same provider as the prior fix):

1. dash.cloudflare.com → `ashbi.ca`
2. DNS → Records → find each A record → edit value to `88.223.82.6`
3. Set TTL to 300 for both
4. Save

## VPS Caddy cleanup

The current Caddy config on 187.77.26.99 likely still has routes for
these two subdomains pointing to the dead Coolify container. After
DNS flips, these routes are dead letters. Cam should:

```bash
ssh root@187.77.26.99

# Check current routes
grep -E 'influencer-link\.ashbi\.ca|link\.ashbi\.ca' /opt/caddy/Caddyfile
# If they're there, remove the blocks

# Reload Caddy
systemctl reload caddy
# OR
cd /opt/caddy && docker compose restart caddy
```

## Post-flight verification

```bash
# DNS resolution
dig +short influencer-link.ashbi.ca A
# Expected: 88.223.82.6
dig +short link.ashbi.ca A
# Expected: 88.223.82.6

# From external resolver
dig @8.8.8.8 +short influencer-link.ashbi.ca A
# Expected: 88.223.82.6

# Old IP gone
dig +short influencer-link.ashbi.ca A | grep -F 187.77.26.99
# Expected: empty

# Sites load
curl -sk -o /dev/null -w '%{http_code}\n' https://influencer-link.ashbi.ca/
curl -sk -o /dev/null -w '%{http_code}\n' https://link.ashbi.ca/
# Expected: 200

# App-side reach (this proves the public_html wildcard on 88.223.82.6 handles them)
curl -sk https://influencer-link.ashbi.ca/api/health
# Expected: 200, similar to app.influencerslink.com response
```

## Acceptance criteria

- [ ] `influencer-link.ashbi.ca` resolves to 88.223.82.6
- [ ] `link.ashbi.ca` resolves to 88.223.82.6
- [ ] Old 187.77.26.99 IP gone from both
- [ ] Both URLs load over HTTPS with 200
- [ ] VPS Caddyfile has the dead routes removed (or commented out)
- [ ] Caddy reloaded

## Rollback

Re-add A records pointing back to 187.77.26.99. Restore Caddy routes from git history if removed.

## Estimated time

5 min DNS + 5 min Caddy cleanup + 5 min verification = 15 min.