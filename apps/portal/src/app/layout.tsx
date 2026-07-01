import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { Inter, JetBrains_Mono } from "next/font/google";
import { MobileMenu } from "@/components/MobileMenu";
import "./globals.css";

// Zorva brand typefaces (see docs/BRANDING_TYPOGRAPHY.md).
// Inter is the default body + heading face; JetBrains Mono handles code.
// Geist + Geist_Mono were declared here for backward compat with
// any component referencing --font-geist-* — but the P11 round-2
// perf sweep confirmed zero CSS consumers (grep -rE "var\(--font-geist"
// returns 0 hits). Dropped to save ~88KB of web-font payload on every
// page. If a future component needs Geist, add it back with an
// explicit consumer reference.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Zorva — AI pre-bill audit for Alberta clinics",
    template: "%s — Zorva",
  },
  description:
    "AI pre-bill audit catches what your billing team misses. Region-pinned " +
    "data, hash-chain audit log, flat-fee pricing published in the IMA.",
  // Marketing pages are indexable so search engines can surface them.
  // Authenticated portal routes (/encounters, /findings, /billing,
  // /dashboard, /settings, /portal/*) each override this in their own
  // page.tsx with `robots: { index: false, follow: false }`.
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
    },
  },
  // OpenGraph + Twitter card defaults (kanban t_05e9b86a). Pages can
  // override per-route via their own `export const metadata: Metadata`.
  openGraph: {
    type: "website",
    siteName: "Zorva",
    title: "Zorva — AI pre-bill audit for Alberta clinics",
    description:
      "Zorva reads every Alberta claim against AHCIP and the SOMB before " +
      "submission, surfacing missed codes and underbilled modifiers that " +
      "drain your monthly revenue. Human-reviewed.",
  },
  twitter: {
    card: "summary_large_image",
    title: "Zorva — AI pre-bill audit for Alberta clinics",
    description:
      "Find the revenue your billers are leaving on the table.",
  },
};

// P11 UX sweep 2026-07-01: viewport meta tag. In Next.js 13+ the
// canonical pattern is to export `viewport` from the layout, NOT
// to put a <meta name="viewport"> in <head>. The latter results in
// a DUPLICATE viewport meta tag in the rendered HTML (Next.js
// auto-generates one and yours stacks on top of it), which is a
// spec violation. The viewportFit=cover bit lets the iPhone notch
// area be used for the sticky header without a white bar.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

// Marketing-site header. Public-only pages (/, /pricing, /how-it-works,
// /security) are linked from here so the security page is reachable from
// the main nav. Authenticated portal pages render their own chrome and
// ignore this header because the body element has display: contents and
// the portal-root pages start with their own <main>.
const NAV = [
  { href: "/", label: "Home" },
  { href: "/pricing", label: "Pricing" },
  { href: "/how-it-works", label: "How it works" },
  { href: "/security", label: "Security" },
  { href: "/contact", label: "Contact" },
];

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable}`}
    >
      <head>
        {/* Force the dark UA form so form controls + scrollbars render
            dark on first paint and never flash white. See AGENTS.md
            "dark-only design choice" note. (kanban t_9bf46d09) */}
        <meta name="color-scheme" content="dark" />
        {/* Privacy-friendly analytics (Plausible). Loaded only when
            NEXT_PUBLIC_PLAUSIBLE_DOMAIN is set at build time. We
            deliberately do NOT use Google Analytics — clinic privacy
            officers will flag it. See kanban t_54240aab.

            Note on Subresource Integrity (SRI): we intentionally do
            NOT pin a sha384 hash here. Plausible updates their
            script.js in place for bug-fixes and feature rollouts
            (event goals, revenue, etc.); pinning a hash would
            silently break the analytics on every update and require
            a code change + redeploy each time. The official
            Plausible installation snippet (plausible.io/docs) also
            omits SRI for exactly this reason. Risk is mitigated by
            serving Plausible over HTTPS, by their CSP and by the
            `data-domain` attribute which scopes events to our
            domain only. */}
        {process.env.NEXT_PUBLIC_PLAUSIBLE_DOMAIN ? (
          <script
            async
            defer
            data-domain={process.env.NEXT_PUBLIC_PLAUSIBLE_DOMAIN}
            src="https://plausible.io/js/script.js"
          />
        ) : null}
      </head>
      <body className="body">
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <header className="site-header">
          <div className="site-header-inner">
            <Link href="/" className="site-brand" aria-label="Zorva — home">
              Zorva
            </Link>
            <nav aria-label="Primary" className="site-nav site-nav-desktop">
              {NAV.map((n) => (
                <Link key={n.href} href={n.href} className="site-nav-link">
                  {n.label}
                </Link>
              ))}
            </nav>
            <MobileMenu links={NAV} />
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
