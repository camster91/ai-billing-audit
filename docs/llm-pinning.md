# LLM model pinning

> Why: the unversioned `MiniMax-M3` alias (and the older
> `ollama/minimax-m3:cloud` tag used in research scripts) is a moving
> target. The provider can roll the underlying model forward without
> notice, which would silently change audit behavior and cost.
> This file documents the pin and how to refresh it.

## Current pin

| What         | Value                        |
|--------------|------------------------------|
| Pinned on    | 2026-06-23                   |
| Pinned model | `MiniMax-M3-2026-06-23`      |
| Set in       | `deploy-to-vps.sh` → `.env`  |
| Referenced by| `docker-compose.yml` (comment block) |

The date suffix is a *literal snapshot name*; if the provider rolls
forward and the dated alias is removed, the next deployment fails
loudly with a 404 from the provider. That is the goal.

## Why not a content digest (`@sha256:…`)?

Ollama's container registry and the Ollama cloud API both describe
a model as `<namespace>/<name>:<tag>`. Digest-style pinning
(`name@sha256:…`) is supported by the OCI distribution spec that
the local Ollama registry implements, but the cloud backend exposes
only the alias. At pin time (2026-06-23) the registry docs / cloud
API were not reachable from the operator environment, so we could
not capture a digest.

When the registry is reachable again, the upgrade path is:

1. `ollama show minimax/MiniMax-M3` (or the equivalent cloud API
   call) → capture the digest from the manifest.
2. Replace `MiniMax-M3-2026-06-23` with
   `MiniMax-M3@sha256:<hex>` in `deploy-to-vps.sh`.
3. Drop the date suffix in the comment block.

Until that is done, the date suffix is the strongest pin we can
guarantee.

## Re-pinning procedure

Bump the pin **quarterly** (suggested cadence: first Monday of
Jan / Apr / Jul / Oct), or immediately when the provider announces
a model change.

1. Confirm the current pin still resolves:
   ```bash
   curl -fsS -H "Authorization: Bearer $MINIMAX_API_KEY" \
        "$MINIMAX_BASE_URL/models/MiniMax-M3-2026-06-23" \
        | jq '.id'
   ```
   Expect the model id back. A 404 means the dated alias has
   been retired — re-pin immediately.
2. Resolve the new model id against the provider's catalog.
3. Update the pin in `deploy-to-vps.sh`:
   ```diff
   -LLM_MODEL=MiniMax-M3-2026-06-23
   +LLM_MODEL=MiniMax-M3-2026-09-29
   ```
4. Update the date in the comment block (the "Pinned on" line and
   the "Pin policy (YYYY-MM-DD)" header) and in the table at the
   top of this file.
5. Re-run the smoke test in `scripts/smartness_test.py` and the
   full v0 baseline in `tests/test_v0_baseline.py` to confirm
   nothing regressed before deploying.
6. Commit with message:
   ```
   chore(llm): re-pin LLM_MODEL to <new-pinned-value>
   ```
7. Deploy with `deploy-to-vps.sh`. The next container boot picks
   up the new value via the regenerated `.env` file.

## Out of scope

- Switching model families (e.g. `MiniMax-M3` → a successor).
  That's a separate decision and gets its own card.
- Auto-bumping the pin on a schedule. The cadence above is
  operator-driven on purpose; auto-bumping a model the auditor
  depends on is exactly the silent-roll-forward we are guarding
  against.
