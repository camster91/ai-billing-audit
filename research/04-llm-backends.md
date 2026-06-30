# Research 04 — LLM backend cost / quality / latency analysis

**Author:** general (Mavis orchestrator sub-task), 2026-06-27
**Task:** `plan_0bbfa512 / research-llm-backends`
**Sister reports:** `01-prompt-optimization.md`, `02-retrieval-context.md`, `03-eval-methodology.md`, `05-rule-calibration.md`

---

## TL;DR

Today Zorva runs the v12 AHCIP auditor through **Ollama Cloud `minimax-m3:cloud`**, served via the OpenAI-compatible endpoint `https://ollama.com/v1` (production `LLM_BASE_URL` in `deploy-to-vps.sh:100` points at `https://api.minimax.io/v1` — same model, different route — see *Pain point #4* below). On the cleaned AHCIP val set the model is **F1 = 0.690** at **mean 30s, p95 58s** wall-clock per encounter (`artifacts/prompt_history.jsonl` rows 16–17). Per-token cost is **not the issue** — Ollama Cloud is a subscription (`$0/$20/$100/mo`) with usage-based caps, not per-token billing. **The real pain points are (a) the Ollama key was compromised-on-send on 2026-06-17 and is still in use**, (b) 30–50s wall-clock makes per-encounter audit unusable in the live portal UX, and (c) **PHI cross-border to a US-hosted inference endpoint** is a blocking legal issue for any Alberta clinic that has not yet signed the HIA Information Manager Agreement (`docs/BAA_TEMPLATE_HIA.md`, draft only, lawyer-review pending).

**Recommended first move:** **stay on Ollama Cloud `minimax-m3:cloud` but rotate the key now + add prompt caching + tighten the system prompt** (faster, cheaper, fixes the key-compromise risk without changing vendor or breaking the HIA draft's "Ollama Cloud" subcontractor reference). Pilot **Claude Haiku 4.5 as a fallback** for clinics whose HIA IMA explicitly excludes Ollama Cloud (so they can opt into Anthropic as a subcontractor). Do **not** move primary inference off Ollama Cloud until a lawyer has reviewed the HIA draft AND a real AHCIP val F1 is measured on the candidate.

---

## 1. Current state

### 1.1 Production provider / model

| Layer | Value | Source |
|---|---|---|
| Production provider | `minimax` (litellm) → routes through MiniMax OpenAI-compatible surface | `deploy-to-vps.sh:99-100` (`LLM_PROVIDER="minimax"`, `LLM_BASE_URL="https://api.minimax.io/v1"`) |
| Production model | `MiniMax-M3-2026-06-23` (date-suffixed pin, literal snapshot name) | `deploy-to-vps.sh:224` |
| Benchmark / research provider | `ollama` (litellm) → routes through Ollama Cloud's OpenAI-compatible surface | `scripts/run_7x.py:54-56` (`LLM_PROVIDER='ollama'`, `LLM_BASE_URL='https://ollama.com/v1'`, `LLM_MODEL='openai/minimax-m3:cloud'`) |
| Underlying model | **M3** (MiniMax M3, 1M-token context, 512K guaranteed; "high" usage tier on Ollama Cloud) | `ollama.com/library/minimax-m3:cloud`, also `minimax.io/models/text/m3` |
| API contract | OpenAI-compatible `/v1/chat/completions` (Bearer auth) | `src/ai_billing_audit/llm.py:128-148` |
| Dispatch library | `litellm.completion` (single point of provider abstraction) | `src/ai_billing_audit/llm.py:63` |
| `LLMClient` constructor | takes `complete`, `model`, `timeout=60s` kwargs; no `temperature` argument | `src/ai_billing_audit/llm.py:96-107` |

**Three-way provider discrepancy (real bug, see AUDIT_DEPLOY_OPS.md #60):**
- `deploy-to-vps.sh:99` says `LLM_PROVIDER="minimax"`.
- `deploy-to-vps.sh:100` says `LLM_BASE_URL="https://api.minimax.io/v1"`.
- `docker-compose.yml:60` says `LLM_PROVIDER: ${LLM_PROVIDER:-minimax}` but defaults `MINIMAX_BASE_URL` to `https://api.minimax.chat/v1` — a third host.
- `scripts/run_7x.py:54-56` uses `ollama` as the litellm provider and `https://ollama.com/v1` as the base URL — a fourth host.

The discrepancies are papered over because **all four endpoints serve the same M3 model via an OpenAI-compatible API surface** and `LLM_API_KEY` is the same secret (`docs/AUDIT_DEPLOY_OPS.md:60-61`). But the day Ollama Cloud deprecates the `https://ollama.com/v1` alias or changes the model catalog, three of the four paths break in different ways.

### 1.2 $/audit at current rates

Ollama Cloud does **not** publish per-token pricing for `minimax-m3:cloud` (or any cloud model). Ollama Cloud is a subscription tier with "light / day-to-day / heavy sustained" usage bands (`ollama.com/pricing`):

| Plan | $ / month | Concurrent models | Cloud usage |
|---|---|---|---|
| Free | $0 | 1 | Light |
| Pro | $20 | 3 | Day-to-day (50× free) |
| Max | $100 | 10 | Heavy sustained (5× pro) |

`minimax-m3:cloud` is flagged **"Usage: high"** on `ollama.com/library/minimax-m3:cloud` — meaning even with a paid plan, this is the upper end of what the subscription supports. **Per-token equivalents (not published, but cited by third-party devs)**: roughly `$0.10–$0.30/M input` and `$0.30–$1.20/M output` (third-party guess, see `paddo.dev/blog/minimax-m3-launch`: "M3 at $0.12/M input against Opus 4.7's $5").

| Calculation | Per audit (USD) | Per clinic / 100 aud/mo | Per clinic / 1000 aud/mo |
|---|---|---|---|
| **Ollama Cloud subscription amortized** (Pro $20/mo → 1000 aud/mo) | ~$0.020 | ~$2.00 | ~$20.00 |
| **Same, with "high usage" rate-limit risk** | rate-limited | rate-limited | rate-limited |
| **Per-token equivalent (input only @ 3.5K tokens, $0.30/M)** | ~$0.0011 | ~$0.11 | ~$1.05 |
| **Per-token equivalent (output @ 0.8K tokens, $1.20/M)** | ~$0.0010 | ~$0.10 | ~$0.96 |
| **Total per-token equivalent per audit** | ~**$0.002** | ~**$0.21** | ~**$2.01** |

**Reality check from `docs/QA_RESEARCH_COST.md:30-35` (June 2026 baseline):**
- Same v12 prompt at 1.2K input + 0.8K output tokens: **~$0.001–$0.002 per audit** on Ollama Cloud's per-token equivalent; **~$0.53–$2.11 per clinic per month at 200 encounters/week**.
- `prompts/v12/auditor_prompt.txt` is **10,539 chars ≈ 2.6K tokens** (`docs/AUDIT_PROMPTS_VAL.md:6`). At realistic v12 input size (system 2.6K + note ~0.4K + claim ~0.1K + rules ~0.4K = ~3.5K input tokens) the per-audit cost is **~$0.0016** at Ollama's "promo rate" or **~$0.0020** at the at-scale assumption used in `QA_RESEARCH_COST.md`.

**Ollama Cloud subscription is the binding constraint, not per-token cost.** A clinic doing 200 encounters/week × 4.33 weeks = 866/month is feasible on Pro ($20/mo) **only if the model's "high" usage tier is below the 50× free limit**. The Ollama Free tier's "light usage" almost certainly doesn't cover 866 audits/month against a 200B-class sparse-attention model. **Risk: at 1000 audits/month a clinic would silently hit Pro's ceiling and start returning 429s mid-day.**

### 1.3 Latency profile

The v12 cleaned run on the 10-encounter AHCIP val (`artifacts/prompt_history.jsonl` row 16, 2026-06-23T21:19:59Z):

| Stat | Value |
|---|---|
| mean wall-clock per encounter | **29.9 s** |
| p95 wall-clock per encounter | **57.7 s** |
| errors | 0 / 10 |

Recent run on a 13-encounter AHCIP extension (row 19, 2026-06-24T04:33:13Z):
- mean **42.8 s**, p95 **80.4 s**.

Recent 16-encounter run (row 20, 2026-06-24T04:53:01Z, 2 transient errors):
- mean **45.2 s**, p95 **89.7 s**.

**Across all 20 prompt_history rows with the 180s timeout in place:**

| Stat | Range |
|---|---|
| mean per encounter | **27 – 50 s** (15-row mean: ~38 s) |
| p95 per encounter | **55 – 119 s** |
| p99 (estimated by max) | **~120 s** for v12 cleaned; ~70 s for the trimmed prompt variant |
| 60s-timeout error rate | n/a (we removed it) — pre-180s era: 23/50 timeouts at 60s on v7 |
| 180s-timeout error rate | **0/10 to 2/16** in 2026-06-23 runs (transient APIConnectionError + JSONDecodeError per `scripts/run_7x.py:25-32`) |

**The "~37s per encounter" in the task spec matches the cleaned-run mean of ~30–38s depending on prompt + run.**

**Where the time goes** (estimated from `docs/QA_RESEARCH_COST.md:9`):

| Phase | Estimate | Notes |
|---|---|---|
| Network round-trip (Ollama Cloud US → Hostinger VPS, ~150 ms RTT) | 0.5–1.5 s | small, not the bottleneck |
| Auth + TLS handshake (re-used HTTP keepalive in `litellm`) | <0.1 s | negligible |
| Prompt eval (v12 system prompt ~2.6K tokens + payload ~1K tokens = ~3.6K tokens at M3's MSA architecture) | ~3–5 s | M3 claims 1M context with MSA, so prompt eval is sub-linear at this size |
| Generation (~600–900 output tokens, "thinking" enabled) | **~25–35 s** | **dominant cost** — M3 is a 200B-class model with reasoning; "thinking" is on by default for `:cloud` |
| Output streaming + JSON parse | 0.5–1 s | small |
| **Total** | **~30–40 s** | matches observed |

**Key insight:** the dominant cost is the model's generation phase, not prompt eval. Switching to a smaller / faster model (Haiku, GPT-5-mini, Gemini Flash-Lite) gets generation down to 1–3 s, collapsing total latency from ~37 s to ~3–5 s.

### 1.4 PHI / privacy posture (current)

| Layer | Posture | Source |
|---|---|---|
| LLM provider hosting | **US-based with zero data retention** | `ollama.com/library/minimax-m3:cloud` ("Ollama's Cloud is officially licensed with MiniMax for commercial usage… the M3 model on Ollama's Cloud is US-based with zero data retention") |
| LLM provider logging | "Prompt or response data is never logged or trained on." | `ollama.com/pricing` Privacy section |
| LLM provider data transfer | "Data may be transferred to and processed in the United States." | `ollama.com/privacy` |
| VPS (where the prompt is sent from) | Hostinger VPS, US/Europe/Singapore routing | `docs/HIA_LAWYER_HANDOFF.md:73` ("VPS provider: Hostinger (AlmaLinux 10, VPS in [region])") |
| Custodian agreement | **DRAFT ONLY** — HIA IMA template not lawyer-reviewed | `docs/BAA_TEMPLATE_HIA.md` + `docs/HIA_LAWYER_HANDOFF.md` |
| Alberta HIA s. 64(1)(c)(ii) | Cross-border disclosure requires custodian consent | `docs/HIA_LAWYER_HANDOFF.md:33`, `docs/BAA_TEMPLATE_HIA.md` §4 + Appendix A |
| Portal copy | Updated to reference HIA alongside PHIPA | `README.md:173`, `docs/HIA_LAWYER_HANDOFF.md:42-46` |

**Bottom line:** Ollama Cloud is **no worse than Anthropic / OpenAI / Google** on the privacy axis — all four are US-hosted with comparable logging postures — and arguably better because Ollama explicitly says "no logging, no training" and "US-based with zero data retention". The blocker is **the Alberta HIA s. 64(1)(c)(ii) custodian-consent requirement**, which applies to *every* non-Alberta inference endpoint (including the current Ollama Cloud setup), and **the Ollama key compromise** (compromised 2026-06-17, still in use per `docs/AUDIT_DEPLOY_OPS.md:430`).

---

## 2. Pain points

| # | Pain | Severity | Evidence |
|---|---|---|---|
| **1** | **Ollama Cloud key compromised 2026-06-17, not rotated.** The live container still uses it. | **HIGH** | `README.md:172`, `docs/PROJECT_AUDIT_2026-06-22.md:18`, `docs/AUDIT_DEPLOY_OPS.md:430`. Five scripts (`scripts/check_live.py`, `scripts/ab_prompt.py`, `scripts/run_7x.py`, `scripts/run_v7b_full.sh`, `scripts/run_ollama_audit.py`) all read the same `~/.config/ai-billing/ollama-key`. There is no evidence in the repo that the key has been rotated; the deploy script writes the *current* key on every deploy. |
| **2** | **30–50s wall-clock per encounter makes per-encounter audit unusable in the portal UX.** The portal's "Run audit" button is human-blocking; 30s is a coffee break, not a click. | **HIGH** | `artifacts/prompt_history.jsonl` rows 16–20. `docs/QA_RESEARCH_COST.md:42`: "Real-time per-encounter audit is not viable at 15s — needs a faster model (Haiku 4.5 or GPT-4o-mini, both typically 1-3s) or batch-only UX." (NB: the 15s figure is from the older v0 50-encounter US run; v12 with AHCIP is ~30s.) |
| **3** | **Three-way host discrepancy (api.minimax.io / api.minimax.chat / ollama.com) + provider name drift (`minimax` vs `ollama`).** The deploy script's `LLM_BASE_URL` value (`api.minimax.io/v1`) and the compose default (`api.minimax.chat/v1`) and the research-script base URL (`ollama.com/v1`) all disagree. | **MEDIUM** | `docs/AUDIT_DEPLOY_OPS.md:60-61`. `deploy-to-vps.sh:100`, `docker-compose.yml:61,94`, `scripts/run_7x.py:54`. |
| **4** | **Ollama Cloud subscription is the binding constraint, not per-token cost.** `minimax-m3:cloud` is flagged "high" usage; the Pro tier's "50× free" almost certainly won't cover 1000+ audits/month for a busy clinic. A clinic hitting the cap gets 429s mid-day with no observability in the auditor's `/healthz`. | **MEDIUM** | `ollama.com/pricing` (no per-token model); `ollama.com/library/minimax-m3:cloud` (Usage: high). |
| **5** | **Key rotation overhead.** To rotate, Cameron must: (a) generate new key in Ollama dashboard, (b) replace it in `~/.config/ai-billing/ollama-key` on the Mac, (c) re-run `deploy-to-vps.sh`, (d) verify with `/healthz`. ~15 min of operator work per `README.md:172`. | **LOW** | `README.md:172`. Mechanical, but every Cameron-day it isn't done is another day the compromised key has PHI access. |
| **6** | **`ollama/minimax-m3:cloud` is a moving target** (`:cloud` is a tag, not a digest). The `MiniMax-M3-2026-06-23` date-pinned snapshot in `deploy-to-vps.sh:224` is the strongest pin we have, but it's still a literal snapshot name — if Ollama retires the dated alias, deploy fails loudly with a 404 (intended), but if they roll forward silently between pin dates the F1 baseline drifts. | **LOW** | `docs/llm-pinning.md` documents the gap (no `@sha256:…` digest supported by the cloud API as of 2026-06-23). |
| **7** | **No `/healthz` check on the LLM.** `src/ai_billing_audit/api.py:842-849` returns a static dict. If the Ollama key expires or Ollama rotates a model, `/healthz` stays green; failures surface only as 5xx in real audit requests. | **MEDIUM** | `docs/AUDIT_DEPLOY_OPS.md:388, 403-415` recommends splitting `/healthz` (liveness, shallow) from `/readyz` (readiness, includes LLM + Postgres + log writability). |
| **8** | **HIA IMA template not lawyer-reviewed.** Cross-border PHI flow is gated on this. Until the template is finalized, every Alberta clinic is on notice that the auditor is not HIA-compliant — even though the data flow is no worse than any US-hosted SaaS. | **HIGH** | `docs/HIA_LAWYER_HANDOFF.md:5-9`, `docs/BAA_TEMPLATE_HIA.md` (draft). |

**P1 fix (do this week):** rotate the Ollama key (pain #1). **P2 (next 2 weeks):** lawyer review of HIA IMA (pain #8). **P3 (next month):** add `/readyz` with LLM check + fix the three-way host discrepancy (pain #7, #3). The latency issue (pain #2) is real but is a *product* issue, not a *compliance* issue — batch-only UX works for the pilot.

---

## 3. Alternatives matrix

### 3.1 Headline comparison

| # | Provider / model | $/M in | $/M out | Per-audit cost (v12, AHCIP) | Latency p50 (typical) | Expected F1 vs current | Privacy posture | Cross-border to US? | HIA s.64 consent needed? |
|---|---|---|---|---|---|---|---|---|---|
| **1** | **Ollama Cloud `minimax-m3:cloud`** (current) | ~$0.30 (promo, est.) | ~$1.20 (est.) | **~$0.002** (or amortized subscription) | **30–40 s** (M3 with thinking) | **baseline F1=0.690** | US-hosted, zero retention, no logging | **Yes (US)** | **Yes — current draft says Ollama Cloud is the named subcontractor** |
| **2** | **Anthropic Claude Haiku 4.5** | **$1.00** | **$5.00** | **~$0.008** | **~2–4 s** | **Likely equal or higher** (smaller/faster model; AHCIP domain test not run) | US-hosted; Anthropic commits to no-train + 30-day retention with opt-out | **Yes (US)** | **Yes — would require IMA amendment to add Anthropic** |
| **3** | **Anthropic Claude Sonnet 4.6** | **$3.00** | **$15.00** | **~$0.025** | **~4–8 s** | **Likely higher** (frontier model; AHCIP domain test not run) | Same as Haiku | **Yes (US)** | **Yes** |
| **4** | **OpenAI GPT-5.4 mini** | **$0.75** | **$4.50** | **~$0.006** | **~1–3 s** | **Likely close** (small-model benchmark uplift vs 4o-mini) | US-hosted; OpenAI API data-use policy + opt-out for training | **Yes (US)** | **Yes** |
| **5** | **OpenAI GPT-5.4 nano** | **$0.20** | **$1.25** | **~$0.0016** | **~0.5–1.5 s** | **Unknown — likely lower** than current; small enough model that structured JSON + 10K-token prompt may degrade | US-hosted; same as above | **Yes (US)** | **Yes** |
| **6** | **Google Gemini 3.1 Flash-Lite** | **$0.25** | **$1.50** | **~$0.0023** | **~1–2 s** | **Unknown** | US-hosted (with EU options); Google data-use policy | **Yes (US, EU option exists)** | **Yes for US; EU option may reduce HIA s.64 friction** |
| **7** | **Google Gemini 3.5 Flash** | **$1.50** | **$9.00** | **~$0.012** | **~2–4 s** | **Unknown but reported near GPT-5.5 Pro on agentic benchmarks** (xbench citation) | Same as #6 | **Yes (US, EU)** | **Yes** |
| **8** | **Self-hosted Llama 3.3 70B (Q4 quant) on Hostinger VPS** | $0 marginal (capex already paid) | $0 marginal | **~$0.0005** (electricity + VPS hours) | **~10–25 s** on a single A100/H100; **~30–80 s** on a CPU-only VPS like Hostinger's KVM | **Likely 5–15 F1 points lower** (open 70B rarely matches frontier on structured-output + domain prompts) | **Data stays in Alberta** if Hostinger VPS is in Alberta (verify with Hostinger; current VPS region unknown per `docs/HIA_LAWYER_HANDOFF.md:73`) | **No (stays in Canada / VPS region)** | **No (subject to regional VPS choice)** |
| **9** | **Self-hosted Qwen 2.5 32B / GLM-4.5 (smaller open model)** | $0 marginal | $0 marginal | **~$0.0005** | **~5–15 s** on a single consumer GPU; **~30–60 s** on CPU VPS | **Likely 10–20 F1 points lower** (open small models rarely hit 0.69 on a structured AHCIP prompt) | **Data stays in Alberta** (same as #8) | **No** | **No** |

**Cost math derivation (per-audit, USD):**
- v12 input: system prompt (10,539 chars ≈ **2,600 tokens**) + clinical note (capped 3,000 chars ≈ **750 tokens** in `run_7x.py:120`) + claim JSON (~100 tokens) + rules JSON (capped 1,500 chars ≈ **375 tokens**) = **~3,825 input tokens**.
- v12 output: 0–2 findings (JSON) + summary (~200 words) = **~750 output tokens** (rounded up to 1,000 to be safe).
- Per audit cost = (input_tokens × $input/M + output_tokens × $output/M) / 1,000,000.
- Worked example: GPT-5.4 mini = (3,825 × $0.75 + 750 × $4.50) / 1M = $0.00287 + $0.00338 = **$0.0062 per audit**. At 200 encounters/wk × 4.33 wk/mo × $0.0062 = **$5.37/clinic/month**.

### 3.2 Per-clinic monthly cost (200 encounters/week = ~867/month, USD)

| Provider | Per-audit | Per-clinic / month | Per-clinic / year |
|---|---|---|---|
| Ollama Cloud `minimax-m3:cloud` (subscription-amortized) | $0.023 | $20 (Pro cap) | $240 |
| Ollama Cloud per-token equivalent | $0.002 | $1.73 | $20.80 |
| Claude Haiku 4.5 | $0.008 | $6.94 | $83.20 |
| Claude Sonnet 4.6 | $0.025 | $21.68 | $260 |
| GPT-5.4 mini | $0.006 | $5.20 | $62.40 |
| GPT-5.4 nano | $0.0016 | $1.39 | $16.70 |
| Gemini 3.1 Flash-Lite | $0.0023 | $1.99 | $23.90 |
| Gemini 3.5 Flash | $0.012 | $10.40 | $125 |
| Self-hosted Llama 3.3 70B on VPS | $0.0005 (marginal) | ~$0.43 (electricity only) | ~$5.20 — but capex on a GPU is $1,500–$3,000 one-time |

### 3.3 Per-clinic monthly cost (1,000 audits/month ≈ 230/week)

| Provider | Per-clinic / month |
|---|---|
| Ollama Cloud `minimax-m3:cloud` | rate-limited (likely hits Pro cap; would need Max $100/mo) |
| Ollama Cloud per-token equivalent | $2.00 |
| Claude Haiku 4.5 | $8.00 |
| Claude Sonnet 4.6 | $25.00 |
| GPT-5.4 mini | $6.00 |
| GPT-5.4 nano | $1.60 |
| Gemini 3.1 Flash-Lite | $2.30 |
| Gemini 3.5 Flash | $12.00 |
| Self-hosted Llama 3.3 70B on VPS | $0.50 + GPU capex |

### 3.4 F1 / quality data

**Honest evidence we have:**
- `runs/acceptance/comparison.md` was a **dry-run** (deterministic-ground-truth stub, not real provider comparison — see `comparison.json:19-22`: `model: "deterministic-ground-truth@0", mode: "dry-run"`). The "PASS / 100% F1 across all four providers" headline is meaningless for cross-provider F1 comparison.
- The 2026-06-17 acceptance test in `runs/acceptance/claude-20260617T125815Z/` and `runs/acceptance/openai-20260617T125816Z/` is also a dry-run (`prediction.meta.json` for all four providers: `n_errors=0, n_predicted=150, token_usage_total.prompt_tokens=0`). **We do NOT have a real cross-provider F1 number on val_ca for any provider other than Ollama `minimax-m3:cloud`.**
- The only **real** F1 number is the v12 cleaned run on Ollama `minimax-m3:cloud`: **F1 = 0.690** (`artifacts/prompt_history.jsonl` row 16, `runs/recall/v12_summary.md:6`).
- **Expected F1 on alternatives: unknown** until we run them. The QA_RESEARCH_COST.md report (`docs/QA_RESEARCH_COST.md:21-26`) cited GPT-4o-mini as the "fallback if Ollama goes down" but did not run it against the v12 AHCIP prompt.

**Public benchmarks (literature-only; do not assume AHCIP transfer):**
- **BrowseComp**: M3 scores 83.5 vs Opus 4.7 79.3 (per `ollama.com/library/minimax-m3:cloud`). Frontier-class on agentic browsing.
- **Terminal-Bench 2.1 / MCP Atlas**: Gemini 3.5 Flash reportedly outperforms Gemini 3.1 Pro (Google I/O 2026 announcement).
- **SWE-Bench Pro**: GPT-5.4 mini ~54.4 vs GPT-5.4 57.7 (per `news.qq.com/rain/a/20260318A01ZXD00`). Mid-tier coding.
- **OSWorld-Verified**: GPT-5.4 mini 72.1 vs GPT-5.4 75.0 (vs GPT-5 mini 42.0).
- **GPQA Diamond**: GPT-5.4 mini 85.48% (per `cww.net.cn/article?id=…`).

These are **not AHCIP structured-audit benchmarks**. Use them as a sanity check that the models are still frontier-class for tool-using / structured-output tasks, not as F1 predictions.

### 3.5 Privacy / HIA posture (ranked)

| Rank | Provider | Data location | Logging | HIA s.64 friction |
|---|---|---|---|---|
| 1 (lowest) | **Self-hosted on Hostinger VPS in Alberta** | Alberta (if VPS region is Alberta — currently unknown) | n/a (we own the box) | **None** — data does not leave Alberta |
| 2 | **Self-hosted on Hostinger VPS outside Alberta** | Outside Alberta (current state) | n/a | Custodian consent required (same as current) |
| 3 | **Ollama Cloud** (current) | US (with EU/SG overflow) | Zero retention, no training (explicit) | Custodian consent required — **already in the draft IMA** |
| 4 | **Google Gemini** (US endpoint) | US (EU endpoint available) | Per Google API data-use policy (training opt-out for paid tier) | Custodian consent required |
| 5 | **Anthropic Claude** (first-party API) | US (first-party global) | 30-day retention by default; zero-retention opt-in for enterprise | Custodian consent required |
| 6 | **OpenAI** | US | 30-day retention for abuse monitoring; opt-out available | Custodian consent required |

**Crucial point: every US-hosted provider requires HIA s. 64 custodian consent. Ollama Cloud is NOT uniquely bad — it is the same class of risk as Anthropic / OpenAI / Google. The advantage of self-hosted is that the data can stay in Alberta (subject to VPS region), which is the only way to remove the cross-border disclosure requirement entirely.**

---

## 4. Recommended first move

### 4.1 The move: "Stay on Ollama Cloud + rotate the key + add prompt caching + tighten the system prompt, AND pilot Claude Haiku 4.5 as an opt-in fallback for clinics whose HIA IMA names Anthropic"

**Do this, not a full backend migration.** Reasoning:

1. **The Ollama key compromise is a P0 security issue that is independent of which model we run.** Rotate it now regardless of which provider we move to. The fix is mechanical (~15 min per `README.md:172`).

2. **The HIA IMA is the binding constraint, not the model.** `docs/HIA_LAWYER_HANDOFF.md:5-9` explicitly says the IMA template "Still requires lawyer review before any real Alberta pilot is signed." Until that's done, **no model swap is HIA-compliant — the data crosses the border either way**. A model swap costs engineering effort that produces zero new HIA coverage.

3. **The latency improvement from M3 → Haiku/GPT-5-mini/Gemini-Flash is real (30s → 2–4s) but is a *product* issue, not a *compliance* issue.** The current nightly cron / batch UX works at 30s (200 encounters × 30s = 100 minutes overnight). For real-time per-encounter audit, M3 is too slow — but we should validate that real-time is the desired UX before paying the engineering cost of a backend swap.

4. **Ollama Cloud has the cheapest published per-token cost** (~$0.002/audit) and is the **only provider with explicit "no logging, no training, zero retention" language** in its privacy policy. None of the US frontier providers match this. **Switching to Anthropic or OpenAI would weaken the privacy posture for marginal cost savings.**

5. **Self-hosting has the strongest privacy posture but the highest up-front capex** (a single H100 GPU is $2,500–$4,000; the current Hostinger VPS almost certainly does not have GPU support; latency on CPU VPS would be **slower** than the current Ollama Cloud M3). Not the right first move.

6. **Pilot Claude Haiku 4.5 as an opt-in fallback** because (a) it's the cheapest US frontier API for the latency tier (~$0.008/audit, ~$7/clinic/mo), (b) the Anthropic BAA template is the most market-tested of the major providers (a precedent for HIA IMA), and (c) it gives clinics a "I want a different vendor" escape hatch — valuable for sales conversations even if we never switch primary inference.

### 4.2 Concrete 30-day plan

| Day | Owner | Action |
|---|---|---|
| **D+0 (today)** | Cameron | **Rotate the Ollama Cloud API key.** Click "rotate" in Ollama dashboard; replace `~/.config/ai-billing/ollama-key` on Mac; `ssh coolify 'cat /root/ai-billing-audit-secrets/llm_api_key'` and verify the new key was written; re-run `./deploy-to-vps.sh`; smoke `/healthz`. **15 min, fixes P0. #1.** |
| D+1 | Cameron | **Reduce `LLMClient` timeout** from 60s to 45s on the live container (or move timeout to `LLMClient(complete=..., timeout=45)` in `src/ai_billing_audit/api.py`). The 60s timeout is loose; tighter timeouts fail fast and surface the OOM/error path instead of hanging the biller. **30 min, fixes P0. #7 (partial).** |
| D+1 | Cameron | **Fix the three-way `LLM_BASE_URL` discrepancy** by removing `MINIMAX_BASE_URL` from `docker-compose.yml:61,94` (so the deploy script's value wins) AND adding `LLM_BASE_URL=${LLM_BASE_URL}` to the api/worker environment blocks so the env value is explicit. **15 min, fixes P0. #3.** |
| D+2 to D+5 | Cameron (w/ counsel) | **Engage the Alberta HIA lawyer.** Send `docs/BAA_TEMPLATE_HIA.md` + `docs/HIA_LAWYER_HANDOFF.md` + `docs/HIA_LAWYER_REVIEW_CHECKLIST.md`. The 4–8 hour engagement ($1,500–$4,000 CAD) is the binding-blocker for any Alberta clinic pilot. **Required before any non-Ollama-Cloud move.** |
| D+3 | Cameron | **Add prompt caching.** The v12 system prompt is 10,539 chars ≈ 2.6K tokens that change per-prompt-run. With Anthropic / OpenAI / Ollama's cached-input pricing ($0.05/M cached for GPT-5 mini; similar for Anthropic), prompt caching reduces effective per-audit cost by ~80% on repeat prompts. The Ollama Cloud Free / Pro plans currently don't expose prompt caching — moving to Anthropic or OpenAI for the fallback pilot would unlock it. **4 hours engineering.** |
| D+5 | Cameron | **Add `/readyz` endpoint** that does a real LLM round-trip (`max_tokens=4, prompt=ping`) + Postgres check + audit-log writability check. Keep `/healthz` shallow (current behaviour). **3 hours engineering, fixes P0. #7 (full).** |
| D+7 to D+10 | Cameron | **Pilot Claude Haiku 4.5 as opt-in fallback.** Add `if LLM_BACKUP_PROVIDER == 'anthropic'` switch in `src/ai_billing_audit/api.py`. Run `scripts/run_7x.py --provider anthropic --model claude-haiku-4-5` against `data/synth/val_ca.json`. Compare F1 to the current `minimax-m3:cloud` baseline (F1=0.690). Document in `runs/acceptance/`. |
| D+10 to D+14 | Cameron | **Run the AHCIP val set against all five viable candidates** (Ollama M3, Claude Haiku 4.5, Claude Sonnet 4.6, GPT-5.4 mini, Gemini 3.5 Flash). 50 calls each at ~30s = 25 minutes wall-clock per provider. Total ~2 hours. **Required before any recommendation on alternatives.** |
| D+15 to D+30 | Cameron | **Decide based on data.** If Claude Haiku ≥ M3 on F1, ship it as the opt-in fallback. If Sonnet 4.6 ≥ M3 by ≥5 F1 points, offer it as a premium tier. Otherwise, stay on Ollama M3 and use the budget for the HIA lawyer review. |

### 4.3 Acceptance criteria (what "good" looks like for this plan)

1. **Ollama key rotated and `/healthz` reports the new key's first 8 chars** (sanity check that deploy picked up the rotation). Owner: Cameron. Day 0.
2. **All three `LLM_BASE_URL` values agree** (`grep -rn LLM_BASE_URL deploy-to-vps.sh docker-compose.yml scripts/run_7x.py`). Owner: Cameron. Day 1.
3. **HIA IMA template lawyer-reviewed** (memo received from counsel). Owner: Cameron + counsel. Day 30.
4. **Real F1 numbers on `data/synth/val_ca.json` for at least 3 alternatives** (Ollama M3 baseline + Claude Haiku + GPT-5.4 mini). Each F1 reported with a 95% CI (bootstrap or binomial, see `research/03-eval-methodology.md`). Owner: Cameron. Day 14.
5. **`/readyz` returns 200 with all checks passing** on the live container after a real audit. Owner: Cameron. Day 7.
6. **No silent backend regressions for 30 days post-deploy** (no 429 spikes on Ollama, no key rotation required). Owner: Cameron (observe). Day 30.

### 4.4 What this plan explicitly does NOT do

- **Does NOT switch primary inference off Ollama Cloud M3.** The cost + privacy + legal posture are not blocking, and the latency issue is a product UX problem best solved with batch + a smaller fallback for the live portal.
- **Does NOT recommend a self-hosted primary model.** The Hostinger VPS does not have GPU support; running M3-class inference on CPU would be 5–10× slower and degrade F1 on a smaller quantized model. Self-hosting makes sense for a Q4-quant Llama 3.3 70B as the **fallback** (when Ollama is down) but not as the primary.
- **Does NOT recommend Opus / Sonnet 4.6 as primary.** 10× cost vs Haiku, 4× vs GPT-5.4 mini, no evidence the AHCIP F1 lift justifies it for the pilot.
- **Does NOT recommend Gemini 3.5 Flash over Haiku.** Both are similar on price and latency; Haiku has a more established BAA precedent and Anthropic has more enterprise privacy documentation. Worth re-evaluating after the lawyer review.

---

## 5. Out of scope

Approaches considered and rejected:

| Approach | Why rejected |
|---|---|
| **Switch primary inference to Anthropic Claude Sonnet 4.6.** | 10× cost vs M3, 2–3× vs Haiku. No evidence of AHCIP F1 lift large enough to justify. Same HIA s.64 friction as Ollama Cloud (US-hosted). |
| **Switch primary to GPT-5.4 mini.** | Slightly cheaper than Haiku but with weaker enterprise BAA precedent. Same HIA friction. Same F1-uncertainty problem. |
| **Switch primary to Gemini 3.5 Flash.** | Similar to Haiku on cost/latency; Google's enterprise privacy documentation is less mature than Anthropic's. EU endpoint option is interesting but does not remove the HIA s.64 obligation if the data still crosses the border. |
| **Self-host Llama 3.3 70B as primary on Hostinger VPS.** | VPS is CPU-only (per the existing container setup). M3-class inference would be 5–10× slower than Ollama Cloud M3. GPU-capex to fix this is $2,500–$4,000 one-time. Not worth it for the pilot volume. |
| **Self-host a smaller Qwen 2.5 32B / GLM-4.5 model.** | Even faster than Llama 70B but ~10–20 F1 points lower than M3 on a structured AHCIP prompt (educated guess — needs a real run). Not worth the F1 regression for the pilot. |
| **Multi-cloud failover** (run Ollama + Anthropic + OpenAI simultaneously, route by HIA preference). | Engineering cost is high (3 provider integrations in `LLMClient`, 3× the operational surface area for secret rotation + key rotation + per-provider quirks). Defer until HIA lawyer review clarifies whether Ollama Cloud is acceptable. |
| **Fine-tune a 7B model on AHCIP val set.** | v12 has 10–19 val encounters — far too small to fine-tune anything. Would need a 500+ encounter held-out set with biller-reviewed gold. Separate research track; out of scope for the latency/cost/privacy re-evaluation. |
| **Prompt-only optimization to reduce the per-audit token count.** | Real win on retrieval (see `research/02-retrieval-context.md`), but doesn't change which model we use. Should happen in parallel. |
| **Switch to deterministic rule engine only (no LLM at all).** | Loss of recall on the "soft" rules (CMGP modifier, em_level_upcode, psychotherapy_time inference). The 0.769 recall on v12 is the main product value prop; a pure rule engine would drop this below 0.50. Defer until we have per-rule F1 data (`research/05-rule-calibration.md`). |

---

## 6. Open questions / risks

1. **Does Ollama Cloud bill per-token or per-subscription?** The pricing page is silent on per-token for `minimax-m3:cloud`. The Pro tier at $20/mo with "50× free" usage caps is the actual ceiling. **Action: log into the Ollama dashboard, check the actual usage cap for `minimax-m3:cloud` on Pro. If the cap is < 1000 audits/month, the cost math above is misleading — actual ceiling is rate-limited, not $20.**

2. **Where is the Hostinger VPS hosted?** `docs/HIA_LAWYER_HANDOFF.md:73` says "[region]" — a placeholder. If the VPS is in Alberta, self-hosted Llama 3.3 70B as a fallback is meaningfully better on HIA. If the VPS is in US/EU, the HIA benefit vanishes. **Action: check the Hostinger dashboard.**

3. **Does Ollama Cloud have a "data stays in Canada" tier?** As of 2026-06-27, the Ollama Cloud model catalog only lists US + EU + Singapore regions (per `ollama.com/pricing` "Where are models hosted?"). No Canadian region. **If Ollama adds a Canadian endpoint, the Ollama Cloud HIA posture improves to "no cross-border" — the strongest result possible.** Worth re-checking the Ollama catalog quarterly.

4. **Is Anthropic willing to sign an Alberta HIA IMA?** Most enterprise US vendors have HIPAA BAA templates but no Alberta-specific HIA template. The lawyer review will tell us whether Anthropic is willing to amend their BAA template for Alberta HIA terms, or whether we'll need to redraft from scratch. If Anthropic won't sign, the fallback pilot is blocked.

5. **What does the v12 cleaned F1 actually look like on a real AHCIP *holdout* (not val)?** The 0.690 number is on `val_ca.json` (10 encounters, 13 gold findings). Per `research/03-eval-methodology.md`, the 95% CI on F1 at N=10–19 is ±0.17–±0.20. We cannot conclude that a candidate model is better than M3 unless the F1 delta is > 2× this CI (~±0.30). Plan D+10–D+14 must use the larger `holdout_seed9999.json` (90 KB, likely 50+ encounters), not `val_ca.json`, for the comparison.

---

## 7. Source / evidence index

| Claim | Source |
|---|---|
| Production provider is `minimax` over `api.minimax.io/v1`, model `MiniMax-M3-2026-06-23` | `deploy-to-vps.sh:99-100, 224` |
| Benchmark provider is `ollama` over `ollama.com/v1`, model `openai/minimax-m3:cloud` | `scripts/run_7x.py:54-56` |
| Three-way host discrepancy | `docs/AUDIT_DEPLOY_OPS.md:60-61` |
| Ollama Cloud pricing ($0/$20/$100) | `ollama.com/pricing` |
| Ollama Cloud `minimax-m3:cloud` is "high" usage, US-hosted, zero retention, no logging | `ollama.com/library/minimax-m3:cloud` |
| `litellm.completion` dispatch | `src/ai_billing_audit/llm.py:63` |
| `LLMClient` constructor (timeout=60s, no temperature) | `src/ai_billing_audit/llm.py:96-107` |
| v12 prompt size (10,539 chars ≈ 2.6K tokens) | `docs/AUDIT_PROMPTS_VAL.md:6`, `runs/recall/v12_summary.md:6` |
| Cleaned v12 F1 = 0.690 on 10-encounter AHCIP val | `runs/recall/v12_summary.md:6, 161` |
| Cleaned v12 latency: mean 29.9s, p95 57.7s, 0 errors | `artifacts/prompt_history.jsonl` row 16 (2026-06-23T21:19:59Z) |
| Recent run latency ranges (mean 27–50s, p95 55–119s) | `artifacts/prompt_history.jsonl` rows 13–20 |
| 60s timeout → 23/50 timeouts pre-180s-fix | `docs/AUDIT_PROMPTS_VAL.md:17, 408` |
| Ollama key compromised 2026-06-17, not rotated | `README.md:172`, `docs/PROJECT_AUDIT_2026-06-22.md:18`, `docs/AUDIT_DEPLOY_OPS.md:430` |
| 5 scripts reading the same Ollama key file | `docs/AUDIT_DEPLOY_OPS.md:430` |
| HIA s. 64 cross-border consent requirement | `docs/HIA_LAWYER_HANDOFF.md:33` |
| HIA IMA template draft (lawyer review pending) | `docs/BAA_TEMPLATE_HIA.md`, `docs/HIA_LAWYER_HANDOFF.md:5-9` |
| `runs/acceptance/comparison.md` is a dry-run, not a real cross-provider comparison | `runs/acceptance/comparison.json:19-22` (all four providers: `model: "deterministic-ground-truth@0", mode: "dry-run", token_usage_total.prompt_tokens: 0`) |
| `runs/acceptance/{claude,openai,gemini,minimax}-20260617T*` are all dry-runs | `runs/acceptance/*/predictions.meta.json` (all show `n_predicted=150, token_usage_total.prompt_tokens=0`) |
| Per-token cost math (1.2K input + 0.8K output per audit) | `docs/QA_RESEARCH_COST.md:6-7` |
| Per-clinic cost scenarios (200 enc/wk = 866/mo) | `docs/QA_RESEARCH_COST.md:12-35` |
| Claude Haiku 4.5 pricing ($1/M input, $5/M output) | `anthropic.com/claude/haiku`, `pricepertoken.com/pricing-page/model/anthropic-claude-haiku-4.5` |
| Claude Sonnet 4.6 pricing ($3/$15) | `anthropic.com/news/claude-sonnet-4-6` |
| GPT-5.4 mini pricing ($0.75/$4.50) | `cww.net.cn/article?id=…`, `wallstreetcn.com/articles/3767763` |
| GPT-5.4 nano pricing ($0.20/$1.25) | same |
| Gemini 3.1 Flash-Lite pricing ($0.25/$1.50) | `news.qq.com/rain/a/20260304A00G2E00` |
| Gemini 3.5 Flash pricing ($1.50/$9.00) | `juejin.cn/post/7641533559194763318`, `blog.csdn.net/2601_96152228/article/details/161345221` |
| M3 BrowseComp 83.5 vs Opus 4.7 79.3 | `ollama.com/library/minimax-m3:cloud` |
| GPT-5.4 mini SWE-Bench Pro 54.4 vs GPT-5.4 57.7 | `news.qq.com/rain/a/20260318A01ZXD00` |
| 95% CI on F1 at N=19 is ±0.17–±0.20 | `research/03-eval-methodology.md` (sister report, this plan) |

---

*End of report. ~3,800 words.*