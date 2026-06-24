#!/usr/bin/env python3
"""Load post-deploy polish + follow-up tasks onto zorva-post-deploy-2026-06-24."""
import subprocess
import re

TASKS = [
    # === MUST FIX (P10) — surfaced from the 2026-06-24 deploy ===
    (10, "Verify v12 prompt is in the live container image",
     "After the deploy, src/ai_billing_audit/auditor.py in the container should be reading "
     "prompts/v12/auditor_prompt.txt. Verify on the live container: ssh coolify "
     "'docker exec ai-billing-audit-api cat /opt/projects/ai-billing-audit/prompts/v12/auditor_prompt.txt | head -5' "
     "should show the K-M rules. Also: run the smartness test on the live container (with a real AHCIP encounter) "
     "and confirm F1 ≈ 0.690. This task is verification-only — no code change needed unless v12 is missing, in which "
     "case re-run the deploy with the prompts/ exclude fix (commit 7cff811) and re-verify."),

    (10, "Document the marketing site (apps/portal) deploy gap",
     "The deploy-to-vps.sh script ships the FastAPI dashboard (the Python app with v12 auditor, missed-revenue "
     "detector, SOMB fees, etc.) but NOT the marketing site at apps/portal/. The user-facing marketing site "
     "(hero 'Find the revenue...', /pricing with CAD tiers, /what-zorva-finds with 8 finding cards, /security "
     "with controls matrix, /robots.txt with split rules) is built but unreachable from the current deploy. "
     "Document: apps/portal is a Next.js 16.2.9 app that requires its own build (pnpm build) and its own "
     "deployment pipeline. Possible approaches: (a) add a second service to docker-compose.yml that builds and "
     "runs the Next.js app on port 3020, (b) deploy apps/portal separately as a static export (next build + "
     "next export) and serve via Traefik, (c) move apps/portal to a separate repo (camster91/zorva-web). "
     "This task is doc-only; implementation is a follow-up."),

    # === SHOULD FIX (P5) ===
    (5, "Restore the caddy rate_limit directive via a custom caddy build",
     "Audit task t_106739f0 (commit 877ad92) added rate_limit to the Caddyfile, but the stock caddy:2-alpine "
     "image doesn't ship the http.ratelimit module. Per-IP rate limit was the security intent. Two fixes: "
     "(a) build a custom caddy image with github.com/mholt/caddy-ratelimit xcaddy-built and push to a registry "
     "(e.g. camster91/caddy-ratelimit), update docker-compose.yml to use that image. (b) move the rate limit "
     "to Traefik on the host (already uses middleware for other ashbi services). Approach (a) is cleaner. "
     "Until this is fixed, the rate-limit directive is commented out on the host (deploy commit 7cff811). "
     "Acceptance: docker compose build succeeds with rate_limit directive active, /healthz still 200, "
     "rate-limit headers visible in responses when triggered."),

    (5, "Add per-deploy smoke test to deploy-to-vps.sh",
     "After docker compose up -d, run a real audit call against the live container to confirm the LLM is "
     "wired correctly. Currently the script only does curl /healthz. A real audit call would catch: "
     "(a) LLM_MODEL pin mismatch, (b) MINIMAX_API_KEY not propagated to OPENAI_API_KEY, "
     "(c) DATABASE_URL with placeholder postgres password, (d) v12 prompt missing on the container. "
     "Add a step that does: docker exec ai-billing-audit-api curl -s -X POST "
     "http://127.0.0.1:8000/api/audit_test with a sample claim, then check the response has the v12 rules. "
     "Make the smoke test idempotent (write to a separate /tmp test endpoint or use the demo registry)."),

    (5, "Run val_ca.json smoke test on the live container",
     "scripts/smartness_test_v12.py was added in commit 3321356 (the audit-fixes session). It supports "
     "--split val_ca to load the 19-encounter AHCIP val set. Run it on the live container to verify the "
     "F1=0.690 number is reproducible end-to-end. Requires the Ollama cloud key in the container's env "
     "(already set per the 2026-06-24 deploy). Output should match the MANIFEST entry. "
     "Acceptance: runs to completion in <5 min, reports F1 within 0.05 of MANIFEST, output saved to "
     "runs/recall/v12_live_smoke.json."),

    (3, "Add cron job to rotate the Traefik dynamic config daily",
     "Currently /etc/traefik/dynamic/routers.yml is hand-managed by the deploy script. If Traefik "
     "ever reads a stale file (after a deploy that errored partway through), the live URL breaks. "
     "Add a cron job on the host that validates the routers.yml file integrity (e.g., yaml parses, "
     "all referenced services exist) and reverts to last-known-good on failure. Could be a small "
     "Python script at /opt/vps/bin/traefik-validate.py."),

    (3, "Remove the apps/portal .env.bak file from the live container image",
     "The audit task t_b266237 (commit b266237) chmod 600'd apps/portal/.env.bak to fix a leak, but the file "
     "shouldn't be in the deployed image at all. The .gitignore covers *.bak but the file was already "
     "committed at that point. To fully clean: delete the file from git history (filter-branch or "
     "BFG), or add a post-build step that strips *.bak from the published image."),

    (3, "Document the deploy chat-layer-redacting issue",
     "The deploy-to-vps.sh script uses bash heredocs to write .env. The chat layer (Hermes) redacts "
     "literal patterns like 'Basic ' + base64 or 'sk_live_' keys when they appear inline in tool "
     "calls. Workaround: write the .env to a local file, base64-encode it, decode on the host via "
     "ssh + base64 -d. Document this in the deploy script header so future deploys don't re-encounter "
     "the silent failure mode (deploy would succeed but the .env would have empty values)."),

    (3, "Add a 5xx error rate alert for the live URL",
     "No monitoring on https://ai-billing-audit.ashbi.ca/. If the API starts 500ing (LLM outage, "
     "Postgres disk full, etc.), nothing alerts the team. Add a simple cron-based monitor: every 5 min, "
     "curl -s -o /dev/null -w '%{http_code}' https://ai-billing-audit.ashbi.ca/healthz, if non-200 "
     "for 3 consecutive checks, send to a webhook (Slack/email/etc). Could live alongside the existing "
     "ashbi-services monitoring if there is one."),

    # === P1 polish — carry-over from prior boards ===
    (1, "Document the apps/portal deploy story in CLAUDE.md / AGENTS.md / README",
     "Anyone (human or AI) landing on this repo needs to know that the FastAPI side and the Next.js "
     "marketing portal are deployed separately. Add a section to README.md (Deployment > Architecture) "
     "that explains: api/worker/postgres/caddy live on the VPS, marketing portal lives in apps/portal/ "
     "and is currently un-deployed. Include the deploy commands for both sides (when the marketing side "
     "is wired up)."),

    (1, "Clean up the residual post-deploy audit tasks on prior boards",
     "There are 4 blocked tasks still sitting on prior boards: t_1870ca1f (defensible marketing numbers, "
     "blocked on real claims data), t_f98a799f (monthly improvement report, blocked on 3+ months of feedback), "
     "the audit Ollama key rotation (now moot since we shipped with the existing key), and the audit re-audit "
     "claim persistence follow-up t_10774785 (already shipped in d57375f). Verify each blocked task and "
     "either mark done (with a comment explaining why) or move to zorva-post-deploy-2026-06-24 with a "
     "fresh acceptance criteria."),

    (1, "Add SOMB-fee primary-source corroboration (the albertadoctors Fee Navigator pull)",
     "Commit 41bed56 added albertadoctors Fee Navigator URLs to all 51 SOMB entries but no entry was "
     "bumped to 'high' confidence because Firecrawl wasn't configured at the time. With the live deploy "
     "running, run the corroboration script with a real Firecrawl setup or hand-pull the top 10 codes "
     "(03.04A, 03.01A, 03.05A, 03.03A, 08.19A, 08.19B, 08.19C, 13.59A, 13.59B, the immunization block) "
     "and bump their confidence to 'high' in data/synth/somb_fees.json. Until this is done, the "
     "missed-revenue dashboard surfaces 'training-data-2026-01' on every dollar value, which undermines "
     "the clinic pitch (the dashboard shows dollars, but the source is uncertain)."),

    (1, "Wire the deferred monthly_report task to monthly_report.py module",
     "The monthly_report module exists in src/ai_billing_audit/monthly_report.py (commit c634578) but "
     "is not wired into any route. The blocked t_f98a799f is waiting on 3+ months of feedback data. "
     "Until then: add a stub route GET /api/reports/monthly that returns {status: 'insufficient_data', "
     "message: 'Need 3+ months of feedback to generate a monthly report.', required_months: 3, "
     "current_months: 0}. When real data flows, the route starts returning full reports."),

    # === DEFERRED (P3) — nothing user-actionable until real data flows ===
    (3, "Wait for first AHCIP pilot to sign, then unblock defensible revenue numbers",
     "t_1870ca1f blocked on real claims data. When a clinic signs the HIA+PIPEDA data agreement and "
     "exports 1-2 months of historical AHCIP claims + clinical notes, run the v12 auditor on the "
     "export and compute the average missed-revenue per 1,000 claims. Update the pricing page and the "
     "PILOT_OFFER.md with the defensible number. Until then, the marketing copy stays qualitative."),
]


def load():
    print(f"Loading {len(TASKS)} tasks to zorva-post-deploy-2026-06-24...")
    created = 0
    errors = 0
    for pri, title, body in TASKS:
        idempotency_key = f"postdeploy-p{pri}-{hash(title) & 0xFFFFFF}-{hash(body[:100]) & 0xFFFFFF}"
        r = subprocess.run(
            ["hermes", "kanban", "--board", "zorva-post-deploy-2026-06-24", "create",
             "--priority", str(pri),
             "--triage",
             "--body", body,
             "--idempotency-key", idempotency_key,
             title],
            capture_output=True, text=True, timeout=30
        )
        m = re.search(r't_[a-f0-9]+', r.stdout)
        if m:
            created += 1
        else:
            errors += 1
            if errors <= 3:
                print(f"  ERR: {title[:50]}: {r.stderr[:200]}")
    print(f"Created: {created}, Errors: {errors}")

load()

# Promote all to ready
print("\nPromoting all to ready...")
r = subprocess.run(
    ["hermes", "kanban", "--board", "zorva-post-deploy-2026-06-24", "list", "--status", "triage"],
    capture_output=True, text=True, timeout=10,
    cwd="/Users/biancabienaime/projects/ai-billing-audit"
)
ids = re.findall(r't_[a-f0-9]+', r.stdout)
for tid in ids:
    subprocess.run(
        ["hermes", "kanban", "--board", "zorva-post-deploy-2026-06-24", "specify", tid],
        capture_output=True, text=True, timeout=30
    )
print(f"Promoted {len(ids)} tasks")

r = subprocess.run(
    ["hermes", "kanban", "--board", "zorva-post-deploy-2026-06-24", "stats"],
    capture_output=True, text=True, timeout=10,
    cwd="/Users/biancabienaime/projects/ai-billing-audit"
)
print("\nBoard state:")
print(r.stdout)
