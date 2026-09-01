import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { test } from "node:test";

const APP_ROOT = path.resolve(process.cwd());

async function source(relativePath: string): Promise<string> {
  return readFile(path.join(APP_ROOT, relativePath), "utf8");
}

test("approved core public routes stay within the evidence-safe claim boundary", async () => {
  const coreRoutes = await Promise.all([
    source("src/app/page.tsx"),
    source("src/app/how-it-works/page.tsx"),
    source("src/app/contact/page.tsx"),
  ]);
  const renderedCopy = coreRoutes.join("\n");

  for (const unsafe of [
    /revenue your billers are leaving on the table/i,
    /reads every Alberta claim/i,
    /audit every claim/i,
    /every encounter is checked/i,
    /underbilled modifiers/i,
    /shadow[- ]billed services/i,
    /exact rule and the exact passage/i,
    /flat monthly fee/i,
    /three tiers bracketed/i,
    /region[- ]pinned (?:data|facility)/i,
    /no cross-region replication/i,
    /HIA\s*\/\s*PHIPA\s*\/\s*HIPAA/i,
    /executed IMA\s*\/\s*BAA/i,
  ]) {
    assert.doesNotMatch(renderedCopy, unsafe);
  }
});

test("homepage offers one bounded conversion journey without deferred routes", async () => {
  const homepage = await source("src/app/page.tsx");
  const hrefs = [...homepage.matchAll(/href="([^"]+)"/g)].map(
    (match) => match[1],
  );

  assert.ok(hrefs.includes("/contact"));
  assert.ok(hrefs.includes("/how-it-works"));
  assert.ok(hrefs.every((href) => ["/contact", "/how-it-works"].includes(href)));
  assert.match(homepage, /Start a conversation/);
  assert.match(homepage, /not self-serve production access/i);
  assert.match(homepage, /No outcome promise/);
  assert.match(homepage, /No sensitive data in first contact/);
});

test("illustrative homepage review contains no fabricated codes or dollar outcomes", async () => {
  const homepage = await source("src/app/page.tsx");

  assert.match(homepage, /ILLUSTRATIVE PRE-SUBMIT REVIEW/);
  assert.match(homepage, /Illustrative workflow · no patient data/);
  assert.doesNotMatch(homepage, /\+\s*\$\d/);
  assert.doesNotMatch(homepage, /\$\d+\.\d{2}/);
  assert.doesNotMatch(homepage, /SOMB\s+(?:GR|Schedule)/);
});
