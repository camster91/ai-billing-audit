"""Run the val split 7 times against ollama cloud. Each run is independent.
Captures variance so we can see if R/P/F1 is stable or noisy.

Writes per-run outputs to runs/acceptance/multi-<timestamp>/run_<N>/ and a
combined summary at runs/acceptance/multi-<timestamp>/summary.json.
"""
import os, json, time, hashlib, sys, importlib.util
from pathlib import Path
from datetime import datetime, timezone

# Pre-imports to avoid the litellm/typing_extensions import-order bug
import inspect as _inspect_mod  # noqa: F401
from pathlib import Path
from datetime import datetime, timezone

# Env
with open(os.path.expanduser('~/.config/ai-billing/ollama-key')) as f:
    key = f.read().strip()
os.environ['OLLAMA_API_KEY'] = key
os.environ['LLM_API_KEY'] = key
# NB: must include /v1 — litellm's openai-compat provider does NOT auto-append
# the version segment for ollama.com, so a bare `https://ollama.com` resolves
# to the ollama.com homepage (HTML) instead of /v1/chat/completions, which
# is what produced the APIConnectionError / JSONDecodeError pair we saw on
# the 2026-06-27 production run. The older run_ollama_audit.py already had
# this right; the /v1 suffix was dropped when we forked run_7x.py for the
# daily-report pivot on 2026-06-27 (commit 5db96e4).
# NB: model prefix must be `openai/` (not `ollama/`) so litellm routes to
# /v1/chat/completions. The `ollama/` prefix makes litellm try the native
# Ollama API at /v1/api/generate which Ollama Cloud does not expose.
os.environ['LLM_BASE_URL'] = 'https://ollama.com/v1'
os.environ['LLM_PROVIDER'] = 'ollama'
os.environ['LLM_MODEL'] = 'openai/minimax-m3:cloud'

# Force real inspect into sys.modules (defensive)
_real = __import__('inspect')
if not hasattr(_real, 'signature'):
    import importlib as _il
    _real = _il.reload(_real)
sys.modules['inspect'] = _real

# CLI args (added 2026-06-27): let operators pin the run to a specific
# split + prompt version. Default = production (val_ca.json + v12) so
# the cron + daily_report reflect what clinics actually see.
# Override: `python scripts/run_7x.py --split val --prompt v0` for the
# legacy US-shaped baseline runs that the QA_RESEARCH_* docs cite.
import argparse
_parser = argparse.ArgumentParser(description="Run a val split N times against the live LLM.")
_parser.add_argument("--split", choices=["val", "val_ca"], default="val_ca",
                    help="Which val set to evaluate against. val_ca (default) is the AHCIP "
                         "10-encounter set v12 was tuned on; val is the 50-encounter US-shaped "
                         "baseline that QA_RESEARCH_* docs cite (F1=0.021 / F1=0.268 floors).")
_parser.add_argument("--prompt", default="v12",
                    help="Which prompt version to use (must match a prompts/{ver}/ directory). "
                         "Default v12 (production). Use v0 for the legacy baseline runs.")
_parser.add_argument("--n-runs", type=int, default=7,
                    help="Number of independent runs (default 7).")
_args = _parser.parse_args()

_split_path = Path("data/synth") / f"{_args.split}.json"
val = json.load(open(_split_path))
gt_by_id = {enc['encounter_id']: enc.get('ground_truth', []) for enc in val}
N_RUNS = _args.n_runs
print(f"Split: {_args.split} ({_split_path}, n={len(val)} encounters)", flush=True)

# Output dir
ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
split_tag = _args.split.replace('_', '')
prompt_tag = _args.prompt.replace(' ', '').replace('/', '_')
out_root = Path(f'runs/acceptance/multi-{split_tag}-{prompt_tag}-{ts}')
out_root.mkdir(parents=True, exist_ok=True)
print(f"Output: {out_root}", flush=True)

# Load llm.py directly
sys.path.insert(0, 'src')
spec = importlib.util.spec_from_file_location('llm_mod', 'src/ai_billing_audit/llm.py')
llm_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(llm_mod)
LLMClient = llm_mod.LLMClient
print("LLMClient loaded", flush=True)

client = LLMClient()
_prompt_path = Path(f"prompts/{_args.prompt}/auditor_prompt.txt")
prompt = open(_prompt_path).read()
print(f"Prompt: {_args.prompt} ({_prompt_path})", flush=True)
schema = {
    "type": "object",
    "properties": {
        "findings": {"type": "array", "items": {"type": "object"}},
        "summary": {"type": "string"}
    },
    "required": ["findings", "summary"]
}

# Build all messages once (same across runs - only model output varies)
def build_messages(enc):
    note = enc.get('clinical_note', '')[:3000]
    claim = enc.get('claim', {})
    claim_str = json.dumps(claim)[:800] if isinstance(claim, dict) else str(claim)[:800]
    rules = enc.get('rules', [])
    rules_str = json.dumps(rules)[:1500] if rules else "No specific rules retrieved."
    return [
        {'role': 'system', 'content': prompt},
        {'role': 'user', 'content': f"""[Clinical_Note]
{note}

[Billed_Claim]
{claim_str}

[Payer_Rules]
{rules_str}"""}
    ]

def score(preds, gt_by_id):
    # Score on rule_id only.
    # The v0/v1 prompts emit rule_id (100% of model findings have it) but
    # NOT category (only ~9% do). Scoring on (category, rule_id) means
    # 91% of model findings count as automatic FPs against a GT that
    # does carry category — i.e., the scorer punishes correct rule_id
    # hits for missing an undocumented field. Per QA_RESEARCH_SUMMARY.md
    # finding #1, scoring on rule_id alone is the right contract for
    # this prompt family.
    def finding_key(f):
        return f.get('rule_id', '')
    tp = fp = fn = 0
    per_enc = []
    for pred in preds:
        eid = pred['encounter_id']
        gt_list = gt_by_id.get(eid, [])
        gt_set = set(finding_key(f) for f in gt_list)
        pred_set = set(finding_key(f) for f in pred.get('findings', []))
        enc_tp = len(gt_set & pred_set)
        enc_fp = len(pred_set - gt_set)
        enc_fn = len(gt_set - pred_set)
        tp += enc_tp; fp += enc_fp; fn += enc_fn
        per_enc.append({'encounter_id': eid, 'gt_count': len(gt_set),
                        'pred_count': len(pred_set), 'tp': enc_tp, 'fp': enc_fp, 'fn': enc_fn,
                        'ok': pred.get('ok', True)})
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
    return {'tp': tp, 'fp': fp, 'fn': fn, 'precision': prec, 'recall': rec, 'f1': f1, 'per_enc': per_enc}

# Run 7 times (overridden by --n-runs CLI arg; default below is preserved
# for callers that don't import _args — _args is only defined when the
# CLI arg parser has run).
all_runs = []
for run_i in range(1, N_RUNS + 1):
    print(f"\n=== Run {run_i}/{N_RUNS} ===", flush=True)
    run_dir = out_root / f'run_{run_i:02d}'
    run_dir.mkdir(parents=True, exist_ok=True)
    results = []
    ok_count = err_count = 0
    t0 = time.time()
    for i, enc in enumerate(val):
        eid = enc['encounter_id']
        messages = build_messages(enc)
        enc_t0 = time.time()
        try:
            result = client.complete_json(messages, schema, max_tokens=4000)
            wall = time.time() - enc_t0
            results.append({
                'encounter_id': eid, 'index': i,
                'is_flagged': enc.get('is_flagged', False),
                'ok': True, 'error_type': None, 'error_message': None,
                'wall_clock_seconds': wall,
                'findings': result.get('findings', []),
                'summary': result.get('summary', '')
            })
            ok_count += 1
        except Exception as e:
            wall = time.time() - enc_t0
            results.append({
                'encounter_id': eid, 'index': i,
                'is_flagged': enc.get('is_flagged', False),
                'ok': False, 'error_type': type(e).__name__,
                'error_message': str(e)[:500],
                'wall_clock_seconds': wall,
                'findings': [], 'summary': ''
            })
            err_count += 1
            print(f"  ERR {eid}: {type(e).__name__}", flush=True)
    elapsed = time.time() - t0

    # Write per-run predictions
    with open(run_dir / 'predictions.jsonl', 'w') as f:
        for r in results:
            f.write(json.dumps(r) + '\n')

    # Score
    s = score(results, gt_by_id)
    s.update({'run': run_i, 'n_encounters': len(val), 'n_ok': ok_count, 'n_errors': err_count,
              'wall_clock_seconds': elapsed, 'model': 'ollama/minimax-m3:cloud'})
    with open(run_dir / 'scores.json', 'w') as f:
        json.dump(s, f, indent=2)

    print(f"  ok={ok_count} err={err_count} P={s['precision']:.3f} R={s['recall']:.3f} F1={s['f1']:.3f} wall={elapsed:.0f}s", flush=True)
    all_runs.append(s)

# Combined summary
import statistics
ps = [r['precision'] for r in all_runs]
rs = [r['recall'] for r in all_runs]
f1s = [r['f1'] for r in all_runs]
summary = {
    'provider': 'ollama',
    'model': 'ollama/minimax-m3:cloud',
    'prompt_version': _args.prompt,
    'prompt_path': str(_prompt_path),
    'prompt_sha256': 'sha256:' + hashlib.sha256(prompt.encode()).hexdigest(),
    'split': _args.split,
    'split_path': str(_split_path),
    'n_gold_findings': sum(len(v) for v in gt_by_id.values()),
    'n_runs': N_RUNS,
    'n_encounters_per_run': len(val),
    'per_run': [
        {'run': r['run'], 'tp': r['tp'], 'fp': r['fp'], 'fn': r['fn'],
         'precision': r['precision'], 'recall': r['recall'], 'f1': r['f1'],
         'n_ok': r['n_ok'], 'n_errors': r['n_errors'],
         'wall_clock_seconds': r['wall_clock_seconds']}
        for r in all_runs
    ],
    'aggregate': {
        'precision_mean': statistics.mean(ps),
        'precision_stdev': statistics.stdev(ps) if len(ps) > 1 else 0,
        'precision_min': min(ps),
        'precision_max': max(ps),
        'recall_mean': statistics.mean(rs),
        'recall_stdev': statistics.stdev(rs) if len(rs) > 1 else 0,
        'recall_min': min(rs),
        'recall_max': max(rs),
        'f1_mean': statistics.mean(f1s),
        'f1_stdev': statistics.stdev(f1s) if len(f1s) > 1 else 0,
        'f1_min': min(f1s),
        'f1_max': max(f1s),
    }
}
with open(out_root / 'summary.json', 'w') as f:
    json.dump(summary, f, indent=2)

print(f"\n{'='*60}")
print(f"7-RUN SUMMARY")
print(f"{'='*60}")
print(f"Precision: {summary['aggregate']['precision_mean']:.3f} ± {summary['aggregate']['precision_stdev']:.3f}  (min={summary['aggregate']['precision_min']:.3f}, max={summary['aggregate']['precision_max']:.3f})")
print(f"Recall:    {summary['aggregate']['recall_mean']:.3f} ± {summary['aggregate']['recall_stdev']:.3f}  (min={summary['aggregate']['recall_min']:.3f}, max={summary['aggregate']['recall_max']:.3f})")
print(f"F1:        {summary['aggregate']['f1_mean']:.3f} ± {summary['aggregate']['f1_stdev']:.3f}  (min={summary['aggregate']['f1_min']:.3f}, max={summary['aggregate']['f1_max']:.3f})")
print(f"\nSaved to: {out_root}/summary.json")
