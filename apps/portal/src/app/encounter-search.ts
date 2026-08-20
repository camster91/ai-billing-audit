// Encounter search helper extracted from apps/portal/src/app/not-found.tsx
// so the failure-vs-empty distinction can be unit-tested without
// mounting the React component.
//
// Issue #67: a non-OK response, an aborted request, a JSON parse
// failure, and a verified empty result must each be reported to
// the caller as a distinct `outcome`. The caller renders a
// recoverable failure message for the first three and a "no
// matches" message only for the last.
//
// Returned shape:
//   { outcome: "empty" }                          — 2xx, results: []
//   { outcome: "results", results: SearchResult[] } — 2xx, results: [...]
//   { outcome: "http_error", status: number }     — non-2xx
//   { outcome: "network_error", message: string }  — fetch / parse threw

export interface SearchResult {
  id: string;
  dateOfService: string;
  patientHash: string;
  isFlagged: boolean;
}

export type SearchOutcome =
  | { outcome: "empty" }
  | { outcome: "results"; results: SearchResult[] }
  | { outcome: "http_error"; status: number }
  | { outcome: "network_error"; message: string };

/**
 * Issue a /api/encounters/search request and return a structured
 * outcome. The `fetchImpl` parameter defaults to the global fetch
 * but is injectable so unit tests can supply a mock.
 */
export async function searchEncounters(
  query: string,
  fetchImpl: typeof fetch = fetch,
): Promise<SearchOutcome> {
  let r: Response;
  try {
    r = await fetchImpl(
      `/api/encounters/search?q=${encodeURIComponent(query)}`,
    );
  } catch (e) {
    return {
      outcome: "network_error",
      message: e instanceof Error ? e.message : "fetch failed",
    };
  }
  if (!r.ok) {
    return { outcome: "http_error", status: r.status };
  }
  let body: { results?: SearchResult[] };
  try {
    body = (await r.json()) as { results?: SearchResult[] };
  } catch (e) {
    return {
      outcome: "network_error",
      message: e instanceof Error ? e.message : "invalid JSON",
    };
  }
  const results = body.results ?? [];
  if (results.length === 0) {
    return { outcome: "empty" };
  }
  return { outcome: "results", results };
}
