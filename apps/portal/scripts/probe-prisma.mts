import { PrismaClient } from "../src/generated/prisma/client";
import { PrismaBetterSqlite3 } from "@prisma/adapter-better-sqlite3";
const c = new PrismaClient({ adapter: new PrismaBetterSqlite3({ url: "./prisma/dev.db" }), log: ["query", "error", "warn"] });
console.log("on available:", typeof (c as any).$on);
(c as any).$on("query", (e: any) => console.log("QUERY:", String(e.query).slice(0, 80)));
const n = await c.encounter.count();
console.log("count:", n);
await c.$disconnect();
