"use client";

// Shared top nav for the auth-gated portal pages.
//
// Desktop: horizontal links + tenant chip.
// Mobile (<720px): hamburger drawer with focus trap + Escape.
// Touch targets ≥ 44×44px; focus-visible rings for keyboard users.

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { ActiveTenant } from "@/lib/active-tenant";
import styles from "./shell.module.css";

const NAV_ITEMS: ReadonlyArray<{ href: string; label: string }> = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/encounters", label: "Encounters" },
  { href: "/findings", label: "Findings" },
  { href: "/billing", label: "Billing" },
  { href: "/team", label: "Team" },
  { href: "/settings", label: "Settings" },
];

interface PortalNavProps {
  current: string;
  tenant: ActiveTenant;
}

export function PortalNav({ current, tenant }: PortalNavProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close();
        buttonRef.current?.focus();
        return;
      }
      if (e.key !== "Tab" || !panelRef.current) return;
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
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close]);

  useEffect(() => {
    if (!open) return;
    const first = panelRef.current?.querySelector<HTMLElement>("a[href]");
    first?.focus();
  }, [open]);

  const dotClass =
    tenant.subscriptionStatus === "past_due"
      ? `${styles.tenantDot} ${styles.tenantDotPastDue}`
      : tenant.subscriptionStatus === "canceled"
        ? `${styles.tenantDot} ${styles.tenantDotCanceled}`
        : styles.tenantDot;

  return (
    <nav className={styles.nav} aria-label="Portal sections">
      <span className={styles.brand}>Zorva</span>

      <div className={styles.navDesktop}>
        {NAV_ITEMS.map((item) => {
          const active = current === item.href;
          const cls = active
            ? `${styles.navLink} ${styles.navLinkActive}`
            : styles.navLink;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cls}
              aria-current={active ? "page" : undefined}
            >
              {item.label}
            </Link>
          );
        })}
      </div>

      <span
        className={styles.tenantChip}
        title={`Tier: ${tenant.tier} · Status: ${tenant.subscriptionStatus}`}
      >
        <span className={dotClass} />
        {tenant.name}
      </span>

      <button
        ref={buttonRef}
        type="button"
        className={styles.navMenuButton}
        aria-label={open ? "Close menu" : "Open menu"}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={styles.navMenuIcon} data-open={open ? "true" : "false"} aria-hidden="true" />
      </button>

      {open ? (
        <div
          className={styles.navBackdrop}
          role="presentation"
          onClick={close}
        />
      ) : null}

      <div
        ref={panelRef}
        id={panelId}
        className={styles.navDrawer}
        data-open={open ? "true" : "false"}
        role="dialog"
        aria-modal="true"
        aria-label="Portal menu"
        hidden={!open}
      >
        {NAV_ITEMS.map((item) => {
          const active = current === item.href;
          const cls = active
            ? `${styles.navDrawerLink} ${styles.navLinkActive}`
            : styles.navDrawerLink;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cls}
              aria-current={active ? "page" : undefined}
              onClick={close}
            >
              {item.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
