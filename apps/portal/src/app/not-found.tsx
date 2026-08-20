// /not-found — custom 404 page with search instead of "page not found".
//
// Kanban: t_968c868b on board 'product-ux'. Issue #67 — distinguish
// failed encounter search from a verified empty result so a biller
// never sees "No matches in this clinic." when the API is down,
// the session expired, or the response was malformed.
//
// Default Next.js 404 is "404 — This page could not be found." That's
// a dead end for a biller who followed a stale bookmark to an old
// encounter id. We replace it with:
//   - "We couldn't find that page"
//   - A search box that searches recent encounters in the active tenant
//   - Two quick-jump links: /encounters, /dashboard
//
// The search is a client-side fetch to /api/encounters/search. The
// fetch + outcome mapping lives in ./encounter-search.ts so the
// failure-vs-empty distinction is unit-testable without mounting
// this component.

"use client";

import { useState } from "react";
import Link from "next/link";
import styles from "./not-found.module.css";
import { searchEncounters, type SearchResult } from "./encounter-search";

interface SearchUI {
  searched: boolean;
  searching: boolean;
  results: SearchResult[];
  /** A user-presentable failure message. Non-null blocks the "no matches" message. */
  errorMessage: string | null;
}

const INITIAL: SearchUI = {
  searched: false,
  searching: false,
  results: [],
  errorMessage: null,
};

export default function NotFound() {
  const [query, setQuery] = useState("");
  const [state, setState] = useState<SearchUI>(INITIAL);

  async function runSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    setState({ searched: false, searching: true, results: [], errorMessage: null });
    const outcome = await searchEncounters(q);
    if (outcome.outcome === "results") {
      setState({
        searched: true,
        searching: false,
        results: outcome.results,
        errorMessage: null,
      });
    } else if (outcome.outcome === "empty") {
      setState({
        searched: true,
        searching: false,
        results: [],
        errorMessage: null,
      });
    } else if (outcome.outcome === "http_error") {
      setState({
        searched: true,
        searching: false,
        results: [],
        errorMessage: httpErrorMessage(outcome.status),
      });
    } else {
      setState({
        searched: true,
        searching: false,
        results: [],
        errorMessage: "The search couldn't be completed. Check your connection and try again.",
      });
    }
  }

  return (
    <main className={styles.page}>
      <div className={styles.card}>
        <span className={styles.code}>404</span>
        <h1 className={styles.title}>We couldn&rsquo;t find that page.</h1>
        <p className={styles.lede}>
          The link may be old, or the encounter may have been deleted. Try
          searching, or jump back to a known-good starting point.
        </p>

        <form onSubmit={runSearch} className={styles.searchForm} role="search">
          <label htmlFor="not-found-search" className={styles.srOnly}>
            Search encounters
          </label>
          <input
            id="not-found-search"
            type="search"
            placeholder="Search by encounter id or patient hash"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className={styles.searchInput}
            autoComplete="off"
            aria-describedby="not-found-search-help"
          />
          <button type="submit" className={styles.searchButton} disabled={state.searching}>
            {state.searching ? "Searching…" : "Search"}
          </button>
        </form>
        <span id="not-found-search-help" className={styles.srOnly}>
          Press Enter to search. Use All encounters or Dashboard for a full list.
        </span>

        {state.errorMessage !== null ? (
          <div
            className={styles.errorBox}
            role="alert"
            aria-live="polite"
            data-testid="not-found-search-error"
          >
            <p className={styles.errorMessage}>{state.errorMessage}</p>
            <button
              type="button"
              className={styles.retryButton}
              onClick={(e) => {
                // re-submit the same query without the user re-typing it
                const form = (e.currentTarget.closest("main") ?? document).querySelector(
                  "form[role='search']",
                ) as HTMLFormElement | null;
                form?.requestSubmit();
              }}
            >
              Try again
            </button>
          </div>
        ) : null}

        {state.searched && !state.errorMessage && state.results.length === 0 ? (
          <p className={styles.noResults} data-testid="not-found-search-empty">
            No matches in this clinic.
          </p>
        ) : null}

        {state.results.length > 0 && !state.errorMessage ? (
          <ul className={styles.results}>
            {state.results.slice(0, 10).map((r) => (
              <li key={r.id}>
                <Link href={`/encounters/${r.id}`}>
                  {r.id}
                  <span className={styles.resultMeta}>
                    {r.dateOfService}
                    {r.isFlagged ? " · flagged" : ""}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : null}

        <nav className={styles.quickLinks} aria-label="Quick navigation">
          <Link href="/encounters" className={styles.quickLink}>
            All encounters
          </Link>
          <Link href="/dashboard" className={styles.quickLink}>
            Dashboard
          </Link>
        </nav>
      </div>
    </main>
  );
}

function httpErrorMessage(status: number): string {
  if (status === 401 || status === 403) {
    return "Your session has expired. Sign in again to search encounters.";
  }
  if (status === 404) {
    return "The search endpoint is not available right now. Try again in a moment.";
  }
  if (status === 429) {
    return "Too many searches in a short time. Wait a few seconds and try again.";
  }
  if (status >= 500) {
    return "The search service is temporarily unavailable. Please try again in a moment.";
  }
  return `The search couldn't be completed (status ${status}). Please try again.`;
}
