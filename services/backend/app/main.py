"""FastAPI entry point.

Endpoints:

* ``GET /healthz`` — liveness check, lists known consultants.
* ``WebSocket /ws/chat`` — streaming chat with per-session persistence.
* ``POST /api/learnings`` — save a voice rule to the consultant's markdown.
* ``GET /api/learnings/{consultant_slug}`` — audit list of saved rules.
* ``POST /api/sessions/{session_id}/upload`` — multipart photo upload.
* ``DELETE /api/sessions/{session_id}/uploads`` — wipe a session's photos.

There is intentionally no authentication here. The trust boundary is the
network — this service is meant to run on the office Mac behind Tailscale,
not on the public internet. See README.md.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware

import json as _json
from pathlib import Path as _Path

from .config import get_settings
from .db import get_db
from .learnings import router as learnings_router
from .runner import StreamEvent, StreamSummary, stream_message
from .uploads import router as uploads_router


def _recover_assistant_text_from_jsonl(claude_session_id: str) -> str:
    """Last-resort recovery: read Claude Code's own session jsonl and
    extract the most recent assistant message's text.

    Claude Code persists every turn at ~/.claude/projects/<encoded>/{id}.jsonl.
    Each line is a JSON event. The `--resume` flag points at this exact
    file. If our stream-event parser misses the text for any reason, this
    is the canonical source — guaranteed to match what Claude itself
    "remembers" as having said.
    """
    matches = list(
        (_Path.home() / ".claude" / "projects").glob(f"*/{claude_session_id}.jsonl")
    )
    if not matches:
        return ""
    # Walk lines bottom-up looking for the most recent assistant text.
    try:
        lines = matches[0].read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:  # noqa: BLE001
        return ""
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            obj = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        # Claude Code's jsonl wraps events under a "message" key with role.
        msg = obj.get("message") or obj
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            joined = "".join(text_parts).strip()
            if joined:
                return joined
    return ""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("harcourts.backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    # Touching the DB here forces the file + schema to exist before the
    # first request, so any permission / disk error fails at boot.
    get_db()
    log.info(
        "backend starting on %s:%s, project_root=%s, %d consultants",
        s.host, s.port, s.project_root, len(s.known_consultants()),
    )
    yield
    log.info("backend shutting down")


app = FastAPI(
    title="Harcourts Listing Backend",
    version="0.3.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

# CORS for the chat UI. We need to accept:
#   - localhost / 127.0.0.1 (Mac browsing on the host itself)
#   - RFC1918 private LAN IPs (phone/laptop on the same Wi-Fi)
#   - Tailscale CGNAT range 100.64.0.0/10 (teammates hitting the host's
#     tailnet IP directly, e.g. http://100.89.167.17:3010 from an
#     iPhone on cellular). The /10 means second octet is 64-127.
#   - Tailscale MagicDNS hostnames (*.tail*.ts.net)
# WebSocket handshakes aren't subject to CORS, but the /healthz fetch is.
# Symptom of missing an origin here: WS connects (green dot) but the
# consultant dropdown stays empty because fetchConsultants() is blocked.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"^https?://("
        r"localhost"
        r"|127\.0\.0\.1"
        r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3}"
        r"|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}"
        r"|[a-z0-9-]+\.tail[0-9a-f]+\.ts\.net"
        r")(:\d+)?$"
    ),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

app.include_router(learnings_router)
app.include_router(uploads_router)


@app.get("/healthz")
def healthz() -> dict:
    s = get_settings()
    return {
        "ok": True,
        "service": "harcourts-backend",
        "project_root": str(s.project_root),
        "consultants": s.known_consultants(),
    }


@app.get("/api/sessions")
def list_sessions(consultant_slug: str | None = None, limit: int = 50) -> list[dict]:
    """List recent sessions, optionally filtered by consultant. Used by the
    frontend's sidebar (when one ships)."""
    return get_db().list_sessions(consultant_slug=consultant_slug, limit=limit)


@app.get("/api/sessions/{session_id}/messages")
def list_session_messages(session_id: str) -> list[dict]:
    """Replay a session's message history. Used when a user reopens a session."""
    if not get_db().get_session(session_id):
        return []
    return get_db().list_messages(session_id=session_id)


@app.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket) -> None:
    """Streaming chat WebSocket.

    Client → Server::

        {
          "type": "user_message",
          "session_id": null,                # null on first turn, else our id
          "consultant_slug": "wendy-squibb",
          "user_name": "Sarah",              # display only, not auth
          "content": "Start a listing for 12 Smith St",
          "claude_session_id": null          # null on first, else claude's id
        }

    Server → Client::

        {"type": "ready"}                                            # once
        {"type": "chunk", "text": "...", "kind": "...", ...}         # streaming
        {"type": "done", "session_id": "<our id>",
         "claude_session_id": "...", "tokens": {...},
         "cost_usd": F, "return_code": N, ...}
        {"type": "error", "message": "..."}

    First turn creates the SQLite session row. ``session_id`` in the
    ``done`` event is what the client should send on subsequent turns.
    """
    settings = get_settings()
    db = get_db()
    await websocket.accept()
    await websocket.send_json({"type": "ready"})

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "invalid JSON"})
                continue

            if msg.get("type") != "user_message":
                await websocket.send_json(
                    {"type": "error", "message": "expected type='user_message'"}
                )
                continue

            slug = (msg.get("consultant_slug") or "").strip()
            content = (msg.get("content") or "").strip()
            user_name = (msg.get("user_name") or "anonymous").strip() or "anonymous"
            resume_id = msg.get("claude_session_id") or None
            session_id = msg.get("session_id") or None

            if not slug:
                await websocket.send_json(
                    {"type": "error", "message": "missing consultant_slug"}
                )
                continue
            if not content:
                await websocket.send_json(
                    {"type": "error", "message": "empty content"}
                )
                continue

            try:
                folder = settings.consultant_folder(slug)
            except (FileNotFoundError, ValueError) as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                continue

            # First turn: create the session row. Subsequent turns: verify the
            # row exists. If the client sends a stale session_id we drop and
            # create a fresh session rather than erroring — easier UX.
            session = db.get_session(session_id) if session_id else None
            if not session:
                session = db.create_session(
                    consultant_slug=slug, user_name=user_name
                )
                session_id = session["id"]
                # Cutting a new session ALSO means we can't honor a stale
                # claude_session_id from the client. If we did, claude
                # would --resume a jsonl on disk whose history doesn't
                # match our DB ("Hi again!" effect). Force a fresh
                # Claude CLI session too.
                resume_id = None

            log.info(
                "turn: session=%s consultant=%s user=%s len=%d resume=%s",
                session_id, slug, user_name, len(content), resume_id,
            )

            db.insert_message(
                session_id=session_id, role="user", content=content
            )

            assistant_text = ""

            # The claude subprocess can take 15–30s for image-heavy turns.
            # If the WebSocket drops mid-stream (mobile Safari backgrounding,
            # cellular handoff, screen sleep), we must still consume the
            # full stream and persist the assistant message — otherwise the
            # work is lost and the user has no way to see Wendy's reply
            # when they come back. Strategy: ALWAYS iterate the stream to
            # completion; WS sends become best-effort, gated by a flag we
            # flip the first time a send raises.
            ws_alive = True

            async def _safe_send(payload: dict) -> None:
                nonlocal ws_alive
                if not ws_alive:
                    return
                try:
                    await websocket.send_json(payload)
                except Exception:  # noqa: BLE001 — WS closed mid-turn
                    ws_alive = False
                    log.info(
                        "ws dropped mid-turn (session=%s); continuing to consume "
                        "claude stream so the assistant message is persisted.",
                        session_id,
                    )

            try:
                async for ev in stream_message(
                    user_message=content,
                    consultant_folder=folder,
                    resume_session_id=resume_id,
                    claude_bin=settings.claude_bin,
                ):
                    if isinstance(ev, StreamSummary):
                        # Safety net: if no text-bearing event populated
                        # assistant_text (e.g. an unusual stream-json shape
                        # for image-heavy turns), fall back to reading
                        # Claude Code's own session jsonl. That file is
                        # what `--resume` reads next turn, so it's the
                        # canonical source of truth.
                        if not assistant_text.strip() and ev.session_id:
                            assistant_text = (
                                _recover_assistant_text_from_jsonl(ev.session_id)
                                or assistant_text
                            )
                            if assistant_text.strip():
                                log.info(
                                    "recovered assistant text from claude jsonl "
                                    "(%d chars) for session=%s",
                                    len(assistant_text), session_id,
                                )
                            else:
                                log.warning(
                                    "assistant_text empty after stream + jsonl "
                                    "fallback for session=%s claude=%s",
                                    session_id, ev.session_id,
                                )

                        # Persist the assistant turn + bump session totals
                        # UNCONDITIONALLY — WS state is irrelevant.
                        db.insert_message(
                            session_id=session_id,
                            role="assistant",
                            content=assistant_text,
                            input_tokens=ev.input_tokens,
                            output_tokens=ev.output_tokens,
                            cost_usd=ev.total_cost_usd,
                        )
                        db.update_session_after_turn(
                            session_id=session_id,
                            claude_session_id=ev.session_id,
                            input_tokens=ev.input_tokens or 0,
                            output_tokens=ev.output_tokens or 0,
                            cost_usd=ev.total_cost_usd or 0.0,
                        )
                        await _safe_send(
                            {
                                "type": "done",
                                "session_id": session_id,
                                "claude_session_id": ev.session_id,
                                "tokens": {
                                    "input": ev.input_tokens,
                                    "output": ev.output_tokens,
                                    "cache_creation": ev.cache_creation_tokens,
                                    "cache_read": ev.cache_read_tokens,
                                },
                                "cost_usd": ev.total_cost_usd,
                                "return_code": ev.return_code,
                                "is_error": ev.is_error,
                                "error_message": ev.error_message,
                            }
                        )
                        break

                    assert isinstance(ev, StreamEvent)
                    # Latest text-bearing event wins. Claude Code's
                    # stream-json emits cumulative text on each assistant
                    # delta, with stop_reason flipping from None to a value
                    # on the final event. The old logic ("first text_delta
                    # only, then text_full overwrites") missed cases where
                    # the final assistant event was a tool_result or had no
                    # text block — leaving assistant_text empty even though
                    # claude generated a full reply. SQLite then persisted
                    # 0 chars and the UI showed a forever-stuck placeholder.
                    if ev.text and ev.kind in ("text_delta", "text_full"):
                        assistant_text = ev.text

                    await _safe_send(
                        {
                            "type": "chunk",
                            "kind": ev.kind,
                            "text": ev.text,
                            "session_id": ev.session_id,
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                log.exception("turn failed: %s", exc)
                await _safe_send({"type": "error", "message": str(exc)})

    except WebSocketDisconnect:
        log.info("ws client disconnected")
    except Exception as exc:  # noqa: BLE001 — keep socket-lifecycle simple
        log.exception("ws error: %s", exc)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            pass


def main() -> None:
    """Entry point for ``python -m app.main`` style invocation."""
    import uvicorn

    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, log_level="info")


if __name__ == "__main__":
    main()
