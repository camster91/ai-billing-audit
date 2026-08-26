// Design-token lint (issue #44).
//
// Scans every *.module.css under apps/portal/src for raw
// values that should be tokens. The intent is NOT to force
// every module to be token-pure in one PR — that is a multi-
// PR migration tracked separately. The intent is to surface a
// per-file list of raw values so a follow-up PR can move them
// to tokens one file at a time.
//
// What this script flags:
//   - Raw hex colors (#abc, #abcdef, #abcdef00) outside tokens.css
//   - Raw rgb()/rgba()/hsl() with non-token values
//   - Raw px values for font-size, border-radius, and box-shadow
//     (we don't flag padding/margin/top/left because the spacing
//     scale is intentionally permissive for one-off layout tweaks)
//
// What this script does NOT flag:
//   - Inline raw values inside tokens.css itself (the source of truth)
//   - Raw values inside scripts/, docs/, or apps/portal/tests/
//   - Existing tokens.css consumers — the goal is to make the
//     raw values visible, not to break the build during the
//     migration

import { readFileSync, readdirSync, statSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join, relative, sep } from "node:path";

import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../src/");
const REPO_ROOT = resolve(HERE, "../../..");
const TOKENS_FILE = "app/tokens.css";

const HEX_RE = /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/g;
const RGB_RE = /\brgba?\(\s*[^)]+\)/g;
const FONT_SIZE_PX_RE = /font-size\s*:\s*(\d+)\s*px/g;
const RADIUS_PX_RE = /border-radius\s*:\s*(\d+)\s*px/g;
const PX_LINE_RE = /(\d+)\s*px/g;

const results = [];

function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const s = statSync(p);
    if (s.isDirectory()) walk(p);
    else if (name.endsWith(".module.css")) results.push(p);
  }
}

function stripStrings(line) {
  // Comments are tolerated; the scanner is per-line and a stray
  // value inside /* ... */ still gets flagged. That is the
  // intended behaviour: a comment that names a raw value is
  // also worth removing or updating.
  return line;
}

function scan(file) {
  const text = readFileSync(file, "utf8");
  const lines = text.split("\n");
  const hits = [];
  for (let i = 0; i < lines.length; i++) {
    const line = stripStrings(lines[i]);
    let m;
    HEX_RE.lastIndex = 0;
    while ((m = HEX_RE.exec(line)) !== null) {
      hits.push({ file, line: i + 1, kind: "hex", value: m[0], context: line.trim().slice(0, 80) });
    }
    RGB_RE.lastIndex = 0;
    while ((m = RGB_RE.exec(line)) !== null) {
      hits.push({ file, line: i + 1, kind: "rgb", value: m[0], context: line.trim().slice(0, 80) });
    }
    FONT_SIZE_PX_RE.lastIndex = 0;
    while ((m = FONT_SIZE_PX_RE.exec(line)) !== null) {
      hits.push({ file, line: i + 1, kind: "font-size-px", value: `${m[1]}px`, context: line.trim().slice(0, 80) });
    }
    RADIUS_PX_RE.lastIndex = 0;
    while ((m = RADIUS_PX_RE.exec(line)) !== null) {
      hits.push({ file, line: i + 1, kind: "radius-px", value: `${m[1]}px`, context: line.trim().slice(0, 80) });
    }
  }
  return hits;
}

walk(ROOT);

if (process.env.CHECK_TOKENS_CHANGED_ONLY === "1") {
  const base = process.env.GITHUB_BASE_REF
    ? `origin/${process.env.GITHUB_BASE_REF}`
    : "HEAD^";
  const changed = new Set(
    execFileSync("git", ["diff", "--name-only", `${base}...HEAD`], {
      cwd: REPO_ROOT,
      encoding: "utf8",
    })
      .split("\n")
      .filter(Boolean)
      .map((path) => resolve(REPO_ROOT, path)),
  );
  for (let i = results.length - 1; i >= 0; i--) {
    if (!changed.has(resolve(results[i]))) results.splice(i, 1);
  }
}

const allHits = [];
for (const file of results) {
  const rel = relative(ROOT, file).split(sep).join("/");
  if (rel === TOKENS_FILE) continue;
  for (const h of scan(file)) allHits.push(h);
}

const byFile = new Map();
for (const h of allHits) {
  const k = relative(ROOT, h.file).split(/[\\/]/).join("/");
  if (!byFile.has(k)) byFile.set(k, []);
  byFile.get(k).push(h);
}

const files = [...byFile.keys()].sort();
console.log(`Design-token lint — found ${allHits.length} raw value(s) across ${files.length} module file(s).\n`);
for (const f of files) {
  const list = byFile.get(f);
  console.log(`--- ${f} (${list.length}) ---`);
  // Group by kind + value, then by line.
  const seen = new Set();
  for (const h of list) {
    const key = `${h.kind}:${h.value}:${h.line}`;
    if (seen.has(key)) continue;
    seen.add(key);
    console.log(`  ${h.line}:${h.kind.padEnd(12)} ${h.value.padEnd(20)} ${h.context}`);
  }
}

console.log("\nMigration guidance:");
console.log("  - hex values       → var(--zorva-green), var(--zorva-amber), var(--zorva-accent), etc.");
console.log("  - rgb()/rgba()     → var(--zorva-line-soft), var(--zorva-green-soft), etc.");
console.log("  - font-size px     → var(--zorva-text-xs / --zorva-text-base / --zorva-text-2xl / etc.)");
console.log("  - border-radius px → var(--zorva-radius-sm / --zorva-radius-md / --zorva-radius-lg / --zorva-radius-xl / --zorva-radius-pill)");
console.log("  - 0px / 1px / 2px  → hairline / divide values; leave as-is");
console.log("  - spacing px       → var(--zorva-space-1 / --zorva-space-2 / --zorva-space-3 / etc.) [opt-in]");

// Full-repository runs remain informational during migration. CI combines
// strict mode with changed-file mode so newly touched modules must be clean.
if (process.env.CHECK_TOKENS_STRICT === "1" && allHits.length > 0) {
  process.exit(1);
}
