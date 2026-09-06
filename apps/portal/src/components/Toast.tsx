"use client";

// Accessible toast notifications for the portal.
//
// Uses aria-live regions so screen readers announce success/error
// without stealing focus. Toasts auto-dismiss; errors stay longer.
// Mount once via <Providers> in the root layout.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import styles from "./Toast.module.css";

export type ToastTone = "success" | "error" | "info";

export interface ToastInput {
  title: string;
  description?: string;
  tone?: ToastTone;
  durationMs?: number;
}

interface ToastItem extends ToastInput {
  id: string;
  tone: ToastTone;
}

interface ToastContextValue {
  push: (toast: ToastInput) => void;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const DEFAULT_DURATION: Record<ToastTone, number> = {
  success: 3200,
  info: 4000,
  error: 5600,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (toast: ToastInput) => {
      const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const tone = toast.tone ?? "info";
      const item: ToastItem = { ...toast, id, tone };
      setToasts((prev) => [...prev.slice(-4), item]);
      const duration = toast.durationMs ?? DEFAULT_DURATION[tone];
      const timer = setTimeout(() => dismiss(id), duration);
      timers.current.set(id, timer);
    },
    [dismiss],
  );

  useEffect(() => {
    const timersRef = timers.current;
    return () => {
      for (const timer of timersRef.values()) clearTimeout(timer);
      timersRef.clear();
    };
  }, []);

  const value = useMemo(() => ({ push, dismiss }), [push, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return ctx;
}

/** Safe hook for optional toast — no-ops outside provider. */
export function useToastOptional(): ToastContextValue {
  const ctx = useContext(ToastContext);
  return (
    ctx ?? {
      push: () => undefined,
      dismiss: () => undefined,
    }
  );
}

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
}) {
  const labelId = useId();
  return (
    <div
      className={styles.viewport}
      role="region"
      aria-label="Notifications"
      aria-describedby={labelId}
    >
      <span id={labelId} className={styles.srOnly}>
        Toast notifications
      </span>
      <ul className={styles.list} aria-live="polite" aria-relevant="additions">
        {toasts.map((toast) => (
          <li
            key={toast.id}
            className={`${styles.toast} ${styles[toast.tone]}`}
            role={toast.tone === "error" ? "alert" : "status"}
          >
            <div className={styles.body}>
              <p className={styles.title}>{toast.title}</p>
              {toast.description ? (
                <p className={styles.description}>{toast.description}</p>
              ) : null}
            </div>
            <button
              type="button"
              className={styles.close}
              aria-label="Dismiss notification"
              onClick={() => onDismiss(toast.id)}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
