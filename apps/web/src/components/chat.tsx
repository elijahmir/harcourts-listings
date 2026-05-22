"use client";

import { BookmarkPlus, RefreshCcw, Send, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { SaveLearningForm } from "@/components/save-learning-form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { UploadButton } from "@/components/upload-button";
import {
  fetchConsultants,
  saveLearning,
  uploadFiles,
  useChat,
  type ChatMessage,
  type ConnectionStatus,
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
          setInitialSessionId(getSessionId(initial));
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

  const { messages, status, isStreaming, send, reset } = useChat({
    backendUrl,
    consultantSlug: slug,
    userName,
    initialSessionId,
    initialClaudeSessionId,
    onSessionIdChange: (id) => {
      if (slug) setSessionId(slug, id);
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

  // The session_id we hold for THIS consultant. Read from localStorage on
  // every render so the upload button can react when the first turn lands.
  const sessionId = useMemo(
    () => (slug ? getSessionId(slug) : null),
    // Reread when messages change (proxy for "a turn just finished").
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [slug, messages.length],
  );

  function pickConsultant(next: string) {
    if (!next || next === slug) return;
    setSlug(next);
    setConsultantSlug(next);
    setInitialSessionId(getSessionId(next));
    setInitialClaudeSessionId(getClaudeSessionId(next));
    setUploads([]);
    setSavedLearningMessageIds(new Set());
    setEditingLearningForId(null);
    reset();
  }

  function startNewConversation() {
    if (!slug) return;
    setSessionId(slug, null);
    setClaudeSessionId(slug, null);
    setInitialSessionId(null);
    setInitialClaudeSessionId(null);
    setUploads([]);
    setSavedLearningMessageIds(new Set());
    setEditingLearningForId(null);
    reset();
  }

  function submitDraft() {
    const text = draft.trim();
    if (!text || !slug || isStreaming || status !== "ready") return;
    send({ content: text });
    setDraft("");
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
}

function Header({
  userName,
  consultants,
  slug,
  onPickConsultant,
  status,
  onNewConversation,
}: HeaderProps) {
  return (
    <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
      <div className="mx-auto flex w-full max-w-3xl items-center gap-3 px-4 py-3">
        <div className="text-sm font-medium text-muted-foreground">
          Harcourts
        </div>
        <select
          value={slug ?? ""}
          onChange={(e) => onPickConsultant(e.target.value)}
          disabled={!consultants || consultants.length === 0}
          className="h-9 rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
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

        <Button
          variant="ghost"
          size="sm"
          onClick={onNewConversation}
          disabled={!slug}
          aria-label="Start a new conversation"
        >
          <RefreshCcw className="mr-1.5 h-3.5 w-3.5" />
          New
        </Button>

        <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          <StatusDot status={status} />
          <span>{userName}</span>
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
            "whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-relaxed",
            isUser
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-foreground",
          )}
        >
          {message.text || (
            <span className="inline-flex gap-1">
              <Dot delay={0} />
              <Dot delay={150} />
              <Dot delay={300} />
            </span>
          )}
          {!isUser && message.meta?.costUsd != null && message.meta.costUsd > 0 && (
            <div className="mt-2 text-[10px] uppercase tracking-wide text-muted-foreground">
              {message.meta.tokensIn ?? 0} in · {message.meta.tokensOut ?? 0} out
              · ${message.meta.costUsd.toFixed(4)}
            </div>
          )}
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

function Dot({ delay }: { delay: number }) {
  return (
    <span
      className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current opacity-60"
      style={{ animationDelay: `${delay}ms` }}
    />
  );
}
