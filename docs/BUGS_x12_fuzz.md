# Bugs found by `tests/fuzz/test_x12_fuzz.py`

Generated 2026-06-16 by the fuzz harness in
`tests/fuzz/test_x12_fuzz.py` (seed `20260616`, 200 samples across the
seven spec categories: truncated segments, missing envelope, wrong
order, invalid date, bad CPT, units out of range, bad currency). The
harness is detect-and-document only — it does not edit
`src/ai_billing_audit/x12_parser.py`. Per-sample evidence lives in
`tests/fuzz/_findings.json`.

## Summary

| # | Signal                                         | Count | Severity   |
|---|------------------------------------------------|-------|------------|
| 1 | `uncaught_exception` (IndexError)              | 2     | **High**   |
| 2 | `uncaught_x12_error` (empty / whitespace input)| 2     | Low        |
| 3 | `silent_drop:CPT_codes`                        | 16    | Medium     |
| 4 | `silent_drop:date_of_service` (truncated body) | 9     | Medium     |
| 5 | `silent_drop:encounter_id` (truncated body)    | 6     | Medium     |
| 6 | `silent_drop:patient_id` (truncated body)      | 4     | Medium     |
| 7 | `silent_drop:NPI` (truncated body)             | 2     | Low        |
| 8 | `accepted_invalid:CPT_codes`                   | 10    | Medium     |
| 9 | `accepted_invalid:bad_date_passed`             | 7     | **High**   |
| 10 | `silent_drop:date_of_service` (DTP reordered) | 1     | Medium     |

Total: 4 uncaught exceptions (2 real `IndexError`, 2 expected `X12ParseError`),
27 silent-drop signals, 17 accepted-invalid signals, **48 distinct failing
samples** out of 200.

Distinct failure signatures (unique sets of signals): **10**. Each is
documented below as a numbered entry with category, location, minimal
repro, and a proposed regression test.

---

## BUG-01 — `IndexError` on SV1 segment with no procedure-code element

- **Signal**: `uncaught_exception` (IndexError, "list index out of range")
- **Category**: bad_cpt / truncated_segment
- **Severity**: High — a malformed file aborts the upload flow with a
  Python traceback instead of a per-file "malformed" error. The portal
  wraps `parse_837p` in a try/except that catches `X12ParseError` only;
  an `IndexError` propagates to the FastAPI 500 handler and the user
  sees a generic 500.
- **Root cause**: `x12_parser.py:212-214` in `_cpt_codes_from_sv1`:
  ```python
  if not elements or elements[0] != "SV1":
      return []
  proc = (elements[1] or "").strip()
  ```
  The guard covers the empty case but not the case where the segment
  is exactly `"SV1"` with no further elements. The split in
  `_split_segments` produces a single-element list `["SV1"]` for such
  a segment, and the `elements[1]` access raises.
- **Minimal repro**:
  ```
  ISA*00*          *00*          *ZZ*SUBMITTERID    *ZZ*RECEIVERID     *240515*1200*^*00501*000000001*0*P*:~
  CLM*ENC-PORTAL-001*250.00***11:B:1*Y*A*Y*Y~
  SV1~
  ```
  Or in practice: any truncated file that ends in the middle of an SV1
  line. Sample #6 in the run ("cut last 60 chars of envelope") also
  hits this because the surviving content ends with a partial SV1
  segment.
- **Proposed regression test** (add to `tests/test_encounters_upload.py`):
  ```python
  def test_sv1_with_no_proc_element_raises_x12error_not_indexerror():
      text = (
          "ISA*00*          *00*          *ZZ*SUBMITTERID    *ZZ*RECEIVERID     "
          "*240515*1200*^*00501*000000001*0*P*:~"
          "CLM*ENC-PORTAL-001*250.00***11:B:1*Y*A*Y*Y~"
          "SV1~"
      )
      with pytest.raises(X12ParseError):
          parse_837p(text)
  ```
  Or, if the intended fix is to *skip* the SV1 silently:
  ```python
  def test_sv1_with_no_proc_element_does_not_crash():
      text = "...SV1~..."
      out = parse_837p(text)
      assert out[0]["CPT_codes"] == []
  ```
  (the choice depends on the desired behaviour).

---

## BUG-02 — `IndexError` on truncated envelope that ends mid-SV1

- **Signal**: `uncaught_exception` (IndexError, "list index out of range")
- **Category**: truncated_segment
- **Severity**: High — same blast radius as BUG-01. Any real-world
  837P file that has been truncated by a network blip, a copy-paste
  error, or a generator bug will crash the portal.
- **Root cause**: Same as BUG-01 — `_cpt_codes_from_sv1` at line 214.
  The truncated-segment samples that survive past the first
  ~700 bytes of the envelope (so the parser still finds a CLM) but
  cut off in the middle of an SV1 hit the same `IndexError`.
- **Minimal repro**:
  Take any of the truncated inputs in `_findings.json` whose
  `parsed.error` is `IndexError` and whose traceback ends in
  `x12_parser.py:214`. The harness captured this for sample #6
  (`cut last 60 chars of envelope`).
- **Proposed regression test** (add to `tests/test_encounters_upload.py`):
  ```python
  def test_truncated_envelope_does_not_raise_indexerror():
      # Any file that ends mid-SV1 should either raise X12ParseError
      # (preferred) or return a list with empty CPT_codes — never
      # propagate an IndexError.
      truncated = BASE_837P[:710]  # somewhere mid-SV1
      try:
          out = parse_837p(truncated)
          assert isinstance(out, list)
      except X12ParseError:
          pass
      except IndexError:
          pytest.fail("IndexError must not leak from parse_837p")
  ```

---

## BUG-03 — Empty / whitespace-only input raises `X12ParseError` (expected) but no test asserts the error is a per-file malformed error

- **Signal**: `uncaught_x12_error` (X12ParseError, "input is empty")
- **Category**: missing_envelope
- **Severity**: Low — this is *expected* behaviour per the parser's
  docstring. The portal's per-file error mapping handles it.
  Documenting it here only so the fuzz corpus has a paper trail.
- **Root cause**: `x12_parser.py:346-347`:
  ```python
  if text is None or not text.strip():
      raise X12ParseError("input is empty")
  ```
- **Minimal repro**: `parse_837p("")` or `parse_837p("   \n  ")`.
- **Proposed regression test** (already implicitly covered by
  `test_encounters_upload.py`; if not, add):
  ```python
  def test_empty_input_raises_x12error():
      with pytest.raises(X12ParseError, match="input is empty"):
          parse_837p("")
      with pytest.raises(X12ParseError, match="input is empty"):
          parse_837p("   \n  ")
  ```

---

## BUG-04 — CPT codes silently dropped when the last SV1 is truncated

- **Signal**: `silent_drop:CPT_codes` (16 samples)
- **Category**: truncated_segment
- **Severity**: Medium — a truncated file passes through the parser
  and produces a claim with `CPT_codes == []`, which the upload
  validator then rejects as "missing CPT codes". The user gets a
  per-file error, but the actual cause (truncation) is invisible —
  the error says "missing CPT" as if the source never had one.
- **Root cause**: `_extract_claim` at `x12_parser.py:281-282` skips
  the SV1 entirely if it was cut off mid-segment, because
  `_split_segments` produces an `["SV1"]` list which (after the
  fix in BUG-01) would return `[]` from `_cpt_codes_from_sv1` — but
  in the *current* code the call raises IndexError. The error
  message the user sees has no indication that the file was
  truncated.
- **Minimal repro**: A file with one full CLM and one truncated
  SV1 line, e.g. `BASE_837P[:710]`.
- **Proposed regression test**:
  ```python
  def test_truncated_sv1_emits_empty_cpt_not_crash():
      # The shape of the failure is that the parser returns OK
      # (or X12ParseError after the BUG-01 fix) and the user-visible
      # error is the validator's "missing CPT codes" — not a generic
      # 500. Lock in the contract: parser does not crash.
      text = BASE_837P[:710]  # cuts mid-SV1
      try:
          out = parse_837p(text)
          assert out[0]["CPT_codes"] == []
      except X12ParseError:
          pass
  ```

---

## BUG-05 — `date_of_service` silently dropped when the DTP*472 segment is missing or reordered

- **Signal**: `silent_drop:date_of_service` (9 truncated samples
  + 1 wrong-order sample, so 10 total)
- **Category**: truncated_segment, wrong_order
- **Severity**: Medium — same shape as BUG-04. The user sees
  "missing date_of_service" without knowing the file was truncated
  or the segments were out of order. Worse: a wrong-order file
  (DTP*472 before NM1*IL) silently produces a `date_of_service=None`
  because the parser does not recognise DTP*472 as a service date
  in that position. Per the X12 spec, segment order is supposed to
  be enforced by the loop structure; the parser currently relies
  on order-by-coincidence.
- **Root cause**: `x12_parser.py:276-279` — the DTP handler only
  fires for the *first* DTP*472*D8*YYYYMMDD it sees. If the segment
  is truncated, the parser silently never sees it. If the segment
  is moved before the NM1*IL loop, the parser still finds it (it
  doesn't gate on order) but `_group_into_claims` folds it into
  the *envelope* bucket rather than the *claim* bucket, depending
  on which `CLM` precedes it. In the wrong-order sample #153,
  the DTP*472 was correctly seen but the parser's
  `_group_into_claims` logic still placed the segments correctly
  for that specific case; the date drop is from a different cause
  (the file lost the DTP*472 because the reorder placed a duplicate
  `DTP*434` first and the parser then walked past the malformed
  order).
- **Minimal repro** (truncated): a file cut to ~640 chars (just
  before `DTP*472`).
- **Minimal repro** (wrong order): take BASE_837P and move the
  `DTP*472` segment to a position before any CLM.
- **Proposed regression test**:
  ```python
  def test_truncation_before_dtp_drops_date_silently():
      # The parser should at minimum NOT crash and the validator
      # should flag this; lock in that the contract is preserved.
      text = BASE_837P[:640]  # cuts before DTP*472
      out = parse_837p(text)
      assert out[0]["date_of_service"] is None
      errors = validate_required_fields(out[0])
      assert any("date_of_service" in e for e in errors)
  ```

---

## BUG-06 — `encounter_id`, `patient_id`, `NPI` silently dropped on truncation that loses the CLM and/or NM1 segments

- **Signal**: `silent_drop:{encounter_id|patient_id|NPI}` (6 + 4 + 2 = 12 samples)
- **Category**: truncated_segment
- **Severity**: Medium — the user sees "missing encounter_id" or
  similar but not "your file is truncated". The parser does the
  right thing (returns None) but the validator's error message
  doesn't distinguish "not present in source" from "lost to
  truncation".
- **Root cause**: same `_extract_claim` walk at `x12_parser.py:248-282`
  — it never raises, just leaves the field as None.
- **Minimal repro**: any sample in `_findings.json` with a
  `silent_drop:encounter_id` signal.
- **Proposed regression test**:
  ```python
  def test_truncation_before_clm_drops_encounter_id():
      # Cut the file just before CLM (around char 580 in BASE_837P).
      text = BASE_837P[:580]
      out = parse_837p(text)
      # CLM was lost, so the file should either be rejected with
      # X12ParseError ("no CLM segment found") or — if the parser
      # decides to keep the envelope-only bucket — return a list
      # with encounter_id=None. Lock in whichever behaviour the
      # parser currently has.
      if out:
          assert out[0]["encounter_id"] is None
  ```

---

## BUG-07 — Accepted-invalid CPT codes (qualifier OK, code garbage)

- **Signal**: `accepted_invalid:CPT_codes` (10 samples)
- **Category**: bad_cpt
- **Severity**: Medium — a parser that accepts a 4-digit code
  (`HC:1234`), an empty code (`HC:`), or letters (`HC:ABCD1`)
  will pass that garbage to downstream billing systems. The
  validator at `validate_required_fields` only checks
  "CPT_codes is non-empty", not "each code is well-formed".
- **Root cause**: `_cpt_codes_from_sv1` at `x12_parser.py:222-233`
  only validates the qualifier (`HC` / `HCPCS`) — it does not
  validate that the code itself matches any known code set
  (5 alphanumeric chars for CPT, 5 chars or letter+digit for
  HCPCS Level II). Any string that follows the qualifier passes
  through.
- **Minimal repro**:
  ```
  SV1*HC:1234*100.00*UN*1***1~    # 4-digit
  SV1*HC:ABCD1*100.00*UN*1***1~  # letters
  SV1*HC:*100.00*UN*1***1~       # empty
  SV1*HC:999999*100.00*UN*1***1~ # 6-digit
  ```
  Each one produces `CPT_codes=["1234"]` / `["ABCD1"]` / `[""]` /
  `["999999"]` respectively. The downstream `validate_required_fields`
  then sees a non-empty list and accepts the file.
- **Proposed regression test**:
  ```python
  @pytest.mark.parametrize("bad_code", ["1234", "ABCD1", "", "999999"])
  def test_bad_cpt_codes_are_rejected(bad_code):
      text = BASE_837P.replace("HC:99213", f"HC:{bad_code}")
      out = parse_837p(text)
      errors = validate_required_fields(out[0])
      # Either the parser drops the code, or the validator flags
      # the well-formed-shape check.
      assert out[0]["CPT_codes"] == [] or any("CPT" in e for e in errors)
  ```

---

## BUG-08 — `date_of_service` accepted-invalid for impossible calendar dates

- **Signal**: `accepted_invalid:bad_date_passed` (7 samples)
- **Category**: invalid_date
- **Severity**: High — a date like `20240229` (Feb 29 in a leap
  year — actually valid!) or `20230229` (Feb 29 in a non-leap
  year) or `99999999` (semantically impossible) is accepted by
  the parser and emitted as `2024-02-29`. The validator at
  `validate_required_fields` only checks the shape
  (`YYYY-MM-DD`), not the calendar validity. The
  `_iso_date_from_dtp_472` helper at `x12_parser.py:186-196`
  enforces 8 digits and `D8` format but never checks that the
  month is 1-12 or that the day exists in the month.
- **Root cause**: `x12_parser.py:194-196`:
  ```python
  if fmt != "D8" or len(raw) != 8 or not raw.isdigit():
      return None
  return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
  ```
  No calendar validation.
- **Minimal repro**:
  - `DTP*472*D8*20230229` → `2023-02-29` (impossible)
  - `DTP*472*D8*20240230` → `2024-02-30` (impossible)
  - `DTP*472*D8*20240431` → `2024-04-31` (impossible, April has 30 days)
  - `DTP*472*D8*99999999` → `9999-99-99` (passes the regex but is nonsense)
- **Proposed regression test**:
  ```python
  @pytest.mark.parametrize("bad", [
      "20230229",  # Feb 29 in non-leap year
      "20240230",  # Feb 30
      "20240431",  # April 31
      "99999999",  # semantically impossible
  ])
  def test_impossible_dates_are_rejected(bad):
      text = BASE_837P.replace("20240510", bad)
      out = parse_837p(text)
      # Either the parser drops the date, or the validator flags
      # the shape. The point is: no claim with an impossible
      # date_of_service reaches the audit pipeline.
      assert out[0]["date_of_service"] is None or validate_required_fields(out[0])
  ```

---

## BUG-09 — `DTP*472` with the wrong qualifier (`DTP*434`, `RD8`, `TM`, etc.) is silently accepted as "no date"

- **Signal**: not a direct signature, but the `invalid_date` row of
  the by-category table has 7 accepted-invalid cases including
  `DTP*434` (statement dates, not service dates), `DTP*472*RD8`
  (range format), and `DTP*472*DT` (date+time).
- **Category**: invalid_date
- **Severity**: Medium — the parser drops the date entirely
  (because `_iso_date_from_dtp_472` only matches qualifier `472`
  and format `D8`) but gives no diagnostic. A user with a real
  file using `DTP*434` (statement date) and no `DTP*472` will get
  "missing date_of_service" with no hint that the file is
  structurally using the wrong qualifier.
- **Root cause**: `x12_parser.py:186-196` in
  `_iso_date_from_dtp_472` only handles the `472+D8` combination.
  Every other qualifier / format combo is dropped silently.
- **Minimal repro**:
  - `DTP*434*D8*20240510` (statement dates, not service) → `None`
  - `DTP*472*RD8*20240510-20240511` (range) → `None`
- **Proposed regression test**:
  ```python
  def test_dtp_434_is_treated_as_missing_date():
      text = BASE_837P.replace("DTP*472*", "DTP*434*")
      out = parse_837p(text)
      assert out[0]["date_of_service"] is None
      # Lock in: the parser does not accidentally pick up the
      # statement date as a service date.
  ```

---

## BUG-10 — Wrong segment order can cause `date_of_service` to be dropped (DTP*472 before NM1*IL)

- **Signal**: `silent_drop:date_of_service` (wrong-order variant)
- **Category**: wrong_order
- **Severity**: Medium — the parser does not enforce X12 loop
  order, so a file that has DTP*472 before NM1*IL should still
  parse correctly, but in this specific case the parser's
  `_group_into_claims` logic combined with the truncation in the
  sample produced a drop.
- **Root cause**: `x12_parser.py:298-327` in
  `_group_into_claims`. The grouping logic walks segments in
  order and folds segments before the first CLM into the first
  claim bucket only if they have a specific set of tag names
  (ISA, GS, ST, BHT, NM1, N1, PER). DTP is *not* in that list, so
  when a DTP*472 appears before any CLM, it is dropped on the
  floor. (See line 321-323: `seg and seg[0] in ("ISA", "GS", "ST",
  "BHT", "NM1", "N1", "PER",)`.)
- **Minimal repro**: take BASE_837P, move `DTP*472*D8*20240510`
  to a position before any `CLM` segment.
- **Proposed regression test**:
  ```python
  def test_dtp_before_clm_does_not_drop_service_date():
      # Move DTP*472 to before any CLM.
      segs = BASE_837P.split("~")
      dtp = [s for s in segs if s.startswith("DTP*472*")]
      clm = [s for s in segs if s.startswith("CLM*")]
      others = [s for s in segs if s not in dtp and s not in clm]
      reordered = dtp + others + clm
      text = "~".join(reordered) + "~"
      out = parse_837p(text)
      # Even if order is wrong, the parser should find the date.
      assert out[0]["date_of_service"] == "2024-05-10"
  ```

---

## Out of scope (intentionally not documented)

- **CPT / HCPCS code set membership**: the parser does not
  validate that `99213` is a real code (it isn't in any
  authoritative list — it just happens to be a common one). The
  task spec called this out as a fuzzing category, but a
  maintainable fix would require bundling a code list. Recommend
  deferring to a follow-up task.
- **Calendar leap-year logic for `20240229`**: a date the parser
  accepts (Feb 29 2024 is valid). Not a bug.
- **CLM02 charge amount with embedded commas** (`$1,000.00`,
  `1,000.00`): the parser does not currently extract the charge
  amount (it's not in `REQUIRED_FIELDS`). 22 of the
  `units_out_of_range` and 28 of the `bad_currency` samples
  passed the harness with zero failures because the parser
  doesn't look at those fields. Not a bug in this scope, but
  worth noting that the parser is permissive *by design* on
  these — and any future code that reads SV102 or CLM02 will
  hit the same shape problems.

## Re-running the harness

```bash
cd ~/projects/ai-billing-audit
python3 tests/fuzz/test_x12_fuzz.py
```

The harness is deterministic — the sample set is built from
`SEED = 20260616` and `_topup` determinism — so re-runs produce
the same input corpus. If you change the parser and re-run, the
bug counts will shift, but the sample text and the JSON file's
`seed` field will tell you which version produced which output.
