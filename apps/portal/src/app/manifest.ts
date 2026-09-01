import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Zorva",
    short_name: "Zorva",
    description: "Human-reviewed pre-submit workflow for Alberta clinic billing teams.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#07111D",
    theme_color: "#0D9488",
    icons: [
      {
        src: "/app-icons/android-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/app-icons/android-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
