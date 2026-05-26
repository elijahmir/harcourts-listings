"use client";

import { AnimatePresence, motion } from "framer-motion";
import { BookmarkPlus, Check, Copy, Download, RefreshCcw, Send, X } from "lucide-react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { AvatarCircle } from "@/components/avatar-circle";
import { userInitials } from "@/lib/avatars";
import { SaveLearningForm } from "@/components/save-learning-form";
import { SessionPicker } from "@/components/session-picker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { UploadButton } from "@/components/upload-button";
import {
  fetchConsultants,
  fetchSessionMessages,
  saveLearning,
  uploadFiles,
  useChat,
  type ChatMessage,
  type ConnectionStatus,
  type SessionRow,
  type UploadedFile,
} from "@/lib/ws";
import {
  getClaudeSessionId,
  getConsultantSlug,
  getSessionId,
  setClaudeSessionId,
  setConsultantSlug,
  setSessionId,
} from "@/lib/storage";
import { cn, formatChatTime, parseBackendTimestamp } from "@/lib/utils";

interface ChatProps {
  userName: string;
  backendUrl: string;
  /** Optional React node rendered inside the chat header's actions area,
   * to the left of the connection status dot. Used by HUP-Sales-App to
   * merge its New/Old variant switch + Tools button into the same row
   * as the consultant dropdown, avoiding the double-toolbar stack. */
  headerSlot?: React.ReactNode;
}

/**
 * Build a markdown export of the current chat and trigger a download.
 * Client-side only — no backend round-trip. Format mirrors what a human
 * would write up after a session: who said what, in order, with the
 * consultant's name as section headers. Skips empty/in-flight messages.
 */
function downloadConversationAsMarkdown(
  messages: ChatMessage[],
  slug: string | null,
  userName: string,
) {
  const consultant = slug
    ? slug
        .split("-")
        .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
        .join(" ")
    : "Consultant";
  const date = new Date().toISOString().slice(0, 10);
  const lines: string[] = [
    `# Harcourts listing session — ${consultant}`,
    "",
    `_Exported ${date}_  ·  _User: ${userName}_`,
    "",
    "---",
    "",
  ];
  for (const m of messages) {
    if (!m.text.trim()) continue;
    const speaker = m.role === "user" ? "You" : consultant;
    lines.push(`## ${speaker}`, "", m.text, "");
  }
  const blob = new Blob([lines.join("\n")], {
    type: "text/markdown;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `harcourts-${slug ?? "session"}-${date}.md`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Revoke after a short delay so Safari has time to start the download
  // before the URL is invalidated.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function prettySlug(slug: string): string {
  return slug
    .split("-")
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join(" ");
}

/* -------------------------------------------------------------------------- */
/* URL deep-link helpers — keep the active session id in `?s=...` so the     */
/* page is refresh-safe and shareable. Three rules:                          */
/*  1. Other params (HUP's ?v=old variant) MUST survive.                     */
/*  2. Use history.replaceState — never pushState. Switching sessions        */
/*     shouldn't pollute the browser back-button stack.                      */
/*  3. SSR-safe: all `window` access guarded by typeof check; the helpers    */
/*     no-op during server render.                                           */
/* -------------------------------------------------------------------------- */

function getSessionIdFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("s");
}

function setSessionIdInUrl(sid: string): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (url.searchParams.get("s") === sid) return; // no-op if unchanged
  url.searchParams.set("s", sid);
  window.history.replaceState(null, "", url.toString());
}

function clearSessionIdFromUrl(): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (!url.searchParams.has("s")) return;
  url.searchParams.delete("s");
  window.history.replaceState(null, "", url.toString());
}

export function Chat({ userName, backendUrl, headerSlot }: ChatProps) {
  const [consultants, setConsultants] = useState<string[] | null>(null);
  const [slug, setSlug] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  // Ref kept for potential future use (e.g. focus the input after an
  // upload error). Starter chips now fire submitDraft() directly rather
  // than pre-filling, so we don't need to focus on chip click.
  const messageInputRef = useRef<HTMLInputElement | null>(null);

  function handlePickStarter(text: string) {
    // Send immediately — every modern chat UX (ChatGPT, Claude.ai,
    // Slack quick-actions) treats a suggested-prompt tap as a fully
    // committed send. We bypass the draft state because setDraft is
    // async and submitDraft would otherwise read the previous value.
    submitDraft(text);
  }
  const [initialSessionId, setInitialSessionId] = useState<string | null>(null);
  const [initialClaudeSessionId, setInitialClaudeSessionId] =
    useState<string | null>(null);
  const [uploads, setUploads] = useState<UploadedFile[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [savedLearningMessageIds, setSavedLearningMessageIds] = useState<
    Set<string>
  >(new Set());
  const [editingLearningForId, setEditingLearningForId] = useState<string | null>(
    null,
  );
  // Tracks the SQLite session id for THIS consultant. Comes from localStorage
  // on consultant change, gets overwritten when the backend confirms one via
  // the `done` event. We hold it in state (not useMemo) so the UploadButton
  // re-renders the instant the first turn finishes.
  const [sessionId, setSessionIdState] = useState<string | null>(null);

  // Load consultant list + restore last selection on first mount.
  // Session-id precedence (highest first):
  //   1. `?s=<id>` from the URL  ← refresh-safe / shareable deep link
  //   2. Per-consultant localStorage (`getSessionId(slug)`)
  //   3. null → backend creates a fresh session on first turn
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await fetchConsultants(backendUrl);
        if (cancelled) return;
        setConsultants(list);
        const saved = getConsultantSlug();
        const initial = saved && list.includes(saved) ? saved : list[0] ?? null;
        setSlug(initial);
        if (initial) {
          // Persist the default consultant slug too, so localStorage is the
          // canonical record of "which consultant am I on" from first load.
          setConsultantSlug(initial);
          const urlSid = getSessionIdFromUrl();
          const sid = urlSid || getSessionId(initial);
          setInitialSessionId(sid);
          setSessionIdState(sid);
          setInitialClaudeSessionId(getClaudeSessionId(initial));
        }
      } catch {
        if (!cancelled) setConsultants([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [backendUrl]);

  const {
    messages,
    status,
    isStreaming,
    activity,
    send,
    reset,
    reconnect,
    setMessages,
  } = useChat({
    backendUrl,
    consultantSlug: slug,
    userName,
    initialSessionId,
    initialClaudeSessionId,
    onSessionIdChange: (id) => {
      if (slug) {
        setSessionId(slug, id);
        setSessionIdState(id);
      }
    },
    onClaudeSessionIdChange: (id) => {
      if (slug) setClaudeSessionId(slug, id);
    },
  });

  // Auto-scroll to the latest message — but ONLY scroll the chat's own
  // overflow container, not every ancestor. `Element.scrollIntoView()`
  // walks UP the DOM and scrolls every scrollable ancestor, which when
  // the chat is embedded in HUP-Sales-App's dashboard caused the WHOLE
  // dashboard surface to jump down on each message. Direct scrollTop
  // assignment confines the motion to the chat's main element.
  // Keep `?s=<id>` in the URL in sync with the active session. Fires
  // whenever sessionId changes — first turn (backend assigns an id),
  // session-picker pick, etc. replaceState (NOT pushState) so the
  // browser back-button doesn't fill with one entry per session swap.
  // Clear the param entirely when sessionId becomes null (after
  // startNewConversation or a session delete).
  useEffect(() => {
    if (sessionId) {
      setSessionIdInUrl(sessionId);
    } else {
      clearSessionIdFromUrl();
    }
  }, [sessionId]);

  const messagesRef = useRef<HTMLOListElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const list = messagesRef.current;
    if (!list) return;
    // Walk up until we find an element with overflow-y: auto/scroll.
    // In our markup that's the immediate parent <main>, but climbing
    // makes the code resilient to wrapper changes.
    let scroller: HTMLElement | null = list.parentElement;
    while (scroller && scroller !== document.body) {
      const overflowY = getComputedStyle(scroller).overflowY;
      if (overflowY === "auto" || overflowY === "scroll") break;
      scroller = scroller.parentElement;
    }
    if (scroller) {
      scroller.scrollTo({ top: scroller.scrollHeight, behavior: "smooth" });
    }
  }, [messages]);

  // History replay. When the page loads (or the user switches to another
  // consultant), fetch the persisted message log for the active session
  // and seed the chat. Without this, refreshing the page wipes the visible
  // history even though Claude itself (--resume) still remembers it.
  //
  // A ref tracks which session we've already replayed, so the WS `done`
  // event setting sessionId for the FIRST turn doesn't trigger a wasteful
  // re-fetch that just reads back what we already have on screen.
  const replayedForRef = useRef<string | null>(null);
  useEffect(() => {
    if (!backendUrl || !sessionId) return;
    if (replayedForRef.current === sessionId) return;
    replayedForRef.current = sessionId;

    let cancelled = false;
    fetchSessionMessages(backendUrl, sessionId)
      .then((rows) => {
        if (cancelled || rows.length === 0) return;
        setMessages(
          rows.map((r) => ({
            id: `db-${r.id}`,
            role: r.role,
            text: r.content,
            // SQLite stores "YYYY-MM-DD HH:MM:SS" in UTC. The helper
            // explicitly appends Z so JS doesn't misread it as local
            // time (which silently shifted timestamps by the user's
            // tz offset — 8h in Manila, hence the 6:52 PM → 10:52 AM
            // bug on refresh).
            createdAt: parseBackendTimestamp(r.created_at),
          })),
        );
      })
      .catch((err) => {
        console.warn("history replay failed", err);
      });
    return () => {
      cancelled = true;
    };
  }, [backendUrl, sessionId, setMessages]);

  // Re-fetch history when the WS transitions from non-ready to ready.
  // Catches the case where a turn was in flight when the WS dropped (mobile
  // Safari backgrounding, cellular handoff, screen sleep). The backend
  // keeps consuming the claude stream and persists the message; this
  // effect pulls the now-persisted reply down to the UI so the user
  // doesn't see a stuck-forever typing-dots placeholder.
  const lastStatusRef = useRef<ConnectionStatus | null>(null);
  useEffect(() => {
    const prev = lastStatusRef.current;
    lastStatusRef.current = status;
    if (!backendUrl || !sessionId) return;
    if (status !== "ready") return;
    if (prev === null || prev === "ready") return; // initial mount handled by replay effect

    let cancelled = false;
    fetchSessionMessages(backendUrl, sessionId)
      .then((rows) => {
        if (cancelled || rows.length === 0) return;
        setMessages(
          rows.map((r) => ({
            id: `db-${r.id}`,
            role: r.role,
            text: r.content,
            // SQLite stores "YYYY-MM-DD HH:MM:SS" in UTC. The helper
            // explicitly appends Z so JS doesn't misread it as local
            // time (which silently shifted timestamps by the user's
            // tz offset — 8h in Manila, hence the 6:52 PM → 10:52 AM
            // bug on refresh).
            createdAt: parseBackendTimestamp(r.created_at),
          })),
        );
      })
      .catch((err) => {
        console.warn("reconnect history refetch failed", err);
      });
    return () => {
      cancelled = true;
    };
  }, [status, backendUrl, sessionId, setMessages]);

  function pickConsultant(next: string) {
    if (!next || next === slug) return;
    setSlug(next);
    setConsultantSlug(next);
    const sid = getSessionId(next);
    setInitialSessionId(sid);
    setSessionIdState(sid);
    setInitialClaudeSessionId(getClaudeSessionId(next));
    setUploads([]);
    setSavedLearningMessageIds(new Set());
    setEditingLearningForId(null);
    replayedForRef.current = null; // allow history replay for the new consultant
    reset();
  }

  function startNewConversation() {
    if (!slug) return;
    setSessionId(slug, null);
    setClaudeSessionId(slug, null);
    setInitialSessionId(null);
    setSessionIdState(null);
    setInitialClaudeSessionId(null);
    setUploads([]);
    setSavedLearningMessageIds(new Set());
    setEditingLearningForId(null);
    replayedForRef.current = null;
    reset();
  }

  function pickSession(s: SessionRow) {
    if (!slug || s.id === sessionId) return;
    setSessionId(slug, s.id);
    setClaudeSessionId(slug, s.claude_session_id);
    setSessionIdState(s.id);
    setInitialSessionId(s.id);
    setInitialClaudeSessionId(s.claude_session_id);
    setUploads([]);
    setSavedLearningMessageIds(new Set());
    setEditingLearningForId(null);
    replayedForRef.current = null; // force history replay
    reset();
  }

  function submitDraft(textOverride?: string) {
    // Allow the caller (e.g. a starter-chip click) to send a specific
    // string without going through the `draft` state — necessary because
    // `setDraft(...)` won't be flushed by the time submitDraft runs on
    // the same tick, so this function would otherwise read the old draft.
    const text = (textOverride ?? draft).trim();
    if (!text || !slug || isStreaming || status !== "ready") return;

    // If files were uploaded since the last send, bundle them into the
    // message text. That way (a) the user's bubble shows what was attached,
    // (b) Claude reads the same content and knows the on-disk paths, and
    // (c) the attachments are tied to the message that referenced them in
    // the persisted history.
    let composed = text;
    if (uploads.length > 0) {
      // All uploads in a single send share a parent dir; derive it once.
      const firstPath = uploads[0].relative_path;
      const parentDir = firstPath.slice(0, firstPath.lastIndexOf("/"));
      const fileList = uploads
        .map((u) => `• ${u.original_filename}`)
        .join("\n");
      composed = `📎 Attached ${uploads.length} file${uploads.length === 1 ? "" : "s"} to \`${parentDir}/\`:\n${fileList}\n\n${text}`;
    }

    send({ content: composed });
    setDraft("");
    setUploads([]); // consumed — next message starts a fresh attachment list
  }

  async function handleFiles(files: File[]) {
    if (!sessionId) {
      setUploadError(
        "Send a message first to start the session, then attach photos.",
      );
      return;
    }
    setUploadError(null);
    try {
      const uploaded = await uploadFiles(backendUrl, sessionId, files);
      setUploads((prev) => [...prev, ...uploaded]);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : String(err));
    }
  }

  function removeUpload(stored: string) {
    setUploads((prev) => prev.filter((u) => u.stored_filename !== stored));
  }

  // Map an assistant message to the user message that came right before it,
  // so the save-learning form can pre-fill "trigger" with that context.
  const triggerForMessage = useMemo(() => {
    const map = new Map<string, string>();
    for (let i = 0; i < messages.length; i++) {
      const m = messages[i];
      if (m.role !== "assistant") continue;
      const prev = messages[i - 1];
      if (prev && prev.role === "user") map.set(m.id, prev.text);
    }
    return map;
  }, [messages]);

  async function handleSaveLearning(
    messageId: string,
    args: { title: string; trigger: string; rule: string },
  ) {
    if (!slug) return;
    await saveLearning({
      backendUrl,
      consultantSlug: slug,
      title: args.title,
      trigger: args.trigger,
      rule: args.rule,
      savedBy: userName,
      sessionId,
    });
    setSavedLearningMessageIds((prev) => new Set(prev).add(messageId));
    setEditingLearningForId(null);
  }

  return (
    // Flex column anchored to the parent's height. In the standalone repo
    // the parent is <body className="h-full">, so this fills the viewport.
    // In HUP-Sales-App the parent is .harcourts-chat-shell which is set to
    // height: 100% inside a flex-grow card — same shape. The previous
    // `fixed inset-x-0 bottom-0` footer broke that second case because
    // the footer anchored to the viewport rather than the card, hiding
    // off-screen below the dashboard chrome.
    <div className="flex h-full min-h-0 flex-col bg-background">
      <Header
        userName={userName}
        consultants={consultants}
        slug={slug}
        onPickConsultant={pickConsultant}
        status={status}
        onNewConversation={startNewConversation}
        onDownloadConversation={() =>
          downloadConversationAsMarkdown(messages, slug, userName)
        }
        canDownload={messages.length > 0}
        onReconnect={reconnect}
        backendUrl={backendUrl}
        currentSessionId={sessionId}
        onPickSession={pickSession}
        onDeletedSession={(id) => {
          // If the user deleted the session they're currently in, clear
          // the chat surface back to the empty state. Otherwise we'd
          // keep showing messages whose session no longer exists, and
          // the next user turn would create a fresh row anyway.
          if (id === sessionId) startNewConversation();
        }}
        headerSlot={headerSlot}
        // Re-bumps the picker's fetch so a freshly-finished turn appears
        // without having to close + reopen.
        sessionsRefreshKey={messages.length}
      />

      {/* Full-bleed scroll container — the scrollbar sits at the card's
          right edge with no inset. The max-width constraint moves to
          the inner content wrapper below so messages still cap at a
          readable line length, but the scroll rail is flush. This is
          the canonical "full-bleed scroller, centred content" pattern
          (Slack, Notion, Linear all use it).
          `min-h-0` lets the flex child shrink below its content size
          so overflow actually scrolls instead of pushing the column. */}
      <main className="chat-scroll flex w-full min-h-0 flex-1 flex-col overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl flex-1 px-4">
          {messages.length === 0 ? (
            <EmptyState slug={slug} onPickStarter={handlePickStarter} />
          ) : (
            <ol ref={messagesRef} className="flex-1 space-y-6 py-6">
              {messages.map((m) => (
                <MessageBubble
                  key={m.id}
                  message={m}
                  backendUrl={backendUrl}
                  consultantSlug={slug}
                  userName={userName}
                  activity={m.streaming ? activity : null}
                  editing={editingLearningForId === m.id}
                  saved={savedLearningMessageIds.has(m.id)}
                  onStartSave={() => setEditingLearningForId(m.id)}
                  onCancelSave={() => setEditingLearningForId(null)}
                  onSubmitSave={(args) => handleSaveLearning(m.id, args)}
                  defaultTrigger={triggerForMessage.get(m.id) ?? ""}
                />
              ))}
              <div ref={bottomRef} />
            </ol>
          )}
        </div>
      </main>

      {/* Footer sits at the end of the flex column. shrink-0 keeps it
          from collapsing when the message list grows; no fixed-position
          tricks needed. */}
      <footer className="shrink-0 border-t bg-background/95 backdrop-blur">
        <div className="mx-auto w-full max-w-5xl space-y-2 p-4">
          {(uploads.length > 0 || uploadError) && (
            <div className="space-y-1.5">
              <div className="flex flex-wrap items-center gap-2">
                {uploads.map((u) => (
                  <span
                    key={u.stored_filename}
                    className="inline-flex items-center gap-1 rounded-full border bg-muted px-2.5 py-1 text-xs"
                  >
                    <span className="max-w-[180px] truncate">
                      {u.original_filename}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeUpload(u.stored_filename)}
                      className="text-muted-foreground hover:text-foreground"
                      aria-label={`Remove ${u.original_filename}`}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
                {uploadError && (
                  <span className="text-xs text-destructive">{uploadError}</span>
                )}
              </div>
              {uploads.length > 0 && (
                <p className="text-[11px] text-muted-foreground">
                  Tip: say &quot;save this for future listings&quot; in your
                  next message to keep it in this consultant&apos;s permanent
                  knowledge. Otherwise it&apos;s attached to this chat only.
                </p>
              )}
            </div>
          )}
          <div className="flex items-end gap-2">
            <UploadButton
              disabled={!sessionId || isStreaming || status !== "ready"}
              onFiles={handleFiles}
            />
            <Input
              ref={messageInputRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submitDraft();
                }
              }}
              placeholder={
                status !== "ready"
                  ? `Connecting to backend…`
                  : isStreaming
                    ? // Static, friendly message while the consultant is
                      // working. The live tool-activity ticker lives in
                      // the bubble — duplicating it here just crowded
                      // the surface.
                      `${slug ? prettySlug(slug) : "The consultant"} is working on it…`
                    : `Message ${slug ? prettySlug(slug) : "the consultant"}…`
              }
              disabled={status !== "ready" || !slug || isStreaming}
              aria-label="Message"
            />
            <Button
              // Wrapped because submitDraft now takes an optional
              // textOverride. Without the wrapper, React passes the
              // MouseEvent through as `textOverride` and TypeScript
              // (correctly) flags the type mismatch.
              onClick={() => submitDraft()}
              disabled={
                !draft.trim() || !slug || isStreaming || status !== "ready"
              }
              size="icon"
              aria-label="Send"
            >
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </footer>
    </div>
  );
}

interface HeaderProps {
  userName: string;
  consultants: string[] | null;
  slug: string | null;
  onPickConsultant: (slug: string) => void;
  status: ConnectionStatus;
  onNewConversation: () => void;
  onDownloadConversation: () => void;
  /** True when there's anything worth downloading (any messages in the
   * current session). Disables the Download button when false. */
  canDownload: boolean;
  onReconnect: () => void;
  backendUrl: string;
  currentSessionId: string | null;
  onPickSession: (s: SessionRow) => void;
  onDeletedSession: (id: string) => void;
  headerSlot?: React.ReactNode;
  sessionsRefreshKey: unknown;
}

function Header({
  userName,
  consultants,
  slug,
  onPickConsultant,
  status,
  onNewConversation,
  onDownloadConversation,
  canDownload,
  onReconnect,
  backendUrl,
  currentSessionId,
  onPickSession,
  onDeletedSession,
  headerSlot,
  sessionsRefreshKey,
}: HeaderProps) {
  // Header is the first flex child of the chat; `shrink-0` stops it
  // being squashed when the message list grows. The old `sticky top-0`
  // was only needed when the chat was a single tall page; now it's a
  // fixed slot in a flex column.
  return (
    <header className="shrink-0 z-10 border-b bg-background/95 backdrop-blur">
      {/* Two clusters with justify-between: left side is the session
          navigation (which consultant, what session, start new); right
          side is meta-controls (host-app extras like New/Old toggle,
          Tools, plus the connection dot). Splitting them visually
          stops the toolbar feeling crowded — left tools have a clear
          job, right tools are "settings". */}
      <div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-4 px-3 py-3 sm:px-4">
        <div className="flex min-w-0 items-center gap-2 sm:gap-3">
          <select
          value={slug ?? ""}
          onChange={(e) => onPickConsultant(e.target.value)}
          disabled={!consultants || consultants.length === 0}
          className="h-9 min-w-0 flex-1 truncate rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 sm:flex-none sm:min-w-[180px]"
          aria-label="Choose a consultant"
        >
          {consultants === null && <option>Loading…</option>}
          {consultants?.length === 0 && <option>No consultants</option>}
          {consultants?.map((s) => (
            <option key={s} value={s}>
              {prettySlug(s)}
            </option>
          ))}
        </select>

        <SessionPicker
          backendUrl={backendUrl}
          consultantSlug={slug}
          currentSessionId={currentSessionId}
          onPick={onPickSession}
          onDeleted={onDeletedSession}
          refreshKey={sessionsRefreshKey}
        />

        <Button
          variant="ghost"
          size="sm"
          onClick={onDownloadConversation}
          disabled={!canDownload}
          aria-label="Download conversation"
          title="Download this conversation as a markdown file"
          className="px-2 sm:px-3"
        >
          <Download className="h-3.5 w-3.5 sm:mr-1.5" />
          <span className="hidden sm:inline">Save</span>
        </Button>

        <Button
          variant="ghost"
          size="sm"
          onClick={onNewConversation}
          disabled={!slug}
          aria-label="Start a new conversation"
          title="Start a new conversation"
          className="px-2 sm:px-3"
        >
          <RefreshCcw className="h-3.5 w-3.5 sm:mr-1.5" />
          <span className="hidden sm:inline">New</span>
        </Button>
        </div>

        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {/* Host-app extras (e.g. HUP's New/Old variant switch + Tools
              button) render here so the chat doesn't end up with two
              stacked toolbar rows. Standalone passes nothing → no slot. */}
          {headerSlot}

          {(status === "closed" || status === "error") ? (
            <button
              type="button"
              onClick={onReconnect}
              className="inline-flex items-center gap-1.5 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-rose-600 hover:bg-rose-500/20 dark:text-rose-400"
              title="The backend connection dropped. Click to retry."
            >
              <span className="h-2 w-2 rounded-full bg-rose-500" />
              <span className="hidden sm:inline">Reconnect</span>
            </button>
          ) : (
            <StatusDot status={status} />
          )}
          {/* userName intentionally NOT rendered here. In HUP-Sales-App
              the dashboard header already shows the signed-in identity;
              in the standalone repo the body wrapper has no chrome but
              the email address inside a chat toolbar is just visual
              noise. The variable is still threaded through Chat props
              because it's needed for outgoing WS messages (the
              backend re-derives it from the JWT, but the dev-mode
              path still uses it as a label). */}
        </div>
      </div>
    </header>
  );
}

function StatusDot({ status }: { status: ConnectionStatus }) {
  // Three visual states, each with a motion variant that reads at a
  // glance:
  //
  //   ready      → emerald, 2s gentle pulse (alpha 0.7→1, scale 1→1.15)
  //                — says "alive, healthy"
  //   connecting → amber, fast 0.8s pulse — says "I'm working on it"
  //   closed/    → rose, no pulse — paired in the host with a Reconnect
  //   error        button so we don't double-animate
  //
  // Plus a soft halo ring underneath the core dot for the ready state —
  // a low-opacity expanding ring that gives the "live signal" feel
  // without grabbing attention. The user explicitly asked for "more
  // animation" on this element.
  const tone =
    status === "ready"
      ? { dot: "bg-emerald-500", halo: "bg-emerald-400/60", label: "Connected" }
      : status === "connecting"
        ? { dot: "bg-amber-500", halo: "bg-amber-400/60", label: "Connecting…" }
        : { dot: "bg-rose-500", halo: "bg-rose-400/0", label: "Disconnected" };

  return (
    <span
      className="relative inline-flex items-center gap-1.5"
      title={tone.label}
    >
      <span className="relative inline-flex h-2.5 w-2.5 items-center justify-center">
        {/* Expanding halo behind the core dot. Disabled for the closed
            state (opacity 0) — animating a "dead" state would be
            misleading. */}
        {(status === "ready" || status === "connecting") && (
          <motion.span
            aria-hidden
            className={cn(
              "absolute inset-0 rounded-full",
              tone.halo,
            )}
            initial={{ opacity: 0.65, scale: 1 }}
            animate={{ opacity: 0, scale: 2.4 }}
            transition={{
              duration: status === "connecting" ? 0.9 : 2,
              repeat: Infinity,
              ease: "easeOut",
            }}
          />
        )}
        <motion.span
          className={cn("relative h-2 w-2 rounded-full", tone.dot)}
          animate={
            status === "ready"
              ? { scale: [1, 1.15, 1], opacity: [1, 0.85, 1] }
              : status === "connecting"
                ? { scale: [1, 1.25, 1], opacity: [1, 0.7, 1] }
                : { scale: 1, opacity: 1 }
          }
          transition={{
            duration: status === "connecting" ? 0.9 : 2,
            repeat: status === "closed" || status === "error" ? 0 : Infinity,
            ease: "easeInOut",
          }}
        />
      </span>
    </span>
  );
}

/**
 * Quick-start prompts shown as clickable chips on the empty state. Click
 * pre-fills the message input — doesn't auto-send, so the user can
 * tweak the wording (add an address, change tone) before committing.
 *
 * Generic across consultants — no per-consultant variation in v1.
 * If a chip ever needs to differ per consultant, lift the list into
 * a per-slug map keyed on `prettySlug(slug)`.
 */
const STARTER_PROMPTS: ReadonlyArray<{ label: string; text: string }> = [
  {
    label: "Start a new listing",
    text:
      "I've got a new listing to put together. The property is at ",
  },
  {
    label: "Research a property",
    text:
      "Can you research the suburb amenities, school catchments, and any recent comparable sales for ",
  },
  {
    label: "What can you help with?",
    text: "What can you help me with on a listing?",
  },
];

function EmptyState({
  slug,
  onPickStarter,
}: {
  slug: string | null;
  onPickStarter: (text: string) => void;
}) {
  // Hero empty state. AnimatePresence + the slug-as-key gives the
  // consultant swap a real motion: the old avatar + name fade out as
  // the new one fades in. The avatar uses layoutId="agent-avatar" so
  // framer-motion morphs its position smoothly across the swap rather
  // than hard-mounting a new node — feels like a deliberate handoff.
  return (
    <div className="flex flex-1 items-center justify-center py-16">
      <AnimatePresence mode="wait">
        <motion.div
          key={slug ?? "no-slug"}
          className="relative max-w-md space-y-5 text-center"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8, scale: 0.98 }}
          transition={{ duration: 0.32, ease: [0.2, 0.7, 0.2, 1] }}
        >
          {/* Soft radial halo so the avatar reads as a focal point, not
              a stamp floating on flat white. Animated separately so the
              halo can "pulse" briefly on agent switch. */}
          <motion.div
            aria-hidden
            className="pointer-events-none absolute left-1/2 top-0 -z-10 h-48 w-48 -translate-x-1/2 rounded-full bg-accent/60 blur-2xl"
            initial={{ scale: 0.7, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.5 }}
          />
          <div className="flex justify-center">
            <AvatarCircle slug={slug} size={112} ringed animate />
          </div>
          <div className="space-y-1.5">
            <h2 className="text-2xl font-semibold text-foreground">
              {slug ? prettySlug(slug) : "Pick a consultant"}
              <span className="text-muted-foreground font-normal">
                {" is ready"}
              </span>
            </h2>
            <p className="text-sm text-muted-foreground">
              Start by asking for a new listing, or paste in a property
              address. Your feedback during the chat updates this
              consultant&apos;s shared voice rules for everyone on the team.
            </p>
          </div>

          {/* Quick-start chips. Stagger the entrance slightly so they
              read as a separate "next step" beat after the headline. */}
          <motion.div
            className="flex flex-wrap justify-center gap-2 pt-2"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.32, delay: 0.18 }}
          >
            {STARTER_PROMPTS.map((s) => (
              <button
                key={s.label}
                type="button"
                onClick={() => onPickStarter(s.text)}
                className="rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground shadow-sm transition-colors hover:border-primary/40 hover:bg-accent hover:text-primary"
              >
                {s.label}
              </button>
            ))}
          </motion.div>
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

interface MessageBubbleProps {
  message: ChatMessage;
  backendUrl: string;
  /** Currently-selected consultant — drives the assistant-side avatar. */
  consultantSlug: string | null;
  /** Signed-in user (email or name) — drives the user-side initials avatar. */
  userName: string;
  /** Live tool-activity summary from the backend; non-null only while
   * this message is streaming. Drives the StillWorkingBadge text. */
  activity: string | null;
  editing: boolean;
  saved: boolean;
  defaultTrigger: string;
  onStartSave: () => void;
  onCancelSave: () => void;
  onSubmitSave: (args: { title: string; trigger: string; rule: string }) => Promise<void>;
}

// Pull every downloadable-file mention out of an assistant message so
// we can render per-file download chips below the prose. The chip
// hits /api/outputs/<filename>; the backend validates that the file
// exists inside outputs/ AND that the extension is on the safe
// allow-list (docx, pdf, csv, txt, md, jpg, jpeg, png, webp) — so a
// stray "report.docx" mention that isn't real is harmless (404), and
// a hostile ".html" mention is rejected upstream (400).
//
// Regex accepts either form:
//   "outputs/foo.docx"     — explicit-path style
//   "saved as foo.jpg"     — friendlier prompt-engineered style
// Extensions match the backend allow-list. Keep these in sync; mismatch
// means a chip renders but the click 400s.
const DOWNLOADABLE_EXT_RE =
  /(?:outputs\/)?([A-Za-z0-9][A-Za-z0-9._\-]*\.(?:docx|pdf|csv|txt|md|jpe?g|png|webp))\b/gi;

function extractOutputFilenames(text: string): string[] {
  const seen = new Set<string>();
  for (const m of text.matchAll(DOWNLOADABLE_EXT_RE)) {
    seen.add(m[1]);
  }
  return [...seen];
}

function MessageBubble({
  message,
  backendUrl,
  consultantSlug,
  userName,
  activity,
  editing,
  saved,
  defaultTrigger,
  onStartSave,
  onCancelSave,
  onSubmitSave,
}: MessageBubbleProps) {
  const isUser = message.role === "user";
  const canSave =
    !isUser && !message.streaming && message.text.trim().length > 0;
  const downloadable = useMemo(
    () =>
      !isUser && !message.streaming
        ? extractOutputFilenames(message.text)
        : [],
    [isUser, message.streaming, message.text],
  );

  return (
    <li
      className={cn(
        "group flex w-full items-end gap-2",
        isUser ? "justify-end" : "justify-start",
      )}
    >
      {/* Assistant avatar — left of the bubble. Uses the consultant's
          actual photo (lib/avatars.ts maps slug→PNG) with the initials
          fallback baked into AvatarCircle. items-end aligns it with
          the bottom of the bubble so a tall message doesn't look top-
          heavy. shrink-0 stops it being squashed on narrow viewports. */}
      {!isUser && (
        <AvatarCircle
          slug={consultantSlug}
          size={32}
          animate={false}
          className="shrink-0"
        />
      )}

      <div className={cn("flex max-w-[80%] flex-col", isUser && "items-end")}>
        <div
          className={cn(
            "rounded-2xl px-4 py-3 text-sm leading-relaxed",
            isUser
              ? "whitespace-pre-wrap bg-primary text-primary-foreground"
              : "bg-muted text-foreground",
          )}
        >
          {message.text ? (
            isUser ? (
              message.text
            ) : (
              <div
                className={cn(
                  // prose colors come from our --tw-prose-* CSS variable
                  // mapping in globals.css (which uses the theme's
                  // --foreground). That's why we DON'T need dark:prose-invert
                  // — prose is theme-aware via CSS variables, not the
                  // Tailwind dark: variant.
                  "prose prose-sm max-w-none",
                  // Tighten the prose for a chat bubble — kill outer spacing
                  // and trim heading sizes so they don't shout.
                  "prose-p:my-2 prose-p:leading-relaxed",
                  "prose-headings:mt-3 prose-headings:mb-1.5 prose-headings:font-semibold",
                  "prose-h1:text-base prose-h2:text-base prose-h3:text-sm",
                  "prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5",
                  "prose-pre:my-2 prose-pre:rounded-md",
                  "prose-code:before:hidden prose-code:after:hidden",
                  "prose-code:bg-background/60 prose-code:px-1.5 prose-code:py-0.5",
                  "prose-code:rounded-sm prose-code:font-normal",
                  "prose-a:underline-offset-2",
                  "first:[&>*]:mt-0 last:[&>*]:mb-0",
                )}
              >
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    // Fenced code blocks get syntax highlighting and a
                    // top-right copy button. Inline code keeps the
                    // existing prose-styled pill look from the `prose`
                    // classes above.
                    code(props) {
                      const { className, children, ...rest } = props;
                      const match = /language-(\w+)/.exec(className || "");
                      const inline = !(
                        match || String(children).includes("\n")
                      );
                      if (inline) {
                        return (
                          <code className={className} {...rest}>
                            {children}
                          </code>
                        );
                      }
                      return (
                        <CodeBlock
                          language={match?.[1] ?? "text"}
                          value={String(children).replace(/\n$/, "")}
                        />
                      );
                    },
                  }}
                >
                  {message.text}
                </ReactMarkdown>
              </div>
            )
          ) : (
            <StreamingPlaceholder activity={activity} />
          )}
          {/* Token / cost metadata is intentionally hidden — your team is on
              the Claude Max subscription, so the per-turn dollar figure is
              misleading. Raw counts are still persisted in SQLite for
              diagnostics. */}
        </div>

        {/* Only show the "still working" badge once the bubble has some
            text. While the bubble is empty, StreamingPlaceholder (inside
            the bubble) already shows the same indicator — rendering both
            simultaneously produced a duplicated "Still working" stack. */}
        {!isUser && message.text.length > 0 && (
          <StillWorkingBadge
            text={message.text}
            streaming={!!message.streaming}
            activity={activity}
          />
        )}

        {/* Combined actions row below the bubble.
            Left side: persistent "Save as voice rule" — the primary
            action, so always visible (no hover required).
            Right side: Copy button, hidden until hover on desktop,
            always-on under @media (hover: none) for touch screens.
            Splitting visibility this way keeps the bubble's footer
            clean during quick reads while still letting the user copy
            without a long-press. */}
        {!isUser && !message.streaming && message.text.length > 0 && (
          <div className="mt-1 flex items-center gap-1 self-start">
            {canSave && !editing && !saved && (
              <button
                type="button"
                onClick={onStartSave}
                className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <BookmarkPlus className="h-3.5 w-3.5" />
                Save as voice rule
              </button>
            )}
            {canSave && saved && (
              <span className="inline-flex items-center gap-1.5 px-2 py-1 text-xs text-emerald-600 dark:text-emerald-500">
                <BookmarkPlus className="h-3.5 w-3.5" />
                Saved to learnings
              </span>
            )}
            <span className="opacity-0 transition-opacity group-hover:opacity-100 [@media(hover:none)]:opacity-100">
              <CopyButton text={message.text} label="Copy" />
            </span>
            <MessageTimestamp ts={message.createdAt} />
          </div>
        )}

        {/* User-side timestamp — under the bubble (right-aligned via
            items-end on the bubble's outer column). Always rendered;
            no copy / voice-rule actions on user messages. */}
        {isUser && (
          <div className="mt-1 flex justify-end self-end">
            <MessageTimestamp ts={message.createdAt} />
          </div>
        )}

        {downloadable.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-2 self-start">
            {downloadable.map((filename) => (
              <a
                key={filename}
                // backendUrl is "" briefly on first paint; we hide the
                // link until it's resolved so iOS Safari doesn't bind
                // a broken href.
                href={
                  backendUrl
                    ? `${backendUrl}/api/outputs/${encodeURIComponent(filename)}`
                    : undefined
                }
                // `download` is a hint; the backend ALWAYS sets
                // Content-Disposition: attachment, which is what
                // actually persuades iOS Safari to save to Files
                // instead of opening Quick Look.
                download={filename}
                className="inline-flex items-center gap-1.5 rounded-md border border-input bg-background px-2.5 py-1 text-xs font-medium text-foreground shadow-sm hover:bg-accent hover:text-accent-foreground"
              >
                <Download className="h-3.5 w-3.5" />
                {filename}
              </a>
            ))}
          </div>
        )}

        {canSave && editing && (
          <SaveLearningForm
            defaultTrigger={defaultTrigger}
            onCancel={onCancelSave}
            onSave={onSubmitSave}
          />
        )}
      </div>

      {/* User avatar — right of the bubble. Cyan-filled circle with
          two-letter initials in white, derived from the signed-in
          email or freeform name (Elijah Mirandilla → "EM"). No PNG
          lookup — the user's photo isn't part of Harcourts' avatar
          library; initials are intentionally generic so any future
          consultant or teammate "just works" without a portrait. */}
      {isUser && (
        <UserInitialsAvatar name={userName} size={32} className="shrink-0" />
      )}
    </li>
  );
}

/**
 * Small timestamp shown under each chat bubble. `ts` is epoch ms.
 * Renders as HH:mm in the user's locale (e.g. "14:32"); a full date
 * tooltip on hover for context. If `ts` is 0/missing (legacy DB row
 * without a parseable created_at) the component renders nothing
 * rather than "Invalid date".
 */
/**
 * Single 30s ticker that drives every visible relative timestamp. One
 * interval, many subscribers via the returned `now`. Cheaper than each
 * MessageTimestamp running its own setInterval. 30s = good enough
 * resolution for "just now" → "1m ago" transitions; saves render
 * thrash from a 1s tick that the user won't perceive.
 */
function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

function MessageTimestamp({ ts }: { ts: number }) {
  const now = useNow();
  if (!ts) return null;
  const d = new Date(ts);
  // Messaging-platform style: "just now" / "5m ago" / "14:32" / etc.
  // Helper picks the right format based on age. Tooltip always shows
  // the full date+time so the user can verify exact timing on hover.
  const friendly = formatChatTime(ts, now);
  const full = d.toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return (
    <time
      dateTime={d.toISOString()}
      title={full}
      className="px-1 text-[10px] text-muted-foreground tabular-nums"
    >
      {friendly}
    </time>
  );
}

function UserInitialsAvatar({
  name,
  size = 32,
  className,
}: {
  name: string;
  size?: number;
  className?: string;
}) {
  const initials = userInitials(name);
  return (
    <div
      className={cn(
        "inline-flex items-center justify-center rounded-full bg-primary text-primary-foreground",
        className,
      )}
      style={{ width: size, height: size }}
      title={name}
      aria-label={name}
    >
      <span
        className="font-semibold leading-none"
        style={{ fontSize: Math.round(size * 0.38) }}
      >
        {initials}
      </span>
    </div>
  );
}

/** Three pulsing dots for the first 8 seconds, then a friendlier "still
 *  working" line so the user doesn't think the chat is frozen during
 *  image-heavy turns (multimodal reads can take 20–30s). */
function StreamingPlaceholder({ activity }: { activity: string | null }) {
  const [showSlowHint, setShowSlowHint] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setShowSlowHint(true), 8000);
    return () => clearTimeout(t);
  }, []);

  // Prefer the live tool-activity summary from the backend (e.g.
  // "Reading IMG_4001.jpeg") over the static slow-hint copy. Activity
  // text only appears once Claude actually starts calling a tool, so
  // the slow-hint serves as the "Claude is thinking, hasn't called
  // anything yet" fallback.
  const label = activity ?? (
    showSlowHint
      ? "Still working — large attachments and complex prompts can take 30 seconds."
      : null
  );

  if (label) {
    return (
      <span className="inline-flex items-center gap-2 text-xs italic text-muted-foreground">
        <span className="inline-flex gap-1">
          <Dot delay={0} />
          <Dot delay={150} />
          <Dot delay={300} />
        </span>
        {label}
      </span>
    );
  }
  return (
    <span className="inline-flex gap-1">
      <Dot delay={0} />
      <Dot delay={150} />
      <Dot delay={300} />
    </span>
  );
}

// Shows a "still thinking" indicator BELOW the bubble when streaming is
// active but text hasn't grown for a while. Solves today's failure mode:
// Claude said "Files received. Preparing the brief now." then went silent
// for ~30s reading 32 photos, and the user typed "what happen?" thinking
// the chat had died. The streaming dots in StreamingPlaceholder only show
// when the bubble is empty — once any text lands, they disappear. This
// badge fills that gap.
function StillWorkingBadge({
  text,
  streaming,
  activity,
}: {
  text: string;
  streaming: boolean;
  activity: string | null;
}) {
  const [stalled, setStalled] = useState(false);

  useEffect(() => {
    if (!streaming) {
      setStalled(false);
      return;
    }
    // Any text update resets the gap timer. After 5s of no growth, show.
    setStalled(false);
    const t = setTimeout(() => setStalled(true), 5000);
    return () => clearTimeout(t);
  }, [text, streaming]);

  // Show the badge IF streaming and EITHER (a) we have an active tool
  // call summary from the backend, OR (b) text has stalled for 5s. The
  // activity from the backend is the strongest signal and skips the
  // staleness wait — if Claude IS in a tool call right now, surface
  // that immediately even after a fresh text delta.
  const visible = streaming && (activity !== null || stalled);
  if (!visible) return null;
  return (
    <span className="mt-2 inline-flex items-center gap-2 self-start text-xs italic text-muted-foreground">
      <span className="inline-flex gap-1">
        <Dot delay={0} />
        <Dot delay={150} />
        <Dot delay={300} />
      </span>
      {activity ?? "Still working…"}
    </span>
  );
}

function Dot({ delay }: { delay: number }) {
  return (
    <span
      className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current opacity-60"
      style={{ animationDelay: `${delay}ms` }}
    />
  );
}

/**
 * Copy text to the clipboard, swap to a green check for 1.2s, then snap
 * back. Standalone (used on per-message rows + per-code-block headers).
 */
function CopyButton({
  text,
  label,
  className,
}: {
  text: string;
  label?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        } catch {
          // Clipboard API can fail under strict permissions (iframe, no
          // user gesture). Swallow — no fallback worth the complexity.
        }
      }}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs",
        "text-muted-foreground hover:bg-muted hover:text-foreground",
        "transition-colors",
        className,
      )}
      aria-label={copied ? "Copied" : label || "Copy"}
      title={copied ? "Copied" : label || "Copy"}
    >
      {copied ? (
        <Check className="h-3.5 w-3.5 text-emerald-500" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
      {label && (
        <span className="hidden sm:inline">{copied ? "Copied" : label}</span>
      )}
    </button>
  );
}

/**
 * Fenced code block: syntax-highlighted, with a Copy button in the
 * top-right corner. Uses the `oneLight` Prism theme — light background,
 * blends with the white card without going monochrome dark.
 */
function CodeBlock({
  language,
  value,
}: {
  language: string;
  value: string;
}) {
  return (
    <div className="not-prose relative my-3 overflow-hidden rounded-md border border-border bg-muted">
      <div className="flex items-center justify-between border-b border-border bg-muted/60 px-3 py-1.5">
        <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          {language === "text" ? "code" : language}
        </span>
        <CopyButton text={value} className="px-1.5" />
      </div>
      <div className="overflow-x-auto text-sm">
        <SyntaxHighlighter
          language={language}
          style={oneLight}
          customStyle={{
            margin: 0,
            padding: "0.75rem 1rem",
            background: "transparent",
            fontSize: "0.85em",
            fontFamily: "var(--font-mono, ui-monospace, SFMono-Regular)",
          }}
          PreTag="div"
          wrapLongLines={false}
        >
          {value}
        </SyntaxHighlighter>
      </div>
    </div>
  );
}
