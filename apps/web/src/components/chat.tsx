"use client";

import { Send, RefreshCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  fetchConsultants,
  useChat,
  type ChatMessage,
  type ConnectionStatus,
} from "@/lib/ws";
import {
  getClaudeSessionId,
  getConsultantSlug,
  setClaudeSessionId,
  setConsultantSlug,
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

  // Load consultant list + restore last selection.
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
        if (initial) setInitialSessionId(getClaudeSessionId(initial));
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
    initialClaudeSessionId: initialSessionId,
    onSessionIdChange: (id) => {
      if (slug) setClaudeSessionId(slug, id);
    },
  });

  // Auto-scroll to the latest message.
  const bottomRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function pickConsultant(next: string) {
    if (!next || next === slug) return;
    setSlug(next);
    setConsultantSlug(next);
    setInitialSessionId(getClaudeSessionId(next));
    reset();
  }

  function startNewConversation() {
    if (!slug) return;
    setClaudeSessionId(slug, null);
    setInitialSessionId(null);
    reset();
  }

  function submitDraft() {
    const text = draft.trim();
    if (!text || !slug || isStreaming || status !== "ready") return;
    send({ content: text });
    setDraft("");
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

      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 pb-32">
        {messages.length === 0 ? (
          <EmptyState slug={slug} />
        ) : (
          <ol className="flex-1 space-y-6 py-6">
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} />
            ))}
            <div ref={bottomRef} />
          </ol>
        )}
      </main>

      <footer className="fixed inset-x-0 bottom-0 border-t bg-background/95 backdrop-blur">
        <div className="mx-auto flex w-full max-w-3xl items-end gap-2 p-4">
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

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <li
      className={cn(
        "flex w-full",
        isUser ? "justify-end" : "justify-start",
      )}
    >
      <div
        className={cn(
          "max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-relaxed",
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
            {message.meta.tokensIn ?? 0} in · {message.meta.tokensOut ?? 0} out ·
            ${message.meta.costUsd.toFixed(4)}
          </div>
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
