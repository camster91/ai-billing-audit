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
  newLeadCount: number | null;
  unownedLeadCount: number | null;
  needsFollowUpCount: number | null;
  activeClientCount: number | null;
  openCompanyTaskCount: number | null;
  overdueCompanyTaskCount: number | null;
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

export async function loadHqOverview(
  now = new Date(),
  access: { leads: boolean; clients: boolean } = { leads: true, clients: true },
): Promise<HqOverview> {
  const staleBefore = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
  const openLeadFilter = { status: { notIn: CLOSED_LEAD_STATES } };

  const [newLeadCount, unownedLeadCount, needsFollowUpCount, activeClientCount, openCompanyTaskCount, overdueCompanyTaskCount, recentLeads] =
    await Promise.all([
      access.leads ? prisma.lead.count({ where: { status: "new" } }) : null,
      access.leads ? prisma.lead.count({ where: { ...openLeadFilter, ownerUserId: null } }) : null,
      access.leads ? prisma.lead.count({
        where: {
          ...openLeadFilter,
          OR: [{ lastContactedAt: null }, { lastContactedAt: { lt: staleBefore } }],
        },
      }) : null,
      access.clients ? prisma.clientEngagement.count({ where: { status: { not: "closed" } } }) : null,
      access.clients ? prisma.companyTask.count({ where: { status: { not: "done" } } }) : null,
      access.clients ? prisma.companyTask.count({ where: { status: { not: "done" }, dueAt: { lt: now } } }) : null,
      access.leads ? prisma.lead.findMany({
        select: LEAD_SELECT,
        orderBy: { createdAt: "desc" },
        take: 10,
      }) : [],
    ]);

  return {
    generatedAt: now,
    newLeadCount,
    unownedLeadCount,
    needsFollowUpCount,
    activeClientCount,
    openCompanyTaskCount,
    overdueCompanyTaskCount,
    recentLeads,
  };
}

export async function loadHqLeadDetail(leadId: string) {
  const [lead, operators, clientOwners] = await Promise.all([
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
        engagement: { select: { id: true, status: true } },
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
    prisma.platformUserRole.findMany({
      where: { active: true, role: { in: ["owner", "client_success"] } },
      select: {
        userId: true,
        role: true,
        user: { select: { name: true, email: true } },
      },
      orderBy: { grantedAt: "asc" },
    }),
  ]);
  return { lead, operators, clientOwners };
}

export async function loadHqClients() {
  return prisma.clientEngagement.findMany({
    select: {
      id: true,
      clinicName: true,
      status: true,
      privacyApprovalStatus: true,
      pilotStartAt: true,
      pilotEndAt: true,
      healthStatus: true,
      owner: { select: { name: true, email: true } },
      _count: { select: { tasks: { where: { status: { not: "done" } } } } },
    },
    orderBy: { createdAt: "desc" },
  });
}

export async function loadHqClientDetail(id: string) {
  const [client, owners] = await Promise.all([
    prisma.clientEngagement.findUnique({
      where: { id },
      select: {
        id: true,
        clinicName: true,
        status: true,
        offerReference: true,
        privacyApprovalStatus: true,
        pilotStartAt: true,
        pilotEndAt: true,
        firstValueAt: true,
        healthStatus: true,
        version: true,
        lead: { select: { id: true, name: true, email: true } },
        tenant: { select: { id: true, name: true, onboardingStep: true, onboardingCompletedAt: true } },
        owner: { select: { name: true, email: true } },
        tasks: {
          select: {
            id: true,
            title: true,
            status: true,
            priority: true,
            ownerUserId: true,
            dueAt: true,
            evidenceReference: true,
            version: true,
            owner: { select: { name: true, email: true } },
          },
          orderBy: [{ status: "asc" }, { createdAt: "asc" }],
        },
      },
    }),
    prisma.platformUserRole.findMany({
      where: { active: true, role: { in: ["owner", "client_success"] } },
      select: { userId: true, role: true, user: { select: { name: true, email: true } } },
      orderBy: { grantedAt: "asc" },
    }),
  ]);
  return { client, owners };
}

export async function loadHqLeads(): Promise<HqLeadSummary[]> {
  return prisma.lead.findMany({
    select: LEAD_SELECT,
    orderBy: [{ status: "asc" }, { createdAt: "desc" }],
  });
}
