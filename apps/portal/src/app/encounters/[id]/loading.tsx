import { EncounterDetailSkeleton } from "@/components/Skeleton";
import styles from "../../shell.module.css";

export default function EncounterDetailLoading() {
  return (
    <main id="main" className={styles.shell} aria-busy="true">
      <h1 className={styles.heading}>Encounter</h1>
      <p className={styles.subheading}>Loading review workspace…</p>
      <EncounterDetailSkeleton />
    </main>
  );
}
