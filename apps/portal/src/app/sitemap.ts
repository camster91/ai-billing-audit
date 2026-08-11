import type { MetadataRoute } from "next";

const SITE_URL = "https://zorva.ashbi.ca";

const PUBLIC_ROUTES = [
  "",
  "/about",
  "/calculator",
  "/case-studies",
  "/changelog",
  "/compare",
  "/contact",
  "/faq",
  "/for/family-medicine",
  "/how-it-works",
  "/legal/privacy",
  "/legal/terms",
  "/pilot",
  "/press",
  "/pricing",
  "/security",
  "/status",
  "/technical",
  "/trust",
  "/what-zorva-finds",
] as const;

export default function sitemap(): MetadataRoute.Sitemap {
  return PUBLIC_ROUTES.map((route) => ({
    url: `${SITE_URL}${route}`,
    lastModified: new Date(),
    changeFrequency: route === "" ? "weekly" : "monthly",
    priority: route === "" ? 1 : 0.7,
  }));
}
