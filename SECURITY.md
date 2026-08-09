# Security Policy

The Zorva (ai-billing-audit) team takes the security of the
operator dashboard, the public v1 API, and the in-flight claim data
we process seriously. This document explains how to report a
vulnerability, what versions are eligible for fixes, and what our
response-time commitments are.

---

## Supported versions

The project is in pre-1.0 (`0.x.y`). The API package, runtime health/metrics
identity, and API image tag currently use `0.4.0`. A deployed image still
requires commit and environment verification; a repository version is not
proof of the live release.

| Release line | Status            | Notes                                  |
|--------------|-------------------|----------------------------------------|
| `0.4.x` | **Repository-supported** | Current API release line; verify deployed commit before support decisions. |

Keep the supported-version policy aligned with the release tags and deployment
runbook. See `docs/OPERATIONS_RUNBOOK.md` and issue #15.

---

## Reporting a vulnerability

**Email:** **security@zorva.ca**

Please do **not** open a public GitHub issue for security reports.
A public issue is a signal to attackers, and the disclosure
clock starts the moment the issue is visible to the public.

### What to include

A useful report includes:

1. A short description of the vulnerability and the impact
   (RCE, SSRF, auth bypass, PII disclosure, etc.).
2. The exact version of `ai-billing-audit` affected
   (the `/healthz` endpoint returns the running version
   string, and `git rev-parse HEAD` of the deployed
   image is also fine).
3. A reproducible proof-of-concept: a `curl` line, a script,
   or a screenshot if the issue is UI-only.
4. Whether the report is **public** (already disclosed
   somewhere) or **private** (first time we are seeing it).
5. Your name / handle and an email address we can use for
   follow-up, if you'd like a credit in the fix release.

### What you can expect from us

We acknowledge all reports within **2 business days**. The
table below is the worst-case timeline; in practice most reports
move faster.

| Severity (CVSS v3.1) | Initial triage | Patch target | Public disclosure |
|----------------------|----------------|--------------|-------------------|
| Critical (9.0–10.0)  | ≤ 24 hours     | ≤ 7 days     | After fix lands   |
| High (7.0–8.9)       | ≤ 2 business days | ≤ 30 days  | After fix lands   |
| Medium (4.0–6.9)     | ≤ 5 business days | ≤ 60 days  | After fix lands   |
| Low (0.1–3.9)        | ≤ 10 business days | Next minor release | Bundled in the next release notes |

**Coordinated disclosure.** We ask that you give us a
reasonable window — typically the "patch target" above —
before publishing details. We are happy to agree to a longer
embargo if you need time to coordinate with downstream
operators.

---

## Bug-bounty scope

**There is no paid bug-bounty program at this time.** We
do not currently offer monetary rewards for vulnerability
reports. The supported versions, the reporting email, and
the response-time SLA above are the entire program.

If a future program is launched, it will be announced on
the project README and on the marketing site (`zorva.ca`),
not retroactively applied to prior reports. Out-of-band
"scalps" sold to third-party brokers are out of scope.

### In scope

Anything in the checked-in ai-billing-audit stack, or on an operator-confirmed
deployment of that stack:

- The FastAPI app (`api` service in `docker-compose.yml`).
- The operator portal (`apps/portal`).
- The in-stack Caddy reverse proxy and its `Caddyfile`.
- The Postgres cluster and the `audit_trail.sql` schema.
- The public v1 API surface (`/v1/audits`, `/v1/webhooks`).
- The webhooks dispatcher and the `webhooks.jsonl` /
  `usage_log.jsonl` storage paths.
- The `deploy-to-vps.sh` provisioning flow, as long as the
  reporter has explicit authorization to run the script
  against the target VPS.

### Out of scope

- Vulnerabilities in upstream dependencies that are already
  publicly disclosed and have a fix available — please
  report those upstream first.
- Social-engineering attacks against Zorva staff or
  customers.
- Denial-of-service attacks that require sustained,
  high-volume traffic; we run a single VPS and the
  deployment has a Cloudflare-style edge in front of it,
  not a multi-region fleet.
- Issues that only manifest on a developer's local
  workstation (e.g. a misconfigured `~/.ssh/known_hosts`).
- Theoretical findings without a reproducible
  proof-of-concept. "Theoretically this could be
  exploitable" is **not** sufficient — show the
  `curl` line.
- Clickjacking, missing-security-headers, and similar
  findings on the **marketing** site (`zorva.ca`).
  The marketing site is static and has no user data
  to protect; rate-limiting and TLS are the only
  guarantees that site makes.
- "I don't like the way this is architected" or
  "this could be better" reports. Those are feature
  requests, not security issues; please file them
  as GitHub issues, not as security reports.

---

## Security best practices for operators

If you self-host Zorva (the project is open source and the
`docker-compose.yml` is the deployment manifest), please:

> The backup instructions in this historical policy are superseded by
> `deploy/scripts/audit-backup.sh`, `deploy/scripts/audit-restore-verify.sh`,
> and `deploy/README.md`. Use the current scripts and retain restore evidence;
> do not infer live retention or compliance status from this document.

1. **Set `ZORVA_API_KEY` to a random ≥ 32-byte secret**
   before exposing `/v1/*` to the public internet.
   The endpoint returns `503 api_key_not_configured` if
   the env var is unset, so the default deploy is
   feature-flagged off — but once you set the key, every
   `/v1/*` call needs a valid `Authorization: Bearer`
   header.
2. **Bind Caddy to loopback only** (`127.0.0.1:3018:80`)
   and put a public TLS edge in front of it. The
   `docker-compose.yml` shipped in the repo already
   does this; if you change the bind, you take on the
   TLS-termination responsibility.
3. **Supply unique FastAPI and portal PostgreSQL passwords.** Compose and the
   deploy scripts fail closed when either password is absent; there is no
   supported production default. Rotate provider credentials independently.
4. **Use the stock `caddy:2-alpine` image declared by Compose.** The public TLS
   edge owns external rate limiting; the in-stack Caddy service is loopback
   only and must not be exposed directly.
5. **Inventory and protect every authoritative store.** The checked-in backup
   scripts currently cover the FastAPI PostgreSQL database; portal PostgreSQL
   and required named volumes remain a production backup/restore gate tracked
   in issue #12.

---

## Acknowledgements

We thank the security researchers and Zorva customers who
have reported vulnerabilities to date. With their
permission, credits are listed in the next release's
`CHANGELOG.md` under the "Security" subsection. Anonymous
reports are honoured with the same response-time SLA;
they just don't get a public credit.

---

## Contact

- **Security reports:** security@zorva.ca
- **General questions / support:** the GitHub issue tracker
  is the right place; the security mailbox is for reports
  only and is not staffed for general support.
- **PGP key:** the security mailbox signs replies with
  a long-term key whose fingerprint will be published on
  `zorva.ca/security` once the program has a published
  public key. Until then, the TLS certificate on
  `ai-billing-audit.ashbi.ca` is the strongest chain we offer.

---

_Last updated: 2026-08-06 - API release metadata aligned to 0.4.0._
