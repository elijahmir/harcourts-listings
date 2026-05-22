"use client";

import { BookmarkPlus, RefreshCcw, Send, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

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
import { cn } from "@/lib/utils";

interface ChatProps {
  userName: string;
  backendUrl: string;
}

function prettySlug(slug: string): string {
  return slug
    .split("-")
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join(" ");
}

export function Chat({ userName, backendUrl }: ChatProps) {
  const [consultants, setConsultants] = useState<string[] | null>(null);
  const [slug, setSlug] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
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
          const sid = getSessionId(initial);
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

  const { messages, status, isStreaming, send, reset, reconnect, setMessages } = useChat({
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

  // Auto-scroll to the latest message.
  const bottomRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
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

  function submitDraft() {
    const text = draft.trim();
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
    <div className="flex min-h-dvh flex-col">
      <Header
        userName={userName}
        consultants={consultants}
        slug={slug}
        onPickConsultant={pickConsultant}
        status={status}
        onNewConversation={startNewConversation}
        onReconnect={reconnect}
        backendUrl={backendUrl}
        currentSessionId={sessionId}
        onPickSession={pickSession}
        // Re-bumps the picker's fetch so a freshly-finished turn appears
        // without having to close + reopen.
        sessionsRefreshKey={messages.length}
      />

      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 pb-44">
        {messages.length === 0 ? (
          <EmptyState slug={slug} />
        ) : (
          <ol className="flex-1 space-y-6 py-6">
            {messages.map((m) => (
              <MessageBubble
                key={m.id}
                message={m}
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
      </main>

      <footer className="fixed inset-x-0 bottom-0 border-t bg-background/95 backdrop-blur">
        <div className="mx-auto w-full max-w-3xl space-y-2 p-4">
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
                  : `Message ${slug ? prettySlug(slug) : "the consultant"}…`
              }
              disabled={status !== "ready" || !slug || isStreaming}
              aria-label="Message"
            />
            <Button
              onClick={submitDraft}
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
  onReconnect: () => void;
  backendUrl: string;
  currentSessionId: string | null;
  onPickSession: (s: SessionRow) => void;
  sessionsRefreshKey: unknown;
}

function Header({
  userName,
  consultants,
  slug,
  onPickConsultant,
  status,
  onNewConversation,
  onReconnect,
  backendUrl,
  currentSessionId,
  onPickSession,
  sessionsRefreshKey,
}: HeaderProps) {
  return (
    <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
      <div className="mx-auto flex w-full max-w-3xl items-center gap-2 px-3 py-3 sm:gap-3 sm:px-4">
        {/* Brand text — hidden on phones; consultant + actions take priority. */}
        <div className="hidden text-sm font-medium text-muted-foreground sm:block">
          Harcourts
        </div>
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
          refreshKey={sessionsRefreshKey}
        />

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

        <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
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
          {/* Username — hidden on phones to save horizontal space; the status
              dot alone conveys connection state. */}
          <span className="hidden sm:inline">{userName}</span>
        </div>
      </div>
    </header>
  );
}

function StatusDot({ status }: { status: ConnectionStatus }) {
  const color =
    status === "ready"
      ? "bg-emerald-500"
      : status === "connecting"
        ? "bg-amber-500"
        : "bg-rose-500";
  const label =
    status === "ready"
      ? "Connected"
      : status === "connecting"
        ? "Connecting…"
        : "Disconnected";
  return (
    <span className="inline-flex items-center gap-1.5" title={label}>
      <span className={cn("h-2 w-2 rounded-full", color)} />
    </span>
  );
}

function EmptyState({ slug }: { slug: string | null }) {
  return (
    <div className="flex flex-1 items-center justify-center py-16">
      <div className="max-w-md space-y-2 text-center">
        <h2 className="text-lg font-medium">
          {slug ? prettySlug(slug) : "Pick a consultant"} is ready
        </h2>
        <p className="text-sm text-muted-foreground">
          Start by asking for a new listing, or paste in a property address.
          Your feedback during the chat updates this consultant&apos;s shared
          voice rules for everyone on the team.
        </p>
      </div>
    </div>
  );
}

interface MessageBubbleProps {
  message: ChatMessage;
  editing: boolean;
  saved: boolean;
  defaultTrigger: string;
  onStartSave: () => void;
  onCancelSave: () => void;
  onSubmitSave: (args: { title: string; trigger: string; rule: string }) => Promise<void>;
}

function MessageBubble({
  message,
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

  return (
    <li className={cn("flex w-full", isUser ? "justify-end" : "justify-start")}>
      <div className={cn("flex max-w-[85%] flex-col", isUser && "items-end")}>
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
                  "prose prose-sm max-w-none dark:prose-invert",
                  // Tighten the prose for a chat bubble — kill outer spacing
                  // and trim heading sizes so they don't shout.
                  "prose-p:my-2 prose-p:leading-relaxed",
                  "prose-headings:mt-3 prose-headings:mb-1.5 prose-headings:font-semibold",
                  "prose-h1:text-base prose-h2:text-base prose-h3:text-sm",
                  "prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5",
                  "prose-pre:my-2 prose-pre:bg-background/60 prose-pre:rounded-md",
                  "prose-code:before:hidden prose-code:after:hidden",
                  "prose-code:bg-background/60 prose-code:px-1.5 prose-code:py-0.5",
                  "prose-code:rounded-sm prose-code:font-normal",
                  "prose-a:text-primary prose-a:underline-offset-2",
                  "first:[&>*]:mt-0 last:[&>*]:mb-0",
                )}
              >
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.text}
                </ReactMarkdown>
              </div>
            )
          ) : (
            <StreamingPlaceholder />
          )}
          {/* Token / cost metadata is intentionally hidden — your team is on
              the Claude Max subscription, so the per-turn dollar figure is
              misleading. Raw counts are still persisted in SQLite for
              diagnostics. */}
        </div>

        {canSave && !editing && !saved && (
          <button
            type="button"
            onClick={onStartSave}
            className="mt-2 inline-flex items-center gap-1.5 self-start rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <BookmarkPlus className="h-3.5 w-3.5" />
            Save as voice rule
          </button>
        )}

        {canSave && saved && (
          <span className="mt-2 inline-flex items-center gap-1.5 self-start text-xs text-emerald-600 dark:text-emerald-500">
            <BookmarkPlus className="h-3.5 w-3.5" />
            Saved to learnings
          </span>
        )}

        {canSave && editing && (
          <SaveLearningForm
            defaultTrigger={defaultTrigger}
            onCancel={onCancelSave}
            onSave={onSubmitSave}
          />
        )}
      </div>
    </li>
  );
}

/** Three pulsing dots for the first 8 seconds, then a friendlier "still
 *  working" line so the user doesn't think the chat is frozen during
 *  image-heavy turns (multimodal reads can take 20–30s). */
function StreamingPlaceholder() {
  const [showSlowHint, setShowSlowHint] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setShowSlowHint(true), 8000);
    return () => clearTimeout(t);
  }, []);

  if (showSlowHint) {
    return (
      <span className="inline-flex items-center gap-2 text-xs italic text-muted-foreground">
        <span className="inline-flex gap-1">
          <Dot delay={0} />
          <Dot delay={150} />
          <Dot delay={300} />
        </span>
        Still working — large attachments and complex prompts can take 30 seconds.
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

function Dot({ delay }: { delay: number }) {
  return (
    <span
      className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current opacity-60"
      style={{ animationDelay: `${delay}ms` }}
    />
  );
}
