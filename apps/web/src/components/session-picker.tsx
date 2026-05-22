"use client";

import { Check, History } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { fetchSessions, type SessionRow } from "@/lib/ws";
import { cn } from "@/lib/utils";

interface SessionPickerProps {
  backendUrl: string;
  consultantSlug: string | null;
  currentSessionId: string | null;
  onPick: (session: SessionRow) => void;
  /** Reflects the live session list — bumped when a new turn lands so we
   *  re-fetch on next open. */
  refreshKey?: unknown;
}

/** Click → fetches sessions for the active consultant → click a row to load
 *  that session. Closes on outside click or Escape. */
export function SessionPicker({
  backendUrl,
  consultantSlug,
  currentSessionId,
  onPick,
  refreshKey,
}: SessionPickerProps) {
  const [open, setOpen] = useState(false);
  const [sessions, setSessions] = useState<SessionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
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
          className="absolute left-0 top-full z-20 mt-1 w-80 max-h-96 overflow-y-auto rounded-md border bg-popover text-popover-foreground shadow-md"
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
              {sessions.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => {
                      onPick(s);
                      setOpen(false);
                    }}
                    className={cn(
                      "flex w-full items-start gap-2 px-3 py-2 text-left text-xs hover:bg-accent",
                      s.id === currentSessionId && "bg-accent/60",
                    )}
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
                    {s.id === currentSessionId && (
                      <Check className="mt-0.5 h-3.5 w-3.5 text-primary" />
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
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
