/** WebSocket client + React hook for streaming chat with the backend.
 *
 * Protocol mirrors services/backend/app/main.py:
 *
 *   Client → Server:
 *     {type: "user_message", session_id, consultant_slug,
 *      user_name, content, claude_session_id}
 *
 *   Server → Client:
 *     {type: "ready"}
 *     {type: "chunk", kind, text, session_id}
 *     {type: "done",  session_id, claude_session_id, tokens, cost_usd, ...}
 *     {type: "error", message}
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Auth plumbing — set once by the page that hosts this chat. Every REST
// helper and the WS hook read this lazily so token rotation works (Supabase
// access tokens expire ~1h; supabase-js refreshes them on demand).
//
// In the standalone harcourts-listings app this stays null and the backend
// runs in dev mode. In HUP-Sales-App, components/harcourts-chat/index.tsx
// calls configureAuth() once with a supabase.auth.getSession() wrapper.
// ---------------------------------------------------------------------------

let _getAccessToken: (() => Promise<string | null>) | null = null;

export function configureAuth(
  getAccessToken: () => Promise<string | null>,
): void {
  _getAccessToken = getAccessToken;
}

// ngrok free-tier serves an HTML interstitial ("ERR_NGROK_6024") whenever a
// browser hits the tunnel without this header. Without it, the JSON fetch
// returns HTML, json.consultants is undefined → "No consultants" in the UI.
// Safe to send unconditionally — non-ngrok hosts ignore it.
const NGROK_HEADER = { "ngrok-skip-browser-warning": "true" } as const;

async function authHeaders(): Promise<HeadersInit> {
  if (!_getAccessToken) return { ...NGROK_HEADER };
  const token = await _getAccessToken();
  return token
    ? { Authorization: `Bearer ${token}`, ...NGROK_HEADER }
    : { ...NGROK_HEADER };
}

async function bearerSubprotocol(): Promise<string | null> {
  if (!_getAccessToken) return null;
  const token = await _getAccessToken();
  return token ? `bearer.${token}` : null;
}

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  /** Epoch ms. Set when the message is created (user send / assistant
   * placeholder) OR pulled from the DB's `created_at`. Drives the small
   * timestamp under each bubble. */
  createdAt: number;
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
  session_id: string;
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

interface ActivityFrame {
  // Transient hint of what Claude is doing right now ("Reading IMG_4001.jpeg",
  // "VaultRE: 158 Preservation", "Writing brochure-text.docx"). Not persisted.
  type: "activity";
  summary: string;
  tool: string | null;
}

interface ErrorFrame {
  type: "error";
  message: string;
}

interface ReadyFrame {
  type: "ready";
}

/** Bubble boundary mid-turn. Fired by the backend when Claude paused
 *  one text block (committed as a DB row) and is about to start a new
 *  one — typically because a tool call ran in between. The frontend
 *  uses this to finalise the current live bubble and spawn a fresh
 *  placeholder so the next text streams into a new bubble, matching
 *  how a real consultant would say "let me check… ok, here's what I
 *  found". Without this, all text from the turn lands in one bubble. */
interface BubbleBreakFrame {
  type: "bubble_break";
  message_id: string;
  session_id: string;
}

type ServerFrame =
  | ReadyFrame
  | ChunkFrame
  | ActivityFrame
  | BubbleBreakFrame
  | DoneFrame
  | ErrorFrame;

export type ConnectionStatus = "connecting" | "ready" | "closed" | "error";

interface UseChatOptions {
  backendUrl: string;
  consultantSlug: string | null;
  userName: string;
  initialSessionId: string | null;
  initialClaudeSessionId: string | null;
  /** Fired when the backend confirms a session id (creates or echoes). */
  onSessionIdChange?: (id: string) => void;
  onClaudeSessionIdChange?: (id: string | null) => void;
}

interface SendArgs {
  content: string;
}

interface UseChatResult {
  messages: ChatMessage[];
  status: ConnectionStatus;
  isStreaming: boolean;
  /** Latest tool-activity summary from the backend, or null if Claude is
   * thinking but not actively in a tool call. Cleared on 'done'. */
  activity: string | null;
  send: (args: SendArgs) => void;
  reset: () => void;
  /** Force a fresh reconnect after a give-up. */
  reconnect: () => void;
  /** Replace the message list — used to seed history on page load. */
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
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
  // Latest tool-call summary from the backend, e.g. "Reading IMG_4001.jpeg".
  // Cleared on 'done' or 'error'. Drives the StillWorkingBadge UI.
  const [activity, setActivity] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const sessionIdRef = useRef<string | null>(opts.initialSessionId);
  const claudeSessionIdRef = useRef<string | null>(opts.initialClaudeSessionId);

  // Track the live assistant message ID so chunk events know what to append to.
  const liveAssistantIdRef = useRef<string | null>(null);

  // The WS "message" listener is bound once when the socket opens, so its
  // closure captures whatever `opts` looked like at that moment. The parent
  // component's callbacks reference state that changes later (e.g. `slug`),
  // so we keep them in a ref that we refresh on every render — the listener
  // always calls the latest version. Without this, the first turn's `done`
  // event invokes a stale callback whose `slug` is still null, and the
  // session id never makes it back to the UI.
  const optsRef = useRef(opts);
  useEffect(() => {
    optsRef.current = opts;
  });

  // Bumps every time someone calls reconnect() — triggers the effect below.
  const [reconnectNonce, setReconnectNonce] = useState(0);
  const reconnect = useCallback(() => setReconnectNonce((n) => n + 1), []);

  // Open the socket, with auto-reconnect on unexpected close. Reconnects
  // are essential because:
  //   - React StrictMode in dev mounts → unmounts → re-mounts, which closes
  //     the first WS before the handshake completes.
  //   - Dev-server hot reload, sleeping macs, transient network drops.
  //
  // Backoff: 0, 500, 1000, 2000, 4000, 5000 ms. Resets on a successful
  // "ready" frame. After MAX_ATTEMPTS straight failures we stop and surface
  // the "closed" status so the UI can offer a manual Reconnect button —
  // avoids spamming the console forever when something is hard-blocking
  // the connection (e.g. a browser extension).
  useEffect(() => {
    if (!opts.backendUrl) return;

    let cancelled = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    const RETRY_DELAYS_MS = [0, 500, 1000, 2000, 4000, 5000];
    const MAX_ATTEMPTS = 8;

    const connect = async () => {
      if (cancelled) return;
      setStatus("connecting");
      // Pass any configured bearer token via Sec-WebSocket-Protocol —
      // browsers don't allow custom WS handshake headers, but the
      // protocol list is settable from the WebSocket constructor.
      const bearer = await bearerSubprotocol();
      const protocols = bearer
        ? ["harcourts.v1", bearer]
        : ["harcourts.v1"];
      try {
        ws = new WebSocket(toWsUrl(opts.backendUrl), protocols);
      } catch (err) {
        console.error("invalid backend URL", opts.backendUrl, err);
        setStatus("error");
        return;
      }
      wsRef.current = ws;

      ws.addEventListener("message", (event) => {
        if (cancelled) return;
        let frame: ServerFrame;
        try {
          frame = JSON.parse(event.data) as ServerFrame;
        } catch {
          return;
        }
        if (frame.type === "ready") {
          attempt = 0; // healthy handshake → reset backoff
        }
        handleFrame(frame);
      });

      ws.addEventListener("close", () => {
        if (cancelled) return;
        setStatus("closed");
        setIsStreaming(false);
        attempt += 1;
        if (attempt >= MAX_ATTEMPTS) {
          // Give up — user must click Reconnect.
          return;
        }
        const delay =
          RETRY_DELAYS_MS[Math.min(attempt, RETRY_DELAYS_MS.length - 1)];
        reconnectTimer = setTimeout(connect, delay);
      });

      ws.addEventListener("error", () => {
        if (cancelled) return;
        setStatus("error");
        setIsStreaming(false);
        // 'error' fires immediately before 'close'; let 'close' schedule
        // the retry to avoid double-booking.
      });
    };

    connect();

    // iOS Safari aggressively suspends the JS runtime when a tab is
    // backgrounded — even briefly (screen dim, app switcher, lock).
    // The WebSocket's `close` event may not fire until resume, and by
    // then the auto-reconnect-on-close path is racing the user's first
    // interaction. Pattern: when the tab becomes visible again, check
    // the socket's readyState and force a reconnect if it isn't OPEN.
    // This is the canonical fix for "WS works on desktop, dies on
    // iPhone after a few seconds of inactivity."
    const onVisible = () => {
      if (cancelled) return;
      if (document.visibilityState !== "visible") return;
      const sock = wsRef.current;
      if (!sock || sock.readyState === WebSocket.CLOSED ||
          sock.readyState === WebSocket.CLOSING) {
        attempt = 0; // user-initiated, give it a fresh budget
        if (reconnectTimer) clearTimeout(reconnectTimer);
        connect();
      }
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisible);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) ws.close();
      wsRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opts.backendUrl, reconnectNonce]);

  // Sync refs when the consultant changes.
  useEffect(() => {
    sessionIdRef.current = opts.initialSessionId;
  }, [opts.initialSessionId]);
  useEffect(() => {
    claudeSessionIdRef.current = opts.initialClaudeSessionId;
  }, [opts.initialClaudeSessionId]);

  function handleFrame(frame: ServerFrame) {
    if (frame.type === "ready") {
      setStatus("ready");
      return;
    }

    if (frame.type === "chunk") {
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

    if (frame.type === "activity") {
      // Update the live ticker. Persists until the next activity arrives
      // or the turn ends ('done' / 'error') — so a brief tool call still
      // shows long enough for the user to notice.
      setActivity(frame.summary);
      return;
    }

    if (frame.type === "bubble_break") {
      // Mid-turn bubble boundary: the backend just committed the
      // current live bubble as its own DB row. Seal it (no longer
      // streaming), stamp it with the persisted DB id so per-message
      // controls (Save as listing, Save as voice rule, Copy) reference
      // a real row, then push a fresh empty placeholder for the next
      // text block to stream into.
      const liveId = liveAssistantIdRef.current;
      const newId = makeId();
      setMessages((prev) => {
        const sealed = prev.map((m) =>
          m.id === liveId
            ? { ...m, id: frame.message_id, streaming: false, createdAt: Date.now() }
            : m,
        );
        return [
          ...sealed,
          {
            id: newId,
            role: "assistant" as ChatRole,
            text: "",
            createdAt: Date.now(),
            streaming: true,
          },
        ];
      });
      liveAssistantIdRef.current = newId;
      // Activity ticker stays on; the next text_delta will overwrite
      // the empty placeholder once Wendy starts typing the next bubble.
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
                // Refresh the timestamp to the moment the assistant
                // actually finished. The placeholder was created when
                // the user sent the message, which can be 5-60s ago
                // for tool-heavy turns. Shown time should reflect the
                // reply, not the prompt.
                createdAt: Date.now(),
                meta: {
                  tokensIn: frame.tokens.input,
                  tokensOut: frame.tokens.output,
                  costUsd: frame.cost_usd,
                },
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
      setActivity(null);

      if (frame.session_id && frame.session_id !== sessionIdRef.current) {
        sessionIdRef.current = frame.session_id;
        optsRef.current.onSessionIdChange?.(frame.session_id);
      }
      if (frame.claude_session_id) {
        claudeSessionIdRef.current = frame.claude_session_id;
        optsRef.current.onClaudeSessionIdChange?.(frame.claude_session_id);
      }
      return;
    }

    if (frame.type === "error") {
      const id = makeId();
      setMessages((prev) => [
        ...prev,
        {
          id,
          role: "assistant",
          text: `_Server error: ${frame.message}_`,
          streaming: false,
          createdAt: Date.now(),
        },
      ]);
      liveAssistantIdRef.current = null;
      setIsStreaming(false);
      setActivity(null);
      return;
    }
  }

  const send = useCallback(
    ({ content }: SendArgs) => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      if (!opts.consultantSlug) return;

      const now = Date.now();
      const userMsg: ChatMessage = {
        id: makeId(),
        role: "user",
        text: content,
        createdAt: now,
      };
      const assistantId = makeId();
      const assistantPlaceholder: ChatMessage = {
        id: assistantId,
        role: "assistant",
        text: "",
        streaming: true,
        // Placeholder timestamp; gets refreshed when the assistant
        // turn finishes via the `done` frame so the visible time
        // matches when Claude actually answered.
        createdAt: now,
      };
      liveAssistantIdRef.current = assistantId;
      setMessages((prev) => [...prev, userMsg, assistantPlaceholder]);
      setIsStreaming(true);
      setActivity(null);

      ws.send(
        JSON.stringify({
          type: "user_message",
          session_id: sessionIdRef.current,
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
    // Clear the WS session refs too. They get set directly by the `done`
    // handler when a turn finishes, which means they live OUTSIDE the
    // initialSessionId/initialClaudeSessionId state in the parent. If we
    // only cleared `messages` here, the next send would carry the stale
    // ids and the backend would re-attach to the previous session instead
    // of creating a fresh one (this is exactly what the session-picker
    // smoke test caught).
    sessionIdRef.current = null;
    claudeSessionIdRef.current = null;
    setIsStreaming(false);
    setActivity(null);
  }, []);

  return {
    messages,
    status,
    isStreaming,
    activity,
    send,
    reset,
    reconnect,
    setMessages,
  };
}

// --- Session list -----------------------------------------------------------

export interface SessionRow {
  id: string;
  claude_session_id: string | null;
  consultant_slug: string;
  user_name: string;
  started_at: string;
  last_active_at: string;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
}

/** Minimal session metadata. Returned by GET /api/sessions/{id}. Used
 *  to learn the session owner so the chat can render a banner when an
 *  admin opens someone else's session. */
export interface SessionInfo {
  id: string;
  consultant_slug: string;
  user_name: string;
  started_at: string;
  last_active_at: string;
}

export async function fetchSessionInfo(
  backendUrl: string,
  sessionId: string,
): Promise<SessionInfo | null> {
  const res = await fetch(
    `${backendUrl.replace(/\/$/, "")}/api/sessions/${encodeURIComponent(sessionId)}`,
    { cache: "no-store", headers: await authHeaders() },
  );
  if (res.status === 404) return null; // not yours and not admin → don't show banner
  if (!res.ok) throw new Error(`fetchSessionInfo ${res.status}: ${res.statusText}`);
  return (await res.json()) as SessionInfo;
}

/** Fetch recent sessions, optionally filtered to a single consultant. */
export async function fetchSessions(
  backendUrl: string,
  consultantSlug?: string,
  limit = 50,
): Promise<SessionRow[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (consultantSlug) params.set("consultant_slug", consultantSlug);
  const res = await fetch(
    `${backendUrl.replace(/\/$/, "")}/api/sessions?${params.toString()}`,
    { cache: "no-store", headers: await authHeaders() },
  );
  if (!res.ok) {
    throw new Error(`fetchSessions ${res.status}: ${res.statusText}`);
  }
  return (await res.json()) as SessionRow[];
}

/**
 * Preview of what `deleteSession()` would remove. Returned by
 * `GET /api/sessions/{id}/cleanup-preview` — used by the confirm modal
 * so the user sees actual file counts before clicking "Delete
 * permanently".
 */
export interface DeletePreview {
  session_id: string;
  uploads: number;
  deliverables: number;
  deliverable_names: string[];
}

/** Non-destructive count of what a session DELETE will wipe. Returns
 *  the structured preview, or throws with the server detail on
 *  failure. The session-picker treats a thrown preview as "soft fail" —
 *  the confirm modal still opens, just without the file counts. */
export async function fetchDeletePreview(
  backendUrl: string,
  sessionId: string,
): Promise<DeletePreview> {
  const res = await fetch(
    `${backendUrl.replace(/\/$/, "")}/api/sessions/${encodeURIComponent(sessionId)}/cleanup-preview`,
    { cache: "no-store", headers: await authHeaders() },
  );
  if (!res.ok) {
    let detail = "";
    try {
      detail = ((await res.json()) as { detail?: string }).detail || "";
    } catch {
      detail = res.statusText;
    }
    throw new Error(`fetchDeletePreview ${res.status}: ${detail}`);
  }
  return (await res.json()) as DeletePreview;
}

/**
 * Hard-delete a session — DB rows + the on-disk session folder + any
 * `outputs/` deliverables the session generated. Auth required (the
 * backend rejects with 403 if you don't own the session in production
 * mode). Throws with the server's detail message on failure so the
 * caller can surface it.
 */
export async function deleteSession(
  backendUrl: string,
  sessionId: string,
): Promise<void> {
  const res = await fetch(
    `${backendUrl.replace(/\/$/, "")}/api/sessions/${encodeURIComponent(sessionId)}`,
    {
      method: "DELETE",
      headers: await authHeaders(),
    },
  );
  if (!res.ok) {
    let detail = "";
    try {
      detail = ((await res.json()) as { detail?: string }).detail || "";
    } catch {
      detail = res.statusText;
    }
    throw new Error(`deleteSession ${res.status}: ${detail}`);
  }
}

// --- History replay ---------------------------------------------------------

/** Row shape returned by GET /api/sessions/{id}/messages. */
export interface SessionMessageRow {
  id: number;
  session_id: string;
  role: ChatRole;
  content: string;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  created_at: string;
}

export async function fetchSessionMessages(
  backendUrl: string,
  sessionId: string,
): Promise<SessionMessageRow[]> {
  const res = await fetch(
    `${backendUrl.replace(/\/$/, "")}/api/sessions/${encodeURIComponent(sessionId)}/messages`,
    { cache: "no-store", headers: await authHeaders() },
  );
  if (!res.ok) {
    throw new Error(`fetchSessionMessages ${res.status}: ${res.statusText}`);
  }
  return (await res.json()) as SessionMessageRow[];
}

// --- REST helpers ----------------------------------------------------------

export async function fetchConsultants(backendUrl: string): Promise<string[]> {
  // /healthz is public so we don't need authHeaders(), but we still need the
  // ngrok-skip-browser-warning header (see authHeaders comment) otherwise the
  // browser request gets ngrok's HTML interstitial and JSON.parse fails.
  const res = await fetch(`${backendUrl.replace(/\/$/, "")}/healthz`, {
    cache: "no-store",
    headers: NGROK_HEADER,
  });
  if (!res.ok) throw new Error(`healthz returned ${res.status}`);
  const json = (await res.json()) as { consultants?: string[] };
  return json.consultants ?? [];
}

export interface SaveLearningArgs {
  backendUrl: string;
  consultantSlug: string;
  title: string;
  trigger: string;
  rule: string;
  savedBy: string;
  sessionId: string | null;
}

export async function saveLearning(args: SaveLearningArgs): Promise<void> {
  const res = await fetch(`${args.backendUrl.replace(/\/$/, "")}/api/learnings`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(await authHeaders()),
    },
    body: JSON.stringify({
      consultant_slug: args.consultantSlug,
      title: args.title,
      trigger: args.trigger,
      rule: args.rule,
      saved_by: args.savedBy,
      session_id: args.sessionId,
    }),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`saveLearning ${res.status}: ${body || res.statusText}`);
  }
}

export interface UploadedFile {
  session_id: string;
  original_filename: string;
  stored_filename: string;
  relative_path: string;
  kind: "photo" | "floorplan" | "pdf" | "other";
  bytes: number;
  converted_from_heic: boolean;
}

// ---------------------------------------------------------------------------
// Listings repo — CopyPro's persisted listings on Supabase.
//
// Owner-scoped reads + writes (admins see all). The backend handles RLS;
// these helpers just shape the requests + thread the existing auth +
// ngrok-skip headers through authHeaders().
// ---------------------------------------------------------------------------

export type Grade = "up" | "down";

/** Thumbs up/down rollup for a listing. Returned by GET /api/listings/{id}
 *  (as `grade_summary`) and by the PUT/DELETE grade endpoints. `my_grade`
 *  is the current user's vote (null if they haven't graded). */
export interface GradeSummary {
  up: number;
  down: number;
  my_grade: Grade | null;
}

export interface ListingRow {
  id: string;
  user_email: string;
  consultant_slug: string;
  chat_session_id: string;
  address: string;
  address_slug: string;
  headline: string | null;
  body_md?: string;                    // only present on GET /api/listings/{id}
  social_caption?: string | null;
  signboard_blurb?: string | null;
  status: "final" | "archived";
  docx_filename: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  revisions?: ListingRevisionRow[];   // populated when include_revisions=true
  grade_summary?: GradeSummary;        // present on GET /api/listings/{id}
}

export interface ListingRevisionRow {
  id: string;
  listing_id: string;
  body_md: string;
  headline: string | null;
  social_caption: string | null;
  signboard_blurb: string | null;
  metadata: Record<string, unknown>;
  edited_by: string;
  edit_summary: string | null;
  created_at: string;
}

export interface CreateListingArgs {
  backendUrl: string;
  chatSessionId: string;
  consultantSlug: string;
  address: string;
  addressSlug: string;
  headline?: string | null;
  bodyMd: string;
  socialCaption?: string | null;
  signboardBlurb?: string | null;
  docxFilename?: string | null;
  metadata?: Record<string, unknown>;
}

/** Save a completed CopyPro listing to the Supabase repo. */
export async function saveListing(args: CreateListingArgs): Promise<ListingRow> {
  const body = {
    chat_session_id: args.chatSessionId,
    consultant_slug: args.consultantSlug,
    address: args.address,
    address_slug: args.addressSlug,
    headline: args.headline ?? null,
    body_md: args.bodyMd,
    social_caption: args.socialCaption ?? null,
    signboard_blurb: args.signboardBlurb ?? null,
    docx_filename: args.docxFilename ?? null,
    metadata: args.metadata ?? {},
  };
  const res = await fetch(
    `${args.backendUrl.replace(/\/$/, "")}/api/listings`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await authHeaders()) },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) {
    let detail = "";
    try { detail = ((await res.json()) as { detail?: string }).detail || ""; }
    catch { detail = res.statusText; }
    throw new Error(`saveListing ${res.status}: ${detail || "failed"}`);
  }
  return (await res.json()) as ListingRow;
}

/** List listings visible to the caller (own + admin-all). */
export async function fetchListings(
  backendUrl: string,
  opts: { consultantSlug?: string; q?: string; limit?: number } = {},
): Promise<ListingRow[]> {
  const params = new URLSearchParams();
  if (opts.consultantSlug) params.set("consultant_slug", opts.consultantSlug);
  if (opts.q) params.set("q", opts.q);
  if (opts.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  const url = `${backendUrl.replace(/\/$/, "")}/api/listings${qs ? `?${qs}` : ""}`;
  const res = await fetch(url, {
    cache: "no-store",
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error(`fetchListings ${res.status}: ${res.statusText}`);
  return (await res.json()) as ListingRow[];
}

/** Fetch one listing in full (body + optional revision history). */
export async function fetchListing(
  backendUrl: string,
  listingId: string,
  opts: { includeRevisions?: boolean } = {},
): Promise<ListingRow> {
  const params = new URLSearchParams();
  if (opts.includeRevisions) params.set("include_revisions", "true");
  const qs = params.toString();
  const url =
    `${backendUrl.replace(/\/$/, "")}/api/listings/${encodeURIComponent(listingId)}` +
    (qs ? `?${qs}` : "");
  const res = await fetch(url, {
    cache: "no-store",
    headers: await authHeaders(),
  });
  if (!res.ok) {
    let detail = "";
    try { detail = ((await res.json()) as { detail?: string }).detail || ""; }
    catch { detail = res.statusText; }
    throw new Error(`fetchListing ${res.status}: ${detail || "failed"}`);
  }
  return (await res.json()) as ListingRow;
}

/** Patch a listing. The backend trigger auto-snapshots prior state into
 *  copypro_listing_revisions when any text field changes. */
export async function updateListing(
  backendUrl: string,
  listingId: string,
  patch: Partial<{
    headline: string;
    body_md: string;
    social_caption: string;
    signboard_blurb: string;
    status: "final" | "archived";
    docx_filename: string;
    metadata: Record<string, unknown>;
    edit_summary: string;
  }>,
): Promise<ListingRow> {
  const res = await fetch(
    `${backendUrl.replace(/\/$/, "")}/api/listings/${encodeURIComponent(listingId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...(await authHeaders()) },
      body: JSON.stringify(patch),
    },
  );
  if (!res.ok) {
    let detail = "";
    try { detail = ((await res.json()) as { detail?: string }).detail || ""; }
    catch { detail = res.statusText; }
    throw new Error(`updateListing ${res.status}: ${detail || "failed"}`);
  }
  return (await res.json()) as ListingRow;
}

/** Set (or change) the current user's thumbs up/down on a listing.
 *  Returns the fresh grade summary so the caller can update in place. */
export async function gradeListing(
  backendUrl: string,
  listingId: string,
  grade: Grade,
  comment?: string | null,
): Promise<GradeSummary> {
  const res = await fetch(
    `${backendUrl.replace(/\/$/, "")}/api/listings/${encodeURIComponent(listingId)}/grade`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...(await authHeaders()) },
      body: JSON.stringify({ grade, comment: comment ?? null }),
    },
  );
  if (!res.ok) {
    let detail = "";
    try { detail = ((await res.json()) as { detail?: string }).detail || ""; }
    catch { detail = res.statusText; }
    throw new Error(`gradeListing ${res.status}: ${detail || "failed"}`);
  }
  return (await res.json()) as GradeSummary;
}

/** Clear the current user's grade on a listing (un-vote). Idempotent. */
export async function clearGrade(
  backendUrl: string,
  listingId: string,
): Promise<GradeSummary> {
  const res = await fetch(
    `${backendUrl.replace(/\/$/, "")}/api/listings/${encodeURIComponent(listingId)}/grade`,
    { method: "DELETE", headers: await authHeaders() },
  );
  if (!res.ok) {
    let detail = "";
    try { detail = ((await res.json()) as { detail?: string }).detail || ""; }
    catch { detail = res.statusText; }
    throw new Error(`clearGrade ${res.status}: ${detail || "failed"}`);
  }
  return (await res.json()) as GradeSummary;
}

export async function uploadFiles(
  backendUrl: string,
  sessionId: string,
  files: File[],
): Promise<UploadedFile[]> {
  const fd = new FormData();
  for (const f of files) fd.append("files", f, f.name);
  const res = await fetch(
    `${backendUrl.replace(/\/$/, "")}/api/sessions/${encodeURIComponent(sessionId)}/upload`,
    {
      method: "POST",
      body: fd,
      // FormData sets Content-Type with the multipart boundary itself,
      // so only Authorization is added here.
      headers: await authHeaders(),
    },
  );
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`upload ${res.status}: ${body || res.statusText}`);
  }
  return (await res.json()) as UploadedFile[];
}

/** Per-byte progress event surfaced to the caller during a batch upload. */
export interface UploadProgress {
  bytesLoaded: number;
  bytesTotal: number;
}

/**
 * Variant of uploadFiles that surfaces real upload-progress events to a
 * callback. Used by the chat UI so a teammate uploading a 50 MB phone
 * photo sees a progress bar fill instead of staring at a frozen
 * paperclip for 30 seconds.
 *
 * Implemented on XMLHttpRequest because the browser fetch() API still
 * does not expose request-body progress (only response progress).
 * Streams API write-side is shipping in some browsers but not all yet.
 * XHR is the boring, portable, ten-year-supported way to do this.
 *
 * onProgress is called many times during the upload (browser-controlled
 * cadence, typically every 50-100ms or every few hundred KB). Caller
 * should patch component state from inside it.
 */
export function uploadFilesWithProgress(
  backendUrl: string,
  sessionId: string,
  files: File[],
  onProgress: (p: UploadProgress) => void,
): Promise<UploadedFile[]> {
  return new Promise<UploadedFile[]>((resolve, reject) => {
    // Build the multipart body the same way fetch() would.
    const fd = new FormData();
    for (const f of files) fd.append("files", f, f.name);

    const xhr = new XMLHttpRequest();
    xhr.open(
      "POST",
      `${backendUrl.replace(/\/$/, "")}/api/sessions/${encodeURIComponent(sessionId)}/upload`,
    );

    // Resolve auth + ngrok headers BEFORE send (xhr.send is sync from
    // here on so we can't await mid-stream). We attach them to the
    // request via setRequestHeader once authHeaders() resolves.
    authHeaders()
      .then((hdrs) => {
        const entries =
          hdrs instanceof Headers
            ? Array.from(hdrs.entries())
            : Object.entries(hdrs as Record<string, string>);
        for (const [k, v] of entries) {
          if (v != null) xhr.setRequestHeader(k, v);
        }

        xhr.upload.onprogress = (ev) => {
          if (ev.lengthComputable) {
            onProgress({ bytesLoaded: ev.loaded, bytesTotal: ev.total });
          }
        };
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            try {
              resolve(JSON.parse(xhr.responseText) as UploadedFile[]);
            } catch (e) {
              reject(
                new Error(
                  `upload parse error: ${
                    e instanceof Error ? e.message : String(e)
                  }`,
                ),
              );
            }
            return;
          }
          // Try to surface the backend's detail message.
          let detail = "";
          try {
            const body = JSON.parse(xhr.responseText) as { detail?: string };
            detail = body.detail || "";
          } catch {
            detail = xhr.responseText.slice(0, 200);
          }
          reject(
            new Error(
              `upload ${xhr.status}: ${detail || xhr.statusText || "failed"}`,
            ),
          );
        };
        xhr.onerror = () =>
          reject(new Error("upload network error"));
        xhr.ontimeout = () => reject(new Error("upload timed out"));

        xhr.send(fd);
      })
      .catch(reject);
  });
}

/**
 * Download a generated deliverable (`outputs/<filename>`) and trigger a
 * native save dialog in the user's browser.
 *
 * Why this exists rather than a plain `<a href>`: the download endpoint
 * is JWT-gated. A direct browser navigation to the URL doesn't send the
 * Authorization header that lib/ws.ts attaches via `fetch()` — it just
 * goes to the URL and gets a 401 "missing token". We fetch the bytes
 * here (with the header), turn the response into a blob, and use a
 * temporary anchor + object URL to invoke the browser's save dialog.
 *
 * Caller usually catches errors and surfaces them in the chat UI.
 */
export async function downloadOutput(
  backendUrl: string,
  filename: string,
): Promise<void> {
  const res = await fetch(
    `${backendUrl.replace(/\/$/, "")}/api/outputs/${encodeURIComponent(filename)}`,
    { cache: "no-store", headers: await authHeaders() },
  );
  if (!res.ok) {
    let detail = "";
    try {
      detail = ((await res.json()) as { detail?: string }).detail || "";
    } catch {
      detail = res.statusText;
    }
    throw new Error(`download ${res.status}: ${detail || "failed"}`);
  }
  const blob = await res.blob();
  // Spin up a one-shot object URL + invisible anchor to invoke the
  // browser's save dialog. Cleaned up immediately so we don't leak
  // memory on a session with many downloads.
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = filename;
  // Some browsers require the anchor to be in the DOM before .click()
  // actually fires the save flow (Safari especially).
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Revoke after a short delay so Safari/Chrome have time to start the
  // download before the URL becomes invalid.
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
}
