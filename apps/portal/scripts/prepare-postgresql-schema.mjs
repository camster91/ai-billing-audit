import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const portalRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourcePath = resolve(portalRoot, "prisma/schema.prisma");
const targetPath = resolve(portalRoot, "prisma/postgresql/schema.prisma");

const source = await readFile(sourcePath, "utf8");
const output = source
  .replace(
    'output   = "../src/generated/prisma"',
    'output   = "../../src/generated/prisma-postgresql"',
  )
  .replace('provider = "sqlite"', 'provider = "postgresql"');

if (output === source) {
  throw new Error("Could not derive the PostgreSQL Prisma schema");
}

await mkdir(dirname(targetPath), { recursive: true });
await writeFile(targetPath, output, "utf8");
