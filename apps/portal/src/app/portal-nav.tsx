// Shared top nav for the auth-gated portal pages.
//
// Renders the spec route list as horizontal links, plus a tenant
// status chip on the right showing the active tenant name and a
// subscription-status dot (green/amber/red). The "active" route
// gets a highlighted background. Pages pass `current` so the nav
// knows which entry to highlight.
//
// Server component (no client JS) — the link set is static.

import Link from "next/link";
import { ActiveTenant } from "@/lib/active-tenant";
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
  const dotClass =
    tenant.subscriptionStatus === "past_due"
      ? `${styles.tenantDot} ${styles.tenantDotPastDue}`
      : tenant.subscriptionStatus === "canceled"
        ? `${styles.tenantDot} ${styles.tenantDotCanceled}`
        : styles.tenantDot;

  return (
    <nav className={styles.nav} aria-label="Portal sections">
      <span className={styles.brand}>AI Billing Portal</span>
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
      <span className={styles.tenantChip} title={`Tier: ${tenant.tier} · Status: ${tenant.subscriptionStatus}`}>
        <span className={dotClass} />
        {tenant.name}
      </span>
    </nav>
  );
}
