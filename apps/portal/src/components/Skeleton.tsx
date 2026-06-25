// Skeleton.tsx — loading skeleton primitives for the Zorva portal.
//
// Kanban: t_0764e0ae on board 'product-ux'.
//
// Used in place of spinners for encounter detail and home loading
// states. The skeleton is layout-stable (no shift when real content
// lands) and announces `aria-busy="true"` to assistive tech.
//
// Usage:
//   <SkeletonBox width="60%" height="1.25rem" />
//   <SkeletonText lines={3} />
//   <SkeletonCard />
//
// All variants honor `prefers-reduced-motion: reduce` and disable the
// shimmer animation in that case.

import styles from "./Skeleton.module.css";

export interface SkeletonBoxProps {
  width?: string | number;
  height?: string | number;
  radius?: string;
  className?: string;
}

export function SkeletonBox({
  width = "100%",
  height = "0.75rem",
  radius,
  className,
}: SkeletonBoxProps) {
  const style: React.CSSProperties = {
    width: typeof width === "number" ? `${width}px` : width,
    height: typeof height === "number" ? `${height}px` : height,
    ...(radius ? { borderRadius: radius } : {}),
  };
  return (
    <div
      role="presentation"
      aria-hidden="true"
      className={`${styles.box} ${className ?? ""}`}
      style={style}
    />
  );
}

export interface SkeletonTextProps {
  lines?: number;
  lastLineWidth?: string;
  className?: string;
}

export function SkeletonText({
  lines = 3,
  lastLineWidth = "60%",
  className,
}: SkeletonTextProps) {
  return (
    <div
      role="presentation"
      aria-hidden="true"
      aria-busy="true"
      className={`${styles.text} ${className ?? ""}`}
    >
      {Array.from({ length: lines }).map((_, i) => (
        <SkeletonBox
          key={i}
          height="0.75rem"
          width={i === lines - 1 ? lastLineWidth : "100%"}
        />
      ))}
    </div>
  );
}

export function SkeletonCard({ className }: { className?: string }) {
  return (
    <div
      role="presentation"
      aria-hidden="true"
      aria-busy="true"
      className={`${styles.card} ${className ?? ""}`}
    >
      <div className={styles.cardHeader}>
        <SkeletonBox width="40%" height="1rem" />
        <SkeletonBox width="4rem" height="1rem" />
      </div>
      <div className={styles.cardBody}>
        <SkeletonText lines={2} />
      </div>
      <div className={styles.cardFooter}>
        <SkeletonBox width="6rem" height="2.25rem" radius="0.5rem" />
        <SkeletonBox width="6rem" height="2.25rem" radius="0.5rem" />
      </div>
    </div>
  );
}

/**
 * Encounter detail skeleton: matches the split-screen layout so the
 * transition from skeleton → real content has zero shift.
 */
export function EncounterDetailSkeleton() {
  return (
    <div role="presentation" aria-busy="true" aria-hidden="true"
         className={styles.encounterDetail}>
      <div className={styles.encounterLeft}>
        <SkeletonBox width="60%" height="1.75rem" />
        <SkeletonText lines={8} />
      </div>
      <div className={styles.encounterRight}>
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    </div>
  );
}

/**
 * Encounter list skeleton: a small batch of SkeletonCard-style rows.
 */
export function EncounterListSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div role="presentation" aria-busy="true" aria-hidden="true"
         className={styles.encounterList}>
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}
