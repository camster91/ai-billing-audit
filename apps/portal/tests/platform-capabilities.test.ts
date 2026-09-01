import assert from "node:assert/strict";
import test from "node:test";
import {
  hasPlatformCapability,
  isPlatformRole,
} from "../src/lib/platform-capabilities";

test("platform roles fail closed for absent, inactive, unknown, and tenant roles", () => {
  for (const role of [null, undefined, "", "admin", "owner", "auditor", "viewer", "unknown"]) {
    // `owner` here is intentionally ambiguous: tenant owners do not receive HQ
    // access unless a separate active PlatformUserRole row supplies that value.
    const activePlatformRecord = role === "owner";
    assert.equal(
      hasPlatformCapability(role, activePlatformRecord ? false : true, "hq:read"),
      false,
      String(role),
    );
  }
  assert.equal(hasPlatformCapability("sales", false, "leads:read"), false);
});

test("only declared platform roles are recognized", () => {
  assert.equal(isPlatformRole("owner"), true);
  assert.equal(isPlatformRole("sales"), true);
  assert.equal(isPlatformRole("client_success"), true);
  assert.equal(isPlatformRole("support"), true);
  assert.equal(isPlatformRole("analyst"), true);
  assert.equal(isPlatformRole("marketing"), true);
  assert.equal(isPlatformRole("admin"), false);
  assert.equal(isPlatformRole("viewer"), false);
});

test("role capabilities grant the smallest current read surface", () => {
  assert.equal(hasPlatformCapability("owner", true, "hq:read"), true);
  assert.equal(hasPlatformCapability("owner", true, "leads:read"), true);
  assert.equal(hasPlatformCapability("owner", true, "leads:write"), true);
  assert.equal(hasPlatformCapability("sales", true, "leads:read"), true);
  assert.equal(hasPlatformCapability("sales", true, "leads:write"), true);
  assert.equal(hasPlatformCapability("owner", true, "clients:read"), true);
  assert.equal(hasPlatformCapability("owner", true, "clients:write"), true);
  assert.equal(hasPlatformCapability("sales", true, "clients:read"), true);
  assert.equal(hasPlatformCapability("sales", true, "clients:write"), false);
  assert.equal(hasPlatformCapability("client_success", true, "leads:read"), true);
  assert.equal(hasPlatformCapability("client_success", true, "leads:write"), false);
  assert.equal(hasPlatformCapability("client_success", true, "clients:read"), true);
  assert.equal(hasPlatformCapability("client_success", true, "clients:write"), true);
  assert.equal(hasPlatformCapability("owner", true, "support:read"), true);
  assert.equal(hasPlatformCapability("owner", true, "support:write"), true);
  assert.equal(hasPlatformCapability("client_success", true, "support:write"), true);
  assert.equal(hasPlatformCapability("support", true, "support:read"), true);
  assert.equal(hasPlatformCapability("support", true, "support:write"), true);
  for (const role of ["support", "analyst"] as const) {
    assert.equal(hasPlatformCapability(role, true, "hq:read"), true);
    assert.equal(hasPlatformCapability(role, true, "leads:read"), false);
    assert.equal(hasPlatformCapability(role, true, "leads:write"), false);
    assert.equal(hasPlatformCapability(role, true, "clients:read"), false);
    assert.equal(hasPlatformCapability(role, true, "clients:write"), false);
  }
  assert.equal(hasPlatformCapability("analyst", true, "support:read"), false);
  assert.equal(hasPlatformCapability("sales", true, "support:read"), false);
  assert.equal(hasPlatformCapability("marketing", true, "marketing:read"), true);
  assert.equal(hasPlatformCapability("marketing", true, "marketing:write"), true);
  assert.equal(hasPlatformCapability("analyst", true, "marketing:read"), true);
  assert.equal(hasPlatformCapability("analyst", true, "marketing:write"), false);
  assert.equal(hasPlatformCapability("sales", true, "marketing:read"), true);
});
