import { readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const testsDir = resolve("tests");
const integrationTests = new Set([
  "contact-form.test.ts", // requires a running portal on TEST_BASE_URL
  "encounter-list-smoke.test.ts", // requires the encounter-list seed fixture
]);

const files = readdirSync(testsDir)
  .filter((name) => name.endsWith(".test.ts") && !integrationTests.has(name))
  .sort();

for (const file of files) {
  const result = spawnSync(
    process.execPath,
    ["--import", "tsx", "--test", resolve(testsDir, file)],
    { stdio: "inherit", env: process.env },
  );
  if (result.status !== 0) process.exit(result.status ?? 1);
}
