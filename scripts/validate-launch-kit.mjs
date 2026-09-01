import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const kitDir = path.join(root, "docs", "launch-kit");
const manifest = JSON.parse(
  fs.readFileSync(path.join(kitDir, "CLAIM_MANIFEST.json"), "utf8"),
);

const errors = [];
const claimIds = new Set(manifest.claims.map((claim) => claim.id));
const approvedRoutes = new Set(manifest.approvedPublicRoutes);
const forbidden = [
  /catches?\s+6[–-]7\s+of\s+10/i,
  /data stays in a Canadian data centre/i,
  /region[- ]pinned/i,
  /HIPAA[- ]compliant/i,
  /HIA[- ]compliant/i,
  /certified compliance/i,
  /guaranteed?\s+(savings|recovery|results?)/i,
  /\$\d+[,.]?\d*\s*(saved|recovered|per month)/i,
  /\b\d+(?:\.\d+)?%\s+(accuracy|savings|reduction|improvement|ROI)/i,
];

for (const claim of manifest.claims) {
  if (!claim.source || !claim.approvalState) {
    errors.push(`${claim.id}: source and approvalState are required`);
  }
  if (claim.publicUse !== false) {
    errors.push(`${claim.id}: publicUse must remain false until approved`);
  }
}

for (const asset of manifest.assets) {
  const filePath = path.join(kitDir, asset.path);
  if (!fs.existsSync(filePath)) {
    errors.push(`${asset.path}: registered asset is missing`);
    continue;
  }
  const text = fs.readFileSync(filePath, "utf8");
  if (!/> DRAFT -/.test(text)) {
    errors.push(`${asset.path}: missing visible draft/approval banner`);
  }
  for (const id of asset.claimIds) {
    if (!claimIds.has(id)) errors.push(`${asset.path}: unknown manifest claim ${id}`);
  }
  for (const match of text.matchAll(/\bZC-\d{3}\b/g)) {
    if (!asset.claimIds.includes(match[0])) {
      errors.push(`${asset.path}: uses undeclared claim ${match[0]}`);
    }
  }
  for (const pattern of forbidden) {
    if (pattern.test(text)) errors.push(`${asset.path}: contains forbidden claim language ${pattern}`);
  }
  for (const match of text.matchAll(/https:\/\/zorva\.ashbi\.ca(?:\/[^\s)>]*)?/g)) {
    const url = new URL(match[0]);
    const route = `${url.origin}${url.pathname}`;
    if (!approvedRoutes.has(route)) {
      errors.push(`${asset.path}: links to unapproved public route ${route}`);
    }
    for (const key of url.searchParams.keys()) {
      if (!["utm_source", "utm_medium", "utm_campaign"].includes(key)) {
        errors.push(`${asset.path}: unsupported attribution parameter ${key}`);
      }
    }
    if (url.search && url.searchParams.get("utm_campaign") !== manifest.campaign) {
      errors.push(`${asset.path}: wrong or missing launch-kit campaign value`);
    }
  }
}

if (errors.length) {
  console.error(`Launch-kit validation failed (${errors.length}):`);
  for (const error of errors) console.error(`- ${error}`);
  process.exit(1);
}

console.log(
  `Launch-kit validation passed: ${manifest.assets.length} assets, ${manifest.claims.length} registered claims, external use disabled.`,
);
