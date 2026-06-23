import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "AI Pre-Bill Audit",
    template: "%s — AI Pre-Bill Audit",
  },
  description:
    "AI pre-bill audit catches what your billing team misses. Region-pinned " +
    "data, hash-chain audit log, AKS-safe-harbor flat-fee pricing.",
  // Live demo is not indexable. Prevent search engines from accidentally
  // indexing the marketing portal at https://ai-billing-audit.ashbi.ca.
  robots: {
    index: false,
    follow: false,
    nocache: true,
    googleBot: {
      index: false,
      follow: false,
      nocache: true,
    },
  },
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
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <header className="site-header">
          <div className="site-header-inner">
            <Link href="/" className="site-brand">
              AI Pre-Bill Audit
            </Link>
            <nav aria-label="Primary" className="site-nav">
              {NAV.map((n) => (
                <Link key={n.href} href={n.href} className="site-nav-link">
                  {n.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
