import { SkeletonCard, SkeletonText } from "@/components/Skeleton";
import styles from "../shell.module.css";

export default function BillingLoading() {
  return (
    <main id="main" className={styles.shell} aria-busy="true">
      <h1 className={styles.heading}>Billing</h1>
      <p className={styles.subheading}>Loading subscription…</p>
      <SkeletonCard />
      <div className={styles.card}>
        <SkeletonText lines={3} />
      </div>
    </main>
  );
}
