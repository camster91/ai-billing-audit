import { prisma } from "@/lib/prisma";

const CLOSED_LEAD_STATES = ["pilot_signed", "lost"];

export interface HqLeadSummary {
  id: string;
  name: string;
  clinicName: string;
  email: string;
  claimVolume: number | null;
  billingSetup: string;
  status: string;
  source: string | null;
  ownerUserId: string | null;
  lastContactedAt: Date | null;
  nextAction: string | null;
  nextActionAt: Date | null;
  lostReason: string | null;
  version: number;
  createdAt: Date;
}

export interface HqOverview {
  generatedAt: Date;
  newLeadCount: number;
  unownedLeadCount: number;
  needsFollowUpCount: number;
  activeClientCount: number;
  recentLeads: HqLeadSummary[];
}

const LEAD_SELECT = {
  id: true,
  name: true,
  clinicName: true,
  email: true,
  claimVolume: true,
  billingSetup: true,
  status: true,
  source: true,
  ownerUserId: true,
  lastContactedAt: true,
  nextAction: true,
  nextActionAt: true,
  lostReason: true,
  version: true,
  createdAt: true,
} as const;

export async function loadHqOverview(now = new Date()): Promise<HqOverview> {
  const staleBefore = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
  const openLeadFilter = { status: { notIn: CLOSED_LEAD_STATES } };

  const [newLeadCount, unownedLeadCount, needsFollowUpCount, activeClientCount, recentLeads] =
    await Promise.all([
      prisma.lead.count({ where: { status: "new" } }),
      prisma.lead.count({ where: { ...openLeadFilter, ownerUserId: null } }),
      prisma.lead.count({
        where: {
          ...openLeadFilter,
          OR: [{ lastContactedAt: null }, { lastContactedAt: { lt: staleBefore } }],
        },
      }),
      prisma.tenant.count({ where: { subscriptionStatus: "active" } }),
      prisma.lead.findMany({
        select: LEAD_SELECT,
        orderBy: { createdAt: "desc" },
        take: 10,
      }),
    ]);

  return {
    generatedAt: now,
    newLeadCount,
    unownedLeadCount,
    needsFollowUpCount,
    activeClientCount,
    recentLeads,
  };
}

export async function loadHqLeadDetail(leadId: string) {
  const [lead, operators] = await Promise.all([
    prisma.lead.findUnique({
      where: { id: leadId },
      select: {
        ...LEAD_SELECT,
        activities: {
          select: {
            id: true,
            kind: true,
            fromValue: true,
            toValue: true,
            actorRole: true,
            occurredAt: true,
            actor: { select: { email: true } },
          },
          orderBy: { occurredAt: "desc" },
          take: 50,
        },
      },
    }),
    prisma.platformUserRole.findMany({
      where: { active: true, role: { in: ["owner", "sales"] } },
      select: {
        userId: true,
        role: true,
        user: { select: { name: true, email: true } },
      },
      orderBy: { grantedAt: "asc" },
    }),
  ]);
  return { lead, operators };
}

export async function loadHqLeads(): Promise<HqLeadSummary[]> {
  return prisma.lead.findMany({
    select: LEAD_SELECT,
    orderBy: [{ status: "asc" }, { createdAt: "desc" }],
  });
}
