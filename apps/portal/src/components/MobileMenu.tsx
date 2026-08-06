"use client";

// Mobile hamburger menu for the public site header (kanban t_b55def09).
//
// At <640px the desktop nav collapses behind a hamburger button. Tapping
// the button opens a slide-down panel that renders the same nav links as
// the desktop nav. The button uses aria-expanded / aria-controls and the
// panel uses role="dialog" with aria-modal="true" so screen readers
// announce the menu correctly. Esc closes the panel; clicking a link also
// closes it. Focus is trapped inside the panel while it's open so the
// Tab key cycles through the panel links only.
//
// The component is intentionally minimal: no framer-motion, no animation
// libraries — just a single useState + CSS transitions on
// [data-open="true"] attributes. That keeps the JS payload tiny and
// makes the menu resilient to JS hydration delays (the markup is the
// same on server and client; only the `data-open` attr flips).

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

export interface MobileMenuLink {
  href: string;
  label: string;
}

export interface MobileMenuProps {
  links: ReadonlyArray<MobileMenuLink>;
}

export function MobileMenu({ links }: MobileMenuProps) {
  const [open, setOpen] = useState(false);
  const panelId = "mobile-menu-panel";
  const buttonId = "mobile-menu-button";
  const panelRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  const close = useCallback(() => setOpen(false), []);

  // Lock body scroll while the panel is open so the page underneath
  // doesn't move on touch devices.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Esc closes the panel and returns focus to the trigger button.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close();
        buttonRef.current?.focus();
      } else if (e.key === "Tab" && panelRef.current) {
        // Simple focus trap: cycle Tab between first link and a close
        // sentinel (the button) when the panel has focus inside it.
        const focusables = panelRef.current.querySelectorAll<HTMLElement>(
          "a[href], button:not([disabled])",
        );
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement as HTMLElement | null;
        if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close]);

  // Move focus into the panel when it opens.
  useEffect(() => {
    if (!open) return;
    const first = panelRef.current?.querySelector<HTMLElement>("a[href]");
    first?.focus();
  }, [open]);

  return (
    <>
      <button
        ref={buttonRef}
        id={buttonId}
        type="button"
        className="mobile-menu-button"
        aria-label={open ? "Close menu" : "Open menu"}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        <span aria-hidden="true" className="mobile-menu-bars" data-open={open}>
          <span />
          <span />
          <span />
        </span>
      </button>

      {open && (
        <div
          className="mobile-menu-backdrop"
          onClick={close}
          aria-hidden="true"
        />
      )}
      <div
        ref={panelRef}
        id={panelId}
        className="mobile-menu-panel"
        data-open={open}
        role="dialog"
        aria-hidden={!open}
        aria-modal={open ? "true" : undefined}
        aria-label="Site navigation"
      >
        <nav aria-label="Primary mobile">
          <ul className="mobile-menu-list">
            {links.map((l) => (
              <li key={l.href}>
                <Link
                  href={l.href}
                  className="mobile-menu-link"
                  onClick={close}
                  tabIndex={open ? 0 : -1}
                >
                  {l.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </>
  );
}
