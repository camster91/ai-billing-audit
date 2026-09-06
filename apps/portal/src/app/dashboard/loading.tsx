import { DashboardSkeleton } from "@/components/Skeleton";
import styles from "../shell.module.css";

export default function DashboardLoading() {
  return (
    <main id="main" className={styles.shell} aria-busy="true">
      <h1 className={styles.heading}>Dashboard</h1>
      <p className={styles.subheading}>Loading your clinic overview…</p>
      <DashboardSkeleton />
    </main>
  );
}
