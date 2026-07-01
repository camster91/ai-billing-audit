// Peppered SHA-256 hash for the `patientHash` column on `encounter` and
// for the `patient_hash` field chained into `audit_trail`.
//
// Why a pepper?
// ------------
// Unsalted SHA-256 of a 6-12 char member-ID is dictionary-attackable
// in seconds: US payer member IDs, Ontario health card numbers, and
// most commercial payer ID shapes live in a small domain. Anyone with
// read access to `audit_trail` could correlate encounters back to
// specific patients by running a small rainbow-table script. HIPAA
// Safe Harbor, HIA (Alberta), and PHIPA (Ontario) all treat such correlation as a breach.
//
// A pepper (a server-side secret mixed into the hash before the
// input) raises the cost of any pre-computed attack by requiring
// the attacker to also possess the pepper. Rotating the pepper
// invalidates every existing hash, which is the right response to a
// suspected breach.
//
// Threat model
// ------------
//   - Database snapshot leak: attacker can read the `patient_hash`
//     column but does NOT have the pepper → cannot run a dictionary
//     attack without also compromising the application host or the
//     secret manager.
//   - Application host compromise: attacker has the pepper, can
//     verify a small candidate set. The mitigation is the same as
//     for any application secret — keep the pepper in a secret
//     manager, not in `.env` committed to the repo.
//
// Environment
// -----------
//   PATIENT_HASH_PEPPER — required in production; optional in dev
//     (the helper falls back to a constant in NODE_ENV !== 'production'
//     so unit tests and the seed script run without a configured
//     secret). The fallback is a security regression if it ever
//     reaches production; the `assertProductionPepper` helper below
//     is called from the audit-write path and throws on boot in
//     production if the env var is unset.

import { createHash } from "node:crypto";

const DEV_FALLBACK_PEPPER =
  "dev-only-patients-hash-pepper-do-not-use-in-production";

export interface PatientHashOptions {
  /**
   * Override the pepper. Tests use this to assert sensitivity to
   * the secret; production code should let the env var drive.
   */
  pepper?: string;
}

function resolvePepper(opts?: PatientHashOptions): string {
  const fromEnv = process.env.PATIENT_HASH_PEPPER;
  // P11 round-2 (2026-07-01): minimum bumped 16 → 32 chars. SHA-256's
  // security is independent of pepper length, but a 16-char pepper is
  // brute-forceable against a known-format dictionary of ~10^9 payer
  // IDs in days on a single GPU. 32 chars (256 bits if hex-derived)
  // matches the hash output width and removes that attack class.
  if (fromEnv && fromEnv.length >= 32) return fromEnv;
  if (opts?.pepper && opts.pepper.length >= 32) return opts.pepper;
  if (process.env.NODE_ENV === "production") {
    // Fail fast: an unset / too-short pepper in production means
    // every patient hash is attackable. We throw rather than fall
    // back so the misconfiguration is loud, not silent.
    throw new Error(
      "PATIENT_HASH_PEPPER must be set to a 32+ char secret in production",
    );
  }
  return DEV_FALLBACK_PEPPER;
}

// P11 round-2 (2026-07-01): cap input length. Real patient identifiers
// (PHN, MRN, ULI) are 9-12 chars; encounter IDs are short slugs. A
// 1024-char cap defends the JSONL log + Postgres row + audit-trail
// chain against accidental / malicious large inputs. The DB column
// has a shape check (`~ '^[0-9a-f]{64}$'`) so a bad input would be
// rejected downstream — but better to fail at the helper boundary
// than persist 1MB to the audit log.
const MAX_PATIENT_ID_LENGTH = 1024;

/**
 * Compute the peppered SHA-256 hex digest of a patient identifier.
 *
 * The output is 64 lowercase hex chars, suitable for the
 * `patientHash` column (which has a `~ '^[0-9a-f]{64}$'` shape
 * expected by the audit-trail verifier).
 */
export function hashPatientId(
  patientId: string,
  opts?: PatientHashOptions,
): string {
  if (typeof patientId !== "string" || !patientId) {
    throw new TypeError("patientId must be a non-empty string");
  }
  if (patientId.length > MAX_PATIENT_ID_LENGTH) {
    throw new RangeError(
      `patientId must be <= ${MAX_PATIENT_ID_LENGTH} chars (got ${patientId.length})`,
    );
  }
  const pepper = resolvePepper(opts);
  // Domain-separate the input from the pepper so an attacker who
  // somehow learns the pepper cannot reuse it as a patientId
  // (collision resistance even when the secrets share a domain).
  return createHash("sha256")
    .update(`patient-hash:v1:${pepper}:${patientId}`, "utf8")
    .digest("hex");
}

/**
 * Assert the pepper is configured. Call this from any production
 * boot path (server startup, audit-write init, etc.) so a missing
 * env var fails fast at process start, not at first request.
 */
export function assertProductionPepper(): void {
  if (process.env.NODE_ENV !== "production") return;
  const fromEnv = process.env.PATIENT_HASH_PEPPER ?? "";
  if (fromEnv.length < 32) {
    throw new Error(
      "PATIENT_HASH_PEPPER must be set to a 32+ char secret in production",
    );
  }
}
