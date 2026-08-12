import type { Metadata } from "next";
import Link from "next/link";
import styles from "./contact.module.css";
import ContactForm from "./ContactForm";

export const metadata: Metadata = {
  title: "Contact Zorva",
  description:
    "Contact Zorva to discuss your clinic's pre-submit billing review workflow.",
  alternates: { canonical: "/contact" },
};

export default function ContactPage() {
  return (
    <div className={styles.page}>
      <main id="main" className={styles.main}>
        <header className={styles.header}>
          <span className={styles.eyebrow}>Contact</span>
          <h1>Tell us about the review workflow you want to improve.</h1>
          <p className={styles.lede}>
            Share a little about your clinic and current workflow. We review
            requests before following up with the appropriate next step.
          </p>
        </header>

        <ContactForm />

        <aside className={styles.altPath}>
          <h2>Want context first?</h2>
          <p>
            Read the{" "}
            <Link href="/how-it-works" className={styles.link}>
              how-it-works page
            </Link>{" "}
            for a plain-language overview of the review path.
          </p>
        </aside>
      </main>
    </div>
  );
}
