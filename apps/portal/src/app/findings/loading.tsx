import { FindingsListSkeleton } from "@/components/Skeleton";
import styles from "../shell.module.css";

export default function FindingsLoading() {
  return (
    <main id="main" className={styles.shell} aria-busy="true">
      <h1 className={styles.heading}>Findings</h1>
      <p className={styles.subheading}>Loading your review queue…</p>
      <FindingsListSkeleton />
    </main>
  );
}
