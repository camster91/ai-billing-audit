#!/bin/bash
set -e
cd /Users/biancabienaime/projects/ai-billing-audit
export LLM_API_KEY="$(cat ~/.config/ai-billing/ollama-key)"
export LLM_PROVIDER=ollama
export LLM_BASE_URL=https://ollama.com
export LLM_MODEL=ollama/minimax-m3:cloud
export ZORVA_SKIP_SMOKE=1
.venv/bin/python scripts/smartness_test.py \
  --prompt prompts/v12/auditor_prompt.txt \
  --val data/synth/val_ca.json \
  --out runs/recall/v12_with_undercode.json \
  --quiet
