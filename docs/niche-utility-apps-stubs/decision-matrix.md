# Niche Utility Apps — Decision Matrix (stub)

**Date:** 2026-06-25
**Author:** Hermes subagent (batch drain)
**Purpose:** One-line decision + blocker per open task so Cam can clear them in
a single sitting. All 8 tasks reduce to either (a) Cam product/business
decisions or (b) work that requires console credentials Cam controls.

## 8 blocked tasks

| Task ID | Title | Decision needed | Blocker type |
|---|---|---|---|
| t_7f2bd26d | Confirm Hermes marketing channels & account permissions | Pick yes/no/needs-creds per channel (Reddit, Product Hunt, niche forums, cold email, Buffer/Hootsuite) | business decision |
| t_a3929197 | Confirm any existing revenue from jw-video and data-broker-removal | Pull App Store Connect + Play Console + Stripe reports | needs API access |
| t_a76cdcd5 | Verify Apple/Google developer account setup for Luna + budget apps | Log into both consoles and confirm signing identity + paid status | needs Cam login |
| t_86db93bd | Decide and spec JW RAG web UI vs. documented CLI | Choose web UI build (Cam confirms if roadmap worth it) | product decision |
| t_735b89f1 | Budget App: iOS submission + family-of-4 mode (no Plaid) | Build family-of-4 feature first (or defer) then submit | M work |
| t_6ca3fde4 | LifeStreak: iOS App Store submission, assets, ASO | Generate screenshots, write ASO copy, then submit | M work |
| t_09543648 | Luna Contractions: submit v56 to iOS App Store + Google Play | Upload existing build, fill metadata | L work |
| t_9ebed017 | Migrate jw-video | Run export/import cycle, verify both stores | M work |

## Channels triage (t_7f2bd26d detail)

Per task body, the 5 channels:

| Channel | Recommended | Why |
|---|---|---|
| Reddit posting | **approved** (low-risk niche subs) | High-trust audience for niche apps, no auth risk |
| Product Hunt | **agent drafts, Cam submits** | Per task body, agreed human/agent split |
| Niche forum posting | **needs-creds** | Need account access for specific forums |
| Cold email sending | **needs-creds** | Need sending account + warmed domain |
| Buffer/Hootsuite | **declined** | Manual social scheduling fine for current volume |

## Recommended next session (60-min block)

1. Cam logs into Apple/Google consoles (t_a76cdcd5) — 15min
2. Cam reviews channel decisions above (t_7f2bd26d) — 10min
3. Pull App Store Connect + Stripe revenue (t_a3929197) — 15min
4. JW RAG product decision (t_86db93bd) — 20min

Then submit queue order: Luna v56 (t_09543648) → LifeStreak (t_6ca3fde4) →
Budget family-of-4 (t_735b89f1) → jw-video migrate (t_9ebed017).

## Parent stays blocked

All 8 tasks remain `blocked` — none are silently done. The matrix above
gives Cam everything needed to unblock them in one focused session.