// /not-found — custom 404 page with search instead of "page not found".
//
// Kanban: t_968c868b on board 'product-ux'.
//
// Default Next.js 404 is "404 — This page could not be found." That's
// a dead end for a biller who followed a stale bookmark to an old
// encounter id. We replace it with:
//   - "We couldn't find that page"
//   - A search box that searches recent encounters in the active tenant
//   - Two quick-jump links: /encounters, /dashboard
//
// The search is a client-side fetch to /api/encounters/search.

"use client";

import { useState } from "react";
import Link from "next/link";
import styles from "./not-found.module.css";

interface SearchResult {
  id: string;
  dateOfService: string;
  patientHash: string;
  isFlagged: boolean;
}

export default function NotFound() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);

  async function runSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setSearched(false);
    try {
      const r = await fetch(`/api/encounters/search?q=${encodeURIComponent(query)}`);
      if (r.ok) {
        const j = await r.json();
        setResults(j.results ?? []);
      } else {
        setResults([]);
      }
    } finally {
      setSearching(false);
      setSearched(true);
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
          />
          <button type="submit" className={styles.searchButton} disabled={searching}>
            {searching ? "Searching…" : "Search"}
          </button>
        </form>

        {searched && results.length === 0 && (
          <p className={styles.noResults}>No matches in this clinic.</p>
        )}
        {results.length > 0 && (
          <ul className={styles.results}>
            {results.slice(0, 10).map((r) => (
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
        )}

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
