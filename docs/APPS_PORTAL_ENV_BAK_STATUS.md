# apps/portal/.env.bak — image hygiene status

**Verdict:** Not tracked in git, not baked into the live container image.
No action required.

## How we checked

```bash
# 1. Confirm the file is not in git history.
git ls-files apps/portal/.env.bak             # (no output)
git log --all --full-history -- 'apps/portal/.env.bak'   # (no output)

# 2. Confirm .gitignore at apps/portal/.gitignore covers it.
grep -E '^\.env|^\*\.bak' apps/portal/.gitignore
# .env*
# *.bak

# 3. Confirm the live container image cannot bake it in.
grep -E '^apps/' .dockerignore
# apps/
```

## Why this is fine

* **Working-tree presence:** `apps/portal/.env.bak` is in the working
  tree on this host (alongside `.env`, `.env.local`, `.env.example`)
  but is untracked.
* **`apps/portal/.gitignore`** ignores `.env*` and `*.bak`, so a
  fresh clone will never contain the file at all and the deploy
  script (`deploy-to-vps.sh`) will never copy it.
* **Root `.dockerignore`** excludes the entire `apps/` tree from the
  FastAPI image build, so even if the file existed in the working
  tree when the image was built, it would not be in
  `ai-billing-audit-api`.
* **No history scrub needed:** Because the file was never committed,
  there is nothing to `git rm` and no BFG / filter-branch pass is
  warranted.

## Operational note

The marketing portal (`apps/portal/`) is currently local-dev only
(see `README.md` "Deploying" and `docs/DEPLOYMENT.md`). When/if it
gets a real deploy target (separate VPS or static host), re-confirm
that the destination's `.gitignore` / build ignore patterns cover
`.env*` and `*.bak`. As of 2026-06-24 they do.

## What this task did NOT do

* Did **not** modify `apps/portal/.gitignore` (already correct).
* Did **not** modify root `.dockerignore` (already excludes `apps/`).
* Did **not** delete `apps/portal/.env.bak` from the working tree
  (it's local host state, untracked; deleting it from this machine
  is a separate concern, not part of `t_952cd444`).
