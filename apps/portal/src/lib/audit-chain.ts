// SHA-256 hash-chain `cryptographic_signature` for the audit_trail table.
//
// This is a TypeScript port of the canonical Python implementation in
// `src/audit_log.py` (sibling of `audit_trail.sql`). The two modules
// must stay byte-for-byte compatible — they produce the same SHA-256
// digest for the same row payload. The Prisma `AuditTrailEntry` row
// stores both `previousSignature` and `cryptographicSignature`; the
// production Postgres DDL (audit_trail.sql) has an append-only trigger
// and a backfill procedure that uses the same SHA-256 algorithm.
//
// Chain shape (mirrors src/audit_log.py verbatim):
//
//   For row i:
//     cryptographicSignature_i = SHA-256(
//       previousSignature_i
//       || eventId_i
//       || timestamp_i
//       || userIdentifier_i
//       || action_i
//       || patientHash_i
//       || dataElements_i
//       || modelRunId_i
//     )
//
// Genesis row carries `previousSignature = "0" * 64` (64 ASCII zeros).
// The chain is walked in (timestamp, eventId) order so ties are
// deterministic; both the unit tests and the runbook rely on that.
//
// Verification checks BOTH (a) that the row's stored previousSignature
// matches the prior row's stored cryptographicSignature, AND (b) that
// the row's stored cryptographicSignature matches the recomputed
// digest. Either failure surfaces as the first broken row's index.
// Checking only the digest leaves the "fabricated previousSignature"
// forgery vector open; checking only the link doesn't catch in-row
// mutations.

import { createHash } from "node:crypto";

// Ordered tuple of fields whose concatenation forms the hash payload,
// AFTER the leading `previousSignature`. MUST match the Python
// `CHAIN_FIELDS` and the SQL DDL's DO-block backfill verbatim — any
// reorder changes every signature and breaks the chain.
export const CHAIN_FIELDS = [
  "eventId",
  "timestamp",
  "userIdentifier",
  "action",
  "patientHash",
  "dataElements",
  "modelRunId",
] as const;

export type ChainField = (typeof CHAIN_FIELDS)[number];

// Genesis row's previousSignature. 64 ASCII zeros.
export const GENESIS_PREVIOUS_SIGNATURE = "0".repeat(64);

const PREVIOUS_SIGNATURE_FIELD = "previousSignature";
const STORED_SIGNATURE_FIELD = "cryptographicSignature";

/** A row that can be fed to computeSignature / verifyChain. */
export interface ChainRow {
  eventId: string;
  timestamp: string; // ISO-8601 text (matches what the DB stores)
  userIdentifier: string;
  action: string;
  patientHash: string;
  dataElements: string;
  modelRunId: string;
  previousSignature: string;
  cryptographicSignature: string;
}

/** Coerce a row field to the exact string we hash. */
function coerceField(
  row: ChainRow,
  field: ChainField | typeof PREVIOUS_SIGNATURE_FIELD | typeof STORED_SIGNATURE_FIELD,
): string {
  const value = (row as unknown as Record<string, unknown>)[field];
  if (value === null || value === undefined) return "";
  return String(value);
}

/**
 * Return the SHA-256 hex digest of `row` chained to `previousSignature`.
 *
 * `previousSignature` must be a 64-character hex string (use
 * GENESIS_PREVIOUS_SIGNATURE for the oldest row in the chain partition).
 * The row's own stored `cryptographicSignature` is ignored — we recompute
 * from the payload, mirroring the Python implementation.
 */
export function computeSignature(previousSignature: string, row: ChainRow): string {
  if (typeof previousSignature !== "string") {
    throw new TypeError(
      `previousSignature must be str, got ${typeof previousSignature}`,
    );
  }
  if (previousSignature.length !== 64) {
    throw new RangeError(
      `previousSignature must be 64 hex chars, got len=${previousSignature.length}`,
    );
  }

  const hasher = createHash("sha256");
  hasher.update(previousSignature, "utf8");
  for (const field of CHAIN_FIELDS) {
    hasher.update(coerceField(row, field), "utf8");
  }
  return hasher.digest("hex");
}

/**
 * Walk `rows` in chain order and return the first broken row's position.
 *
 * The chain is walked in the order the iterable yields rows. The caller
 * is responsible for sorting by (timestamp, eventId) — see walkChain
 * for the canonical ordering helper.
 *
 * Returns the 0-based index of the first row whose recomputed signature
 * does not match its stored `cryptographicSignature`, or whose stored
 * `previousSignature` does not match the prior row's stored
 * `cryptographicSignature`. Returns null when the entire chain verifies.
 */
export function verifyChain(rows: Iterable<ChainRow>): number | null {
  let previousSignature: string = GENESIS_PREVIOUS_SIGNATURE;
  let index = 0;
  for (const row of Array.from(rows)) {
    const storedPrev = coerceField(row, PREVIOUS_SIGNATURE_FIELD);
    if (storedPrev !== previousSignature) {
      return index;
    }
    const expected = computeSignature(previousSignature, row);
    const stored = coerceField(row, STORED_SIGNATURE_FIELD);
    if (stored !== expected) {
      return index;
    }
    // Advance using the just-verified stored signature, not the
    // recomputed one. This tolerates a non-canonical encoding choice
    // on the row we just verified while still detecting any downstream
    // break — the stored value propagates forward.
    previousSignature = stored;
    index += 1;
  }
  return null;
}

/**
 * Return `rows` sorted by (timestamp, eventId) ascending.
 *
 * Matches the SQL DDL backfill's ORDER BY and the Python walk_chain.
 * The chain walk is deterministic on this ordering even when the DB
 * returns rows in a different order (e.g. when an event_id cuid
 * happens to share a timestamp with its predecessor).
 */
export function walkChain<T extends ChainRow>(rows: Iterable<T>): T[] {
  const materialized = Array.from(rows);
  materialized.sort((a, b) => {
    const ts = a.timestamp.localeCompare(b.timestamp);
    if (ts !== 0) return ts;
    return a.eventId.localeCompare(b.eventId);
  });
  return materialized;
}
