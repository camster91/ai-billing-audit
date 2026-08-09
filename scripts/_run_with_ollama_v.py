"""Helper: source ollama key cleanly, run shadow_audit with progress per encounter."""

import os
import sys
from pathlib import Path

# Load as module via direct path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import importlib.util as _iu

spec = _iu.spec_from_file_location(
    "shadow_audit", str(Path(__file__).resolve().parent / "shadow_audit.py")
)
shadow_audit = _iu.module_from_spec(spec)
sys.modules["shadow_audit"] = shadow_audit

# Load env
OLLAMA_KEY_PATH = Path.home() / ".config" / "ai-billing" / "ollama-key"
if OLLAMA_KEY_PATH.is_file():
    key = OLLAMA_KEY_PATH.read_text().strip()
    os.environ["OPENAI_API_KEY"] = key
    os.environ["LLM_API_KEY"] = key

os.environ.setdefault("LLM_PROVIDER", "ollama")
os.environ.setdefault("LLM_BASE_URL", "https://ollama.com/v1")
os.environ.setdefault("LLM_MODEL", "minimax/minimax-m3:cloud")

spec.loader.exec_module(shadow_audit)


def main_with_progress():
    import argparse
    import datetime as dt
    import json as _j

    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--provider", default="stub")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--out-dir", type=Path, default=Path("runs/shadow"))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    if not args.input.is_file():
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        return 2
    encounters = shadow_audit.load_encounters(args.input)
    if args.limit:
        encounters = encounters[: args.limit]
    if not encounters:
        print("ERROR: no encounters loaded", file=sys.stderr)
        return 3
    run = shadow_audit._auditor_for(args.provider, args.base_url)
    for i, enc in enumerate(encounters):
        t_enc = dt.datetime.now(tz=dt.timezone.utc)
        findings = run(enc)
        enc["findings"] = findings
        elapsed = (dt.datetime.now(tz=dt.timezone.utc) - t_enc).total_seconds()
        print(
            f"  [{i + 1}/{len(encounters)}] {enc['encounter_id']}: {len(findings)} findings ({elapsed:.1f}s)",
            file=sys.stderr,
        )
    summary = shadow_audit._summarise(encounters)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.input.stem
    ts = dt.datetime.now(tz=dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    md_path = args.out_dir / f"{stem}-{ts}.md"
    json_path = args.out_dir / f"{stem}-{ts}.json"
    md_path.write_text(
        shadow_audit._render_markdown(args.input, encounters, summary, args.provider)
    )
    json_path.write_text(
        _j.dumps(
            shadow_audit._render_json(args.input, encounters, summary, args.provider),
            indent=2,
        )
    )
    print(
        f"OK: {len(encounters)} encounters, {summary['n_findings']} findings",
        file=sys.stderr,
    )
    print(f"    Markdown: {md_path}", file=sys.stderr)
    print(f"    JSON:     {json_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main_with_progress())
