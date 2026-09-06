"use client";

// Marketing site header. Hidden on authenticated portal routes so
// PortalNav is the only chrome (avoids double-nav stacking).

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { MobileMenu, type MobileMenuLink } from "@/components/MobileMenu";

const PORTAL_PREFIXES = [
  "/dashboard",
  "/encounters",
  "/findings",
  "/billing",
  "/team",
  "/settings",
  "/portal",
  "/hq",
  "/login",
  "/verify-request",
  "/auth",
] as const;

export function MarketingHeader({
  links,
}: {
  links: ReadonlyArray<MobileMenuLink>;
}) {
  const pathname = usePathname() || "/";
  const hide = PORTAL_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
  if (hide) return null;

  return (
    <header className="site-header">
      <div className="site-header-inner">
        <Link href="/" className="site-brand" aria-label="Zorva — home">
          <Image
            src="/brand/zorva-mark-dark.svg"
            width={24}
            height={24}
            alt=""
            aria-hidden="true"
            priority
          />
          <span>Zorva</span>
        </Link>
        <nav aria-label="Primary" className="site-nav site-nav-desktop">
          {links.map((n) => (
            <Link key={n.href} href={n.href} className="site-nav-link">
              {n.label}
            </Link>
          ))}
        </nav>
        <MobileMenu links={links} />
      </div>
    </header>
  );
}
