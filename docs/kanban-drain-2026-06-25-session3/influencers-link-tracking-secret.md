# influencers-link — Set TRACKING_SECRET across all 23 WP stores

**Task:** `t_8256d554` (blocked)
**Owner:** Cam generates secret, runs bulk script
**Goal:** Stop the 23 active stores' plugin heartbeats from being rejected with "no per-store secret for unknown and no global TRACKING_SECRET".

## Context

The v5.3.0 bootstrap never ran the per-store `signing_secret` migration,
and no `TRACKING_SECRET` env var was set on the dashboard. Every
heartbeat POST is silently dropped → stores show stale `last_seen`,
dispute webhooks stop firing, subscription data goes cold.

## Step 1 — Generate the secret (Cam)

```bash
# Pick a strong random 64-char hex
openssl rand -hex 32
# e.g. 8f3a2b9c1d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a
# Save this in 1Password under "WCM TRACKING_SECRET (shared)"
SECRET='<paste>'
```

## Step 2 — Set it on the dashboard (Cam)

```bash
# SSH to Hostinger box where the dashboard runs
ssh user@app.influencerslink.com  # or via ashbi-hostinger profile

# Edit the .htaccess that hosts the app
vi /home/u633679196/domains/app.influencerslink.com/public_html/.htaccess

# Add (next to existing CREDENTIAL_KEY and GITHUB_TOKEN SetEnv lines):
SetEnv TRACKING_SECRET "<the-secret>"

# Save + exit
```

## Step 3 — Bulk-update the 23 stores (script does this)

The script `./influencers-link-bulk-set-tracking-secret.sh` iterates
all 23 stores via WP-CLI over SSH.

## Step 4 — Verify rejection logs clear

```bash
# On the dashboard host, tail the error log
tail -F /home/u633679196/domains/app.influencerslink.com/public_html/stderr.log

# Look for:
#   "[Tracking] Rejected unsigned request: no per-store secret..."
# Expected: 0 new occurrences within 5 minutes of step 3 completing
# Also expected:
#   "[Tracking] Accepted signed heartbeat for store_id=N"  ← success messages
```

## Acceptance criteria

- [ ] `TRACKING_SECRET` set in `~/.htaccess` next to CREDENTIAL_KEY
- [ ] All 23 stores have `wcm_tracking_secret` option set in wp_options
- [ ] stderr.log no longer shows "Rejected unsigned request" lines
- [ ] At least one store shows updated `last_seen` within 10 minutes
- [ ] 1Password entry saved under "WCM TRACKING_SECRET (shared)"

## Out of scope

- Rotating CREDENTIAL_KEY or GITHUB_TOKEN
- Migrating to per-store signing keys (this batch uses the shared secret)
- Changing the dashboard's TRACKING_SECRET verification code

## Rollback

```bash
# Per-store: just delete the option
wp option delete wcm_tracking_secret --allow-root

# Dashboard: remove the SetEnv line from .htaccess
```

## Estimated time

5 min for secret gen + .htaccess edit, 3 min for bulk script, 5 min to verify.