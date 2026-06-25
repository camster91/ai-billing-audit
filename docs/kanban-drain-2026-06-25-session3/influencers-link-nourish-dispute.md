# influencers-link — URGENT Nourish Wellness dispute evidence

**Task:** `t_619b5e1a` (blocked)
**Deadline:** Tomorrow 23:59 UTC (originally Jun 15 — this is past the
original deadline, check Stripe dashboard for current deadline or
escalate to Natalie)
**Owner:** Cam (Stripe dashboard access) + agent (DB migration + code)

## Context

Stripe dispute `du_1Tcmn3DlzswYV7ifpDB81CPB`:
- Customer: Keisha L Johnson
- Amount: $1.50
- Reason: "Subscription canceled"
- Account: `acct_1S5VSZDlzswYV7if` (Nourish Wellness)

The dashboard has NO `stripe_secret_key` for this store — the lost
Coolify volume had it, and the new schema doesn't have those columns
either. Need a migration + a temporary workaround.

## Steps

### 1. Check current Stripe dispute state

```bash
# Get the live Stripe secret key from the WP install on Hostinger
ssh user@nourishwellness.com  # or use wp-cli over SSH
wp option get woocommerce_stripe_settings --allow-root --format=json | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('secret_key:', d.get('secret_key',''))
print('webhook_secret:', d.get('webhook_secret',''))
"

# Use that key to fetch the dispute
curl -sk https://api.stripe.com/v1/disputes/du_1Tcmn3DlzswYV7ifpDB81CPB \
  -u "$STRIPE_LIVE_KEY:" | python3 -m json.tool
```

### 2. Add migration 026 to the dashboard schema

```bash
cd /Users/biancabienaime/repos/influencers-link/dashboard
# New migration file: migrations/026_stripe_keys.sql
cat > migrations/026_stripe_keys.sql <<'EOF'
ALTER TABLE stores ADD COLUMN stripe_secret_key TEXT;
ALTER TABLE stores ADD COLUMN stripe_secret_key_encrypted TEXT;
-- Backfill: leave NULL for now (operators will populate per-store)
COMMENT ON COLUMN stores.stripe_secret_key IS 'Plaintext Stripe live secret key (sk_live_...). Encrypted column preferred.';
COMMENT ON COLUMN stores.stripe_secret_key_encrypted IS 'AES-256-GCM encrypted via CREDENTIAL_KEY. Use this for production.';
EOF

# Apply
psql "$DATABASE_URL" -f migrations/026_stripe_keys.sql
```

### 3. Encrypt + store the Nourish Wellness key

```bash
# In Node.js (use the existing CREDENTIAL_KEY helper)
node -e "
const c = require('./src/services/credential-cipher');
const fs = require('fs');
const key = process.argv[2];  // sk_live_...
const encrypted = c.encrypt(key);
process.stdout.write(encrypted);
" "sk_live_..." > /tmp/nw-encrypted.txt

# Update the dashboard row (use the encrypted form)
psql "$DATABASE_URL" -c "
UPDATE stores
SET stripe_secret_key_encrypted = '$(cat /tmp/nw-encrypted.txt)',
    stripe_secret_key = NULL  -- prefer the encrypted form
WHERE slug = 'nourish-wellness';
"
```

### 4. Sync the dispute to the disputes table

```bash
cd /Users/biancabienaime/repos/influencers-link/dashboard
# Run the existing sync (should now work since the key is available)
node src/services/dispute-sync-service.js sync-one du_1Tcmn3DlzswYV7ifpDB81CPB
```

### 5. Generate evidence (read existing patterns)

```bash
# Find existing dispute evidence patterns
grep -rn 'evidence' src/services/ | head -20
# Likely: dispute-evidence-service.js

# Generate evidence for this dispute
node src/services/dispute-evidence-service.js build \
  --dispute du_1Tcmn3DlzswYV7ifpDB81CPB \
  --output /tmp/nw-evidence.json

# Submit to Stripe
node src/services/dispute-evidence-service.js submit \
  --dispute du_1Tcmn3DlzswYV7ifpDB81CPB \
  --evidence /tmp/nw-evidence.json \
  --submit
```

### 6. Verify

```bash
# Dispute is now "under_review" or similar
curl -sk https://api.stripe.com/v1/disputes/du_1Tcmn3DlzswYV7ifpDB81CPB \
  -u "$STRIPE_LIVE_KEY:" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('status:', d.get('status'))
print('evidence_submitted:', bool(d.get('evidence_details',{}).get('due_by')))
print('amount:', d.get('amount'))
"

# Dashboard shows it as resolved
node src/services/dispute-sync-service.js status du_1Tcmn3DlzswYV7ifpDB81CPB
```

## Acceptance criteria

- [ ] Migration 026 applied to live DB
- [ ] Nourish Wellness store has `stripe_secret_key_encrypted` populated
- [ ] Dispute synced to disputes table
- [ ] Evidence submitted to Stripe
- [ ] Stripe shows status != "needs_response"
- [ ] Natalie (accounting@influencerslink.com) notified of completion

## If auto-submit fails by EOD

Send a Slack message to #accounting:
> Nourish Wellness dispute du_1Tcmn3DlzswYV7ifpDB81CPB ($1.50, due [DATE])
> status: [evidence failed / Stripe API error / etc]
> Action: Natalie to manually upload evidence via Stripe dashboard.
> Stripe dashboard URL: https://dashboard.stripe.com/disputes/du_1Tcmn3DlzswYV7ifpDB81CPB

## Estimated time

1 hour if all credentials work, 3 hours if Stripe key needs retrieval.