import { createHash } from "node:crypto";

import { encryptPortalString } from "@/lib/data-encryption";
import {
  FINDING_CATEGORIES,
  type FindingCategory,
} from "@/lib/encounter-types";
import type { EngineFinding } from "@/lib/fastapi";
import { prisma } from "@/lib/prisma";

export type ImportEngineAuditResult =
  | { kind: "imported"; count: number }
  | { kind: "already_imported"; count: number }
  | { kind: "not_found" };

function portalFindingId(
  tenantId: string,
  encounterId: string,
  engineFindingId: string,
): string {
  return `eng_${createHash("sha256")
    .update(`${tenantId}\0${encounterId}\0${engineFindingId}`, "utf8")
    .digest("hex")}`;
}

export function engineFindingStorageKey(finding: EngineFinding): string {
  const supplied = finding.finding_id.trim();
  if (supplied) return `id:${supplied}`;
  const content = JSON.stringify({
    category: finding.category,
    explanation: finding.explanation,
    quote: finding.quote,
    ruleId: finding.rule_id ?? "",
    ruleIds: finding.rule_ids ?? [],
    severity: finding.severity,
    suggestedCode: finding.suggested_code ?? null,
  });
  return `content:${createHash("sha256").update(content, "utf8").digest("hex")}`;
}

function category(value: string): FindingCategory {
  return (FINDING_CATEGORIES as readonly string[]).includes(value)
    ? (value as FindingCategory)
    : "other";
}

function ruleReference(finding: EngineFinding): string {
  const ids = [...(finding.rule_ids ?? []), finding.rule_id ?? ""]
    .map((value) => value.trim())
    .filter(Boolean);
  return [...new Set(ids)].join(", ").slice(0, 1000) || "Engine finding";
}

/**
 * Idempotently import a completed engine job into the portal review store.
 * Evidence is encrypted before the transaction and a terminal review state is
 * never overwritten by a later poll.
 */
export async function importEngineAuditResult(args: {
  tenantId: string;
  encounterId: string;
  engineJobId: string;
  findings: EngineFinding[];
}): Promise<ImportEngineAuditResult> {
  const normalized = args.findings.slice(0, 500).map((finding) => ({
    id: portalFindingId(
      args.tenantId,
      args.encounterId,
      engineFindingStorageKey(finding),
    ),
    category: category(finding.category),
    billingRuleReference: ruleReference(finding),
    suggestedCode: finding.suggested_code?.slice(0, 64) || null,
    evidenceQuote: encryptPortalString(finding.quote.slice(0, 10_000)),
  }));

  return prisma.$transaction(async (tx) => {
    const dispatch = await tx.auditDispatch.findFirst({
      where: {
        tenantId: args.tenantId,
        encounterId: args.encounterId,
        engineJobId: args.engineJobId,
      },
    });
    if (!dispatch) return { kind: "not_found" } as const;
    if (dispatch.resultImportedAt) {
      return { kind: "already_imported", count: normalized.length } as const;
    }

    for (const finding of normalized) {
      const existing = await tx.finding.findUnique({ where: { id: finding.id } });
      if (existing) {
        if (existing.encounterId !== args.encounterId) {
          throw new Error("engine finding id collision");
        }
        if (existing.status === "pending") {
          await tx.finding.update({
            where: { id: finding.id },
            data: {
              category: finding.category,
              billingRuleReference: finding.billingRuleReference,
              suggestedCode: finding.suggestedCode,
              evidenceQuote: finding.evidenceQuote,
            },
          });
        }
        continue;
      }
      await tx.finding.create({
        data: {
          ...finding,
          encounterId: args.encounterId,
          currentCode: null,
          estFinancialImpactCents: 0,
          status: "pending",
        },
      });
    }

    const now = new Date();
    await tx.encounter.update({
      where: { id: args.encounterId },
      data: { status: normalized.length > 0 ? "awaiting_review" : "completed" },
    });
    await tx.auditDispatch.update({
      where: { id: dispatch.id },
      data: {
        status: "done",
        completedAt: now,
        resultImportedAt: now,
        lastError: null,
      },
    });
    return { kind: "imported", count: normalized.length } as const;
  });
}
