import { EncounterListSkeleton } from "@/components/Skeleton";
import styles from "../shell.module.css";

export default function EncountersLoading() {
  return (
    <main id="main" className={styles.shell} aria-busy="true">
      <h1 className={styles.heading}>Encounters</h1>
      <p className={styles.subheading}>Loading encounter list…</p>
      <EncounterListSkeleton />
    </main>
  );
}
