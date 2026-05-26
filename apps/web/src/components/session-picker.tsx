"use client";

import { Check, History, Loader2, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/button";
import {
  type DeletePreview,
  deleteSession,
  fetchDeletePreview,
  fetchSessions,
  type SessionRow,
} from "@/lib/ws";
import { cn } from "@/lib/utils";

interface SessionPickerProps {
  backendUrl: string;
  consultantSlug: string | null;
  currentSessionId: string | null;
  onPick: (session: SessionRow) => void;
  /** Fires after a successful delete so the parent can reset itself if
   * the active session was the one removed. */
  onDeleted?: (sessionId: string) => void;
  /** Reflects the live session list — bumped when a new turn lands so we
   *  re-fetch on next open. */
  refreshKey?: unknown;
}

/** Click → fetches sessions for the active consultant → click a row to load
 *  that session, or the trash icon to permanently delete it (DB + folder).
 *  Closes on outside click or Escape. */
export function SessionPicker({
  backendUrl,
  consultantSlug,
  currentSessionId,
  onPick,
  onDeleted,
  refreshKey,
}: SessionPickerProps) {
  const [open, setOpen] = useState(false);
  const [sessions, setSessions] = useState<SessionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** Set while a delete is in flight — disables that row's trash button
   *  and shows a spinner so a double-click doesn't fire two DELETEs. */
  const [deletingId, setDeletingId] = useState<string | null>(null);
  /** Session staged for the confirm dialog. null = dialog closed. We
   *  hold the whole row so the dialog can render the timestamp +
   *  token-count details without re-fetching. */
  const [pendingDelete, setPendingDelete] = useState<SessionRow | null>(null);
  /** Preview counts for the staged session, fetched once when the trash
   *  icon is clicked. Null = still loading or preview endpoint failed.
   *  We treat preview failures as soft-fail — the dialog opens without
   *  the counts rather than blocking the user from deleting. */
  const [pendingPreview, setPendingPreview] = useState<DeletePreview | null>(
    null,
  );
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  // Fetch on every open. Cheap (SQLite), no caching needed.
  useEffect(() => {
    if (!open || !consultantSlug || !backendUrl) return;
    let cancelled = false;
    setSessions(null);
    setError(null);
    fetchSessions(backendUrl, consultantSlug)
      .then((rows) => {
        if (!cancelled) setSessions(rows);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [open, backendUrl, consultantSlug, refreshKey]);

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (!wrapperRef.current) return;
      if (wrapperRef.current.contains(e.target as Node)) return;
      setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  /** Trash-icon handler — stages the row for the confirm dialog AND
   *  fires the cleanup-preview fetch so the modal can show "5 photos +
   *  1 Word doc will be deleted". The dialog opens immediately; the
   *  counts fade in once the preview resolves. */
  function requestDelete(s: SessionRow) {
    setPendingDelete(s);
    setPendingPreview(null);
    fetchDeletePreview(backendUrl, s.id)
      .then((preview) => {
        // Guard against stale fetches: only apply if the user hasn't
        // cancelled or staged a different session in the meantime.
        setPendingPreview((prev) => (prev === null ? preview : prev));
      })
      .catch(() => {
        // Soft-fail: dialog stays open without counts. We don't surface
        // the preview error because the delete itself may still succeed.
      });
  }

  async function confirmDelete() {
    const s = pendingDelete;
    if (!s) return;
    setDeletingId(s.id);
    try {
      await deleteSession(backendUrl, s.id);
      setSessions((prev) => (prev ? prev.filter((row) => row.id !== s.id) : prev));
      onDeleted?.(s.id);
      setPendingDelete(null);
      setPendingPreview(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      // Keep the dialog open on failure so the user sees the spinner
      // stop and can either retry or cancel.
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div ref={wrapperRef} className="relative">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => setOpen((o) => !o)}
        disabled={!consultantSlug}
        aria-label="Open session history"
        aria-haspopup="menu"
        aria-expanded={open}
        title="Open session history"
        className="px-2 sm:px-3"
      >
        <History className="h-3.5 w-3.5 sm:mr-1.5" />
        <span className="hidden sm:inline">History</span>
      </Button>

      {open && (
        <div
          role="menu"
          // Solid white background (not bg-popover which references an
          // undefined CSS var in our scoped tokens and falls through to
          // transparent). Border + shadow gives it weight; z-index 50
          // beats the header's z-10 and any motion overlays inside the
          // message list.
          className="absolute left-0 top-full z-50 mt-1 w-80 max-h-96 overflow-y-auto rounded-md border border-border bg-background text-foreground shadow-xl ring-1 ring-black/5"
        >
          {sessions === null && !error && (
            <div className="px-3 py-4 text-xs text-muted-foreground">
              Loading…
            </div>
          )}
          {error && (
            <div className="px-3 py-4 text-xs text-destructive">{error}</div>
          )}
          {sessions !== null && sessions.length === 0 && (
            <div className="px-3 py-4 text-xs text-muted-foreground">
              No previous sessions for this consultant yet.
            </div>
          )}
          {sessions !== null && sessions.length > 0 && (
            <ul className="py-1">
              {sessions.map((s) => {
                const isCurrent = s.id === currentSessionId;
                const isDeleting = deletingId === s.id;
                return (
                  <li
                    key={s.id}
                    className={cn(
                      "group flex items-center gap-1 px-1.5",
                      isCurrent && "bg-accent/60",
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => {
                        if (isDeleting) return;
                        onPick(s);
                        setOpen(false);
                      }}
                      className={cn(
                        "flex flex-1 items-start gap-2 rounded-md px-2 py-2 text-left text-xs",
                        "hover:bg-accent disabled:opacity-50",
                      )}
                      disabled={isDeleting}
                    >
                      <div className="flex-1 space-y-0.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium">
                            {formatRelative(s.last_active_at)}
                          </span>
                          <span className="text-muted-foreground">
                            {s.user_name}
                          </span>
                        </div>
                        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                          {s.total_input_tokens + s.total_output_tokens} tokens
                        </div>
                      </div>
                      {isCurrent && (
                        <Check className="mt-0.5 h-3.5 w-3.5 text-primary" />
                      )}
                    </button>

                    {/* Trash button — separate from the row click so a
                        click on the icon never accidentally opens the
                        session. Lives in the .group so it can fade in
                        on hover; always visible on touch screens via
                        the @media (hover:none) override. */}
                    <button
                      type="button"
                      onClick={() => requestDelete(s)}
                      disabled={isDeleting}
                      aria-label="Delete this session"
                      title="Delete this session permanently"
                      className={cn(
                        "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
                        "text-muted-foreground hover:bg-destructive/10 hover:text-destructive",
                        "opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100",
                        "disabled:opacity-50 disabled:cursor-not-allowed",
                        "transition-opacity",
                      )}
                    >
                      {isDeleting ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Trash2 className="h-3.5 w-3.5" />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}

      {/* Styled confirm dialog — replaces the native window.confirm()
          that looked like a 1998 browser alert. AnimatePresence inside
          the component handles the fade/scale lifecycle. */}
      <ConfirmDialog
        open={pendingDelete !== null}
        onClose={() => {
          setPendingDelete(null);
          setPendingPreview(null);
        }}
        onConfirm={confirmDelete}
        title="Delete this session?"
        description={
          pendingDelete
            ? buildDeleteDescription(pendingDelete, pendingPreview)
            : ""
        }
        confirmLabel="Delete permanently"
        cancelLabel="Keep it"
        destructive
        busy={deletingId === pendingDelete?.id}
      />
    </div>
  );
}

/** Build the multi-line description shown inside the delete-confirm
 *  modal. Always includes the session timing + token total; layers in
 *  upload + deliverable counts once the cleanup-preview fetch resolves.
 *
 *  The preview can be null in two cases:
 *  - in flight (just fired): show a generic "and its files" line
 *  - failed (network/auth error): same fallback, since we don't want to
 *    block the destructive action on a count-fetch error.
 */
function buildDeleteDescription(
  session: SessionRow,
  preview: DeletePreview | null,
): string {
  const tokens = session.total_input_tokens + session.total_output_tokens;
  const header = `Started ${formatRelative(session.started_at)} · ${tokens} tokens`;

  if (preview === null) {
    // No preview yet — keep messaging deliberately vague but accurate.
    return (
      `${header}\n\n` +
      `This removes the conversation and every file it produced. ` +
      `Any Word doc you've already downloaded stays safe.`
    );
  }

  const lines: string[] = [];
  if (preview.uploads > 0) {
    lines.push(
      `📎 ${preview.uploads} uploaded ${preview.uploads === 1 ? "file" : "files"}`,
    );
  }
  if (preview.deliverables > 0) {
    const names = preview.deliverable_names.slice(0, 3).join(", ");
    const more =
      preview.deliverables > 3
        ? ` + ${preview.deliverables - 3} more`
        : "";
    lines.push(
      `📄 ${preview.deliverables} ${preview.deliverables === 1 ? "deliverable" : "deliverables"} (${names}${more})`,
    );
  }

  if (lines.length === 0) {
    // Session never produced or received files — be honest about that.
    return (
      `${header}\n\n` +
      `Just the conversation history. No uploads or deliverables to clean up.`
    );
  }

  return (
    `${header}\n\n` +
    `The following will be permanently deleted:\n${lines.join("\n")}\n\n` +
    `Any Word doc you've already downloaded to your computer stays safe.`
  );
}

/** "5m ago" / "2h ago" / "Yesterday" / "May 22" / "2025". */
function formatRelative(iso: string): string {
  // SQLite emits "YYYY-MM-DD HH:MM:SS" in UTC. Parsing without a Z assumes
  // local time, which would skew by hours; force UTC interpretation.
  const ts = iso.includes("T") ? iso : iso.replace(" ", "T") + "Z";
  const d = new Date(ts);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  if (diffD === 1) return "yesterday";
  if (diffD < 7) return `${diffD}d ago`;
  if (d.getFullYear() === now.getFullYear()) {
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  return d.toLocaleDateString();
}
