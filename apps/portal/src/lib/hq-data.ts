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
  qualificationStatus: string;
  qualificationReason: string | null;
  qualificationEvidenceRef: string | null;
  qualificationReviewedAt: Date | null;
  submissionCount: number;
  lastSubmittedAt: Date | null;
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
  openSupportCaseCount: number | null;
  overdueSupportCaseCount: number | null;
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
  qualificationStatus: true,
  qualificationReason: true,
  qualificationEvidenceRef: true,
  qualificationReviewedAt: true,
  submissionCount: true,
  lastSubmittedAt: true,
  version: true,
  createdAt: true,
} as const;

export async function loadHqOverview(
  now = new Date(),
  access: { leads: boolean; clients: boolean; support?: boolean } = { leads: true, clients: true, support: true },
): Promise<HqOverview> {
  const staleBefore = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
  const openLeadFilter = { status: { notIn: CLOSED_LEAD_STATES } };

  const supportAccess = access.support ?? true;
  const [newLeadCount, unownedLeadCount, needsFollowUpCount, activeClientCount, openCompanyTaskCount, overdueCompanyTaskCount, openSupportCaseCount, overdueSupportCaseCount, recentLeads] =
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
      supportAccess ? prisma.supportCase.count({ where: { status: { notIn: ["resolved", "closed"] } } }) : null,
      supportAccess ? prisma.supportCase.count({ where: { status: { notIn: ["resolved", "closed"] }, dueAt: { lt: now } } }) : null,
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
    openSupportCaseCount,
    overdueSupportCaseCount,
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

export async function loadHqSupportCases() {
  const [cases, engagements, owners] = await Promise.all([
    prisma.supportCase.findMany({
      select: {
        id: true, category: true, severity: true, status: true, safeSummary: true,
        dueAt: true, createdAt: true, version: true,
        engagement: { select: { id: true, clinicName: true } },
        owner: { select: { name: true, email: true } },
      },
      orderBy: [{ status: "asc" }, { severity: "desc" }, { createdAt: "desc" }],
    }),
    prisma.clientEngagement.findMany({
      where: { status: { not: "closed" } },
      select: { id: true, clinicName: true },
      orderBy: { clinicName: "asc" },
    }),
    prisma.platformUserRole.findMany({
      where: { active: true, role: { in: ["owner", "client_success", "support"] } },
      select: { userId: true, role: true, user: { select: { name: true, email: true } } },
      orderBy: { grantedAt: "asc" },
    }),
  ]);
  return { cases, engagements, owners };
}

export async function loadHqSupportCaseDetail(id: string) {
  const [supportCase, owners] = await Promise.all([
    prisma.supportCase.findUnique({
      where: { id },
      select: {
        id: true, category: true, severity: true, status: true, safeSummary: true,
        ownerUserId: true, dueAt: true, acknowledgedAt: true, resolvedAt: true,
        linkedIssueReference: true, version: true, createdAt: true,
        engagement: { select: { id: true, clinicName: true } },
        owner: { select: { name: true, email: true } },
        activities: {
          select: { id: true, kind: true, actorRole: true, changesJson: true, occurredAt: true, actor: { select: { name: true, email: true } } },
          orderBy: { occurredAt: "desc" },
          take: 100,
        },
      },
    }),
    prisma.platformUserRole.findMany({
      where: { active: true, role: { in: ["owner", "client_success", "support"] } },
      select: { userId: true, role: true, user: { select: { name: true, email: true } } },
      orderBy: { grantedAt: "asc" },
    }),
  ]);
  return { supportCase, owners };
}

export async function loadHqMarketingRegistry() {
  const [claims, assets, campaigns, owners] = await Promise.all([
    prisma.claimApproval.findMany({ select: { id: true, exactClaim: true, evidenceType: true, status: true, allowedSurfacesJson: true, reviewAt: true, expiresAt: true, version: true, approver: { select: { name: true, email: true } } }, orderBy: { createdAt: "desc" } }),
    prisma.contentAsset.findMany({ select: { id: true, title: true, assetType: true, targetSegment: true, channel: true, status: true, containsMarketingClaim: true, plannedAt: true, version: true, owner: { select: { name: true, email: true } }, claimApproval: { select: { id: true, exactClaim: true, status: true } } }, orderBy: { createdAt: "desc" } }),
    prisma.campaign.findMany({ select: { id: true, name: true, sourceKey: true, objective: true, targetSegment: true, channel: true, status: true, plannedStartAt: true, reviewAt: true, version: true, owner: { select: { name: true, email: true } }, contentAsset: { select: { id: true, title: true, status: true } }, _count: { select: { snapshots: true } } }, orderBy: { createdAt: "desc" } }),
    prisma.platformUserRole.findMany({ where: { active: true, role: { in: ["owner", "marketing"] } }, select: { userId: true, role: true, user: { select: { name: true, email: true } } }, orderBy: { grantedAt: "asc" } }),
  ]);
  return { claims, assets, campaigns, owners };
}

export async function loadHqMarketingRecord(type: "claim" | "asset", id: string) {
  const activities = prisma.marketingActivity.findMany({ where: { recordType: type === "claim" ? "marketing_claim" : "content_asset", recordId: id }, select: { id: true, kind: true, changesJson: true, actorRole: true, occurredAt: true, actor: { select: { name: true, email: true } } }, orderBy: { occurredAt: "desc" }, take: 100 });
  const owners = prisma.platformUserRole.findMany({ where: { active: true, role: { in: ["owner", "marketing"] } }, select: { userId: true, role: true, user: { select: { name: true, email: true } } }, orderBy: { grantedAt: "asc" } });
  if (type === "claim") return { claim: await prisma.claimApproval.findUnique({ where: { id } }), asset: null, activities: await activities, owners: await owners };
  return { claim: null, asset: await prisma.contentAsset.findUnique({ where: { id } }), activities: await activities, owners: await owners };
}

export async function loadHqCampaignDetail(id: string) {
  const [campaign, owners, assets, activities] = await Promise.all([
    prisma.campaign.findUnique({ where: { id }, include: { snapshots: { orderBy: { periodEndAt: "desc" }, take: 100 } } }),
    prisma.platformUserRole.findMany({ where: { active: true, role: { in: ["owner", "marketing"] } }, select: { userId: true, role: true, user: { select: { name: true, email: true } } }, orderBy: { grantedAt: "asc" } }),
    prisma.contentAsset.findMany({ where: { status: "approved" }, select: { id: true, title: true, channel: true, status: true }, orderBy: { title: "asc" } }),
    prisma.marketingActivity.findMany({ where: { recordType: "campaign", recordId: id }, select: { id: true, kind: true, changesJson: true, actorRole: true, occurredAt: true, actor: { select: { name: true, email: true } } }, orderBy: { occurredAt: "desc" }, take: 100 }),
  ]);
  return { campaign, owners, assets, activities };
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
