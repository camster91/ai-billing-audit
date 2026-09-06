"use client";

import type { ReactNode } from "react";
import { ToastProvider } from "./Toast";

/** Client providers for the portal root layout. */
export function Providers({ children }: { children: ReactNode }) {
  return <ToastProvider>{children}</ToastProvider>;
}
