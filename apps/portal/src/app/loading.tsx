// Root loading state for the portal.
//
// Shown during the initial root layout render + any segment-level
// Suspense boundaries that don't have their own loading.tsx.
// SkeletonCard is the canonical loading visual used across the
// portal so the page never flashes empty / "Loading..." text.
//
// P11 bug-sweep fix (2026-07-01): the portal had no root loading
// state, so first-paint on slow connections showed blank space or
// the default browser spinner.

import { SkeletonCard } from "@/components/Skeleton";

export default function Loading() {
  return (
    <div
      style={{
        maxWidth: 960,
        margin: "32px auto",
        padding: "0 20px",
        display: "grid",
        gap: 16,
      }}
      aria-label="Loading Zorva portal"
      aria-busy="true"
    >
      <SkeletonCard />
      <SkeletonCard />
      <SkeletonCard />
    </div>
  );
}