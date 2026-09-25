"use client";

// /findings inbox — interactive client component.
//
// Owns the row-selection state, the two confirmation modals (bulk
// accept + bulk dismiss), and the filter form. Renders a multi-select
// table on top of the server-loaded row set, with the bulk action
// bar pinned to the top of the table once any rows are selected.
//
// The modals do their work via fetch() to the bulk API routes
// (`/api/findings/bulk/accept` and `/api/findings/bulk/dismiss`).
// On success the page reloads (router.refresh() is enough since the
// underlying rows are read in a server component) and the selection
// is cleared.
//
// Filter form: a plain HTML <form method="GET"> round-trips through
// the URL so filter/sort state survives refresh, exactly like the
// /encounters list. The status filter lives outside the form (it
// reuses the existing query-param shape) so the three multi-selects
// and the "Export CSV" link submit together.

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useTransition,
} from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import styles from "../../shell.module.css";
import { toUserFacingError } from "@/lib/ui-error";
import {
  FINDING_CATEGORY_LABEL,
  FINDING_STATUSES,
  type DismissReason,
  type FindingCategory,
  type FindingStatus,
} from "@/lib/encounter-types";

interface FindingRow {
  id: string;
  encounterId: string;
  dateOfService: string;
  category: FindingCategory;
  billingRuleReference: string;
  currentCode: string | null;
  suggestedCode: string | null;
  estFinancialImpactCents: number;
  providerName: string;
  providerNpi: string;
  payer: string;
}

interface FindingsInboxProps {
  rows: FindingRow[];
  categoryOptions: string[];
  providerOptions: string[];
  payerOptions: string[];
  initialStatus: FindingStatus;
  initialCategories: string[];
  initialProviders: string[];
  initialPayers: string[];
}

const DISMISS_REASONS: { value: DismissReason; label: string }[] = [
  { value: "wrong_payer_policy", label: "Wrong payer policy" },
  { value: "hallucinated_fact", label: "Hallucinated fact" },
  { value: "too_conservative", label: "Too conservative" },
  { value: "other_with_text", label: "Other (specify)" },
];

const BULK_FINDING_ID_MAX_CLIENT = 200;

function useModalAccessibility(onCancel: () => void, busy: boolean) {
  const modalRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef(onCancel);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  cancelRef.current = onCancel;

  useEffect(() => {
    previousFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const modal = modalRef.current;
    if (!modal) return;
    const focusable = () =>
      Array.from(
        modal.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], select:not([disabled]), textarea:not([disabled]), input:not([disabled])',
        ),
      );
    const first = focusable()[0];
    first?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!busy) cancelRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const controls = focusable();
      if (controls.length === 0) return;
      const firstControl = controls[0];
      const lastControl = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === firstControl) {
        event.preventDefault();
        lastControl.focus();
      } else if (!event.shiftKey && document.activeElement === lastControl) {
        event.preventDefault();
        firstControl.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocusRef.current?.focus();
    };
  }, [busy]);

  return modalRef;
}

function formatImpact(cents: number): string {
  const sign = cents < 0 ? "-" : "+";
  const abs = Math.abs(cents);
  return `${sign}$${(abs / 100).toFixed(2)}`;
}

function impactClass(cents: number): string {
  if (cents > 0) return styles.impactPositive;
  if (cents < 0) return styles.impactNegative;
  return styles.impactZero;
}

export function FindingsInbox({
  rows,
  categoryOptions,
  providerOptions,
  payerOptions,
  initialStatus,
  initialCategories,
  initialProviders,
  initialPayers,
}: FindingsInboxProps) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [acceptModal, setAcceptModal] = useState(false);
  const [dismissModal, setDismissModal] = useState(false);
  const [dismissReason, setDismissReason] = useState<DismissReason>(
    "wrong_payer_policy",
  );
  const [dismissText, setDismissText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Use the rows that match the current filter selection as the
  // selectable set. The server already filtered; the client only
  // computes the totals + drives the checkbox state.
  const selectable = useMemo(() => rows.map((r) => r.id), [rows]);
  useEffect(() => {
    const visible = new Set(selectable);
    setSelected((previous) => {
      const next = new Set(
        Array.from(previous).filter((findingId) => visible.has(findingId)),
      );
      return next.size === previous.size ? previous : next;
    });
  }, [selectable]);
  const allSelected =
    selectable.length > 0 && selectable.every((id) => selected.has(id));
  const someSelected = selected.size > 0;

  const selectedRows = useMemo(
    () => rows.filter((r) => selected.has(r.id)),
    [rows, selected],
  );
  const totalImpactCents = selectedRows.reduce(
    (acc, r) => acc + r.estFinancialImpactCents,
    0,
  );

  const toggleAll = useCallback(() => {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(selectable));
    }
  }, [allSelected, selectable]);

  const toggleOne = useCallback(
    (id: string) => {
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
    },
    [],
  );

  const clearSelection = useCallback(() => {
    setSelected(new Set());
  }, []);

  const handleAcceptClick = useCallback(() => {
    if (!someSelected) return;
    setError(null);
    setAcceptModal(true);
  }, [someSelected]);

  const handleDismissClick = useCallback(() => {
    if (!someSelected) return;
    setError(null);
    setDismissReason("wrong_payer_policy");
    setDismissText("");
    setDismissModal(true);
  }, [someSelected]);

  const submitAccept = useCallback(async () => {
    if (selectedRows.length === 0) return;
    if (selectedRows.length > BULK_FINDING_ID_MAX_CLIENT) {
      setError(`Bulk accept is limited to ${BULK_FINDING_ID_MAX_CLIENT} findings at a time.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/findings/bulk/accept", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          findingIds: selectedRows.map((r) => r.id),
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(
          (data as { error?: string }).error ??
            `HTTP ${res.status}`,
        );
      }
      setAcceptModal(false);
      setSelected(new Set());
      startTransition(() => router.refresh());
    } catch (err) {
      setError(toUserFacingError(err, "Could not accept findings. Please try again."));
    } finally {
      setBusy(false);
    }
  }, [router, selectedRows]);

  const submitDismiss = useCallback(async () => {
    if (selectedRows.length === 0) return;
    if (selectedRows.length > BULK_FINDING_ID_MAX_CLIENT) {
      setError(`Bulk dismiss is limited to ${BULK_FINDING_ID_MAX_CLIENT} findings at a time.`);
      return;
    }
    if (dismissReason === "other_with_text" && dismissText.trim().length === 0) {
      setError("Reason text is required when reason is \"Other (specify)\".");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/findings/bulk/dismiss", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          findingIds: selectedRows.map((r) => r.id),
          reason: dismissReason,
          reasonText:
            dismissReason === "other_with_text" ? dismissText.trim() : undefined,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(
          (data as { error?: string }).error ??
            `HTTP ${res.status}`,
        );
      }
      setDismissModal(false);
      setSelected(new Set());
      startTransition(() => router.refresh());
    } catch (err) {
      setError(toUserFacingError(err, "Could not dismiss findings. Please try again."));
    } finally {
      setBusy(false);
    }
  }, [dismissReason, dismissText, router, selectedRows]);

  // Build the export URL from the active filter set so the CSV
  // matches the table view exactly.
  const exportUrl = useMemo(() => {
    const params = new URLSearchParams();
    params.set("status", initialStatus);
    for (const c of initialCategories) params.append("category", c);
    for (const p of initialProviders) params.append("provider", p);
    for (const p of initialPayers) params.append("payer", p);
    return `/api/findings/export?${params.toString()}`;
  }, [initialStatus, initialCategories, initialProviders, initialPayers]);

  return (
    <>
      <form method="GET" className={styles.filterBar}>
        <div className={styles.filterGroup}>
          <label className={styles.filterLabel} htmlFor="status">Status</label>
          <select
            id="status"
            name="status"
            defaultValue={initialStatus}
            className={styles.filterSelect}
          >
            {FINDING_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.filterGroup}>
          <label className={styles.filterLabel} htmlFor="category">Category</label>
          <select
            id="category"
            name="category"
            multiple
            defaultValue={initialCategories}
            className={styles.filterSelect}
            style={{ minHeight: 60 }}
          >
            {categoryOptions.map((c) => (
              <option key={c} value={c}>
                {FINDING_CATEGORY_LABEL[c as FindingCategory] ?? c}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.filterGroup}>
          <label className={styles.filterLabel} htmlFor="provider">Provider</label>
          <select
            id="provider"
            name="provider"
            multiple
            defaultValue={initialProviders}
            className={styles.filterSelect}
            style={{ minHeight: 60 }}
          >
            {providerOptions.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.filterGroup}>
          <label className={styles.filterLabel} htmlFor="payer">Payer</label>
          <select
            id="payer"
            name="payer"
            multiple
            defaultValue={initialPayers}
            className={styles.filterSelect}
            style={{ minHeight: 60 }}
          >
            {payerOptions.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <button type="submit" className={styles.exportLink} style={{ marginLeft: 0 }}>
          Apply filters
        </button>
        <a
          className={styles.exportLink}
          href={exportUrl}
          // The CSV export is a server-rendered download — opening
          // it in a new tab keeps the inbox on screen so the
          // user can re-export after further filter changes.
          target="_blank"
          rel="noreferrer"
        >
          Export action plan (CSV)
        </a>
      </form>

      {error ? <div role="alert" aria-live="assertive" className={styles.flash}>{error}</div> : null}

      {someSelected ? (
        <div className={styles.bulkBar} role="region" aria-label="Bulk actions">
          <span>
            {selectedRows.length} selected · est. impact{" "}
            <strong className={impactClass(totalImpactCents)}>
              {formatImpact(totalImpactCents)}
            </strong>
          </span>
          <button
            type="button"
            className={styles.bulkAccept}
            onClick={handleAcceptClick}
            disabled={busy || pending}
          >
            Bulk accept
          </button>
          <button
            type="button"
            className={styles.bulkDismiss}
            onClick={handleDismissClick}
            disabled={busy || pending}
          >
            Bulk dismiss
          </button>
          <button
            type="button"
            className={styles.bulkClear}
            onClick={clearSelection}
            disabled={busy || pending}
          >
            Clear selection
          </button>
        </div>
      ) : null}

      {rows.length === 0 ? (
        <section className={styles.empty} data-testid="findings-filtered-empty">
          <h2>Nothing in this view</h2>
          <p>
            No {initialStatus} findings match the current filters. Clear a
            filter, switch status, or open Encounters to run a new audit.
          </p>
          <div className={styles.emptyInlineActions} style={{ justifyContent: "center", marginTop: 20 }}>
            <a className={styles.ctaPrimary} href="/findings">
              Reset filters
            </a>
            <a className={styles.ctaSecondary} href="/encounters">
              Browse encounters
            </a>
          </div>
        </section>
      ) : (
        <div className={styles.findingsTableScroller} tabIndex={0} aria-label="Findings table; scroll horizontally">
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.selectCell}>
                <input
                  type="checkbox"
                  className={styles.checkbox}
                  checked={allSelected}
                  onChange={toggleAll}
                  aria-label="Select all findings on this page"
                />
              </th>
              <th>Category</th>
              <th>Code change</th>
              <th>Rule reference</th>
              <th>Provider</th>
              <th>Payer</th>
              <th>Impact</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const isSelected = selected.has(r.id);
              return (
                <tr key={r.id} style={isSelected ? { background: "rgba(45, 212, 191, 0.04)" } : undefined}>
                  <td className={styles.selectCell}>
                    <input
                      type="checkbox"
                      className={styles.checkbox}
                      checked={isSelected}
                      onChange={() => toggleOne(r.id)}
                      aria-label={`Select finding ${r.id}`}
                    />
                  </td>
                  <td>{FINDING_CATEGORY_LABEL[r.category] ?? r.category}</td>
                  <td>
                    <code style={{ fontSize: 12 }}>
                      {r.currentCode ?? "—"}{" → "}
                      {r.suggestedCode ?? "—"}
                    </code>
                  </td>
                  <td>{r.billingRuleReference}</td>
                  <td style={{ fontSize: 13 }}>{r.providerName}</td>
                  <td style={{ fontSize: 13 }}>{r.payer}</td>
                  <td>
                    <span className={impactClass(r.estFinancialImpactCents)}>
                      {formatImpact(r.estFinancialImpactCents)}
                    </span>
                  </td>
                  <td>
                    <Link href={`/encounters/${r.encounterId}`}>
                      Open encounter →
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        </div>
      )}

      {acceptModal ? (
        <AcceptModal
          count={selectedRows.length}
          totalImpactCents={totalImpactCents}
          busy={busy}
          error={error}
          onCancel={() => {
            if (busy) return;
            setAcceptModal(false);
            setError(null);
          }}
          onConfirm={submitAccept}
        />
      ) : null}

      {dismissModal ? (
        <DismissModal
          count={selectedRows.length}
          busy={busy}
          error={error}
          reason={dismissReason}
          reasonText={dismissText}
          onReasonChange={setDismissReason}
          onReasonTextChange={setDismissText}
          onCancel={() => {
            if (busy) return;
            setDismissModal(false);
            setError(null);
          }}
          onConfirm={submitDismiss}
        />
      ) : null}
    </>
  );
}

interface AcceptModalProps {
  count: number;
  totalImpactCents: number;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}

function AcceptModal({
  count,
  totalImpactCents,
  busy,
  error,
  onCancel,
  onConfirm,
}: AcceptModalProps) {
  const modalRef = useModalAccessibility(onCancel, busy);
  const impactClassName =
    totalImpactCents < 0
      ? `${styles.impactTotal} ${styles.impactTotalNegative}`
      : styles.impactTotal;
  return (
    <div
      className={styles.modalOverlay}
      role="dialog"
      aria-modal="true"
      aria-labelledby="accept-modal-title"
    >
      <div ref={modalRef} className={styles.modal}>
        <h2 id="accept-modal-title">Bulk accept {count} findings</h2>
        <p>
          You&rsquo;re about to accept {count} finding{count === 1 ? "" : "s"}.
          Each write is recorded in the audit log with a shared batch
          identifier so the runbook can re-walk the group as a single
          event.
        </p>
        <p style={{ marginBottom: 4 }}>Total estimated impact</p>
        <p className={impactClassName}>{formatImpact(totalImpactCents)}</p>
        {error ? <div role="alert" aria-live="assertive" className={styles.flash}>{error}</div> : null}
        <div className={styles.modalActions}>
          <button
            type="button"
            className={styles.modalCancel}
            onClick={onCancel}
            disabled={busy}
          >
            Cancel
          </button>
          <button
            type="button"
            className={styles.modalConfirm}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Accepting…" : `Accept ${count} finding${count === 1 ? "" : "s"}`}
          </button>
        </div>
      </div>
    </div>
  );
}

interface DismissModalProps {
  count: number;
  busy: boolean;
  error: string | null;
  reason: DismissReason;
  reasonText: string;
  onReasonChange: (r: DismissReason) => void;
  onReasonTextChange: (s: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
}

function DismissModal({
  count,
  busy,
  error,
  reason,
  reasonText,
  onReasonChange,
  onReasonTextChange,
  onCancel,
  onConfirm,
}: DismissModalProps) {
  const modalRef = useModalAccessibility(onCancel, busy);
  return (
    <div
      className={styles.modalOverlay}
      role="dialog"
      aria-modal="true"
      aria-labelledby="dismiss-modal-title"
    >
      <div ref={modalRef} className={styles.modal}>
        <h2 id="dismiss-modal-title">Bulk dismiss {count} findings</h2>
        <p>
          Dismissing {count} finding{count === 1 ? "" : "s"} with the same
          reason. Pick a reason that applies to every row in the
          selection; per-finding reasons are not supported in this bulk
          action.
        </p>
        <label className={styles.modalField} htmlFor="dismiss-reason">
          Dismiss reason
        </label>
        <select
          id="dismiss-reason"
          className={styles.modalSelect}
          value={reason}
          onChange={(e) => onReasonChange(e.target.value as DismissReason)}
          disabled={busy}
        >
          {DISMISS_REASONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
        {reason === "other_with_text" ? (
          <>
            <label className={styles.modalField} htmlFor="dismiss-text">
              Reason details (1-2000 chars)
            </label>
            <textarea
              id="dismiss-text"
              className={styles.modalTextarea}
              value={reasonText}
              onChange={(e) => onReasonTextChange(e.target.value)}
              maxLength={2000}
              disabled={busy}
              placeholder="What didn't hold up in the AI's recommendation?"
            />
          </>
        ) : null}
        {error ? <div role="alert" aria-live="assertive" className={styles.flash}>{error}</div> : null}
        <div className={styles.modalActions}>
          <button
            type="button"
            className={styles.modalCancel}
            onClick={onCancel}
            disabled={busy}
          >
            Cancel
          </button>
          <button
            type="button"
            className={`${styles.modalConfirm} ${styles.modalConfirmDanger}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Dismissing…" : `Dismiss ${count} finding${count === 1 ? "" : "s"}`}
          </button>
        </div>
      </div>
    </div>
  );
}
