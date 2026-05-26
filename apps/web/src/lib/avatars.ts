/**
 * Consultant avatar lookup.
 *
 * Maps a consultant slug (e.g. "wendy-squibb") to its avatar URL served
 * from /public/avatars/. Falls back to initials in a cyan circle when
 * no PNG matches — so adding a future consultant is a two-step:
 *
 *   1. Drop their first-name-cased PNG into apps/web/public/avatars/
 *   2. Add an entry to SLUG_TO_AVATAR below (or rely on the auto-derive
 *      heuristic if their PNG matches the first-token-cased convention)
 *
 * No backend round-trip — Next serves these as static assets so the
 * empty-state avatar paints instantly on agent selection.
 */

// Explicit mapping. Keep this list ordered to match the consultant
// dropdown order in chat.tsx so adding/removing one is a single-file edit.
const SLUG_TO_AVATAR: Record<string, string> = {
  "wendy-squibb": "/avatars/Wendy.png",
  "kurt-knowles": "/avatars/Kurt.png",
  "jakub-lehman": "/avatars/Jakub.png",
  "jarrod-burr": "/avatars/Jarrod.png",
  "raymond-buitenhuis": "/avatars/Raymond.png",
  "jodi-tunn": "/avatars/Jodi.png",
  "colin-tunn": "/avatars/Colin.png",
};

export function avatarUrl(slug: string | null | undefined): string | null {
  if (!slug) return null;
  return SLUG_TO_AVATAR[slug] ?? null;
}

/** Pretty display name from a slug, e.g. "wendy-squibb" → "Wendy Squibb". */
export function displayName(slug: string | null | undefined): string {
  if (!slug) return "Consultant";
  return slug
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

/** Two-letter initials, e.g. "wendy-squibb" → "WS". Used by AvatarCircle
 * when no PNG is available. */
export function initialsOf(slug: string | null | undefined): string {
  if (!slug) return "?";
  const parts = slug.split("-").filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
}

/**
 * Initials from a user's email or freeform name. Mirrors the backend's
 * _first_name() logic but keeps both name segments so we get "EM" for
 * `elijah.mirandilla@harcourts.com.au` instead of just "E".
 *
 *   "elijah.mirandilla@harcourts.com.au"  → "EM"
 *   "brad@harcourts.com.au"               → "B"
 *   "James Wilson"                        → "JW"
 *   "Sarah"                               → "S"
 *
 * Drives the user-side avatar circle next to outgoing messages.
 */
export function userInitials(nameOrEmail: string | null | undefined): string {
  const raw = (nameOrEmail ?? "").trim();
  if (!raw) return "?";
  // Strip @domain
  const local = raw.includes("@") ? raw.split("@", 1)[0]! : raw;
  // Split on any common name separator
  const parts = local.split(/[.\s_-]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0]![0]!.toUpperCase();
  return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
}
