# Kanban Drain Session 3 — 2026-06-25

**Boards drained:** alinenasseh, family-planner, influencers-link,
joesheating, tkd-ux-qa, tkd-polish, splashtown, ffh-hotels,
taekwondo-tournament.

**Strategy:** Every blocked/ready task in this batch needs live access
(SSH to VPS / WP admin / Stripe dashboard / Asana / browser DevTools)
that is unreachable from a bare CLI session. Instead of leaving them
stuck, this drain ships **S-effort sub-deliverables** that make each
task immediately claimable:

- Per-task runbook (1–2 page spec) with exact steps, URLs, credentials
  pointers, acceptance criteria
- Where useful, a small probe script that pre-flights the work
  (DNS check, file scan, grep audit, curl smoke)

**Counts:** see `SUMMARY.md` in this folder.

**Sub-deliverables shipped (one file per blocked parent where the
work decomposes cleanly):**

| Board | File | What it does |
|---|---|---|
| joesheating | `joesheating-runbook.md` | Step-by-step for the 11 ready tasks (nav reorder, image uploads, GA4 setup, JS debug) |
| joesheating | `joesheating-probe.sh` | Pre-flight: WP REST reachable, admin endpoint health, image attachment audit |
| alinenasseh | `alinenasseh-dns-flip.md` | DNS A-record change runbook with dig verification steps |
| alinenasseh | `alinenasseh-secrets-rotation.md` | `.env` rotation runbook for the PHP service |
| alinenasseh | `alinenasseh-dns-probe.sh` | dig-based propagation check + README staging-vs-prod table template |
| ffh-hotels | `ffh-hotels-ssh-commands.md` | All 7 SSH tasks: robots.txt verify, H1 architecture scan, broken links fix, Markup triage, Rank Math reset, !important refactor, continents visual review |
| influencers-link | `influencers-link-tracking-secret.md` | TRACKING_SECRET generation + per-store bulk update script (`bulk-set-tracking-secret.sh`) |
| influencers-link | `influencers-link-dns-followup.md` | 2 subdomains (influencer-link.ashbi.ca, link.ashbi.ca) DNS flip to 88.223.82.6 |
| influencers-link | `influencers-link-nourish-dispute.md` | Nourish Wellness dispute evidence submission runbook |
| family-planner | `family-planner-security-pass3.sh` | Curl-based security tester (kid/teen escalation, CSRF, SQLi, XSS, JWT, rate-limit, ID enum, invite brute, route audit, password reset) |
| tkd-ux-qa | `tkd-settings-tabs-spec.md` | 9-section → 3-tab collapse spec for TournamentSettings.tsx |
| tkd-polish | `tkd-a11y-violations-breakdown.md` | 21 WCAG 2.1 AA violations grouped by category + fix patterns from prior 41b13a7 |
| splashtown | `splashtown-workflow-fix-spec.md` | .github/workflows/build-and-push.yml 0s failure — what to inspect + common fixes |
| taekwondo-tournament | `taekwondo-tournament-pg-migration.md` | lull-relay Postgres migration plan (durability + scale) |

Each file is small enough to read in 60 seconds. A future agent with
the right access (WP admin, SSH, Stripe dashboard) can claim the parent
task, read the runbook, and execute against verified acceptance criteria.