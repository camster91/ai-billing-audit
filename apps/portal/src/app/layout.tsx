import type { Metadata, Viewport } from "next";
import Image from "next/image";
import Link from "next/link";
import {
  Inter,
  JetBrains_Mono,
  Fraunces,
  IBM_Plex_Mono,
} from "next/font/google";
import { MobileMenu } from "@/components/MobileMenu";
import AnalyticsBoot from "@/components/AnalyticsBoot";
import { Providers } from "@/components/Providers";
import { MarketingHeader } from "@/components/MarketingHeader";
import { publicMarketingMetadata } from "@/lib/public-marketing-metadata";
import "./globals.css";

// Zorva brand typefaces (see docs/BRANDING_TYPOGRAPHY.md).
// Inter is the default body + heading face; JetBrains Mono handles code.
// Geist + Geist_Mono were declared here for backward compat with
// any component referencing --font-geist-* — but the P11 round-2
// perf sweep confirmed zero CSS consumers (grep -rE "var\(--font-geist"
// returns 0 hits). Dropped to save ~88KB of web-font payload on every
// page. If a future component needs Geist, add it back with an
// explicit consumer reference.
//
// Fraunces (serif display) and IBM Plex Mono are loaded here for the
// / landing page editorial system. They are declared as CSS variables
// and consumed in page.module.css; the actual font files are
// self-hosted by `next/font/google` at build time so the production
// CSP `font-src 'self' data:` is satisfied without an external
// stylesheet fetch.
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

// Fraunces: editorial serif for the marketing landing page display
// headings. next/font/google only accepts the standard 100-900 weight
// increments for Fraunces, so we pull 400 (body-weight display) +
// 500 (slightly emphasized headings) + 600 (strong display) with the
// italic axis for the editorial `<em>` accents. This keeps the
// self-hosted font payload well under 50KB gzipped — same approach
// Inter + JetBrains_Mono already use below.
const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
});

// IBM Plex Mono: monospace for the landing page micro-labels
// (eyebrow tags, "PRE-SUBMIT REVIEW" mockup header, claim-line
// codes, FAQ plus-mark, etc.). 400 + 500 covers both body and
// slightly-emphasized micro-copy without bloating the request.
const ibmPlexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500"],
});

export const metadata: Metadata = publicMarketingMetadata;

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
  { href: "/how-it-works", label: "How it works" },
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
      className={`${inter.variable} ${jetbrainsMono.variable} ${fraunces.variable} ${ibmPlexMono.variable}`}
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
        <MarketingHeader links={NAV} />
        <AnalyticsBoot />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
