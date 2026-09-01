// src/lib/fastapi.ts
//
// Typed fetch wrapper for the FastAPI backend at
// https://ai-billing-audit.ashbi.ca.
//
// The portal at https://zorva.ashbi.ca fetches three read-only
// endpoints from this wrapper to surface denial-risk + appeal-letter
// UI on the encounter-detail page:
//
//   - GET /api/encounters/{id}/denial-risk    → DenialRiskPanel
//   - GET /api/encounters/{id}/appeal-letter  → AppealLetterPanel
//   - GET /api/encounters/{id}/appeal-letters → AppealLettersList
//
// Every request carries a short-lived tenant principal signed by the portal
// plus the service bearer token. The wrapper also owns audit enqueue and
// result polling, so credentials remain server-side.
//
// Legacy and pre-dispatch 404s become a graceful unavailable state.

import {
  buildFastApiAuthHeaders,
  type FastApiPrincipal,
} from "@/lib/fastapi-principal";
import { createHash } from "node:crypto";

const FASTAPI_BASE_URL =
  process.env.FASTAPI_BASE_URL ??
  process.env.NEXT_PUBLIC_FASTAPI_URL ??
  "https://ai-billing-audit.ashbi.ca";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Per-finding denial-risk breakdown from the FastAPI's
 * `/api/encounters/{id}/denial-risk` endpoint. Mirrors
 * `src/ai_billing_audit/denial_risk.py` on the FastAPI side.
 */
export interface DenialRiskPerFinding {
  finding_id: string;
  rule_id: string;
  severity: "low" | "medium" | "high" | "critical";
  category: string;
  weight: number;
  contributes_to_risk: boolean;
}

export interface DenialRisk {
  encounter_id: string;
  /** 0.0–1.0 (or null when no findings exist). */
  denial_probability: number | null;
  tier: "low" | "medium" | "high" | "critical" | "n/a";
  n_findings: number;
  per_finding: DenialRiskPerFinding[];
  /** Empty when no finding dominates; otherwise the highest-weight finding. */
  top_risk: DenialRiskPerFinding | null;
}

export interface AppealLetter {
  letter_id: string;
  encounter_id: string;
  subject: string;
  body_markdown: string;
  generated_at: string;
  basis: string;
  cited_rule_ids: string[];
  requested_action: string;
}

export interface AppealLetterSummary {
  letter_id: string;
  encounter_id: string;
  subject: string;
  basis: string;
  requested_action: string;
  generated_at: string;
  has_outcome: boolean;
  outcome_status?:
    | "won"
    | "lost"
    | "withdrawn"
    | "pending"
    | "did_not_file";
}

export type FastApiResult<T> =
  | { kind: "ok"; data: T }
  | { kind: "not_found" } // FastAPI has no record of this encounter_id
  | { kind: "error"; status: number; message: string };

export interface PortalAuditSubmission {
  encounterId: string;
  patientHash: string;
  providerNpi: string;
  dateOfService: string;
  cptCodes: string[];
  diagnosisCodes: string[];
  clinicalNote: string;
}

export interface Portal837PreviewRow {
  encounter_id: string | null;
  patient_id: string | null;
  NPI: string | null;
  date_of_service: string | null;
  CPT_codes: string[];
  diagnosis_codes: string[];
  source_filename: string;
  errors: string[];
}

export interface Portal837Preview {
  filename: string;
  rows: Portal837PreviewRow[];
  error?: string;
}

export interface EngineFinding {
  finding_id: string;
  category: string;
  severity: number;
  rule_id?: string;
  rule_ids?: string[];
  suggested_code?: string | null;
  quote: string;
  explanation: string;
}

export interface PortalAuditJob {
  job_id: string;
  encounter_id: string;
  status: "queued" | "running" | "done" | "failed" | "canceled";
  error: string | null;
  result: { summary?: string; findings: EngineFinding[] } | null;
}

interface EngineRequestOptions {
  fetchImpl?: typeof fetch;
  bearerToken?: string;
  signingSecret?: string;
}

export type PortalAuditSubmitResult =
  | { kind: "ok"; jobId: string; statusUrl: string; dedupHit: boolean }
  | { kind: "error"; status: number; message: string };

export type PortalAuditJobResult =
  | { kind: "ok"; job: PortalAuditJob }
  | { kind: "not_found" }
  | { kind: "error"; status: number; message: string };

export async function previewPortal837P(
  fileName: string,
  bytes: Buffer,
  principal: FastApiPrincipal,
  options: EngineRequestOptions = {},
): Promise<FastApiResult<Portal837Preview>> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const authHeaders = buildFastApiAuthHeaders(principal, {
    bearerToken: options.bearerToken,
    signingSecret: options.signingSecret,
  });
  const form = new FormData();
  form.set(
    "file",
    new Blob([new Uint8Array(bytes)], { type: "application/octet-stream" }),
    fileName,
  );
  let response: Response;
  try {
    response = await fetchImpl(`${FASTAPI_BASE_URL}/encounters/upload/preview`, {
      method: "POST",
      credentials: "omit",
      headers: { Accept: "application/json", ...authHeaders },
      body: form,
      cache: "no-store",
    });
  } catch (error) {
    return {
      kind: "error",
      status: 0,
      message: error instanceof Error ? error.message : String(error),
    };
  }
  if (!response.ok) {
    return {
      kind: "error",
      status: response.status,
      message: (await response.text()).slice(0, 500),
    };
  }
  try {
    return { kind: "ok", data: (await response.json()) as Portal837Preview };
  } catch (error) {
    return {
      kind: "error",
      status: response.status,
      message: `JSON parse failed: ${error instanceof Error ? error.message : String(error)}`,
    };
  }
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

async function fastapiFetch<T>(
  path: string,
  principal: FastApiPrincipal,
  init: RequestInit = {},
): Promise<FastApiResult<T>> {
  const url = `${FASTAPI_BASE_URL}${path}`;
  let res: Response;
  try {
    const authHeaders = buildFastApiAuthHeaders(principal);
    res = await fetch(url, {
      ...init,
      // The portal's session cookie is httpOnly + SameSite=Lax by
      // default; we don't send it cross-origin to the FastAPI. The
      // CORS-configured FastAPI endpoints are public-read.
      credentials: "omit",
      headers: {
        Accept: "application/json",
        ...authHeaders,
        ...(init.headers ?? {}),
      },
      // Next.js fetch cache: revalidate every 5 min so a re-audit on
      // the FastAPI shows up in the portal without a full page reload.
      // (Setting `next: { revalidate: 300 }` only works inside server
      // components; this helper runs on both sides, so callers opt in.)
    });
  } catch (e) {
    return {
      kind: "error",
      status: 0,
      message: e instanceof Error ? e.message : String(e),
    };
  }
  if (res.status === 404) {
    return { kind: "not_found" };
  }
  if (!res.ok) {
    let body = "";
    try {
      body = await res.text();
    } catch {
      // ignore — keep body empty
    }
    return {
      kind: "error",
      status: res.status,
      message: body.slice(0, 500),
    };
  }
  try {
    const data = (await res.json()) as T;
    return { kind: "ok", data };
  } catch (e) {
    return {
      kind: "error",
      status: res.status,
      message: `JSON parse failed: ${e instanceof Error ? e.message : String(e)}`,
    };
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Fetch the denial-risk score for an encounter. Returns:
 *
 *   - `{ kind: "ok", data }`           — FastAPI has an audit result
 *   - `{ kind: "not_found" }`          — FastAPI has no record of this encounter_id
 *                                        (the portal and FastAPI use separate data
 *                                        stores; many portal IDs don't match)
 *   - `{ kind: "error", status, msg }` — network / 5xx / parse error
 */
export async function fetchDenialRisk(
  encounterId: string,
  principal: FastApiPrincipal,
): Promise<FastApiResult<DenialRisk>> {
  return fastapiFetch<DenialRisk>(
    `/api/encounters/${encodeURIComponent(encounterId)}/denial-risk`,
    principal,
  );
}

/**
 * Fetch the most recent appeal letter for an encounter.
 *
 * Returns the first element of `fetchAppealLetters()` (the list is
 * ordered newest-first by the FastAPI). The FastAPI has no
 * single-letter GET endpoint — only POST (generate) and a list GET.
 * Calling `appeal-letter` (singular) over GET would hit a 405
 * method-not-allowed; this helper wraps the list and unwraps [0].
 */
export async function fetchLatestAppealLetter(
  encounterId: string,
  principal: FastApiPrincipal,
): Promise<FastApiResult<AppealLetterSummary | null>> {
  const result = await fetchAppealLetters(encounterId, principal);
  if (result.kind !== "ok") {
    // Propagate not_found / error so the caller can render the right
    // fallback. We can't distinguish "no letters yet" from
    // "encounter not in registry" here — the caller should check the
    // original list response if that matters.
    return result;
  }
  return { kind: "ok", data: result.data[0] ?? null };
}

/**
 * Fetch the full history of appeal letters for an encounter (most
 * recent first). Used by the appeal-letter panel's "previous letters"
 * dropdown.
 */
export async function fetchAppealLetters(
  encounterId: string,
  principal: FastApiPrincipal,
): Promise<FastApiResult<AppealLetterSummary[]>> {
  return fastapiFetch<AppealLetterSummary[]>(
    `/api/encounters/${encodeURIComponent(encounterId)}/appeal-letters`,
    principal,
  );
}

export async function submitPortalAudit(
  submission: PortalAuditSubmission,
  principal: FastApiPrincipal,
  options: EngineRequestOptions = {},
): Promise<PortalAuditSubmitResult> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const authHeaders = buildFastApiAuthHeaders(principal, {
    bearerToken: options.bearerToken,
    signingSecret: options.signingSecret,
  });
  const idempotencyDigest = createHash("sha256")
    .update(`${principal.tenantId}\0${submission.encounterId}`, "utf8")
    .digest("hex");
  const response = await fetchImpl(`${FASTAPI_BASE_URL}/api/audits`, {
    method: "POST",
    credentials: "omit",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "Idempotency-Key": `portal-audit-${idempotencyDigest}`,
      ...authHeaders,
    },
    body: JSON.stringify({
      encounter_id: submission.encounterId,
      patient_id: submission.patientHash,
      NPI: submission.providerNpi,
      date_of_service: submission.dateOfService,
      CPT_codes: submission.cptCodes,
      diagnosis_codes: submission.diagnosisCodes,
      clinical_note: submission.clinicalNote,
    }),
    cache: "no-store",
  });
  if (!response.ok) {
    return {
      kind: "error",
      status: response.status,
      message: (await response.text()).slice(0, 500),
    };
  }
  const body = (await response.json()) as {
    job_id: string;
    status_url: string;
    dedup_hit?: boolean;
  };
  return {
    kind: "ok",
    jobId: body.job_id,
    statusUrl: body.status_url,
    dedupHit: Boolean(body.dedup_hit),
  };
}

export async function fetchPortalAuditJob(
  jobId: string,
  principal: FastApiPrincipal,
  options: EngineRequestOptions = {},
): Promise<PortalAuditJobResult> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const authHeaders = buildFastApiAuthHeaders(principal, {
    bearerToken: options.bearerToken,
    signingSecret: options.signingSecret,
  });
  const response = await fetchImpl(
    `${FASTAPI_BASE_URL}/encounters/upload/jobs/${encodeURIComponent(jobId)}`,
    {
      credentials: "omit",
      headers: { Accept: "application/json", ...authHeaders },
      cache: "no-store",
    },
  );
  if (response.status === 404) return { kind: "not_found" };
  if (!response.ok) {
    return {
      kind: "error",
      status: response.status,
      message: (await response.text()).slice(0, 500),
    };
  }
  return { kind: "ok", job: (await response.json()) as PortalAuditJob };
}

/** The configured FastAPI origin. Useful for the "Open in FastAPI"
 *  link on the encounter-detail page. */
export const FASTAPI_ORIGIN = FASTAPI_BASE_URL;

/**
 * Build the FastAPI encounter-detail URL for a given encounter_id.
 * Falls back to the FastAPI root if the id is empty.
 */
export function fastapiEncounterUrl(encounterId: string): string {
  if (!encounterId) return `${FASTAPI_BASE_URL}/`;
  return `${FASTAPI_BASE_URL}/encounter/${encodeURIComponent(encounterId)}`;
}
