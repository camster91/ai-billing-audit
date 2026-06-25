# alinenasseh — Rotate production secrets in /opt/alinenasseh-php/.env

**Task:** `t_d534669b` (blocked)
**Owner:** Cam (needs Stripe dashboard + mail provider credentials)
**Goal:** Replace placeholder Stripe + SMTP secrets in the live `.env` so checkout and the contact form mail work.

## Current state (pre-flight)

```bash
ssh root@187.77.26.99 'cat /opt/alinenasseh-php/.env'
```

Expected placeholders to replace:
- `STRIPE_SECRET_KEY=CHANGEME_xxx` (currently starts with `pk_test_` or has `CHANGEME`)
- `STRIPE_WEBHOOK_SECRET=whsec_CHANGEME_xxx`
- `MAIL_SMTP_PASS=CHANGEME`
- `MAIL_FROM_EMAIL=noreply@alinenasseh.com` (but mail is not actually sending)

**Do NOT touch** (already real):
- `DB_PASSWORD=...`
- `ADMIN_BCRYPT_HASH=...`

## Steps (Cam)

### 1. Stripe live keys

1. Log into https://dashboard.stripe.com (live mode, top-right toggle)
2. Developers → API keys → Reveal live key → copy `sk_live_...`
3. Developers → Webhooks → select the live endpoint (the URL
   `https://alinenasseh.com/api/stripe/webhook`) → Reveal signing
   secret → copy `whsec_...`

### 2. Mail provider credentials

Use whichever provider is configured (check `.env` for `MAIL_SMTP_HOST`).
- If Hostinger mail: get SMTP password from hPanel → Emails → manage
- If SendGrid: dashboard → Settings → API keys
- If Postmark: dashboard → Servers → credentials

The `MAIL_FROM_EMAIL` MUST be on a verified sender domain. For
`alinenasseh.com`, that means adding DNS records (SPF + DKIM) at the
DNS provider — see the DNS flip doc for that.

If the DNS isn't set up yet, use a temporary `@ashbi.ca` address
(initially `noreply@ashbi.ca`, change later when alinenasseh.com's
mail is verified).

### 3. Edit the .env on the VPS

```bash
ssh root@187.77.26.99
cd /opt/alinenasseh-php
cp .env .env.backup-$(date +%Y%m%d-%H%M%S)
# Use sed or a text editor to replace ONLY these 4 lines:
#   STRIPE_SECRET_KEY=sk_live_NEW_VALUE_HERE
#   STRIPE_WEBHOOK_SECRET=whsec_NEW_VALUE_HERE
#   MAIL_SMTP_PASS=NEW_VALUE_HERE
#   MAIL_FROM_EMAIL=noreply@ashbi.ca  (or verified @alinenasseh.com)
```

### 4. Reload the service

```bash
# Find the service name
systemctl list-units --type=service | grep -i 'alinenasseh\|php-fpm'
# Then:
systemctl reload alinenasseh-php    # if the service exists
# OR
systemctl restart php8.2-fpm       # fallback for FPM
# OR (if Docker-based)
cd /opt/alinenasseh-php && docker compose restart php
```

### 5. Verify

```bash
# Stripe checkout works (need a real test product)
curl -sk -X POST https://alinenasseh.com/api/stripe/checkout-test \
  -H 'Content-Type: application/json' -d '{}' --max-time 15
# Expected: 200 with session_id OR 400 with a clear "missing product" message
# NOT: 500 "Invalid API Key"

# Contact form actually sends
curl -sk -X POST https://alinenasseh.com/contact \
  -d 'name=Test&email=test@ashbi.ca&message=secret-rotation-smoke-test' \
  --max-time 15
# Expected: 200 with success message AND email arrives in inbox

# Confirm via the mail provider's dashboard that the send was logged
```

## Acceptance criteria

- [ ] `STRIPE_SECRET_KEY` starts with `sk_live_` (no `CHANGEME`)
- [ ] `STRIPE_WEBHOOK_SECRET` is real `whsec_...`, not placeholder
- [ ] `MAIL_SMTP_PASS` and `MAIL_FROM_EMAIL` are real
- [ ] `MAIL_FROM_EMAIL` uses a verified sender domain
- [ ] DB password + admin bcrypt hash unchanged
- [ ] Service reloaded after the edit
- [ ] Live Stripe test checkout succeeds (or appropriate API call)
- [ ] Contact form submission results in email received

## Out of scope

- Rotating DB password or admin bcrypt hash
- Changing application code, config schemas, non-env settings
- Creating new Stripe products / prices / webhook endpoints
- Migrating to a different mail provider

## Rollback

```bash
ssh root@187.77.26.99 'cd /opt/alinenasseh-php && cp .env.backup-LATEST .env && systemctl reload alinenasseh-php'
```

## Estimated time

10 min if keys are already in 1Password; 30 min if you need to
generate Stripe live keys + verify mail sender domain first.