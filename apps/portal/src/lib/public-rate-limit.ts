/**
 * Small in-process guard for public write endpoints.
 *
 * This is deliberately a backstop, not a replacement for an edge WAF. The
 * portal currently runs as one replica; an upstream rate limit remains the
 * stronger cross-replica and denial-of-service control.
 */
const WINDOW_MS = 10 * 60 * 1000;
const LEAD_LIMIT = 5;
const MAX_ENTRIES = 10_000;

type Entry = { count: number; resetAt: number };

const entries = new Map<string, Entry>();

function clientKey(request: Request): string {
  const realIp = request.headers.get("x-real-ip")?.trim();
  if (realIp) return realIp;

  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) return forwardedFor.split(",")[0]?.trim() || "unknown";

  return "unknown";
}

function prune(now: number): void {
  if (entries.size < MAX_ENTRIES) return;

  for (const [key, entry] of entries) {
    if (entry.resetAt <= now) entries.delete(key);
  }

  // A flood of unique forged addresses must not grow this process without
  // bound. Dropping the oldest iterator entries is acceptable for this
  // best-effort backstop; a proper edge limiter remains the durable control.
  while (entries.size >= MAX_ENTRIES) {
    const first = entries.keys().next().value;
    if (!first) break;
    entries.delete(first);
  }
}

export type RateLimitResult =
  | { allowed: true; remaining: number; resetAt: number }
  | { allowed: false; retryAfterSeconds: number };

export function takeLeadSubmission(request: Request, now = Date.now()): RateLimitResult {
  prune(now);

  const key = clientKey(request);
  const current = entries.get(key);
  if (!current || current.resetAt <= now) {
    entries.set(key, { count: 1, resetAt: now + WINDOW_MS });
    return { allowed: true, remaining: LEAD_LIMIT - 1, resetAt: now + WINDOW_MS };
  }

  if (current.count >= LEAD_LIMIT) {
    return {
      allowed: false,
      retryAfterSeconds: Math.max(1, Math.ceil((current.resetAt - now) / 1000)),
    };
  }

  current.count += 1;
  return { allowed: true, remaining: LEAD_LIMIT - current.count, resetAt: current.resetAt };
}
