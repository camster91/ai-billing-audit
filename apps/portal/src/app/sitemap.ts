import type { MetadataRoute } from "next";

const SITE_URL = "https://zorva.ashbi.ca";

const PUBLIC_ROUTES = [
  "",
  "/contact",
  "/how-it-works",
] as const;

export default function sitemap(): MetadataRoute.Sitemap {
  return PUBLIC_ROUTES.map((route) => ({
    url: `${SITE_URL}${route}`,
    changeFrequency: route === "" ? "weekly" : "monthly",
    priority: route === "" ? 1 : 0.7,
  }));
}
