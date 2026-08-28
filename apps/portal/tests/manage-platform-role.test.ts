import assert from "node:assert/strict";
import test from "node:test";
import { parseOptions } from "../scripts/manage-platform-role";

test("platform role CLI requires a declared action, existing email shape, actor, and role", () => {
  assert.throws(() => parseOptions([]));
  assert.throws(() => parseOptions(["--action", "grant", "--email", "owner@example.test", "--granted-by", "operator"]));
  assert.throws(() => parseOptions(["--action", "grant", "--email", "bad", "--role", "owner", "--granted-by", "operator"]));
  assert.throws(() => parseOptions(["--action", "grant", "--email", "owner@example.test", "--role", "admin", "--granted-by", "operator"]));
});

test("platform role CLI parses grant and revoke confirmations without changing data", () => {
  const grant = parseOptions([
    "--action", "grant", "--email", "Owner@Example.Test", "--role", "owner",
    "--granted-by", "cameron", "--confirm-role-change", "--confirm-production",
  ]);
  assert.deepEqual(grant, {
    action: "grant",
    email: "owner@example.test",
    role: "owner",
    grantedBy: "cameron",
    confirmed: true,
    productionConfirmed: true,
  });
  const revoke = parseOptions([
    "--action", "revoke", "--email", "owner@example.test", "--granted-by", "cameron",
  ]);
  assert.equal(revoke.role, null);
  assert.equal(revoke.confirmed, false);
});
