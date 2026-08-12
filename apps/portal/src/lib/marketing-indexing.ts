// Search-discovery policy for public Zorva pages.
//
// A route belongs in REVIEWED_MARKETING_ROUTES only after its copy and public
// claims have the evidence described in docs/MARKETING_PUBLIC_LAUNCH_GATES.md.
// Keep every other public marketing route in DEFERRED_MARKETING_PREFIXES.

export const REVIEWED_MARKETING_ROUTES = [
  "",
  "/contact",
  "/how-it-works",
] as const;

export const DEFERRED_MARKETING_PREFIXES = [
  "/about",
  "/blog",
  "/calculator",
  "/careers",
  "/case-studies",
  "/changelog",
  "/compare",
  "/demo-request",
  "/faq",
  "/for",
  "/glossary",
  "/legal",
  "/pilot",
  "/press",
  "/pricing",
  "/security",
  "/security.pdf",
  "/status",
  "/technical",
  "/trust",
  "/try",
  "/what-zorva-finds",
] as const;
