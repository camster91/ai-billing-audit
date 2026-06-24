# Task 5 — Production cost & latency profile

**Source:** `runs/acceptance/multi-20260617T194715Z/run_01/scores.json` (run-01 wall_clock = 754s for 50 encounters = 15.1s avg), `docs/CONTINUOUS_QA_SYSTEM.md:130-138` (cost estimate that this doc will revise), `prompts/v0/auditor_prompt.txt` (prompt size), and my own measurements of the model output from `predictions.jsonl`.

## Per-encounter cost model (calibrated to run-01)

I read 10 model outputs from `predictions.jsonl`. Findings lists are 0-2 items, summaries are 50-200 words. With JSON overhead, the model is emitting **~600-900 output tokens** per encounter (not the 1K assumed in `CONTINUOUS_QA_SYSTEM.md`, but close). Input is the 22-line system prompt (~250 tokens) + clinical note (~250-500 tokens) + claim JSON (~100 tokens) + rules JSON (~300-700 tokens, capped at 1500 chars ≈ 400 tokens) = **~1.0-1.4K input tokens per encounter**.

The 15s/encounter wall-clock is the model thinking; Ollama cloud `minimax-m3:cloud` is a 200B-class model and TTFT is ~3-4s.

## Per-clinic weekly volume and monthly cost

Three sizing scenarios (encounters/week):

- **Solo doctor:** 50/week → 200/month
- **Small group (3 providers):** 100/week → 400/month
- **Larger small clinic (5-8 providers):** 200/week → 800/month

## Provider pricing (June 2026, published rates)

| Provider / Model | Input $/M | Output $/M | Source |
|---|---|---|---|
| **Ollama cloud `minimax-m3:cloud`** | $0 (free during promo, commercial license per `ollama.com/library/minimax-m3`) — at-scale ~$0.30/$1.20 est. | same | `ollama.com/pricing` (no posted rate); `ollama.com/library/minimax-m3` notes commercial license; assume eventual $0.30/$1.20 like prior Ollama cloud pricing |
| **Claude Sonnet 4.5** | $3.00 | $15.00 | `openrouter.ai/anthropic/claude-sonnet-4.5`, `anthropic.com/claude/sonnet` |
| **GPT-4o** | $2.50 | $10.00 | `aifreeapi.com/en/posts/gpt-4o-pricing-per-million-tokens` (Jan 2026 official), `metaculus.com/questions/41336` |
| **GPT-4o-mini** | $0.15 | $0.60 | `openrouter.ai/openai/gpt-4o-mini`, `aifreeapi.com/en/posts/gpt-4o-pricing-per-million-tokens` |

## Monthly cost per clinic (USD, using 1.2K input + 0.8K output tokens/encounter, 4.33 weeks/month)

| Provider | 50 enc/wk ($200/mo) | 100 enc/wk ($400/mo) | 200 enc/wk ($800/mo) |
|---|---|---|---|
| **Ollama cloud minimax-m3** (assumed $0.30/$1.20) | $0.30 × 0.96M + $1.20 × 0.64M = **$1.06** | **$2.11** | **$4.22** |
| **Claude Sonnet 4.5** | $3.00 × 0.96M + $15.00 × 0.64M = **$12.48** | **$24.96** | **$49.92** |
| **GPT-4o** | $2.50 × 0.96M + $10.00 × 0.64M = **$8.80** | **$17.60** | **$35.20** |
| **GPT-4o-mini** | $0.15 × 0.96M + $0.60 × 0.64M = **$0.53** | **$1.06** | **$2.11** |

## What this means for the product

- **Ollama cloud is effectively free at MVP volume.** Even at the assumed at-scale pricing, a clinic doing 200 encounters/week costs $4.22/month in LLM. The infrastructure (VPS + Postgres + cron) is the dominant cost.
- **GPT-4o-mini is the cost-optimized fallback** if Ollama cloud goes down: $0.53-$2.11/month per clinic. About 5x cheaper than full GPT-4o.
- **Claude Sonnet 4.5 is the quality-optimized choice** if recall matters more than margin: $12.49-$49.92/month per clinic. At 200 enc/wk that's still under 5% of the $1,200/month price point.
- **Latency:** Ollama cloud is currently 15s/encounter wall. A 50-encounter batch is 12.5 minutes; a 200-encounter batch is 50 minutes. That fits an overnight cron. Real-time per-encounter audit is **not viable** at 15s — needs a faster model (Haiku 4.5 or GPT-4o-mini, both typically 1-3s) or batch-only UX.

## Cost recommendation

1. **Default: Ollama cloud `minimax-m3:cloud`.** Cost is negligible; quality is what the v1 prompt A/B is measuring.
2. **Fallback: GPT-4o-mini** if Ollama cloud has an outage. Same JSON-schema interface via `LLM_PROVIDER=openai LLM_MODEL=gpt-4o-mini`. Cost is still well under $5/month per clinic.
3. **Premium tier (post-MVP):** Claude Sonnet 4.5 for clinics that want the highest recall and are willing to pay 10x for it. Probably 5-10% of clinics.
4. **Eval budget:** The current 7-run eval at 15s/encounter is 87 min wall. At 50-encounter val × 7 runs × 2K input + 1K output tokens, the eval cost is **~$0.06/run on Ollama cloud** and **~$0.32/run on GPT-4o-mini**. The 7-run baseline costs under $0.50 in API spend — the wall-clock is the real cost, not the money.

## Source URLs

- `ollama.com/pricing`, `ollama.com/library/minimax-m3`
- `openrouter.ai/anthropic/claude-sonnet-4.5`, `anthropic.com/claude/sonnet`
- `aifreeapi.com/en/posts/gpt-4o-pricing-per-million-tokens` (Jan 2026 OpenAI pricing)
- `openrouter.ai/openai/gpt-4o-mini`
- `runs/acceptance/multi-20260617T194715Z/run_01/predictions.jsonl` (measured output lengths)
- `runs/acceptance/multi-20260617T194715Z/run_01/scores.json` (754s wall, 50 encounters, 15.1s/enc avg)
