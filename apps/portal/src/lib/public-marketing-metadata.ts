import type { Metadata } from "next";

/**
 * Safe fallback metadata for any public page that does not provide its own
 * route metadata. Keep this capability-focused: individual claims belong on
 * a reviewed route with its supporting evidence.
 */
export const publicMarketingMetadata: Metadata = {
  metadataBase: new URL("https://zorva.ashbi.ca"),
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
      { url: "/favicon-16x16.png", sizes: "16x16", type: "image/png" },
    ],
    shortcut: "/favicon.ico",
    apple: [{ url: "/app-icons/ios-180.png", sizes: "180x180", type: "image/png" }],
  },
  title: {
    default: "Zorva | Pre-submit review for Alberta clinic billing teams",
    template: "%s | Zorva",
  },
  description:
    "A human-reviewed pre-submit workflow for Alberta clinic billing teams.",
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
    },
  },
  openGraph: {
    type: "website",
    siteName: "Zorva",
    title: "Zorva | Pre-submit review for Alberta clinic billing teams",
    description:
      "A human-reviewed pre-submit workflow for billing teams that want a clearer review queue before claims are sent.",
  },
  twitter: {
    card: "summary_large_image",
    title: "Zorva | Pre-submit review for Alberta clinic billing teams",
    description:
      "A human-reviewed pre-submit workflow for Alberta clinic billing teams.",
  },
};
