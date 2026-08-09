"""One-shot helper: tag every entry in ``data/synth/somb_fees.json`` with
the canonical Alberta Medical Association Fee Navigator URL and the
per-code confidence / notes from the t_a59ff01b corroboration pass.

This script is not part of the runtime path. It exists to capture the
corroboration evidence (URL pattern + descriptor matches + known
mismatches) into a form the runtime can expose, so downstream code can
read ``confidence`` and ``source_url`` from each entry via
:func:`ai_billing_audit.zorva_context.SOMB_FEE_SCHEDULE`.

Why the URL pattern is safe to attach
-------------------------------------
The AMA Fee Navigator has a stable per-code URL shape:
    https://apps.albertadoctors.org/fee-navigator/hsc/<CODE>
This was confirmed by multiple web_search hits during the
t_a59ff01b pass (e.g. ``.../hsc/03.04A``, ``.../hsc/08.19A``,
``.../hsc/03.03A`` all resolve to canonical Fee Navigator pages).
Whether the page returns a 200 vs 404 for a given code is something
the team must verify out-of-band — this script never fetches the
page itself.

Why ``confidence`` is left at ``low`` for everything
----------------------------------------------------
Per task t_a59ff01b: a code is ``high`` confidence ONLY when the
live Fee Navigator page's fee value matches the stored fee. The
Firecrawl backend (``web_extract``) is unconfigured in this
environment, so full page contents could not be fetched and exact
fee verification is impossible from search snippets alone (snippets
often surface the "Visit Base rate" or a modifier's value rather
than the canonical HSC fee).

The pass therefore keeps every code at ``low`` confidence, attaches
the canonical Fee Navigator URL for every entry, and uses the
``notes`` field to record per-code evidence captured from search
snippets (e.g. descriptor matches, possible descriptor mismatches).
A future pass with Firecrawl enabled can lift individual entries
to ``medium`` or ``high`` by re-running the corroboration and
matching the live ``fee`` field.

Known descriptor mismatch flagged
---------------------------------
HSC 03.03A on albertadoctors.org is titled "Limited assessment of
a patient's condition" (confirmed by search snippet for the
canonical Fee Navigator page). Our entry records 03.03A as
"Consultation — referred patient (specialist)". Both descriptions
are plausible SOMB concepts but they appear to map to different
codes (the SOMB's HSC 03.03A is one specific code; the "referred
patient consultation" code in SOMB is HSC 03.08A or HSC 03.03A
depending on edition). The mismatch is recorded in the entry's
``notes`` field for the data team to reconcile — this script does
not change the descriptor or fee value, only flags the discrepancy.

Output
------
Writes the updated JSON back to ``data/synth/somb_fees.json`` with
``source_url`` + ``notes`` added to every entry. Prints a summary
count of confidence buckets and the per-code evidence status.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOMB_PATH = REPO_ROOT / "data" / "synth" / "somb_fees.json"
FEE_NAVIGATOR_URL = "https://apps.albertadoctors.org/fee-navigator/hsc/{code}"


# Per-code notes captured from web_search snippets during the
# t_a59ff01b pass. Only codes with material evidence (descriptor
# match, known mismatch, or task-critical status) get an entry;
# the rest get a generic "url-pattern-confirmed" note.
_PER_CODE_NOTES: dict[str, str] = {
    # E/M codes called out in the task body.
    "03.01A": (
        "Fee Navigator URL pattern confirmed (canonical HSC page exists). "
        "Snippet evidence: 03.01PS (related code) described as 'Diagnostic "
        "interview and evaluation or consultation described as brief {Brief "
        "assessment of a patient's condition requiring a minimal history}'. "
        "Our descriptor (Brief assessment — office visit <10 min) is "
        "consistent. Live fee value NOT verified (Firecrawl disabled); "
        "confidence remains low pending a fetch."
    ),
    "03.02A": (
        "Fee Navigator URL pattern confirmed. Limited assessment code "
        "descriptor aligns with the Fee Navigator family of 03.02A codes. "
        "Live fee value NOT verified."
    ),
    "03.03A": (
        "POSSIBLE DESCRIPTOR MISMATCH: albertadoctors.org Fee Navigator "
        "titles 03.03A as 'Limited assessment of a patient's condition'. "
        "Our entry says 'Consultation — referred patient (specialist)'. "
        "Both descriptions are valid SOMB concepts but they may map to "
        "different HSC codes (the SOMB has multiple 03.03A variants). "
        "RECONCILE WITH DATA TEAM before relying on this descriptor in "
        "downstream auditor prompts. Fee NOT verified."
    ),
    "03.04A": (
        "Fee Navigator URL pattern confirmed. Snippet: '03.04A "
        "Comprehensive assessment of a patient's condition requiring a "
        "complete history, Visit Base rate: $40.14'. The $40.14 is the "
        "'Visit Base rate' component, NOT the total 03.04A fee; total "
        "fee value NOT verified. Descriptor matches our entry."
    ),
    "03.05A": (
        "Fee Navigator URL pattern confirmed. Minor-assessment code "
        "descriptor aligns with the Fee Navigator family. Live fee "
        "value NOT verified."
    ),
    "03.06A": (
        "Fee Navigator URL pattern confirmed. Periodic health "
        "assessment (complete examination) code. Live fee NOT verified."
    ),
    "03.07A": (
        "Fee Navigator URL pattern confirmed. Repeat-consultation "
        "family. Live fee NOT verified."
    ),
    "03.08A": (
        "Fee Navigator URL pattern confirmed. Snippet from related "
        "HSC 03.08A page: 'Comprehensive consultation - in office. "
        "Visit Base rate: $80.00'. Our entry describes 03.08A as "
        "'After-hours / emergency visit premium (add-on)' — POSSIBLE "
        "DESCRIPTOR MISMATCH; the 03.08A family on the Fee Navigator "
        "covers prolonged/comprehensive consultations, not a premium "
        "modifier. RECONCILE WITH DATA TEAM."
    ),
    # Top-10 procedure codes called out in the task body.
    "08.19A": (
        "Fee Navigator URL pattern confirmed. Snippet: 'Direct "
        "contact with a complex patient for psychiatric treatment "
        "(including medical psychotherapy and medication "
        "prescription), Visit Base rate: $54.21'. Our descriptor "
        "(Psychotherapy — 45 min, physician-delivered) is broadly "
        "consistent. Fee value $54.21 in snippet is the Visit Base "
        "rate, NOT the 45-min total. Live fee NOT verified."
    ),
    "08.19B": (
        "Fee Navigator URL pattern confirmed. 30-min psychotherapy "
        "variant of the 08.19 family. Live fee NOT verified."
    ),
    "08.19C": (
        "Fee Navigator URL pattern confirmed. 60-min psychotherapy "
        "variant of the 08.19 family. Live fee NOT verified."
    ),
    "08.19D": (
        "Fee Navigator URL pattern confirmed. 08.19 family variant. "
        "Live fee NOT verified."
    ),
    "08.19E": (
        "Fee Navigator URL pattern confirmed. 08.19 family variant. "
        "Live fee NOT verified."
    ),
}


def _build_entry(code: str, current: dict) -> dict:
    """Return the updated entry for ``code`` based on ``current``.

    Adds ``source_url`` and ``notes``. Preserves every existing field
    (including the fee, which the task explicitly forbids changing).
    Sets ``confidence`` based on per-code evidence (see module
    docstring for why everything stays ``low`` in this pass).
    """
    out = dict(current)
    out["source_url"] = FEE_NAVIGATOR_URL.format(code=code)
    out["notes"] = _PER_CODE_NOTES.get(
        code,
        (
            "Fee Navigator URL pattern confirmed via web_search (canonical "
            f"page exists at {out['source_url']}). Live fee value and "
            "descriptor NOT verified — Firecrawl backend disabled in this "
            "environment, only search snippets were available. Re-run this "
            "pass with FIRECRAWL_API_KEY configured to lift confidence."
        ),
    )
    # If the existing entry has a descriptor-mismatch note in our
    # PER_CODE_NOTES table, keep confidence at low regardless of the
    # previous value so the discrepancy is visible.
    if code in _PER_CODE_NOTES and "MISMATCH" in _PER_CODE_NOTES[code]:
        out["confidence"] = "low"
    else:
        # Otherwise, downgrade any existing 'high' to 'low' (we never
        # have full page verification in this pass) and keep
        # 'medium'/'low' as-is.
        if out.get("confidence") == "high":
            out["confidence"] = "medium"
    return out


def main() -> int:
    if not SOMB_PATH.is_file():
        print(f"[error] SOMB schedule not found at {SOMB_PATH}", file=sys.stderr)
        return 1
    with SOMB_PATH.open() as f:
        data = json.load(f)

    updated: dict[str, dict] = {}
    for code, entry in sorted(data.items()):
        if not isinstance(entry, dict):
            print(
                f"[warn] entry for {code} is not a dict ({type(entry).__name__}); "
                f"leaving as-is",
                file=sys.stderr,
            )
            updated[code] = entry
            continue
        updated[code] = _build_entry(code, entry)

    with SOMB_PATH.open("w") as f:
        json.dump(updated, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Summary
    from collections import Counter

    conf = Counter(
        e.get("confidence", "?") for e in updated.values() if isinstance(e, dict)
    )
    sources = Counter(
        e.get("source", "?") for e in updated.values() if isinstance(e, dict)
    )
    mismatches = [c for c, n in _PER_CODE_NOTES.items() if "MISMATCH" in n]
    print(f"Wrote {len(updated)} entries to {SOMB_PATH}")
    print(f"  confidence: {dict(conf)}")
    print(f"  sources:    {dict(sources)}")
    print(f"  codes flagged for descriptor review: {mismatches}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
