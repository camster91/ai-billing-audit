import type { Metadata } from "next";

/**
 * Safe fallback metadata for any public page that does not provide its own
 * route metadata. Keep this capability-focused: individual claims belong on
 * a reviewed route with its supporting evidence.
 */
export const publicMarketingMetadata: Metadata = {
  metadataBase: new URL("https://zorva.ashbi.ca"),
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
