export const CLIENT_ENGAGEMENT_STATUSES = [
  "pilot_planning",
  "onboarding",
  "active_pilot",
  "active_client",
  "paused",
  "closed",
] as const;

export const PRIVACY_APPROVAL_STATUSES = ["pending", "approved", "changes_required"] as const;
export const CLIENT_HEALTH_STATUSES = ["unknown", "healthy", "watch", "at_risk"] as const;
