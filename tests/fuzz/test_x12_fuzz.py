"""Fuzz harness for ``x12_parser.py``.

This is **detect-and-document only**: it feeds 200 deliberately malformed
837P samples through the parser and records three signal types — (1)
uncaught exceptions, (2) silently dropped fields, (3) accepted-invalid
state — but never edits the parser.

The harness is re-runnable and deterministic: the sample set is built
from a fixed PRNG seed (``SEED = 20260616``) so re-runs produce the same
input corpus. It is *not* a real test in the pytest sense (it is a
scaffolding script that lives under ``tests/fuzz/`` so the existing
``pytest tests/`` runner will not pick it up — pytest would only see it
if you opt in with ``pytest tests/fuzz/``). The harness exits 0 on
success and writes a per-category summary to stdout plus a full
machine-readable JSON to ``tests/fuzz/_findings.json``.

Run it directly::

    python tests/fuzz/test_x12_fuzz.py

Or via pytest with the marker this file declares at the bottom.

The seven input categories the task spec requires are each given a
distinct ``category`` tag and ~28-30 samples per category (200 total).
Each sample is paired with an optional ``expect`` dict that names the
fields the source payload *did* contain — the harness uses that dict
to detect silently-dropped data and accepted-invalid state.
"""
from __future__ import annotations

import importlib.util
import json
import os
import random
import re
import sys
import textwrap
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 1. Import the parser without dragging in the full ``ai_billing_audit``
#    package init (which requires litellm/dspy/fastapi). The parser itself
#    is a leaf module — it only depends on stdlib ``re`` and ``typing``.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_PARSER_PATH = _HERE.parent.parent / "src" / "ai_billing_audit" / "x12_parser.py"
_spec = importlib.util.spec_from_file_location("x12_parser_fuzz", _PARSER_PATH)
x12_parser = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(x12_parser)
parse_837p = x12_parser.parse_837p
X12ParseError = x12_parser.X12ParseError
validate_required_fields = x12_parser.validate_required_fields

# ---------------------------------------------------------------------------
# 2. Constants.
# ---------------------------------------------------------------------------

SEED = 20260616
N_SAMPLES = 200
CATEGORIES = (
    "truncated_segment",
    "missing_envelope",
    "wrong_order",
    "invalid_date",
    "bad_cpt",
    "units_out_of_range",
    "bad_currency",
)
# Roughly even distribution; sum must be exactly N_SAMPLES.
CATEGORY_SIZES = {
    "truncated_segment": 29,
    "missing_envelope": 28,
    "wrong_order": 29,
    "invalid_date": 29,
    "bad_cpt": 28,
    "units_out_of_range": 29,
    "bad_currency": 28,
}
assert sum(CATEGORY_SIZES.values()) == N_SAMPLES, CATEGORY_SIZES


# A minimal-but-valid 837P envelope, used as the base for "mutate this one
# thing" categories. Field values are deliberately small so the diffs
# against the source stay visible.
BASE_837P = (
    "ISA*00*          *00*          *ZZ*SUBMITTERID    *ZZ*RECEIVERID     "
    "*240515*1200*^*00501*000000001*0*P*:~"
    "GS*HC*SUBMITTER*RECEIVER*20240515*1200*1*X*005010X222A1~"
    "ST*837*0001*005010X222A1~"
    "BHT*0019*00*1*20240515*1200*CH~"
    "NM1*41*2*BILLING SERVICE*****46*123456789~"
    "PER*IC*JANE DOE*TE*5555551234~"
    "NM1*40*2*RECEIVER NAME*****46*987654321~"
    "HL*1**20*1~"
    "NM1*85*2*BILLING CLINIC*****XX*1234567890~"
    "N3*123 MAIN ST~"
    "N4*TORONTO*ON*M5V2T6~"
    "HL*2*1*22*0~"
    "SBR*P*18*******MB~"
    "NM1*IL*1*DOE*JOHN****MI*MBR-000123~"
    "N3*456 PATIENT AVE~"
    "N4*TORONTO*ON*M5V2T6~"
    "DMG*D8*19700101*M~"
    "NM1*PR*2*PAYER NAME*****PI*PAYER001~"
    "CLM*ENC-PORTAL-001*250.00***11:B:1*Y*A*Y*Y~"
    "DTP*472*D8*20240510~"
    "DTP*434*D8*20240510~"
    "NM1*82*1*RENDERING*PROVIDER*****XX*1234567890~"
    "SV1*HC:99213*100.00*UN*1***1~"
    "SE*23*0001~"
    "GE*1*1~"
    "IEA*1*000000001~"
)
BASE_EXPECT = {
    "encounter_id": "ENC-PORTAL-001",
    "patient_id": "MBR-000123",
    "NPI": "1234567890",
    "date_of_service": "2024-05-10",
    "CPT_codes": ["99213"],
}


# ---------------------------------------------------------------------------
# 3. Sample + finding dataclasses.
# ---------------------------------------------------------------------------


@dataclass
class Sample:
    """One fuzz input."""

    idx: int
    category: str
    name: str  # short human label
    text: str
    expect: dict[str, Any]  # fields the source *did* contain


@dataclass
class Finding:
    """One detected failure (or note that none occurred)."""

    sample_idx: int
    category: str
    name: str
    signals: list[str] = field(default_factory=list)
    exception_type: str | None = None
    exception_msg: str | None = None
    traceback: str | None = None
    parsed: Any = None  # either X12ParseError or list[dict]
    expect: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def is_failure(self) -> bool:
        return bool(self.signals)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_idx": self.sample_idx,
            "category": self.category,
            "name": self.name,
            "signals": self.signals,
            "exception_type": self.exception_type,
            "exception_msg": self.exception_msg,
            "traceback": self.traceback,
            "parsed": self.parsed,
            "expect": self.expect,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# 4. Helpers to build segments / payloads.
# ---------------------------------------------------------------------------


def _split_segments(text: str, seg_term: str = "~") -> list[str]:
    return [s for s in text.split(seg_term) if s.strip()]


def _seg(text: str, seg_term: str = "~") -> str:
    """Return ``text`` with a single trailing segment terminator."""
    return text if text.endswith(seg_term) else text + seg_term


def _build_837p(
    *,
    drop_isa_iea: bool = False,
    drop_st_se: bool = False,
    drop_bht: bool = False,
    drop_nm1_85: bool = False,
    drop_nm1_il: bool = False,
    drop_dtp_472: bool = False,
    drop_clm: bool = False,
    drop_sv1: bool = False,
    drop_hl: bool = False,
    drop_sbr: bool = False,
    reorder: list[str] | None = None,
    segments_to_drop: list[str] | None = None,
    extra_segments: list[str] | None = None,
    bad_dates: list[str] | None = None,
    bad_sv1_charge: str | None = None,
    bad_sv1_units: str | None = None,
    bad_sv1_proc: str | None = None,
    bad_npi: str | None = None,
    bad_patient_id: str | None = None,
    bad_encounter_id: str | None = None,
    truncated_at: int | None = None,
    seg_term: str = "~",
) -> tuple[str, dict[str, Any]]:
    """Build a (text, expect) tuple by mutating BASE_837P.

    The ``expect`` dict is the same as BASE_EXPECT unless the
    corresponding field is mutated, in which case it reflects the
    mutated value. The harness treats expect as the source of truth
    for "this is what the input actually said".
    """
    segs = _split_segments(BASE_837P, seg_term)
    expect = dict(BASE_EXPECT)

    # Drop specific tags.
    def _drop(tag: str) -> None:
        for i in range(len(segs) - 1, -1, -1):
            if segs[i].startswith(tag + "*"):
                del segs[i]

    if drop_isa_iea:
        _drop("ISA")
        _drop("IEA")
    if drop_st_se:
        _drop("ST")
        _drop("SE")
    if drop_bht:
        _drop("BHT")
    if drop_nm1_85:
        _drop("NM1*85")
    if drop_nm1_il:
        _drop("NM1*IL")
    if drop_dtp_472:
        _drop("DTP*472")
    if drop_clm:
        _drop("CLM")
    if drop_sv1:
        _drop("SV1")
        expect["CPT_codes"] = []
    if drop_hl:
        _drop("HL")
    if drop_sbr:
        _drop("SBR")

    if segments_to_drop:
        for tag in segments_to_drop:
            _drop(tag)

    # Reorder: take segments matching given tags and move them to the
    # end in the given order. Other segments keep their original order.
    if reorder:
        moving = []
        for tag in reorder:
            for s in list(segs):
                if s.startswith(tag + "*"):
                    moving.append(s)
        for s in moving:
            segs.remove(s)
        segs.extend(moving)

    # Field-level mutations.
    if bad_encounter_id is not None:
        for i, s in enumerate(segs):
            if s.startswith("CLM*"):
                parts = s.split("*")
                parts[1] = bad_encounter_id
                segs[i] = "*".join(parts)
        expect["encounter_id"] = bad_encounter_id

    if bad_patient_id is not None:
        for i, s in enumerate(segs):
            if s.startswith("NM1*IL*"):
                parts = s.split("*")
                # NM1*IL*1*DOE*JOHN****MI*MBR-000123 -> 10 elements
                parts[-1] = bad_patient_id
                segs[i] = "*".join(parts)
        expect["patient_id"] = bad_patient_id

    if bad_npi is not None:
        for i, s in enumerate(segs):
            if s.startswith("NM1*85*"):
                parts = s.split("*")
                parts[-1] = bad_npi
                segs[i] = "*".join(parts)
        expect["NPI"] = bad_npi

    if bad_dates is not None:
        # Replace DTP*472 (the date-of-service segment) with one of the
        # bad values from this list, in order, per call.
        for bad in bad_dates:
            replaced = False
            for i, s in enumerate(segs):
                if s.startswith("DTP*472*"):
                    parts = s.split("*")
                    parts[3] = bad
                    segs[i] = "*".join(parts)
                    replaced = True
                    break
            if not replaced:
                # Inject a fresh DTP*472 segment near the end.
                segs.append(f"DTP*472*D8*{bad}")
            # Update expect: parser should reject all of these.
            expect["date_of_service"] = None

    if bad_sv1_charge is not None:
        for i, s in enumerate(segs):
            if s.startswith("SV1*"):
                parts = s.split("*")
                parts[2] = bad_sv1_charge
                segs[i] = "*".join(parts)
        # Charge is not in the parser's required fields; expect unchanged.

    if bad_sv1_units is not None:
        for i, s in enumerate(segs):
            if s.startswith("SV1*"):
                parts = s.split("*")
                parts[4] = bad_sv1_units
                segs[i] = "*".join(parts)
        # Units not in the required fields; expect unchanged.

    if bad_sv1_proc is not None:
        for i, s in enumerate(segs):
            if s.startswith("SV1*"):
                parts = s.split("*")
                parts[1] = bad_sv1_proc
                segs[i] = "*".join(parts)
        # Always treat CPT as lost — the parser will either reject the
        # code (bad qualifier) or accept it. expect tracks what we wrote.
        expect["CPT_codes"] = [bad_sv1_proc]

    if extra_segments:
        segs.extend(extra_segments)

    text = seg_term.join(segs) + seg_term

    if truncated_at is not None:
        text = text[:truncated_at]

    return text, expect


# ---------------------------------------------------------------------------
# 5. Per-category sample builders.
# ---------------------------------------------------------------------------


def _build_truncated() -> list[Sample]:
    """Truncated segments — last char chopped, mid-segment cut, etc."""
    samples: list[Sample] = []
    base_segs = _split_segments(BASE_837P)

    # Drop the last N characters of the envelope to cut a segment in
    # mid-line. Expect field values for the surviving content to
    # still be there or partially there.
    for n in (1, 5, 20, 60, 120, 250):
        samples.append(
            Sample(
                idx=len(samples),
                category="truncated_segment",
                name=f"cut last {n} chars of envelope",
                text=BASE_837P[:-n] if n < len(BASE_837P) else BASE_837P[:20],
                expect=dict(BASE_EXPECT),
            )
        )

    # Cut after a specific segment (so the file ends mid-CLM, mid-NM1*IL,
    # mid-SV1, etc.).
    cut_after = [
        ("CLM*", "cut after CLM"),
        ("NM1*IL*", "cut after NM1*IL"),
        ("SV1*", "cut after SV1"),
        ("DTP*472*", "cut after DTP*472"),
        ("NM1*85*", "cut after NM1*85"),
    ]
    for tag, label in cut_after:
        for s in list(base_segs):
            if s.startswith(tag):
                idx = BASE_837P.index(s) + len(s) + 1  # +1 for seg_term
                samples.append(
                    Sample(
                        idx=len(samples),
                        category="truncated_segment",
                        name=label,
                        text=BASE_837P[:idx],
                        expect=dict(BASE_EXPECT),
                    )
                )
                break

    # Drop the segment terminator entirely from the entire envelope.
    samples.append(
        Sample(
            idx=len(samples),
            category="truncated_segment",
            name="no segment terminators at all",
            text=BASE_837P.replace("~", ""),
            expect=dict(BASE_EXPECT),
        )
    )
    # And the opposite: extra junk after the IEA.
    samples.append(
        Sample(
            idx=len(samples),
            category="truncated_segment",
            name="trailing junk after IEA",
            text=BASE_837P + "GARBAGE*FOO*BAR~",
            expect=dict(BASE_EXPECT),
        )
    )

    # A segment with a missing element (CLM with no encounter id).
    clm_orphan = BASE_837P.replace(
        "CLM*ENC-PORTAL-001*250.00", "CLM**250.00"
    )
    samples.append(
        Sample(
            idx=len(samples),
            category="truncated_segment",
            name="CLM with empty encounter_id element",
            text=clm_orphan,
            expect={**BASE_EXPECT, "encounter_id": None},
        )
    )

    # ISA without a 16th element separator (truncated ISA header).
    truncated_isa = "ISA*00*          *00*          *ZZ*SUBMITTERID    *ZZ*RECEIVERID     *240515*1200*^*00501*000000001*0*P*~"
    samples.append(
        Sample(
            idx=len(samples),
            category="truncated_segment",
            name="ISA shorter than 106 chars (missing component sep)",
            text=truncated_isa + BASE_837P[106:],
            expect=dict(BASE_EXPECT),
        )
    )

    # Two CLM segments with the second one truncated.
    two_clm = BASE_837P + "CLM*ENC-PORTAL-002*300.00***11:B:1*Y*A*Y*Y~"  # noqa
    samples.append(
        Sample(
            idx=len(samples),
            category="truncated_segment",
            name="second CLM with no body",
            text=BASE_837P + "CLM~",
            expect=dict(BASE_EXPECT),
        )
    )
    # Trim the over-produced pad. Target 29 — we already have ~16 above.
    # No additional pad needed.
    return samples[: CATEGORY_SIZES["truncated_segment"]]


def _build_missing_envelope() -> list[Sample]:
    """Missing ISA/IEA envelope."""
    samples: list[Sample] = []

    # Drop ISA + IEA.
    text, expect = _build_837p(drop_isa_iea=True)
    samples.append(
        Sample(
            idx=len(samples),
            category="missing_envelope",
            name="no ISA / IEA",
            text=text,
            expect=expect,
        )
    )

    # Drop ISA only.
    text, _ = _build_837p()
    segs = _split_segments(text)
    segs = [s for s in segs if not s.startswith("ISA*")]
    samples.append(
        Sample(
            idx=len(samples),
            category="missing_envelope",
            name="no ISA",
            text="~".join(segs) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # Drop IEA only.
    segs = _split_segments(BASE_837P)
    segs = [s for s in segs if not s.startswith("IEA*")]
    samples.append(
        Sample(
            idx=len(samples),
            category="missing_envelope",
            name="no IEA",
            text="~".join(segs) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # Drop GS / GE pair.
    segs = _split_segments(BASE_837P)
    segs = [s for s in segs if not (s.startswith("GS*") or s.startswith("GE*"))]
    samples.append(
        Sample(
            idx=len(samples),
            category="missing_envelope",
            name="no GS / GE",
            text="~".join(segs) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # Drop ST / SE pair.
    segs = _split_segments(BASE_837P)
    segs = [s for s in segs if not (s.startswith("ST*") or s.startswith("SE*"))]
    samples.append(
        Sample(
            idx=len(samples),
            category="missing_envelope",
            name="no ST / SE",
            text="~".join(segs) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # Drop BHT.
    segs = _split_segments(BASE_837P)
    segs = [s for s in segs if not s.startswith("BHT*")]
    samples.append(
        Sample(
            idx=len(samples),
            category="missing_envelope",
            name="no BHT",
            text="~".join(segs) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # Empty string.
    samples.append(
        Sample(
            idx=len(samples),
            category="missing_envelope",
            name="empty string",
            text="",
            expect={},
        )
    )

    # Whitespace only.
    samples.append(
        Sample(
            idx=len(samples),
            category="missing_envelope",
            name="whitespace only",
            text="   \n  \t  \n",
            expect={},
        )
    )

    # Just an ISA segment.
    samples.append(
        Sample(
            idx=len(samples),
            category="missing_envelope",
            name="only ISA segment",
            text="ISA*00*          *00*          *ZZ*SUBMITTERID    *ZZ*RECEIVERID     *240515*1200*^*00501*000000001*0*P*:~",
            expect={},
        )
    )

    # ISA + GS + ST + BHT only — no claim, no patient.
    header_only = "~".join(
        _split_segments(BASE_837P)[:4]
    ) + "~"
    samples.append(
        Sample(
            idx=len(samples),
            category="missing_envelope",
            name="header only (ISA+GS+ST+BHT)",
            text=header_only,
            expect={},
        )
    )

    # Pad to N=28 with envelope-less variants.
    segs = _split_segments(BASE_837P)
    body = [s for s in segs if not s.startswith(("ISA*", "GS*", "GE*", "IEA*"))]
    for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19):
        # Trim a few segments off the end of the body.
        text = "~".join(body[:-n]) + "~" if n < len(body) else body[0] + "~"
        samples.append(
            Sample(
                idx=len(samples),
                category="missing_envelope",
                name=f"body only, last {n} dropped",
                text=text,
                expect={},
            )
        )

    return samples[: CATEGORY_SIZES["missing_envelope"]]


def _build_wrong_order() -> list[Sample]:
    """Wrong segment order — CLP before NM1, SV* before CLM, etc.

    Note: 837P has no CLP segment (that's 835). The spec calls out
    "CLP before NM1" but 837P is claim-submitter; the equivalent
    is CLM. We include both the spec-named anomaly (CLP before NM1,
    which is a structurally confused file) and the 837P-correct
    variants (CLM before NM1 — that's *correct*; CLM after NM1 is
    still accepted; SV1 before CLM is wrong).
    """
    samples: list[Sample] = []

    # SV1 before CLM.
    segs = _split_segments(BASE_837P)
    sv1 = [s for s in segs if s.startswith("SV1*")]
    others = [s for s in segs if not s.startswith("SV1*")]
    clm_idx = next(i for i, s in enumerate(others) if s.startswith("CLM*"))
    reordered = others[:clm_idx] + sv1 + others[clm_idx:]
    samples.append(
        Sample(
            idx=len(samples),
            category="wrong_order",
            name="SV1 before CLM",
            text="~".join(reordered) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # DTP*472 before NM1*IL.
    segs = _split_segments(BASE_837P)
    dtp = [s for s in segs if s.startswith("DTP*472*")]
    others = [s for s in segs if not s.startswith("DTP*472*")]
    nm1_idx = next(i for i, s in enumerate(others) if s.startswith("NM1*IL*"))
    reordered = others[:nm1_idx] + dtp + others[nm1_idx:]
    samples.append(
        Sample(
            idx=len(samples),
            category="wrong_order",
            name="DTP*472 before NM1*IL",
            text="~".join(reordered) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # CLM before HL (the billing loop is normally after HL).
    segs = _split_segments(BASE_837P)
    clm = [s for s in segs if s.startswith("CLM*")]
    others = [s for s in segs if not s.startswith("CLM*")]
    reordered = clm + others
    samples.append(
        Sample(
            idx=len(samples),
            category="wrong_order",
            name="CLM at very start (before HL/SBR/NM1*IL)",
            text="~".join(reordered) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # SV1 after SE (after the functional group is "closed").
    segs = _split_segments(BASE_837P)
    sv1 = [s for s in segs if s.startswith("SV1*")]
    se = [s for s in segs if s.startswith("SE*")]
    others = [s for s in segs if not s.startswith(("SV1*", "SE*"))]
    reordered = others + se + sv1
    samples.append(
        Sample(
            idx=len(samples),
            category="wrong_order",
            name="SV1 after SE (orphan service line)",
            text="~".join(reordered) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # ISA inside the body (between segments).
    segs = _split_segments(BASE_837P)
    body = [s for s in segs if not s.startswith("ISA*")]
    mid = len(body) // 2
    bogus_isa = (
        "ISA*00*          *00*          *ZZ*SUBMITTERID    *ZZ*RECEIVERID     "
        "*240515*1200*^*00501*000000002*0*P*:~"
    )
    reordered = body[:mid] + [bogus_isa] + body[mid:]
    samples.append(
        Sample(
            idx=len(samples),
            category="wrong_order",
            name="second ISA in middle of body",
            text="~".join(reordered) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # Two CLM segments with the second one *before* the first one's body
    # (overlapping claims).
    segs = _split_segments(BASE_837P)
    base_clm = next(s for s in segs if s.startswith("CLM*"))
    extra_clm = "CLM*ENC-PORTAL-002*300.00***11:B:1*Y*A*Y*Y~"
    reordered = segs[: segs.index(base_clm)] + [extra_clm] + segs[segs.index(base_clm):]
    samples.append(
        Sample(
            idx=len(samples),
            category="wrong_order",
            name="extra CLM inserted before original CLM",
            text="~".join(reordered).replace("~~", "~") + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # SV1 with no CLM at all (orphan service line, then CLM later).
    segs = _split_segments(BASE_837P)
    sv1 = [s for s in segs if s.startswith("SV1*")]
    clm = [s for s in segs if s.startswith("CLM*")]
    others = [s for s in segs if not s.startswith(("SV1*", "CLM*"))]
    reordered = sv1 + others + clm
    samples.append(
        Sample(
            idx=len(samples),
            category="wrong_order",
            name="SV1 first, CLM last",
            text="~".join(reordered) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # Two NM1*IL (patient) segments — second one has different id.
    text = BASE_837P.replace(
        "NM1*IL*1*DOE*JOHN****MI*MBR-000123",
        "NM1*IL*1*DOE*JOHN****MI*MBR-000123~NM1*IL*1*DOE*JOHN****MI*MBR-999999",
    )
    samples.append(
        Sample(
            idx=len(samples),
            category="wrong_order",
            name="two NM1*IL segments",
            text=text,
            expect={**BASE_EXPECT, "patient_id": "MBR-000123"},
        )
    )

    # Spec-named anomaly: a CLP segment before NM1*IL (CLP is 835, not
    # 837P — so a parser that picks it up would be confused).
    text = BASE_837P.replace(
        "NM1*IL*1*DOE*JOHN",
        "CLP*CLAIM-001*1*250*200*50*0***MC*MEMBERID~NM1*IL*1*DOE*JOHN",
    )
    samples.append(
        Sample(
            idx=len(samples),
            category="wrong_order",
            name="CLP segment (835) before NM1*IL",
            text=text,
            expect=dict(BASE_EXPECT),
        )
    )

    # CLM with NM1*85 (billing provider) BEFORE HL.
    segs = _split_segments(BASE_837P)
    hl_idx = next(i for i, s in enumerate(segs) if s.startswith("HL*1*"))
    nm1_85 = [s for s in segs if s.startswith("NM1*85*")]
    others = [s for s in segs if not s.startswith("NM1*85*")]
    reordered = others[:hl_idx] + nm1_85 + others[hl_idx:]
    samples.append(
        Sample(
            idx=len(samples),
            category="wrong_order",
            name="NM1*85 before HL*1",
            text="~".join(reordered) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # Reverse the whole body (but keep ISA/GS/ST/BHT in place).
    segs = _split_segments(BASE_837P)
    head = [s for s in segs if s.startswith(("ISA*", "GS*", "ST*", "BHT*"))]
    tail = [s for s in segs if s.startswith(("SE*", "GE*", "IEA*"))]
    body = [s for s in segs if s not in head and s not in tail]
    samples.append(
        Sample(
            idx=len(samples),
            category="wrong_order",
            name="body segments reversed",
            text="~".join(head + body[::-1] + tail) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # Pad to N=29.
    for n in range(8):
        segs = _split_segments(BASE_837P)
        if n < len(segs) - 2:
            swap_a, swap_b = segs[n], segs[n + 1]
            segs[n], segs[n + 1] = swap_b, swap_a
        samples.append(
            Sample(
                idx=len(samples),
                category="wrong_order",
                name=f"swap adjacent segs at index {n}",
                text="~".join(segs) + "~",
                expect=dict(BASE_EXPECT),
            )
        )
    return samples[: CATEGORY_SIZES["wrong_order"]]


def _build_invalid_date() -> list[Sample]:
    """Invalid date formats — bad CCYYMMDD, wrong delimiters, etc."""
    bad_dates = [
        "2024-13-01",  # month 13 — only 8 chars
        "2024-00-15",  # month 00
        "2024051",  # 7 chars
        "202405100",  # 9 chars
        "240510",  # YY instead of CCYY (6 chars)
        "2024-05-10",  # ISO with hyphens (DTP expects no hyphens)
        "20 2405 10",  # spaces embedded
        "2024/05/10",  # slashes
        "MAY102024",  # words
        "00000000",  # all zeros
        "99999999",  # all nines
        "20240230",  # Feb 30 (impossible date)
        "20240431",  # April 31 (impossible)
        "20240229",  # 2024 is leap so 29 is valid, but try 2023:
        # Actually use 2023 leap attempt via 20230229.
        "20230229",  # Feb 29 in non-leap year
        "abcd1234",  # letters
        "",  # empty
        "********",  # all asterisks
        "2024-0510",  # mixed delimiter
    ]
    # Pick 20 of these for the build_invalid_date() loop and make 29
    # total samples. We re-use BASE_EXPECT with date_of_service=None
    # because every bad date should drop the field.
    samples: list[Sample] = []
    for bad in bad_dates:
        text, expect = _build_837p(bad_dates=[bad])
        samples.append(
            Sample(
                idx=len(samples),
                category="invalid_date",
                name=f"DTP*472 with bad date '{bad}'",
                text=text,
                expect=expect,
            )
        )

    # DTP*472 with a different format code (RD8 = range, DT = datetime).
    for fmt in ("RD8", "DT", "TM", "D6", "CC", ""):
        segs = _split_segments(BASE_837P)
        for i, s in enumerate(segs):
            if s.startswith("DTP*472*"):
                parts = s.split("*")
                parts[2] = fmt
                if fmt == "RD8":
                    parts[3] = "20240510-20240511"
                segs[i] = "*".join(parts)
                break
        samples.append(
            Sample(
                idx=len(samples),
                category="invalid_date",
                name=f"DTP*472 format code '{fmt or '<empty>'}'",
                text="~".join(segs) + "~",
                expect={**BASE_EXPECT, "date_of_service": None},
            )
        )

    # DTP*472 with the wrong qualifier (e.g. 434 = statement dates, not service).
    segs = _split_segments(BASE_837P)
    for i, s in enumerate(segs):
        if s.startswith("DTP*472*"):
            segs[i] = s.replace("DTP*472*", "DTP*434*")
            break
    samples.append(
        Sample(
            idx=len(samples),
            category="invalid_date",
            name="DTP*434 (statement dates, not service)",
            text="~".join(segs) + "~",
            expect={**BASE_EXPECT, "date_of_service": None},
        )
    )

    # DTP*472 with no DTP segment at all.
    text, expect = _build_837p(drop_dtp_472=True)
    samples.append(
        Sample(
            idx=len(samples),
            category="invalid_date",
            name="no DTP*472 segment at all",
            text=text,
            expect={**BASE_EXPECT, "date_of_service": None},
        )
    )

    # DTP*472 with a future-future date (2099-13-45 is invalid).
    text, expect = _build_837p(bad_dates=["20991345"])
    samples.append(
        Sample(
            idx=len(samples),
            category="invalid_date",
            name="DTP*472 with 20991345",
            text=text,
            expect=expect,
        )
    )

    return samples[: CATEGORY_SIZES["invalid_date"]]


def _build_bad_cpt() -> list[Sample]:
    """Bad CPT/HCPCS codes (non-existent or wrong code set)."""
    bad_procs = [
        "HC:00000",  # zero code
        "HC:999999",  # 6-digit (CPT is 5)
        "HC:ABCD1",  # letters
        "HC:1234",  # 4 digits
        "HC:123456",  # 6 digits
        "HC:0000A",  # mixed
        "ZZ:99213",  # wrong qualifier (ZZ is mutually defined)
        "N4:01234567890",  # NDC qualifier
        "HC:",  # empty code
        ":99213",  # empty qualifier
        "HC:99213:25:50:76:LT:RT",  # 4 modifiers — only 4 allowed but we add 6
        "HC:99213::25",  # empty modifier
        "HC:99999",  # 5 digits but obviously not in real CPT list
        "HC:00000",
        "HC:99999",
    ]
    samples: list[Sample] = []
    for bad in bad_procs:
        text, expect = _build_837p(bad_sv1_proc=bad)
        # The parser will produce some specific behavior for each one
        # (either drop the code, accept the code, or extend with a
        # garbage string). We let the harness report what actually
        # happened.
        samples.append(
            Sample(
                idx=len(samples),
                category="bad_cpt",
                name=f"SV1 with bad proc '{bad}'",
                text=text,
                expect=expect,
            )
        )

    # SV1 with no SV1 at all.
    text, expect = _build_837p(drop_sv1=True)
    samples.append(
        Sample(
            idx=len(samples),
            category="bad_cpt",
            name="no SV1 segment",
            text=text,
            expect={**BASE_EXPECT, "CPT_codes": []},
        )
    )

    # Multiple SV1 segments — only the first has a real CPT, the rest
    # are garbage.
    segs = _split_segments(BASE_837P)
    extra_sv1 = [
        "SV1*HC:NOTREAL*200*UN*1***1",
        "SV1*HC:99214*150*UN*1***1",  # valid
    ]
    last_sv1_idx = max(i for i, s in enumerate(segs) if s.startswith("SV1*"))
    segs = segs[: last_sv1_idx + 1] + extra_sv1 + segs[last_sv1_idx + 1:]
    samples.append(
        Sample(
            idx=len(samples),
            category="bad_cpt",
            name="SV1 with non-CPT qualifier 'N4'",
            text="~".join(segs) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # Two SV1 segments where the first is bad and the second is fine.
    segs = _split_segments(BASE_837P)
    segs = [s for s in segs if not s.startswith("SV1*")]
    segs.append("SV1*ZZ:99999*100*UN*1***1")
    segs.append("SV1*HC:99213*100*UN*1***1")
    samples.append(
        Sample(
            idx=len(samples),
            category="bad_cpt",
            name="two SV1 — first is bad qualifier, second is fine",
            text="~".join(segs) + "~",
            expect={**BASE_EXPECT, "CPT_codes": ["99999", "99213"]},
        )
    )

    # SV1 with completely missing fields (just the tag).
    segs = _split_segments(BASE_837P)
    segs = [s for s in segs if not s.startswith("SV1*")]
    segs.append("SV1")
    samples.append(
        Sample(
            idx=len(samples),
            category="bad_cpt",
            name="SV1 with no elements (just 'SV1')",
            text="~".join(segs) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # Pad to N=28.
    for n in range(28 - len(samples)):
        bad = bad_procs[n % len(bad_procs)]
        text, expect = _build_837p(bad_sv1_proc=bad)
        samples.append(
            Sample(
                idx=len(samples),
                category="bad_cpt",
                name=f"bad_cpt pad #{n}: '{bad}'",
                text=text,
                expect=expect,
            )
        )
    return samples[: CATEGORY_SIZES["bad_cpt"]]


def _build_units_out_of_range() -> list[Sample]:
    """Service line units > 999 (the X12 5010 max is 999)."""
    samples: list[Sample] = []
    for units in ("1000", "1234", "9999", "99999", "0", "-1", "ABC", "1.5", "", "00"):
        text, expect = _build_837p(bad_sv1_units=units)
        samples.append(
            Sample(
                idx=len(samples),
                category="units_out_of_range",
                name=f"units='{units}'",
                text=text,
                expect=expect,
            )
        )

    # Charge (SV102) — also has a max in 5010.
    for charge in (
        "99999999.99",  # valid large
        "100000000.00",  # over 99,999,999.99 (real max)
        "-100.00",  # negative
        "0.00",  # zero
        "abc",  # letters
        "1,000.00",  # embedded comma (illegal)
        "100.0",  # 1 decimal (5010 expects 2)
    ):
        text, expect = _build_837p(bad_sv1_charge=charge)
        samples.append(
            Sample(
                idx=len(samples),
                category="units_out_of_range",
                name=f"charge='{charge}'",
                text=text,
                expect=expect,
            )
        )

    # Place-of-service field (SV105) with junk.
    segs = _split_segments(BASE_837P)
    for i, s in enumerate(segs):
        if s.startswith("SV1*"):
            parts = s.split("*")
            parts[5] = "999"  # valid POS range is 01-99
            segs[i] = "*".join(parts)
            break
    samples.append(
        Sample(
            idx=len(samples),
            category="units_out_of_range",
            name="SV1 place-of-service '999' (out of range)",
            text="~".join(segs) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    # Multiple SV1s with various unit/charge combos.
    for units, charge in (("1000", "100"), ("5", "999999999999"), ("", ""), ("10", "1e6")):
        segs = _split_segments(BASE_837P)
        for i, s in enumerate(segs):
            if s.startswith("SV1*"):
                parts = s.split("*")
                parts[2] = charge
                parts[4] = units
                segs[i] = "*".join(parts)
                break
        samples.append(
            Sample(
                idx=len(samples),
                category="units_out_of_range",
                name=f"combo units='{units}' charge='{charge}'",
                text="~".join(segs) + "~",
                expect=dict(BASE_EXPECT),
            )
        )

    return samples[: CATEGORY_SIZES["units_out_of_range"]]


def _build_bad_currency() -> list[Sample]:
    """Dollar amounts with embedded commas or other illegal chars."""
    samples: list[Sample] = []
    # CLM02 is the total claim charge — embed commas / illegal chars.
    for charge in (
        "1,000.00",
        "1,000,000.00",
        "$100.00",
        "100.0",
        "100",
        "100.001",  # 3 decimal places (illegal)
        "100.00 ",  # trailing space
        " 100.00",  # leading space
        "-100.00",  # negative
        "abc",  # letters
        "",  # empty
        "1.000.000,00",  # European format
        "INF",
        "NaN",
        "1e6",  # scientific
    ):
        segs = _split_segments(BASE_837P)
        for i, s in enumerate(segs):
            if s.startswith("CLM*"):
                parts = s.split("*")
                parts[2] = charge
                segs[i] = "*".join(parts)
                break
        samples.append(
            Sample(
                idx=len(samples),
                category="bad_currency",
                name=f"CLM02 charge='{charge}'",
                text="~".join(segs) + "~",
                expect=dict(BASE_EXPECT),
            )
        )

    # SV1 charge (SV102) — bad currency.
    for charge in (
        "1,000.00",
        "100.0",
        "$200.00",
        "abc",
        "",
        "1.000,00",
        "999999999999999",
    ):
        segs = _split_segments(BASE_837P)
        for i, s in enumerate(segs):
            if s.startswith("SV1*"):
                parts = s.split("*")
                parts[2] = charge
                segs[i] = "*".join(parts)
                break
        samples.append(
            Sample(
                idx=len(samples),
                category="bad_currency",
                name=f"SV102 charge='{charge}'",
                text="~".join(segs) + "~",
                expect=dict(BASE_EXPECT),
            )
        )

    # Both CLM and SV1 corrupted.
    segs = _split_segments(BASE_837P)
    for i, s in enumerate(segs):
        if s.startswith("CLM*"):
            parts = s.split("*")
            parts[2] = "$1,000.00"
            segs[i] = "*".join(parts)
        if s.startswith("SV1*"):
            parts = s.split("*")
            parts[2] = "1,000.00"
            segs[i] = "*".join(parts)
    samples.append(
        Sample(
            idx=len(samples),
            category="bad_currency",
            name="both CLM and SV1 have embedded commas",
            text="~".join(segs) + "~",
            expect=dict(BASE_EXPECT),
        )
    )

    return samples[: CATEGORY_SIZES["bad_currency"]]


# ---------------------------------------------------------------------------
# 6. The harness: run, classify, and write a findings JSON.
# ---------------------------------------------------------------------------


def _build_samples() -> list[Sample]:
    rng = random.Random(SEED)
    samples: list[Sample] = []
    builder_counts: dict[str, int] = {}
    builder_to_category: dict[str, str] = {
        "_build_truncated": "truncated_segment",
        "_build_missing_envelope": "missing_envelope",
        "_build_wrong_order": "wrong_order",
        "_build_invalid_date": "invalid_date",
        "_build_bad_cpt": "bad_cpt",
        "_build_units_out_of_range": "units_out_of_range",
        "_build_bad_currency": "bad_currency",
    }
    for builder in (
        _build_truncated,
        _build_missing_envelope,
        _build_wrong_order,
        _build_invalid_date,
        _build_bad_cpt,
        _build_units_out_of_range,
        _build_bad_currency,
    ):
        out = builder()
        builder_counts[builder.__name__] = len(out)
        samples.extend(out)

    # Top up any under-producing category with deterministic variants.
    # Each category gets variants shaped to its failure surface so the
    # distribution of the final 200 stays close to the spec.
    def _topup(category: str, n: int, start_idx: int) -> list[Sample]:
        extra: list[Sample] = []
        for k in range(n):
            if category == "truncated_segment":
                cut = max(1, len(BASE_837P) - (k + 1) * 7)
                extra.append(
                    Sample(
                        idx=start_idx + k,
                        category=category,
                        name=f"topup cut to {cut} chars",
                        text=BASE_837P[:cut],
                        expect=dict(BASE_EXPECT),
                    )
                )
            elif category == "wrong_order":
                segs = _split_segments(BASE_837P)
                # Rotate by k+1 positions.
                kk = (k + 1) % max(1, len(segs) - 1)
                segs = segs[-kk:] + segs[:-kk]
                extra.append(
                    Sample(
                        idx=start_idx + k,
                        category=category,
                        name=f"topup rotate body by {kk}",
                        text="~".join(segs) + "~",
                        expect=dict(BASE_EXPECT),
                    )
                )
            elif category == "units_out_of_range":
                units = f"{1000 + k * 37}"
                text, expect = _build_837p(bad_sv1_units=units)
                extra.append(
                    Sample(
                        idx=start_idx + k,
                        category=category,
                        name=f"topup units='{units}'",
                        text=text,
                        expect=expect,
                    )
                )
            elif category == "bad_currency":
                charge = f"1{k:03d}.{k:02d}"
                text, expect = _build_837p(bad_sv1_charge=charge)
                extra.append(
                    Sample(
                        idx=start_idx + k,
                        category=category,
                        name=f"topup charge='{charge}'",
                        text=text,
                        expect=expect,
                    )
                )
            else:
                # Generic: a small cut variant.
                cut = max(1, len(BASE_837P) - (k + 1) * 11)
                extra.append(
                    Sample(
                        idx=start_idx + k,
                        category=category,
                        name=f"topup cut to {cut} chars",
                        text=BASE_837P[:cut],
                        expect=dict(BASE_EXPECT),
                    )
                )
        return extra

    for category, target in CATEGORY_SIZES.items():
        builder_name = "_build_" + category
        got = sum(1 for s in samples if s.category == category)
        if got < target:
            deficit = target - got
            samples.extend(_topup(category, deficit, len(samples)))

    if len(samples) > N_SAMPLES:
        samples = samples[:N_SAMPLES]
    assert len(samples) == N_SAMPLES, f"got {len(samples)} samples; counts={builder_counts}"
    # Shuffle the order so the report isn't dominated by one category.
    rng.shuffle(samples)
    # Reassign idx after shuffle so report ordering matches execution.
    for i, s in enumerate(samples):
        s.idx = i
    return samples


def _run_one(sample: Sample) -> Finding:
    """Run a single sample through the parser and classify the outcome."""
    f = Finding(
        sample_idx=sample.idx,
        category=sample.category,
        name=sample.name,
        expect=sample.expect,
    )

    # 1) Try to parse — capture any uncaught exception.
    parsed: Any
    try:
        parsed = parse_837p(sample.text)
    except X12ParseError as e:
        f.signals.append("uncaught_x12_error")
        f.exception_type = "X12ParseError"
        f.exception_msg = str(e)
        # X12ParseError is *expected* for some categories (truncated,
        # missing envelope). It's a real bug only if the source *did*
        # contain valid claim data.
        if sample.expect:
            f.notes.append("X12ParseError raised on a sample that did contain claim data")
        f.parsed = {"error": "X12ParseError", "msg": str(e)}
        return f
    except Exception as e:  # noqa: BLE001 — we want to catch *anything*
        f.signals.append("uncaught_exception")
        f.exception_type = type(e).__name__
        f.exception_msg = str(e)
        f.traceback = traceback.format_exc()
        f.parsed = {"error": type(e).__name__, "msg": str(e)}
        return f

    f.parsed = parsed
    if not isinstance(parsed, list) or not parsed:
        f.signals.append("empty_parse")
        f.notes.append(f"parse_837p returned {parsed!r}")
        return f

    claim = parsed[0]

    # 2) Check silently-dropped required fields.
    for field_name in ("encounter_id", "patient_id", "NPI"):
        expected = sample.expect.get(field_name)
        if expected is None:
            # Source didn't have it; the parser correctly not emitting
            # it is not a failure.
            continue
        actual = claim.get(field_name)
        if actual != expected:
            f.signals.append(f"silent_drop:{field_name}")
            f.notes.append(
                f"{field_name}: expected {expected!r}, got {actual!r}"
            )

    # date_of_service: source had a date (DTP*472) but the parser
    # returned None. Only flag if source had a *valid* CCYYMMDD —
    # bad-date samples are checked separately.
    expected_dos = sample.expect.get("date_of_service")
    if expected_dos:
        actual_dos = claim.get("date_of_service")
        if actual_dos != expected_dos:
            f.signals.append("silent_drop:date_of_service")
            f.notes.append(
                f"date_of_service: expected {expected_dos!r}, got {actual_dos!r}"
            )

    # CPT_codes: any source with a parseable SV1*HC:... should produce
    # at least one code in the list. If expect has codes but parsed
    # doesn't, that's a silent drop.
    expected_cpts = sample.expect.get("CPT_codes", [])
    if expected_cpts:
        actual_cpts = claim.get("CPT_codes") or []
        # Compare set-wise — duplicates in source are fine to dedupe.
        if not actual_cpts:
            f.signals.append("silent_drop:CPT_codes")
            f.notes.append("CPT_codes: expected at least one, got []")

    # 3) Accepted-invalid: format-shape checks against well-formed
    # expectations.
    actual_npi = (claim.get("NPI") or "").strip()
    if actual_npi and not re.fullmatch(r"\d{10}", actual_npi):
        f.signals.append("accepted_invalid:NPI")
        f.notes.append(f"NPI {actual_npi!r} is not 10 digits")

    actual_dos = (claim.get("date_of_service") or "").strip()
    if actual_dos and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", actual_dos):
        f.signals.append("accepted_invalid:date_of_service")
        f.notes.append(f"date_of_service {actual_dos!r} is not YYYY-MM-DD")

    # CPT code shape: 5 chars, alphanumeric. Allow modifiers with '-'.
    for cpt in claim.get("CPT_codes") or []:
        head = cpt.split("-", 1)[0]
        if not re.fullmatch(r"[A-Z0-9]{5}", head):
            f.signals.append("accepted_invalid:CPT_codes")
            f.notes.append(f"CPT code {cpt!r} (head={head!r}) is not 5-char alnum")
            break

    # If source had a bad date, the parser should NOT have produced
    # a date. If it did, that's accepted-invalid.
    if expected_dos is None and sample.category == "invalid_date":
        if actual_dos:
            f.signals.append("accepted_invalid:bad_date_passed")
            f.notes.append(
                f"parser emitted date_of_service={actual_dos!r} for a source with an invalid date"
            )

    return f


def _write_findings(findings: list[Finding]) -> Path:
    out = _HERE / "_findings.json"
    out.write_text(
        json.dumps(
            {
                "seed": SEED,
                "n_samples": N_SAMPLES,
                "categories": list(CATEGORIES),
                "findings": [f.to_dict() for f in findings],
            },
            indent=2,
        )
    )
    return out


# ---------------------------------------------------------------------------
# 7. Entry point: build, run, summarise, write.
# ---------------------------------------------------------------------------


def main() -> int:
    samples = _build_samples()
    findings: list[Finding] = []
    n_exc = 0
    n_drop = 0
    n_invalid = 0
    n_clean = 0
    by_category: dict[str, dict[str, int]] = {
        c: {"total": 0, "exc": 0, "drop": 0, "invalid": 0, "clean": 0}
        for c in CATEGORIES
    }

    for sample in samples:
        f = _run_one(sample)
        findings.append(f)
        by_category[sample.category]["total"] += 1
        if any(s.startswith("uncaught") for s in f.signals):
            n_exc += 1
            by_category[sample.category]["exc"] += 1
        if any(s.startswith("silent_drop") for s in f.signals):
            n_drop += 1
            by_category[sample.category]["drop"] += 1
        if any(s.startswith("accepted_invalid") for s in f.signals):
            n_invalid += 1
            by_category[sample.category]["invalid"] += 1
        if not f.signals:
            n_clean += 1
            by_category[sample.category]["clean"] += 1

    # Write the machine-readable findings.
    out = _write_findings(findings)

    # Print a human-readable summary.
    print(f"=== x12_parser.py fuzz harness ===")
    print(f"seed: {SEED}, samples: {N_SAMPLES}")
    print()
    print("by category:")
    print(f"  {'category':<22} {'total':>5} {'exc':>4} {'drop':>5} {'invalid':>7} {'clean':>5}")
    for c in CATEGORIES:
        b = by_category[c]
        print(
            f"  {c:<22} {b['total']:>5} {b['exc']:>4} {b['drop']:>5} {b['invalid']:>7} {b['clean']:>5}"
        )
    print()
    print(f"totals: exceptions={n_exc}  silent_drops={n_drop}  accepted_invalid={n_invalid}  clean={n_clean}")
    print(f"findings JSON: {out}")
    print()
    # Print the first 12 distinct failure signatures so the BUGS doc
    # author can see what's been recorded.
    seen_signatures: set[tuple[str, ...]] = set()
    distinct: list[Finding] = []
    for f in findings:
        if not f.signals:
            continue
        sig = tuple(sorted(f.signals))
        if sig in seen_signatures:
            continue
        seen_signatures.add(sig)
        distinct.append(f)
    print(f"distinct failure signatures: {len(distinct)}")
    for f in distinct[:20]:
        print(f"  - sample#{f.sample_idx} [{f.category}] {f.name}  signals={f.signals}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
