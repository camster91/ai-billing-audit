import { prisma } from "@/lib/prisma";

export type MetricState = "known" | "unknown" | "unavailable" | "delayed";

export interface CompanyMetric {
  key: string;
  label: string;
  value: number | null;
  unit: "count" | "percent" | "hours" | "cad_cents";
  state: MetricState;
  source: string;
  definition: string;
}

export interface CampaignOutcomeRow {
  campaignId: string;
  campaignName: string;
  sourceKey: string;
  periodStartAt: Date;
  periodEndAt: Date;
  revenueCents: number | null;
  clientCount: number | null;
  recordedSpendCents: number | null;
  state: "known" | "unknown" | "delayed";
  sourceReference: string;
}

export interface CompanyReport {
  generatedAt: Date;
  periodStartAt: Date;
  periodEndAt: Date;
  metrics: CompanyMetric[];
  campaignOutcomes: CampaignOutcomeRow[];
}

function metric(
  key: string,
  label: string,
  value: number | null,
  unit: CompanyMetric["unit"],
  state: MetricState,
  source: string,
  definition: string,
): CompanyMetric {
  return { key, label, value, unit, state, source, definition };
}

export async function loadCompanyReport(
  periodStartAt: Date,
  periodEndAt: Date,
  generatedAt = new Date(),
): Promise<CompanyReport> {
  if (!(periodStartAt < periodEndAt)) throw new Error("Report period start must precede its end.");
  const inPeriod = { gte: periodStartAt, lt: periodEndAt };

  const [
    acquiredLeads,
    pilotTransitions,
    lostTransitions,
    engagementsCreated,
    firstValueReached,
    activeClients,
    atRiskClients,
    supportOpened,
    supportResolved,
    openUrgentSupport,
    campaignSnapshots,
  ] = await Promise.all([
    prisma.lead.count({ where: { createdAt: inPeriod } }),
    prisma.leadActivity.count({ where: { kind: "stage_changed", toValue: "pilot_signed", occurredAt: inPeriod } }),
    prisma.leadActivity.count({ where: { kind: "stage_changed", toValue: "lost", occurredAt: inPeriod } }),
    prisma.clientEngagement.count({ where: { createdAt: inPeriod } }),
    prisma.clientEngagement.count({ where: { firstValueAt: inPeriod } }),
    prisma.clientEngagement.count({ where: { status: { not: "closed" } } }),
    prisma.clientEngagement.count({ where: { status: { not: "closed" }, healthStatus: { in: ["at_risk", "critical"] } } }),
    prisma.supportCase.count({ where: { createdAt: inPeriod } }),
    prisma.supportCase.findMany({ where: { resolvedAt: inPeriod }, select: { createdAt: true, resolvedAt: true } }),
    prisma.supportCase.count({ where: { status: { notIn: ["resolved", "closed"] }, severity: { in: ["high", "critical"] } } }),
    prisma.campaignAttributionSnapshot.findMany({
      where: { periodEndAt: inPeriod },
      select: {
        campaignId: true,
        periodStartAt: true,
        periodEndAt: true,
        revenueCents: true,
        clientCount: true,
        sourceReference: true,
        recordedAt: true,
        campaign: { select: { name: true, sourceKey: true, recordedSpendCents: true } },
      },
      orderBy: [{ campaignId: "asc" }, { periodEndAt: "desc" }, { recordedAt: "desc" }],
    }),
  ]);

  const closedDecisions = pilotTransitions + lostTransitions;
  const pilotConversionPercent = closedDecisions === 0 ? null : (pilotTransitions / closedDecisions) * 100;
  const resolvedHours = supportResolved
    .filter((record): record is typeof record & { resolvedAt: Date } => record.resolvedAt !== null)
    .map((record) => (record.resolvedAt.getTime() - record.createdAt.getTime()) / 3_600_000);
  const meanResolutionHours = resolvedHours.length === 0
    ? null
    : resolvedHours.reduce((sum, hours) => sum + hours, 0) / resolvedHours.length;

  const latestByCampaign = new Map<string, (typeof campaignSnapshots)[number]>();
  for (const snapshot of campaignSnapshots) {
    if (!latestByCampaign.has(snapshot.campaignId)) latestByCampaign.set(snapshot.campaignId, snapshot);
  }
  const staleBefore = new Date(generatedAt.getTime() - 14 * 24 * 60 * 60 * 1000);
  const campaignOutcomes = [...latestByCampaign.values()].map((snapshot) => ({
    campaignId: snapshot.campaignId,
    campaignName: snapshot.campaign.name,
    sourceKey: snapshot.campaign.sourceKey,
    periodStartAt: snapshot.periodStartAt,
    periodEndAt: snapshot.periodEndAt,
    revenueCents: snapshot.revenueCents,
    clientCount: snapshot.clientCount,
    recordedSpendCents: snapshot.campaign.recordedSpendCents,
    state: snapshot.periodEndAt < staleBefore
      ? "delayed" as const
      : snapshot.revenueCents === null && snapshot.clientCount === null
        ? "unknown" as const
        : "known" as const,
    sourceReference: snapshot.sourceReference,
  }));

  return {
    generatedAt,
    periodStartAt,
    periodEndAt,
    metrics: [
      metric("acquired_leads", "Acquired leads", acquiredLeads, "count", "known", "Lead.createdAt", "Lead records created during the selected half-open period."),
      metric("pilot_decisions", "Pilots signed", pilotTransitions, "count", "known", "LeadActivity(stage_changed)", "Recorded stage transitions to pilot_signed during the period; current stage is not substituted."),
      metric("pilot_conversion", "Closed-decision pilot rate", pilotConversionPercent, "percent", pilotConversionPercent === null ? "unknown" : "known", "LeadActivity(stage_changed)", "Pilot-signed transitions divided by pilot-signed plus lost transitions during the period."),
      metric("engagements_created", "Client engagements created", engagementsCreated, "count", "known", "ClientEngagement.createdAt", "Commercial client/pilot records created during the period."),
      metric("first_value", "First-value milestones", firstValueReached, "count", "known", "ClientEngagement.firstValueAt", "Engagements whose recorded first-value timestamp falls in the period."),
      metric("active_clients", "Open client engagements", activeClients, "count", "known", "ClientEngagement.status", "Current snapshot of engagements not marked closed; not a historical period count."),
      metric("at_risk_clients", "At-risk client engagements", atRiskClients, "count", "known", "ClientEngagement.healthStatus", "Current open engagements explicitly marked at_risk or critical; unknown health is not counted as healthy."),
      metric("support_opened", "Support cases opened", supportOpened, "count", "known", "SupportCase.createdAt", "Internal no-PHI support cases created during the period."),
      metric("support_resolution", "Mean support resolution time", meanResolutionHours, "hours", meanResolutionHours === null ? "unknown" : "known", "SupportCase.createdAt/resolvedAt", "Arithmetic mean for cases resolved during the period; unknown when none were resolved."),
      metric("urgent_support", "Open high-priority support", openUrgentSupport, "count", "known", "SupportCase.status/severity", "Current open cases marked high or critical."),
      metric("revenue", "Company recognized revenue", null, "cad_cents", "unavailable", "No accounting ledger connected", "Unavailable until an approved accounting source and recognition policy are connected."),
      metric("cost_to_serve", "Cost to serve", null, "cad_cents", "unavailable", "No time/cost ledger connected", "Unavailable until approved labour, infrastructure, and vendor-cost allocation sources exist."),
    ],
    campaignOutcomes,
  };
}
