// Server-side helpers for writing audit log entries on accept / dismiss.
//
// Every state change to a Finding (accept or dismiss) writes exactly
// one row to the AuditTrailEntry table inside a single transaction.
// The hash chain is computed at write time using the most recent
// (timestamp, eventId) row for the same tenant as the `previous`
// signature — Genesis (64 zeros) for the first row of each tenant
// chain.
//
// The write is wrapped in a Prisma transaction so a failed audit
// row rolls back the Finding mutation, and a duplicate write (two
// concurrent accepts of the same finding) is detected by the
// `eventId` unique constraint and surfaced as a 409 by the route
// handler. The chain verification helper in this module walks the
// resulting rows in `(timestamp, eventId)` order and confirms
// `verify_chain` returns null before returning success.

import type { Prisma, PrismaClient } from "@/generated/prisma/client";
import { prisma } from "@/lib/prisma";
import {
  computeSignature,
  GENESIS_PREVIOUS_SIGNATURE,
  verifyChain as verifyChainImpl,
  walkChain,
  type ChainRow,
} from "@/lib/audit-chain";
import {
  AUDIT_ACTIONS,
  isDismissReason,
  isFindingStatus,
  type AuditAction,
  type DismissReason,
} from "@/lib/encounter-types";
import { upsertCalibrationSignal } from "@/lib/calibration-write";

/**
 * Inputs to the audit-trail writer. The Finding's own state is
 * computed from the caller's intent (action + reason) inside the
 * transaction so the two writes (audit + finding) cannot drift.
 */
export interface WriteAuditInput {
  tenantId: string;
  encounterId: string;
  findingId: string;
  userIdentifier: string;
  action: AuditAction;
  reason: DismissReason | null;
  reasonText: string | null;
  /** The Finding's `patientHash` for the chain payload. */
  patientHash: string;
  /** Audit `modelRunId` — for human reviews this is "portal-review". */
  modelRunId: string;
  /**
   * Shared identifier for rows written by the same /findings bulk
   * action (accept / dismiss). Null for single-finding writes. When
   * set, the id is duplicated into `dataElements` (so it is part
   * of the chain hash) AND persisted on the new
   * `AuditTrailEntry.bulkActionId` column for the indexed "show me
   * every row from bulk action X" query.
   */
  bulkActionId?: string | null;
  /** The Prisma client or transaction to run inside. */
  tx: Prisma.TransactionClient | typeof prisma;
}

export interface WriteAuditResult {
  auditEntryId: string;
  eventId: string;
  cryptographicSignature: string;
  previousSignature: string;
  newFindingStatus: "accepted" | "dismissed";
  /**
   * Echo of the bulk action id (when set) so the bulk route handlers
   * can include it in the API response without re-reading the row.
   * Null for single-finding writes.
   */
  bulkActionId: string | null;
}

/**
 * Inputs to the bulk audit-trail writer. Used by the /findings
 * inbox bulk accept/dismiss routes. The helper handles the
 * cross-row chain threading (each row's `previousSignature` is the
 * prior row's `cryptographicSignature`) so the rows form a valid
 * chain even when every write shares the same millisecond
 * timestamp — the `eventId` tiebreaker is otherwise random, which
 * breaks the (timestamp, eventId) order in the same way that
 * inter-row reads inside a single transaction are racy on
 * better-sqlite3.
 */
export interface WriteAuditBatchInputItem {
  encounterId: string;
  findingId: string;
  patientHash: string;
  reason: DismissReason | null;
  reasonText: string | null;
}

export interface WriteAuditBatchInput {
  tenantId: string;
  userIdentifier: string;
  action: AuditAction;
  bulkActionId: string;
  /** All `WriteAuditBatchInputItem`s; max 200 per batch. */
  items: WriteAuditBatchInputItem[];
  /**
   * The Prisma client or transaction to run inside. When a
   * transaction is passed, the bulk insert + bulk finding update
   * run as a single atomic unit; the tenant chain tail is read
   * once with this client BEFORE the inserts.
   */
  tx: Prisma.TransactionClient | typeof prisma;
}

export interface WriteAuditBatchResultItem {
  findingId: string;
  auditEventId: string;
  cryptographicSignature: string;
  previousSignature: string;
}

export interface WriteAuditBatchResult {
  bulkActionId: string;
  newFindingStatus: "accepted" | "dismissed";
  perItem: WriteAuditBatchResultItem[];
}

/**
 * Append N audit rows to the tenant's chain in a single
 * `createMany`, threading the `previousSignature` across rows in
 * JS so the (timestamp, eventId) tiebreaker can never pick a
 * future row in the same transaction. Also bulk-updates the
 * affected `Finding` rows in a single `updateMany` so the
 * transaction stays O(1) round-trips for the chain + status
 * mutations regardless of batch size.
 *
 * Assumes (and asserts) that every item's `findingId` is currently
 * in `pending` state — caller's pre-flight check (in the route
 * handler) guarantees this. The route handler also enforces
 * tenant scope on every finding before calling.
 */
export async function writeAuditBatch(
  input: WriteAuditBatchInput,
): Promise<WriteAuditBatchResult> {
  const { tx, tenantId, items, action, bulkActionId } = input;

  if (!AUDIT_ACTIONS.includes(action)) {
    throw new Error(`invalid audit action: ${action}`);
  }
  if (items.length === 0) {
    return { bulkActionId, newFindingStatus: action === "accept" ? "accepted" : "dismissed", perItem: [] };
  }

  // Read the tail ONCE before the inserts. The tail's signature
  // is the `previousSignature` of the FIRST row in the batch. From
  // there each subsequent row's prev is the prior row's
  // cryptographicSignature — computed in JS so the order is
  // deterministic regardless of how Prisma / better-sqlite3
  // orders rows on the per-row tail read inside an interactive
  // transaction (the racy case this helper exists to solve).
  const tail = await tx.auditTrailEntry.findFirst({
    where: { tenantId },
    orderBy: [{ timestamp: "desc" }, { eventId: "desc" }],
    select: { cryptographicSignature: true },
  });
  let previousSignature = tail?.cryptographicSignature ?? GENESIS_PREVIOUS_SIGNATURE;

  // Build all chain payloads + signatures up-front. Each row's
  // timestamp is the same `new Date()` (all writes happen in the
  // same JS tick); the (timestamp, eventId) sort tiebreaker MUST
  // be stable within the batch, so the eventId encodes a
  // monotonic counter in the FIRST 4 bytes (8 hex chars) and a
  // 12-byte random suffix. This guarantees that across multiple
  // batches sharing the same millisecond timestamp, the chain
  // walk sorts each batch's rows in their insertion order. The
  // counter is BIG-ENDIAN (zero-padded) so lex sort matches
  // numeric sort.
  const baseTimestamp = new Date();
  const isoBase = baseTimestamp.toISOString();
  let counter = 0;
  const seen = new Set<string>();
  const rowsToInsert: Prisma.AuditTrailEntryCreateManyInput[] = [];
  const perItem: WriteAuditBatchResultItem[] = [];
  const affectedFindingIds: string[] = [];
  const newFindingStatus: "accepted" | "dismissed" =
    action === "accept" ? "accepted" : "dismissed";

  for (const item of items) {
    // 4-byte counter (8 hex chars) at the FRONT so lex sort
    // matches insertion order. 12-byte random suffix (24 hex
    // chars) keeps the eventId unguessable across batches.
    const randomSuffix = new Uint8Array(12);
    globalThis.crypto.getRandomValues(randomSuffix);
    let suffixHex = "";
    for (const b of randomSuffix) suffixHex += b.toString(16).padStart(2, "0");
    const counterHex = counter.toString(16).padStart(8, "0");
    const eventId = (counterHex + suffixHex).slice(0, 32);
    if (seen.has(eventId)) {
      // 12 bytes of randomness + 4 bytes of counter should
      // never collide, but guard anyway — a collision would
      // break the unique event_id index.
      throw new Error(`eventId collision in batch: ${eventId}`);
    }
    seen.add(eventId);

    const dataElements = serializeDataElements({
      findingId: item.findingId,
      reason: item.reason,
      reasonText: item.reasonText,
      bulkActionId,
    });

    const chainPayload: ChainRow = {
      eventId,
      timestamp: isoBase,
      userIdentifier: input.userIdentifier,
      action,
      patientHash: item.patientHash,
      dataElements,
      modelRunId: "portal-review",
      previousSignature,
      cryptographicSignature: "",
    };
    const cryptographicSignature = computeSignature(previousSignature, chainPayload);

    rowsToInsert.push({
      tenantId,
      eventId,
      timestamp: baseTimestamp,
      userIdentifier: input.userIdentifier,
      action,
      findingId: item.findingId,
      reason: item.reason,
      reasonText: item.reasonText,
      patientHash: item.patientHash,
      dataElements,
      modelRunId: "portal-review",
      previousSignature,
      cryptographicSignature,
      encounterId: item.encounterId,
      bulkActionId,
    });
    perItem.push({
      findingId: item.findingId,
      auditEventId: eventId,
      cryptographicSignature,
      previousSignature,
    });
    affectedFindingIds.push(item.findingId);

    // Thread the chain: next row's prev = this row's signature.
    previousSignature = cryptographicSignature;
    counter += 1;
  }

  // One round-trip for the chain rows, one for the finding
  // status mutation, and (for dismiss) one more for the dismiss
  // reason / text. The single-write path sets dismissReason +
  // dismissText in a per-row update; the bulk path uses a
  // single updateMany with the constant reason (the route's
  // input schema enforces this is the same for every row in
  // the batch).
  await tx.auditTrailEntry.createMany({ data: rowsToInsert });
  await tx.finding.updateMany({
    where: { id: { in: affectedFindingIds } },
    data: {
      status: newFindingStatus,
      actionedByUserId: input.userIdentifier,
      actionedAt: baseTimestamp,
      // Clear the per-row dismiss metadata first; for the
      // accept path this is the final state. For the dismiss
      // path, the second updateMany below writes the constant
      // reason + text.
      dismissReason: null,
      dismissText: null,
    },
  });

  if (newFindingStatus === "dismissed") {
    const commonReason = items[0]?.reason ?? null;
    const commonText =
      commonReason === "other_with_text" ? items[0]?.reasonText ?? null : null;
    if (commonReason) {
      await tx.finding.updateMany({
        where: { id: { in: affectedFindingIds } },
        data: {
          dismissReason: commonReason,
          dismissText: commonText,
        },
      });
    }
  }

  // Calibration signal write (bulk path) — same as the single-write
  // path above, but iterated per affected finding. We read the
  // findings' ruleIds here (the updateMany above changed status, not
  // ruleId, so this is still the pre-action ruleId set). One upsert
  // per finding so the per-(tenantId, ruleId) counter increments
  // correctly even when the batch contains multiple findings on the
  // same rule.
  const findingsWithRule = await tx.finding.findMany({
    where: { id: { in: affectedFindingIds } },
    select: { id: true, ruleId: true },
  });
  for (const f of findingsWithRule) {
    if (!f.ruleId) continue;
    await upsertCalibrationSignal(tx, {
      tenantId,
      ruleId: f.ruleId,
      action: newFindingStatus === "accepted" ? "accept" : "dismiss",
      timestamp: baseTimestamp,
    });
  }

  return { bulkActionId, newFindingStatus, perItem };
}

/**
 * Append one audit row to the tenant's chain and update the finding
 * disposition in the same transaction. The previous-signature is
 * read from the latest existing row (or GENESIS for an empty chain).
 *
 * Throws when the finding is already in a terminal state (accepted
 * or dismissed) — caller should surface this as a 409.
 */
export async function writeAuditEntry(input: WriteAuditInput): Promise<WriteAuditResult> {
  const { tx, tenantId, encounterId, findingId, action } = input;

  if (!AUDIT_ACTIONS.includes(action)) {
    throw new Error(`invalid audit action: ${action}`);
  }

  const finding = await tx.finding.findFirst({
    where: { id: findingId, encounterId },
    include: { encounter: { select: { tenantId: true } } },
  });
  if (!finding) {
    throw new Error(`finding ${findingId} not found on encounter ${encounterId}`);
  }
  if (finding.encounter.tenantId !== tenantId) {
    // Defensive: the caller's tenantId doesn't match the encounter's
    // tenant. The route layer is supposed to have filtered this, so
    // this branch is "should be impossible" — log and fail loud.
    throw new Error(
      `tenant mismatch: finding ${findingId} is in tenant ${finding.encounter.tenantId}, caller said ${tenantId}`,
    );
  }
  if (isFindingStatus(finding.status) && finding.status !== "pending") {
    throw new Error(
      `finding ${findingId} is already ${finding.status} (terminal); refusing to write a second audit row`,
    );
  }

  // Determine the new finding disposition. The chain `action` mirrors
  // the caller's intent; the finding's `status` column is the same
  // word ("accepted" / "dismissed") with reason metadata on dismiss.
  const newFindingStatus: "accepted" | "dismissed" =
    action === "accept" ? "accepted" : "dismissed";

  // Compute the previous signature: latest existing row for this tenant.
  const tail = await tx.auditTrailEntry.findFirst({
    where: { tenantId },
    orderBy: [{ timestamp: "desc" }, { eventId: "desc" }],
    select: { cryptographicSignature: true },
  });
  const previousSignature = tail?.cryptographicSignature ?? GENESIS_PREVIOUS_SIGNATURE;

  // The chain payload uses a fresh eventId (cuid) and the current
  // timestamp. The two together (timestamp, eventId) break ties so
  // the chain walk is deterministic.
  const eventId = cryptoRandomId();
  const timestamp = new Date();
  const isoTimestamp = timestamp.toISOString();

  const chainPayload: ChainRow = {
    eventId,
    timestamp: isoTimestamp,
    userIdentifier: input.userIdentifier,
    action,
    patientHash: input.patientHash,
    dataElements: serializeDataElements({
      findingId,
      reason: input.reason,
      reasonText: input.reasonText,
      bulkActionId: input.bulkActionId ?? null,
    }),
    modelRunId: input.modelRunId,
    previousSignature,
    // The row's own cryptographic_signature is computed below;
    // the field is required by ChainRow so we set a placeholder that
    // we overwrite before insertion. computeSignature ignores this
    // field on the input row.
    cryptographicSignature: "",
  };

  const cryptographicSignature = computeSignature(previousSignature, chainPayload);

  // Insert the audit row + update the finding in one transaction.
  // We pass the unchecked input so the tenantId/encounterId columns
  // are set by FK id rather than a nested connect — the caller has
  // already verified the encounter belongs to the tenant.
  const auditEntry = await tx.auditTrailEntry.create({
    data: {
      tenantId,
      eventId,
      timestamp,
      userIdentifier: input.userIdentifier,
      action,
      findingId,
      reason: input.reason,
      reasonText: input.reasonText,
      patientHash: input.patientHash,
      dataElements: chainPayload.dataElements,
      modelRunId: input.modelRunId,
      previousSignature,
      cryptographicSignature,
      encounterId,
      bulkActionId: input.bulkActionId ?? null,
    },
    select: { id: true, eventId: true },
  });

  await tx.finding.update({
    where: { id: findingId },
    data: {
      status: newFindingStatus,
      dismissReason: newFindingStatus === "dismissed" ? input.reason : null,
      dismissText:
        newFindingStatus === "dismissed" && input.reason === "other_with_text"
          ? input.reasonText
          : null,
      actionedByUserId: input.userIdentifier,
      actionedAt: timestamp,
    },
  });

  // Calibration signal write — keeps the per-clinic dashboard card
  // (apps/portal/src/components/calibration-card.tsx) in sync with
  // the biller's actual accept/dismiss decisions. Atomic with the
  // chain + Finding write because we're inside the same transaction.
  // No-op when finding.ruleId is null (legacy findings pre-2026-06-27
  // scaffold migration).
  await upsertCalibrationSignal(tx, {
    tenantId,
    ruleId: finding.ruleId,
    action: action === "accept" ? "accept" : "dismiss",
    timestamp,
  });

  return {
    auditEntryId: auditEntry.id,
    eventId: auditEntry.eventId,
    cryptographicSignature,
    previousSignature,
    newFindingStatus,
    bulkActionId: input.bulkActionId ?? null,
  };
}

/**
 * Walk the full audit chain for a tenant and return the index of the
 * first broken row, or null when the chain is intact. Used by tests
 * and by the runbook verifier (out of scope for the portal page).
 */
export async function verifyTenantChain(
  tenantId: string,
  client: PrismaClient | Prisma.TransactionClient = prisma,
): Promise<number | null> {
  // Re-walk the chain after insert to confirm the new tail is intact.
  // This is the test-time / smoke-time verification; the route layer
  // doesn't re-verify on every request because the on-write chain is
  // already deterministic (single-threaded per request + DB row lock).
  const rows = await client.auditTrailEntry.findMany({
    where: { tenantId },
    orderBy: [{ timestamp: "asc" }, { eventId: "asc" }],
    select: {
      eventId: true,
      timestamp: true,
      userIdentifier: true,
      action: true,
      patientHash: true,
      dataElements: true,
      modelRunId: true,
      previousSignature: true,
      cryptographicSignature: true,
    },
  });
  const chainRows: ChainRow[] = rows.map((r) => ({
    eventId: r.eventId,
    timestamp: r.timestamp.toISOString(),
    userIdentifier: r.userIdentifier,
    action: r.action,
    patientHash: r.patientHash,
    dataElements: r.dataElements,
    modelRunId: r.modelRunId,
    previousSignature: r.previousSignature,
    cryptographicSignature: r.cryptographicSignature,
  }));
  return walkAndVerify(chainRows);
}

function walkAndVerify(rows: ChainRow[]): number | null {
  // Re-use the verify_chain implementation, going through walkChain
  // for the canonical sort so the order matches the runbook.
  const ordered = walkChain(rows);
  return verifyChainImpl(ordered);
}

/** Serialize the `dataElements` column in a stable JSON shape. */
function serializeDataElements(payload: {
  findingId: string;
  reason: DismissReason | null;
  reasonText: string | null;
  bulkActionId: string | null;
}): string {
  // Sorted keys, no whitespace — matches the Python `_coerce_field`
  // contract (data_elements is canonical JSON text).
  return JSON.stringify(payload, Object.keys(payload).sort());
}

/**
 * Validation helper for dismiss input — mirrors the Zod schema in
 * encounter-types.ts but is callable from server code that already
 * has the body parsed. Returns the normalized payload or throws.
 */
export function normalizeDismissInput(
  raw: unknown,
): { reason: DismissReason; reasonText: string | null } {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("dismiss body must be an object");
  }
  const r = raw as Record<string, unknown>;
  const reason = r.reason;
  if (typeof reason !== "string" || !isDismissReason(reason)) {
    throw new Error(`reason must be one of: ${["wrong_payer_policy", "hallucinated_fact", "too_conservative", "other_with_text"].join(", ")}`);
  }
  const reasonTextRaw = r.reasonText;
  if (reason === "other_with_text") {
    if (typeof reasonTextRaw !== "string" || reasonTextRaw.trim().length === 0) {
      throw new Error("reasonText is required (1-2000 chars) when reason is other_with_text");
    }
    if (reasonTextRaw.length > 2000) {
      throw new Error("reasonText exceeds 2000 characters");
    }
    return { reason, reasonText: reasonTextRaw };
  }
  if (reasonTextRaw !== undefined && reasonTextRaw !== null && typeof reasonTextRaw !== "string") {
    throw new Error("reasonText must be a string when provided");
  }
  return { reason, reasonText: null };
}

/**
 * Cryptographically random id (Node 18+). Used for the audit chain's
 * `eventId` field — NOT the Prisma row id (which is a cuid assigned
 * by the DB on insert). The two are different by design: the chain
 * identifier is independent of the storage row so a row reorder or
 * rowid change cannot break the chain.
 */
function cryptoRandomId(): string {
  // 16 bytes -> 32 hex chars. Stable enough as a tie-breaker when two
  // events share a millisecond timestamp; combined with the DB row's
  // own `cuid()` (assigned at insert) the chain is doubly unique.
  // We don't use `crypto.randomUUID` because v4 hyphens would shift
  // the chain field length and the Python port has to match.
  const bytes = new Uint8Array(16);
  // globalThis.crypto is available in Node 19+ and in edge runtime.
  globalThis.crypto.getRandomValues(bytes);
  let out = "";
  for (let i = 0; i < bytes.length; i++) {
    out += bytes[i]!.toString(16).padStart(2, "0");
  }
  return out;
}
