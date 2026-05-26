import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Compose Tailwind class strings, with later classes overriding earlier ones. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Parse a backend-emitted datetime string into an epoch millisecond
 * number. The backend uses SQLite's `datetime('now')`, which emits
 * "YYYY-MM-DD HH:MM:SS" in UTC, NO timezone marker. JavaScript's
 * Date.parse() treats such a string as LOCAL time, which silently
 * skews timestamps by the user's offset (Manila +8h, NYC -4h, etc.).
 *
 * Pattern: detect the bare "YYYY-MM-DD HH:MM:SS" shape and append `Z`
 * to force UTC interpretation. Strings already containing `T`/`Z`/
 * timezone offsets are passed through unchanged.
 *
 *   "2026-05-26 18:52:34"     → parsed as 2026-05-26T18:52:34Z
 *   "2026-05-26T18:52:34Z"    → unchanged
 *   "2026-05-26T18:52:34+08:00" → unchanged
 *
 * Returns 0 on parse failure so the caller can branch (e.g. hide the
 * timestamp UI) without showing "Invalid Date".
 */
export function parseBackendTimestamp(s: string | null | undefined): number {
  if (!s) return 0;
  // SQLite bare form: "YYYY-MM-DD HH:MM:SS" (no T, no Z, no offset)
  const bareSqliteUtc = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/;
  const normalised = bareSqliteUtc.test(s)
    ? s.replace(" ", "T") + "Z"
    : s;
  const ms = Date.parse(normalised);
  return Number.isFinite(ms) ? ms : 0;
}

/**
 * Friendly relative timestamp string, messaging-platform style.
 *
 *   < 1 minute   → "just now"
 *   < 1 hour     → "5m ago"
 *   today,>=1h   → HH:mm (locale-aware 12/24h)
 *   yesterday    → "Yesterday 14:32"
 *   < 7 days     → "Mon 14:32"
 *   this year    → "26 May"
 *   older        → "26 May 2025"
 *
 * `now` is injected so callers can share a single ticking clock across
 * many timestamps (avoids each <MessageTimestamp> ticking its own
 * interval). If omitted, uses Date.now() once at call time.
 */
export function formatChatTime(ts: number, now: number = Date.now()): string {
  if (!ts) return "";
  const d = new Date(ts);
  const diffMs = now - ts;
  const diffMin = Math.floor(diffMs / 60_000);

  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;

  // Today: just show HH:mm in the user's locale (12/24h follows locale).
  const today = new Date(now);
  const isSameDay =
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate();
  if (isSameDay) {
    return d.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  // Yesterday vs this-week vs older.
  const dayMs = 86_400_000;
  const diffDay = Math.floor((now - ts) / dayMs);
  const time = d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  if (diffDay === 1) return `Yesterday ${time}`;
  if (diffDay < 7) {
    const weekday = d.toLocaleDateString(undefined, { weekday: "short" });
    return `${weekday} ${time}`;
  }
  if (d.getFullYear() === today.getFullYear()) {
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }
  return d.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
