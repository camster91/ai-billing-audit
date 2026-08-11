import type { MetadataRoute } from "next";
import { REVIEWED_MARKETING_ROUTES } from "@/lib/marketing-indexing";

const SITE_URL = "https://zorva.ashbi.ca";

export default function sitemap(): MetadataRoute.Sitemap {
  return REVIEWED_MARKETING_ROUTES.map((route) => ({
    url: `${SITE_URL}${route}`,
    changeFrequency: route === "" ? "weekly" : "monthly",
    priority: route === "" ? 1 : 0.7,
  }));
}
