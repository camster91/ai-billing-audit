// Small UI formatters for the encounter review surface.
//
// The split-screen page uses these for currency, dates, and claim JSON
// rendering. They are intentionally pure (no I/O, no React) so the
// server component and the client dismiss form share the same output.
//
// The single `dangerouslySetInnerHTML` call site in the codebase is
// `src/app/encounters/[id]/_components/clinical-note.tsx`, which
// passes the `html` field produced by `wrapEvidenceQuotes` here.
// The function escapes every non-`<mark>` character (see `escapeHtml`
// and `escapeAttr`) so the input is fully sanitized — no untrusted
// data ever reaches the DOM as raw markup.

import type { ClaimPayload } from "@/lib/encounter-types";

/** Format an integer cents value as a signed USD string. */
export function formatCents(cents: number, options: { signed?: boolean } = {}): string {
  const dollars = cents / 100;
  const sign =
    options.signed === false
      ? ""
      : dollars < 0
        ? "-"
        : dollars > 0
          ? "+"
          : "";
  const abs = Math.abs(dollars).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return cents === 0 ? abs : `${sign}${abs}`;
}

/** Format an ISO date string (YYYY-MM-DD) as a US-style M/D/YYYY. */
export function formatDate(iso: string | Date): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  if (Number.isNaN(d.getTime())) return typeof iso === "string" ? iso : "";
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

/**
 * Parse and validate an `EncounterClaim.cptCodesJson` string.
 *
 * Returns null on parse failure or schema mismatch — the page falls
 * back to showing the raw JSON. We don't throw because a malformed
 * claim is a data-integrity issue, not a user error.
 */
export function parseClaimPayload(json: string): ClaimPayload | null {
  try {
    const parsed = JSON.parse(json);
    if (typeof parsed !== "object" || parsed === null) return null;
    if (!Array.isArray((parsed as ClaimPayload).lines)) return null;
    return parsed as ClaimPayload;
  } catch {
    return null;
  }
}

export interface EvidenceQuote {
  id: string;
  quote: string;
}

export interface EvidenceMatch {
  id: string;
  index: number;
  length: number;
}

/**
 * Wrap occurrences of each `quote` in `text` with a
 * `<mark class="evidence" data-evidence-id="…">` span. The output is
 * fully escaped — only `<mark>` tags are emitted; everything else
 * is HTML-escaped character-for-character. Safe to render with
 * `dangerouslySetInnerHTML` once the resulting `html` is the only input.
 *
 * Matching is case-sensitive, longest-quote-first, non-overlapping.
 * The function returns the original-text offsets of each match so
 * the page can scroll the first one into view.
 */
export function wrapEvidenceQuotes(
  text: string,
  quotes: EvidenceQuote[],
): { html: string; matches: EvidenceMatch[] } {
  const ordered = quotes
    .filter((q) => q.quote.length > 0)
    .sort((a, b) => b.quote.length - a.quote.length);
  if (ordered.length === 0) {
    return { html: escapeHtml(text), matches: [] };
  }

  // Find all candidate matches, one regex per quote, so we can
  // attribute each match to its id and drop overlapping shorter ones.
  const candidates: EvidenceMatch[] = [];
  for (const q of ordered) {
    const pattern = escapeRegExp(q.quote);
    const re = new RegExp(pattern, "g");
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      candidates.push({ id: q.id, index: m.index, length: m[0].length });
      // Guard against zero-length matches in pathological input.
      if (m.index === re.lastIndex) re.lastIndex += 1;
    }
  }
  // Sort by start position, then by length descending so longer wins
  // when two quotes share a starting offset.
  candidates.sort((a, b) => {
    if (a.index !== b.index) return a.index - b.index;
    return b.length - a.length;
  });
  // Drop overlapping shorter matches.
  const deduped: EvidenceMatch[] = [];
  let lastEnd = -1;
  for (const c of candidates) {
    if (c.index >= lastEnd) {
      deduped.push(c);
      lastEnd = c.index + c.length;
    }
  }

  // Build the output HTML.
  const out: string[] = [];
  let cursor = 0;
  for (const m of deduped) {
    if (m.index > cursor) {
      out.push(escapeHtml(text.slice(cursor, m.index)));
    }
    const quoted = escapeHtml(text.slice(m.index, m.index + m.length));
    out.push(
      `<mark class="evidence" data-evidence-id="${escapeAttr(m.id)}">${quoted}</mark>`,
    );
    cursor = m.index + m.length;
  }
  if (cursor < text.length) {
    out.push(escapeHtml(text.slice(cursor)));
  }
  return { html: out.join(""), matches: deduped };
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(s: string): string {
  return escapeHtml(s);
}
