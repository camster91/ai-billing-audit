// KeyboardShortcuts.tsx — encounter-detail keyboard shortcuts.
//
// Kanban: t_d86b072a on board 'product-ux'.
//
// Bindings:
//   A → accept focused finding (or top pending if nothing focused)
//   D → dismiss focused finding (or top pending)
//   R → re-run the auditor on this encounter (POST /api/encounters/{id}/re-run)
//   F → flag finding (sets dismissReason='flag' so it shows up in next week's report)
//   J → next finding (focus)
//   K → previous finding (focus)
//   U → undo last accept/dismiss (within the 5s window — t_f9a8d929)
//
// We DO NOT bind these when focus is in a form field (input, textarea,
// select, contenteditable), to avoid eating keystrokes a biller is
// typing into a dismiss-reason textarea.
//
// A "?" anywhere opens the cheat-sheet dialog.

"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./keyboard-shortcuts.module.css";

export interface KeyboardShortcutHandlers {
  onAccept: () => void;
  onDismiss: () => void;
  onRerun: () => void;
  onFlag: () => void;
  onNext: () => void;
  onPrev: () => void;
  onUndo: () => void;
}

function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return true;
  if (el.isContentEditable) return true;
  return false;
}

export function useEncounterKeyboardShortcuts(h: KeyboardShortcutHandlers) {
  // We keep a ref to the latest handlers so the listener we install
  // once on mount always sees the current closure.
  const ref = useRef(h);
  ref.current = h;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (isTypingTarget(e.target)) return;
      // Cmd/Ctrl-modified keys we leave alone (browser shortcuts).
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const key = e.key.toLowerCase();
      switch (key) {
        case "a": ref.current.onAccept(); break;
        case "d": ref.current.onDismiss(); break;
        case "r": ref.current.onRerun(); break;
        case "f": ref.current.onFlag(); break;
        case "j": ref.current.onNext(); break;
        case "k": ref.current.onPrev(); break;
        case "u": ref.current.onUndo(); break;
        default: return;
      }
      // Prevent scroll-on-space, etc., but only after we've handled it.
      e.preventDefault();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

export function KeyboardShortcutsCheatSheet() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (isTypingTarget(e.target)) return;
      if (e.key === "?") {
        setOpen((v) => !v);
        e.preventDefault();
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  if (!open) return null;
  return (
    <div className={styles.backdrop} role="dialog" aria-modal="true" aria-label="Keyboard shortcuts">
      <div className={styles.sheet}>
        <h2 className={styles.title}>Keyboard shortcuts</h2>
        <dl className={styles.list}>
          <dt><kbd>A</kbd></dt><dd>Accept focused finding</dd>
          <dt><kbd>D</kbd></dt><dd>Dismiss focused finding</dd>
          <dt><kbd>R</kbd></dt><dd>Re-run auditor</dd>
          <dt><kbd>F</kbd></dt><dd>Flag finding (for follow-up)</dd>
          <dt><kbd>J</kbd> / <kbd>K</kbd></dt><dd>Next / previous finding</dd>
          <dt><kbd>U</kbd></dt><dd>Undo last accept/dismiss (5s window)</dd>
          <dt><kbd>?</kbd></dt><dd>Show this cheat-sheet</dd>
          <dt><kbd>Esc</kbd></dt><dd>Close this cheat-sheet</dd>
        </dl>
        <button
          type="button"
          className={styles.closeButton}
          onClick={() => setOpen(false)}
          autoFocus
        >
          Close
        </button>
      </div>
    </div>
  );
}
