/** WebSocket client + React hook for streaming chat with the backend.
 *
 * Protocol mirrors services/backend/app/main.py:
 *
 *   Client → Server:
 *     {type: "user_message", consultant_slug, user_name, content, claude_session_id?}
 *
 *   Server → Client:
 *     {type: "ready"}
 *     {type: "chunk", kind: "text_delta" | "text_full" | ..., text, session_id}
 *     {type: "done",  claude_session_id, tokens, cost_usd, return_code, is_error, error_message}
 *     {type: "error", message}
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  /** True while this assistant message is still being streamed. */
  streaming?: boolean;
  /** Populated on the assistant message once the turn finishes. */
  meta?: {
    tokensIn?: number | null;
    tokensOut?: number | null;
    costUsd?: number | null;
  };
}

interface DoneFrame {
  type: "done";
  claude_session_id: string | null;
  tokens: {
    input: number | null;
    output: number | null;
    cache_creation: number | null;
    cache_read: number | null;
  };
  cost_usd: number | null;
  return_code: number;
  is_error: boolean;
  error_message: string | null;
}

interface ChunkFrame {
  type: "chunk";
  kind: string;
  text: string | null;
  session_id: string | null;
}

interface ErrorFrame {
  type: "error";
  message: string;
}

interface ReadyFrame {
  type: "ready";
}

type ServerFrame = ReadyFrame | ChunkFrame | DoneFrame | ErrorFrame;

export type ConnectionStatus = "connecting" | "ready" | "closed" | "error";

interface UseChatOptions {
  backendUrl: string;
  consultantSlug: string | null;
  userName: string;
  initialClaudeSessionId: string | null;
  /** Fired when a turn completes so callers can persist the session id. */
  onSessionIdChange?: (id: string | null) => void;
}

interface SendArgs {
  content: string;
}

interface UseChatResult {
  messages: ChatMessage[];
  status: ConnectionStatus;
  isStreaming: boolean;
  send: (args: SendArgs) => void;
  reset: () => void;
}

function makeId(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function toWsUrl(httpUrl: string): string {
  const u = new URL(httpUrl);
  u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
  u.pathname = "/ws/chat";
  return u.toString();
}

export function useChat(opts: UseChatOptions): UseChatResult {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [isStreaming, setIsStreaming] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const claudeSessionIdRef = useRef<string | null>(opts.initialClaudeSessionId);

  // Track the live assistant message ID so chunk events know what to append to.
  const liveAssistantIdRef = useRef<string | null>(null);

  // Open / close the socket. Re-opens when the backend URL changes.
  useEffect(() => {
    let cancelled = false;
    setStatus("connecting");
    const ws = new WebSocket(toWsUrl(opts.backendUrl));
    wsRef.current = ws;

    ws.addEventListener("message", (event) => {
      if (cancelled) return;
      let frame: ServerFrame;
      try {
        frame = JSON.parse(event.data) as ServerFrame;
      } catch {
        return;
      }
      handleFrame(frame);
    });

    ws.addEventListener("open", () => {
      if (cancelled) return;
      // We treat the server's "ready" frame as the real ready signal; "open"
      // just means TCP is up.
    });

    ws.addEventListener("close", () => {
      if (cancelled) return;
      setStatus("closed");
      setIsStreaming(false);
    });

    ws.addEventListener("error", () => {
      if (cancelled) return;
      setStatus("error");
      setIsStreaming(false);
    });

    return () => {
      cancelled = true;
      ws.close();
      wsRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opts.backendUrl]);

  // Sync the ref when the initial session id changes (e.g. switching consultants).
  useEffect(() => {
    claudeSessionIdRef.current = opts.initialClaudeSessionId;
  }, [opts.initialClaudeSessionId]);

  function handleFrame(frame: ServerFrame) {
    if (frame.type === "ready") {
      setStatus("ready");
      return;
    }

    if (frame.type === "chunk") {
      // Only render assistant text events. Tool events / system events are
      // hidden from the user.
      if (frame.kind !== "text_delta" && frame.kind !== "text_full") return;
      if (!frame.text) return;

      setMessages((prev) => {
        const liveId = liveAssistantIdRef.current;
        if (!liveId) return prev;
        return prev.map((m) =>
          m.id === liveId ? { ...m, text: frame.text || "" } : m,
        );
      });
      return;
    }

    if (frame.type === "done") {
      const liveId = liveAssistantIdRef.current;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === liveId
            ? {
                ...m,
                streaming: false,
                meta: {
                  tokensIn: frame.tokens.input,
                  tokensOut: frame.tokens.output,
                  costUsd: frame.cost_usd,
                },
                // If the run errored, surface it inline.
                text:
                  frame.is_error && frame.error_message
                    ? `${m.text}\n\n_Error: ${frame.error_message}_`
                    : m.text,
              }
            : m,
        ),
      );
      liveAssistantIdRef.current = null;
      setIsStreaming(false);

      if (frame.claude_session_id) {
        claudeSessionIdRef.current = frame.claude_session_id;
        opts.onSessionIdChange?.(frame.claude_session_id);
      }
      return;
    }

    if (frame.type === "error") {
      // Surface a top-level error as a synthetic assistant message.
      const id = makeId();
      setMessages((prev) => [
        ...prev,
        {
          id,
          role: "assistant",
          text: `_Server error: ${frame.message}_`,
          streaming: false,
        },
      ]);
      liveAssistantIdRef.current = null;
      setIsStreaming(false);
      return;
    }
  }

  const send = useCallback(
    ({ content }: SendArgs) => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      if (!opts.consultantSlug) return;

      const userMsg: ChatMessage = {
        id: makeId(),
        role: "user",
        text: content,
      };
      const assistantId = makeId();
      const assistantPlaceholder: ChatMessage = {
        id: assistantId,
        role: "assistant",
        text: "",
        streaming: true,
      };
      liveAssistantIdRef.current = assistantId;
      setMessages((prev) => [...prev, userMsg, assistantPlaceholder]);
      setIsStreaming(true);

      ws.send(
        JSON.stringify({
          type: "user_message",
          consultant_slug: opts.consultantSlug,
          user_name: opts.userName,
          content,
          claude_session_id: claudeSessionIdRef.current,
        }),
      );
    },
    [opts.consultantSlug, opts.userName],
  );

  const reset = useCallback(() => {
    setMessages([]);
    liveAssistantIdRef.current = null;
    setIsStreaming(false);
  }, []);

  return { messages, status, isStreaming, send, reset };
}

/** Fetch the list of consultant slugs from the backend's /healthz endpoint. */
export async function fetchConsultants(backendUrl: string): Promise<string[]> {
  const res = await fetch(`${backendUrl.replace(/\/$/, "")}/healthz`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`healthz returned ${res.status}`);
  const json = (await res.json()) as { consultants?: string[] };
  return json.consultants ?? [];
}
