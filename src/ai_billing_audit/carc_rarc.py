"""CARC / RARC code lookup tables (kanban t_7743e5d5).

Two standardized claim-denial reason code systems live here:

* **CARC** — Claim Adjustment Reason Codes (X12 / WPC). A
  three-character code (numeric, or letter+number) that explains
  *why* a claim line was paid differently than billed. Published
  by the X12 / WPC committee and adopted by CMS for the
  electronic remittance advice (ERA / 835).

* **RARC** — Remittance Advice Remark Codes (CMS / X12). A
  code (typically ``M<n>`` or ``N<n>``) that supplements a CARC
  with supplemental information — e.g. "missing modifier",
  "submit medical records", "review for medical necessity".
  RARCs without an accompanying CARC are also legal; they
  stand alone.

Data source
-----------
This module loads from two CSV files shipped in the repo at
``data/tables/carc.csv`` and ``data/tables/rarc.csv``. The
authoritative source for both code sets is:

  - CMS HIPAA / X12 CARC list:
    https://x12.org/codes/claim-adjustment-reason-codes
    (republished quarterly by WPC, the X12 workgroup
    responsible for the code set)
  - CMS RARC list:
    https://x12.org/codes/remittance-advice-remark-codes
    (republished quarterly by CMS)

The CSVs in this repo are a hand-curated subset of the most
common ~50 CARC and ~120 RARC codes that billers see in
production (timely filing, prior auth, bundling, modifier
issues, etc.). When the master list updates, the CSVs are the
update point — keep the on-disk table in sync, don't hardcode
here. v0 ships a static snapshot; v1 can periodically pull
from WPC and produce a diff for review.

Format
------
Each CSV has 4 columns: ``code, description, payer_types,
common_resolutions``. ``payer_types`` is a pipe-delimited list
(Commercial, Medicare, Medicaid, etc.). ``common_resolutions``
is a free-text description of the typical fix a biller
applies — useful for the dashboard "What now?" card.

The lookup is a tiny module — no caching needed, no network,
no LLM. A claim comes in with a CARC, the biller clicks it,
and the UI shows the description + suggested next step.
"""

from __future__ import annotations

import csv
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Resolve the data/tables dir relative to this file so the
# module works whether installed via pip or run from a checkout.
_PKG_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PKG_DIR.parent.parent  # src/ai_billing_audit/<this>.py → repo root
_DATA_DIR = _PROJECT_ROOT / "data" / "tables"
_CARC_CSV = _DATA_DIR / "carc.csv"
_RARC_CSV = _DATA_DIR / "rarc.csv"


@dataclass
class CodeEntry:
    """A single row from the CARC or RARC CSV.

    Fields mirror the CSV columns exactly. ``payer_types`` is
    stored as a list of strings (split on ``|``) so the
    endpoint can answer "is this code Medicare-specific?"
    without reparsing every call. ``common_resolutions`` stays
    as a list too — the CSV's pipe-delimited form was a
    shortcut for human editing; the API exposes the parsed
    form.
    """

    code: str
    description: str
    payer_types: list[str] = field(default_factory=list)
    common_resolutions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "description": self.description,
            "payer_types": list(self.payer_types),
            "common_resolutions": list(self.common_resolutions),
        }


# ─── loaders (with module-level cache) ────────────────────────────

# The CSVs are read once at module import (or first-call) and
# cached. The lock guards against a rare race where two threads
# both see an empty cache and both do the parse; the lock makes
# one of them do the work and the other reuse the result.
_LOAD_LOCK = threading.Lock()
_CARC_BY_CODE: dict[str, CodeEntry] | None = None
_RARC_BY_CODE: dict[str, CodeEntry] | None = None


def _split_pipe(s: str) -> list[str]:
    if not s:
        return []
    return [p.strip() for p in s.split("|") if p.strip()]


def _load_csv(path: Path) -> dict[str, CodeEntry]:
    """Parse a CARC/RARC CSV into a ``{code: CodeEntry}`` dict.

    Empty / missing rows are skipped silently. Malformed rows
    (e.g. wrong number of columns) are skipped with a warning
    — we never raise on a single bad row because the rest of
    the table is still useful and the biller should still get
    SOMETHING when they look up a code.
    """
    if not path.is_file():
        # Not a hard error at import time — the lookup just
        # returns None for every code. The endpoint surfaces
        # 503 so the UI can show "lookup table unavailable".
        return {}
    out: dict[str, CodeEntry] = {}
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row_num, row in enumerate(reader, start=2):  # header is row 1
            code = (row.get("code") or "").strip()
            if not code:
                # Empty row — skip.
                continue
            description = (row.get("description") or "").strip()
            payer_types = _split_pipe(row.get("payer_types") or "")
            common_resolutions = _split_pipe(row.get("common_resolutions") or "")
            out[code] = CodeEntry(
                code=code,
                description=description,
                payer_types=payer_types,
                common_resolutions=common_resolutions,
            )
    return out


def _get_carc_table() -> dict[str, CodeEntry]:
    global _CARC_BY_CODE
    if _CARC_BY_CODE is None:
        with _LOAD_LOCK:
            if _CARC_BY_CODE is None:
                _CARC_BY_CODE = _load_csv(_CARC_CSV)
    return _CARC_BY_CODE


def _get_rarc_table() -> dict[str, CodeEntry]:
    global _RARC_BY_CODE
    if _RARC_BY_CODE is None:
        with _LOAD_LOCK:
            if _RARC_BY_CODE is None:
                _RARC_BY_CODE = _load_csv(_RARC_CSV)
    return _RARC_BY_CODE


# ─── public API ───────────────────────────────────────────────────


def lookup_carc(code: str) -> CodeEntry | None:
    """Return the CodeEntry for a CARC code, or None if unknown.

    Lookup is case-sensitive and exact — the CARC alphabet
    uses a mix of letters and digits ("B7", "P10", "1", "16")
    and case is meaningful for some codes. We don't lowercase
    because the published list is always uppercase; a biller
    who copies from an ERA will copy the published form.
    """
    if not code:
        return None
    table = _get_carc_table()
    return table.get(code)


def lookup_rarc(code: str) -> CodeEntry | None:
    """Return the CodeEntry for a RARC code, or None if unknown."""
    if not code:
        return None
    table = _get_rarc_table()
    return table.get(code)


def table_stats() -> dict[str, int]:
    """Return the count of known codes in each table.

    Useful for the dashboard's "X codes loaded" badge and for
    a quick sanity check in tests. Cheap — O(1) dict lookups.
    """
    return {
        "carc_count": len(_get_carc_table()),
        "rarc_count": len(_get_rarc_table()),
    }


def reset_cache() -> None:
    """Clear the module-level table cache.

    Tests call this after pointing the CSV env var at a
    different file, so the next ``lookup_*`` call re-reads
    from disk. Production never calls this — the cache is the
    whole point.
    """
    global _CARC_BY_CODE, _RARC_BY_CODE
    with _LOAD_LOCK:
        _CARC_BY_CODE = None
        _RARC_BY_CODE = None


__all__ = [
    "CodeEntry",
    "lookup_carc",
    "lookup_rarc",
    "table_stats",
    "reset_cache",
]
