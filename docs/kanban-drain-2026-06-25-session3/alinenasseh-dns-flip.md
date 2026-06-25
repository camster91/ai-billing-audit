# alinenasseh — Flip DNS A-record to 187.77.26.99

**Task:** `t_1e257000` (blocked)
**Owner:** Cam (needs DNS provider login)
**Goal:** Repoint `alinenasseh.com` from WP Engine (141.193.213.10/.11) to the new VPS (187.77.26.99) where the artisan.ashbi.ca preview lives.

## Pre-flight (CLI can do this)

1. Verify current state:
   ```bash
   dig +short alinenasseh.com A
   # Expected currently: 141.193.213.10\n141.193.213.11
   dig +short alinenasseh.com AAAA
   # Likely empty
   ```

2. Verify the new host serves production content:
   ```bash
   curl -sk https://187.77.26.99/ -H 'Host: alinenasseh.com' | head -50
   # Should render the artisan.ashbi.ca page
   curl -sk -o /dev/null -w '%{http_code}\n' https://187.77.26.99/
   # Should be 200 (or 301→https)
   curl -sk -o /dev/null -w '%{http_code}\n' https://artisan.ashbi.ca/
   # Should be 200
   ```

3. Confirm staging-vs-prod mapping (what will go in the README):
   ```
   | Domain              | Purpose           | Host              |
   |---------------------|-------------------|-------------------|
   | alinenasseh.com     | Production        | 187.77.26.99      |
   | artisan.ashbi.ca    | Staging / preview | 187.77.26.99      |
   | alinenasseh.ca      | (legacy)          | WP Engine         |
   ```

## DNS change (Cam action)

The DNS provider for alinenasseh.com is **WP Engine's dashboard** (since the domain was registered through them, or via Cloudflare if Cam moved it). Either way:

### Option A — WP Engine DNS (most likely)
1. Log into my.wpengine.com
2. Domains → alinenasseh.com → DNS records
3. Delete the two A records pointing to `141.193.213.10` and `141.193.213.11`
4. Add one A record:
   - Host: `@` (apex)
   - Value: `187.77.26.99`
   - TTL: 300 (5 min — accelerate propagation)
5. Save

### Option B — Cloudflare
1. Log into dash.cloudflare.com → alinenasseh.com
2. DNS → Records → A `@`
3. Edit: 141.193.213.10 → 187.77.26.99
4. Delete the .11 record (or change to same)
5. Set TTL to Auto (300s)
6. Save

## Post-flight verification (Cam + probe script)

After saving, wait 60 seconds, then:
```bash
./alinenasseh-dns-probe.sh
```

Manual checks:
```bash
# From your local resolver:
dig +short alinenasseh.com A
# Expected: 187.77.26.99

# From external resolver (Google DNS):
dig @8.8.8.8 +short alinenasseh.com A
# Expected: 187.77.26.99

# HTTPS works:
curl -I https://alinenasseh.com
# Expected: HTTP/2 200 (or 301 → https with valid cert)

# Old IPs gone:
dig +short alinenasseh.com A | grep -E '141.193.213'
# Expected: empty

# SSL cert valid:
echo | openssl s_client -servername alinenasseh.com -connect alinenasseh.com:443 2>/dev/null | openssl x509 -noout -subject -issuer -dates
# Expected: subject CN = alinenasseh.com, valid dates
```

## README update (Cam — can be done at any time)

In `/Users/biancabienaime/repos/alinenasseh/README.md`, add a section:
```markdown
## Domains & environments

| Domain              | Purpose           | Host              | Notes                          |
|---------------------|-------------------|-------------------|--------------------------------|
| alinenasseh.com     | Production        | 187.77.26.99      | Apex A-record pointed here     |
| artisan.ashbi.ca    | Staging / preview | 187.77.26.99      | Same host, different vhost     |
| alinenasseh.ca      | (legacy)          | WP Engine         | DO NOT use — redirect pending  |
```

## Acceptance criteria

- [ ] `dig alinenasseh.com A` returns 187.77.26.99 (after propagation)
- [ ] Old WP Engine IPs (141.193.213.10, 141.193.213.11) no longer appear
- [ ] https://alinenasseh.com loads over HTTPS with a valid cert
- [ ] README contains the staging-vs-prod mapping
- [ ] DNS change confirmed from at least two external resolvers

## Out of scope

- Migrating WordPress content / DB / theme data from WP Engine
- Setting up or renewing TLS certificates (assumed handled by the 187.77.26.99 host)
- Email / MX / CNAMEs / other DNS records beyond the apex A-record
- Code changes to the site itself

## Rollback (if something breaks)

Re-add the A records:
- `@` → `141.193.213.10` (TTL 300)
- `@` → `141.193.213.11` (TTL 300)

Wait 60s for propagation. Site should be back at WP Engine.

## Estimated time

5 min for the DNS change, 5–30 min for full global propagation.