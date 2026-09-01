import { prisma } from "../src/lib/prisma";

const [encounterId, tenantId] = process.argv.slice(2);
if (!encounterId || !tenantId) throw new Error("encounterId and tenantId are required");

const encounter = await prisma.encounter.findFirst({
  where: { id: encounterId, tenantId },
  include: { findings: { orderBy: { createdAt: "asc" } }, claim: true },
});
if (!encounter) throw new Error("encounter not found");
console.log(JSON.stringify({
  id: encounter.id,
  sourceUploadDigest: encounter.sourceUploadDigest,
  status: encounter.status,
  findingIds: encounter.findings.map((finding) => finding.id),
  claimJson: encounter.claim.cptCodesJson,
}));
await prisma.$disconnect();
