// Legacy public onboarding previously called API routes that never existed.
// Paid onboarding begins at checkout and continues at /portal/onboarding.

import type { Metadata } from "next";
import { redirect } from "next/navigation";

export const metadata: Metadata = {
  title: "Get started — Zorva",
  description: "Choose a plan to begin secure clinic onboarding.",
};

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default function NewClinicOnboardingPage() {
  redirect("/pricing");
}
