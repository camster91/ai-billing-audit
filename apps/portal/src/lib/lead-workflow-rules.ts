export const LEAD_STAGES = [
  "new",
  "contacted",
  "engaged",
  "demo_scheduled",
  "pilot_signed",
  "lost",
] as const;

export type LeadStage = (typeof LEAD_STAGES)[number];

export const LEAD_QUALIFICATION_STATUSES = [
  "unreviewed",
  "qualified",
  "nurture",
  "disqualified",
] as const;

const TRANSITIONS: Record<LeadStage, ReadonlySet<LeadStage>> = {
  new: new Set(["contacted", "lost"]),
  contacted: new Set(["engaged", "demo_scheduled", "lost"]),
  engaged: new Set(["contacted", "demo_scheduled", "lost"]),
  demo_scheduled: new Set(["engaged", "pilot_signed", "lost"]),
  pilot_signed: new Set(),
  lost: new Set(),
};

export function canTransitionLead(from: string, to: LeadStage): boolean {
  if (from === to) return true;
  if (!(LEAD_STAGES as readonly string[]).includes(from)) return false;
  return TRANSITIONS[from as LeadStage].has(to);
}
