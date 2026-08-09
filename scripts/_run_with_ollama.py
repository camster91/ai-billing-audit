"""Helper: source ollama key cleanly, run shadow_audit with --provider ollama."""

import os
import sys
from pathlib import Path

OLLAMA_KEY_PATH = Path.home() / ".config" / "ai-billing" / "ollama-key"
if OLLAMA_KEY_PATH.is_file():
    key = OLLAMA_KEY_PATH.read_text().strip()
    os.environ["OPENAI_API_KEY"] = key
    os.environ["LLM_API_KEY"] = key

os.environ.setdefault("LLM_PROVIDER", "ollama")
os.environ.setdefault("LLM_BASE_URL", "https://ollama.com/v1")
os.environ.setdefault("LLM_MODEL", "minimax/minimax-m3:cloud")

# Run shadow_audit.py as if invoked from CLI, with the args from THIS script's argv
sys.argv[0] = "shadow_audit.py"
script = Path(__file__).resolve().parent / "shadow_audit.py"
# Build shadow runner argv: [script, --provider ollama, ...user_args]
user_args = sys.argv[1:]
sys.argv = [str(script), "--provider", "ollama"] + user_args
exec(open(script).read(), {"__name__": "__main__", "__file__": str(script)})
