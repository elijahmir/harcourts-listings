"""FastAPI entry point.

Two endpoints:

* ``GET /healthz`` — liveness check, lists known consultants.
* ``WebSocket /ws/chat`` — one user-turn per ``user_message`` frame; the
  server spawns ``claude`` as a subprocess and streams partial assistant
  text back to the client.

There is intentionally no authentication here. The trust boundary is the
network — this service is meant to run on the office Mac behind Tailscale,
not on the public internet. See README.md.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status

from .config import get_settings
from .runner import StreamEvent, StreamSummary, stream_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("harcourts.backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    log.info(
        "backend starting on %s:%s, project_root=%s, %d consultants",
        s.host, s.port, s.project_root, len(s.known_consultants()),
    )
    yield
    log.info("backend shutting down")


app = FastAPI(
    title="Harcourts Listing Backend",
    version="0.2.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)


@app.get("/healthz")
def healthz() -> dict:
    s = get_settings()
    return {
        "ok": True,
        "service": "harcourts-backend",
        "project_root": str(s.project_root),
        "consultants": s.known_consultants(),
    }


@app.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket) -> None:
    """Stateless chat WebSocket.

    Client → Server::

        {
          "type": "user_message",
          "consultant_slug": "wendy-squibb",
          "user_name": "Sarah",                  # display only, not auth
          "content": "Start a new listing for 12 Smith St",
          "claude_session_id": null               # set on subsequent turns
        }

    Server → Client::

        {"type": "ready"}                                 # once after accept
        {"type": "chunk", "text": "...", "kind": "..."}   # streaming events
        {"type": "done", "claude_session_id": "...",
         "tokens": {"input": N, "output": N,
                    "cache_creation": N, "cache_read": N},
         "cost_usd": F, "return_code": N}
        {"type": "error", "message": "..."}
    """
    settings = get_settings()
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

            log.info(
                "turn: consultant=%s user=%s len=%d resume=%s",
                slug, user_name, len(content), resume_id,
            )

            try:
                async for ev in stream_message(
                    user_message=content,
                    consultant_folder=folder,
                    resume_session_id=resume_id,
                    claude_bin=settings.claude_bin,
                ):
                    if isinstance(ev, StreamSummary):
                        await websocket.send_json(
                            {
                                "type": "done",
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
                    await websocket.send_json(
                        {
                            "type": "chunk",
                            "kind": ev.kind,
                            "text": ev.text,
                            "session_id": ev.session_id,
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                log.exception("turn failed: %s", exc)
                await websocket.send_json({"type": "error", "message": str(exc)})

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
