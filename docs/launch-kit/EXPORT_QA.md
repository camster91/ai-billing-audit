# One-page overview export QA

**Artifact:** `output/pdf/zorva-controlled-pilot-overview-draft.pdf`
**Source:** `docs/launch-kit/ONE_PAGE_OVERVIEW.md`
**Build:** `scripts/build-launch-kit-pdf.py`
**Status:** visual and export checks passed; PDF tagging remains an external-use blocker

## Passed on 2026-09-01

- one US Letter page with no clipping, overlap, overflow, broken glyphs, or
  illegible content in a 144-DPI Poppler render
- visible draft and approval warning at the top of the page
- all body text extractable in logical reading order
- two link annotations, one to `/contact` and one to `/how-it-works`, with only
  the approved non-personal UTM parameters
- title, author, subject, page size, and no JavaScript or form fields verified
- teal, charcoal, and amber combinations visually conform to the documented
  high-contrast brand palette
- deterministic PDF generation enabled for traceable review artifacts

## Open before external use

`pdfinfo` reports `Tagged: no`. The Markdown source remains accessible and the
PDF text order is extractable, but that is not sufficient proof of a fully
tagged screen-reader experience. The PDF must remain draft-only until it is
exported with a real document structure tree and then checked with an
accessibility validator and representative screen reader. This limitation is
not waived by the visual pass.
