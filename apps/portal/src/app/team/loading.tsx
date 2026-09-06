import { SkeletonCard, SkeletonText } from "@/components/Skeleton";
import styles from "../shell.module.css";

export default function TeamLoading() {
  return (
    <main id="main" className={styles.shell} aria-busy="true">
      <h1 className={styles.heading}>Team</h1>
      <p className={styles.subheading}>Loading members…</p>
      <SkeletonCard />
      <div className={styles.card}>
        <SkeletonText lines={4} />
      </div>
    </main>
  );
}
