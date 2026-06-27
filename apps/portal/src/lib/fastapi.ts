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
// All three are public-read endpoints (the FastAPI's bearer-auth
// middleware whitelists them; they operate on the demo encounter
// registry, no PHI). The POST endpoints (generate appeal letter,
// log outcome) require a service-to-service bearer token that
// the portal doesn't have yet — those are out of scope here.
//
// The wrapper handles the 404 case gracefully: many portal-side
// encounter IDs don't exist in the FastAPI's audit registry
// (separate data stores), so the UI shows "deep audit not
// available" instead of a hard error.

const FASTAPI_BASE_URL =
  process.env.NEXT_PUBLIC_FASTAPI_URL ?? "https://ai-billing-audit.ashbi.ca";

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

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

async function fastapiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<FastApiResult<T>> {
  const url = `${FASTAPI_BASE_URL}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      // The portal's session cookie is httpOnly + SameSite=Lax by
      // default; we don't send it cross-origin to the FastAPI. The
      // CORS-configured FastAPI endpoints are public-read.
      credentials: "omit",
      headers: {
        Accept: "application/json",
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
): Promise<FastApiResult<DenialRisk>> {
  return fastapiFetch<DenialRisk>(
    `/api/encounters/${encodeURIComponent(encounterId)}/denial-risk`,
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
): Promise<FastApiResult<AppealLetterSummary | null>> {
  const result = await fetchAppealLetters(encounterId);
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
): Promise<FastApiResult<AppealLetterSummary[]>> {
  return fastapiFetch<AppealLetterSummary[]>(
    `/api/encounters/${encodeURIComponent(encounterId)}/appeal-letters`,
  );
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