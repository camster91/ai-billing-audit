import Link from "next/link";
import styles from "./hq.module.css";

export function HqNav() {
  return (
    <nav className={styles.nav} aria-label="Zorva HQ sections">
      <Link href="/hq" className={styles.brand}>Zorva HQ</Link>
      <Link href="/hq" className={styles.navLink}>Today</Link>
      <Link href="/hq/leads" className={styles.navLink}>Leads</Link>
      <Link href="/hq/clients" className={styles.navLink}>Clients</Link>
      <Link href="/hq/support" className={styles.navLink}>Support</Link>
      <Link href="/dashboard" className={styles.navLink}>Clinic portal</Link>
    </nav>
  );
}
