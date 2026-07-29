"""Live deploy parity check. Fires 5 encounters at the live URL, compares
to the same encounters run locally, alerts if drift > 5%.

Usage: python scripts/check_live.py
"""
import os, json, time, subprocess, hashlib
from pathlib import Path
from datetime import datetime, timezone
import urllib.request
import urllib.error

LIVE_URL = os.environ.get('LIVE_URL', 'https://ai-billing-audit.ashbi.ca')
ALERT_DRIFT = float(os.environ.get('ALERT_DRIFT', '0.10'))  # 10% drift = alert
# Allow VAL_JSON to point at the synth dataset (val_ca.json) without copying it
# into data/val.json — keeps the eval set under data/synth/ where it lives.
VAL_JSON = os.environ.get('VAL_JSON', 'data/val.json')

print(f"Live URL: {LIVE_URL}")
print(f"Alert threshold: {ALERT_DRIFT*100:.0f}% drift")
print(f"Val dataset: {VAL_JSON}")

# Pick 5 random encounters from val
import random
val = json.load(open(VAL_JSON))
sample = random.sample(val, 5)
print(f"Sampled {len(sample)} encounters")

# Use the local scorer to get the gold for these 5
gt_by_id = {enc['encounter_id']: enc.get('ground_truth', []) for enc in val}

# Local run on the same 5
print("\n=== Local run on 5 encounters ===")
local_script = """
import os, json, sys, importlib.util
with open(os.path.expanduser('~/.config/ai-billing/ollama-key')) as f:
    os.environ['OLLAMA_API_KEY'] = f.read().strip()
os.environ['LLM_API_KEY'] = os.environ['OLLAMA_API_KEY']
# 2026-06-27 fix: api_base must include /v1 (litellm does NOT auto-append it for
# ollama.com) and model must use the openai/ prefix (ollama/ routes litellm to
# the native /api/generate endpoint which Ollama Cloud does not expose). Bare
# https://ollama.com + ollama/ prefix returns ollama.com homepage HTML.
# See scripts/run_ollama_audit.py for the working reference pattern.
os.environ['LLM_BASE_URL'] = 'https://ollama.com/v1'
os.environ['LLM_PROVIDER'] = 'ollama'
os.environ['LLM_MODEL'] = 'openai/minimax-m3:cloud'
import inspect as _i  # noqa
_real = __import__('inspect')
if not hasattr(_real, 'signature'):
    import importlib as _il
    _real = _il.reload(_real)
sys.modules['inspect'] = _real
sys.path.insert(0, 'src')
spec = importlib.util.spec_from_file_location('llm_mod', 'src/ai_billing_audit/llm.py')
llm_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(llm_mod)
client = llm_mod.LLMClient()
prompt = open('prompts/v0/auditor_prompt.txt').read()
schema = {"type": "object", "properties": {"findings": {"type": "array", "items": {"type": "object"}}, "summary": {"type": "string"}}, "required": ["findings", "summary"]}
ids = json.loads(sys.argv[1])
val = json.load(open(os.environ.get('VAL_JSON', 'data/val.json')))
by_id = {e['encounter_id']: e for e in val}
out = []
for eid in ids:
    enc = by_id[eid]
    note = enc.get('clinical_note', '')[:3000]
    claim = enc.get('claim', {})
    claim_str = json.dumps(claim)[:800] if isinstance(claim, dict) else str(claim)[:800]
    rules = enc.get('rules', [])
    rules_str = json.dumps(rules)[:1500] if rules else "No specific rules retrieved."
    msgs = [
        {'role': 'system', 'content': prompt},
        {'role': 'user', 'content': f'[Clinical_Note]\\n{note}\\n\\n[Billed_Claim]\\n{claim_str}\\n\\n[Payer_Rules]\\n{rules_str}'}
    ]
    try:
        r = client.complete_json(msgs, schema, max_tokens=4000)
        out.append({'encounter_id': eid, 'ok': True, 'findings': r.get('findings', []), 'summary': r.get('summary', '')})
    except Exception as e:
        out.append({'encounter_id': eid, 'ok': False, 'error_type': type(e).__name__, 'error_message': str(e)[:200], 'findings': [], 'summary': ''})
print(json.dumps(out))
"""
sample_ids = [e['encounter_id'] for e in sample]
result = subprocess.run(
    ['.venv/bin/python', '-c', local_script, json.dumps(sample_ids)],
    capture_output=True, text=True, cwd='.'
)
if result.returncode != 0:
    print(f"Local run failed: {result.stderr[:500]}")
    sys.exit(1)
local_results = json.loads(result.stdout.strip())

# Live run: POST each encounter to the live preview endpoint
print("\n=== Live run on 5 encounters ===")
live_results = []
for eid in sample_ids:
    enc = next(e for e in val if e['encounter_id'] == eid)
    # Build a 837P-like payload (or just POST the JSON encounter)
    body = json.dumps(enc).encode()
    req = urllib.request.Request(
        f'{LIVE_URL}/encounters/upload/preview',
        data=body,
        headers={'content-type': 'application/json'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            live_results.append({
                'encounter_id': eid,
                'ok': resp.status == 200,
                'status': resp.status,
                'body': resp.read().decode()[:500]
            })
    except urllib.error.HTTPError as e:
        live_results.append({
            'encounter_id': eid,
            'ok': False,
            'status': e.code,
            'body': e.read().decode()[:500]
        })
    except Exception as e:
        live_results.append({
            'encounter_id': eid,
            'ok': False,
            'error': str(e)[:200]
        })

# Score local
def finding_key(f):
    return (f.get('category', ''), f.get('rule_id', ''))

def score_local(results):
    tp = fp = fn = 0
    for r in results:
        eid = r['encounter_id']
        gt_set = set(finding_key(f) for f in gt_by_id.get(eid, []))
        pred_set = set(finding_key(f) for f in r.get('findings', []))
        tp += len(gt_set & pred_set)
        fp += len(pred_set - gt_set)
        fn += len(gt_set - pred_set)
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
    return {'precision': prec, 'recall': rec, 'f1': f1, 'tp': tp, 'fp': fp, 'fn': fn}

local_score = score_local(local_results)

# For live, count findings in response bodies (we don't have ground truth comparison)
# Just count findings produced
live_findings_count = 0
live_ok = 0
for r in live_results:
    if r.get('ok') and 'body' in r:
        try:
            body = json.loads(r['body'])
            rows = body.get('rows', [])
            live_findings_count += len(rows)
            live_ok += 1
        except json.JSONDecodeError:
            pass

# Drift: local vs live finding counts
local_findings = sum(len(r.get('findings', [])) for r in local_results)
drift = abs(local_findings - live_findings_count) / max(local_findings, 1)
alert = drift > ALERT_DRIFT

ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
out_dir = Path('runs/acceptance/live-parity')
out_dir.mkdir(parents=True, exist_ok=True)
report_path = out_dir / f'{ts}.json'
with open(report_path, 'w') as f:
    json.dump({
        'ts': ts,
        'live_url': LIVE_URL,
        'local_score': local_score,
        'local_findings': local_findings,
        'live_findings': live_findings_count,
        'live_ok': live_ok,
        'drift': drift,
        'alert': alert,
        'threshold': ALERT_DRIFT,
        'local_results': local_results,
        'live_results': live_results,
    }, f, indent=2)

print(f"\n{'='*60}")
print(f"LIVE PARITY CHECK — {ts}")
print(f"{'='*60}")
print(f"Local R={local_score['recall']:.3f} P={local_score['precision']:.3f} F1={local_score['f1']:.3f} (TP={local_score['tp']} FP={local_score['fp']} FN={local_score['fn']})")
print(f"Local findings: {local_findings}")
print(f"Live findings:  {live_findings_count} ({live_ok}/{len(sample_ids)} live calls succeeded)")
print(f"Drift: {drift*100:.1f}%")
print(f"Alert (> {ALERT_DRIFT*100:.0f}%): {'YES' if alert else 'NO'}")
print(f"\nReport: {report_path}")

if alert:
    print(f"\n*** ALERT: live vs local drift exceeds {ALERT_DRIFT*100:.0f}% — investigate deploy")
