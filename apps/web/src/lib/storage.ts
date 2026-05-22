/** localStorage helpers. Soft identity + per-consultant session continuity.
 *
 * There is no authentication anywhere in this app. The "user name" is just a
 * label for the audit trail and learning attribution; the trust boundary is
 * the network (Tailscale).
 */

const KEY_USER_NAME = "harcourts.userName";
const KEY_CONSULTANT_SLUG = "harcourts.consultantSlug";
const KEY_CLAUDE_SESSION_PREFIX = "harcourts.claudeSessionId.";

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export function getUserName(): string | null {
  if (!isBrowser()) return null;
  return localStorage.getItem(KEY_USER_NAME);
}

export function setUserName(name: string): void {
  if (!isBrowser()) return;
  localStorage.setItem(KEY_USER_NAME, name);
}

export function getConsultantSlug(): string | null {
  if (!isBrowser()) return null;
  return localStorage.getItem(KEY_CONSULTANT_SLUG);
}

export function setConsultantSlug(slug: string): void {
  if (!isBrowser()) return;
  localStorage.setItem(KEY_CONSULTANT_SLUG, slug);
}

/** Each consultant gets its own conversation thread, persisted per-slug. */
export function getClaudeSessionId(slug: string): string | null {
  if (!isBrowser()) return null;
  return localStorage.getItem(KEY_CLAUDE_SESSION_PREFIX + slug);
}

export function setClaudeSessionId(slug: string, id: string | null): void {
  if (!isBrowser()) return;
  if (id === null) {
    localStorage.removeItem(KEY_CLAUDE_SESSION_PREFIX + slug);
  } else {
    localStorage.setItem(KEY_CLAUDE_SESSION_PREFIX + slug, id);
  }
}
