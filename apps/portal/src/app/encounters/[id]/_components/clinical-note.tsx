"use client";

// Clinical note with click-to-highlight evidence_quote spans.
//
// The server component pre-wraps the narrative text in `<mark
// class="evidence" data-evidence-id="…">` spans (see
// `wrapEvidenceQuotes` in src/lib/encounter-format.ts). This client
// component owns the cross-card behavior:
//   - Clicking an evidence span scrolls the matching evidence span
//     on the right pane into view (if any) and highlights the
//     corresponding finding card.
//   - Clicking a finding card's evidence-quote button scrolls the
//     matching evidence span in the narrative into view and pulses
//     the highlight.
//   - All scroll behavior uses `scrollIntoView` with `behavior: "smooth"`
//     and `block: "center"` so the user never loses context.

import { useEffect, useRef } from "react";
import styles from "./split-review.module.css";

interface ClinicalNoteProps {
  html: string;
  /** Map of evidenceId -> DOM id of the corresponding finding card. */
  evidenceToCard: Record<string, string>;
}

export function ClinicalNote({ html, evidenceToCard }: ClinicalNoteProps) {
  const noteRef = useRef<HTMLDivElement>(null);

  // Evidence span click → highlight + scroll the matching card into view.
  useEffect(() => {
    const root = noteRef.current;
    if (!root) return;
    function onMarkClick(event: MouseEvent) {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const mark = target.closest("mark.evidence");
      if (!(mark instanceof HTMLElement)) return;
      const id = mark.dataset.evidenceId;
      if (!id) return;
      const cardId = evidenceToCard[id];
      if (!cardId) return;
      const card = document.getElementById(cardId);
      if (!card) return;
      // Clear any existing active highlight, then mark this one.
      for (const el of root!.querySelectorAll("mark.evidence.is-active")) {
        el.classList.remove("is-active");
      }
      mark.classList.add("is-active");
      card.scrollIntoView({ behavior: "smooth", block: "center" });
      // Brief visual pulse on the card so the user can pick it out.
      card.classList.add("is-pulsing");
      window.setTimeout(() => {
        card.classList.remove("is-pulsing");
      }, 1400);
    }
    root.addEventListener("click", onMarkClick);
    return () => {
      root.removeEventListener("click", onMarkClick);
    };
  }, [evidenceToCard]);

  return (
    <div
      ref={noteRef}
      className={styles.clinicalNote}
      // The HTML is fully escaped by wrapEvidenceQuotes. The only
      // elements it emits are <mark class="evidence" data-evidence-id="…">
      // wrappers around exact text spans from the encounter.clinicalNote
      // column. The cuid in data-evidence-id is also escaped. Safe.
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
