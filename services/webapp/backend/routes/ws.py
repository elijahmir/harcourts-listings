"""WebSocket chat endpoint.

Wire protocol (JSON each direction):

Client -> server:
  {"type": "user_message", "content": "..."}

Server -> client:
  {"type": "event", "kind": "init|text_delta|text_full|rate_limit|turn_summary|tool_use|result|error|raw", ...}
  {"type": "result", "summary": {...}}     final summary including tokens and cost
  {"type": "error",  "message": "..."}      fatal error, ws will close after

Auth is via ``?token=<jwt>`` query param — browsers cannot set custom headers
on a WebSocket handshake. The same supabase-validated JWT used for the REST
routes is required here; an invalid or missing token closes the socket with
1008 (policy violation).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from ..auth import _verify
from ..claude_runner import StreamEvent, StreamSummary, stream_message
from ..config import get_settings
from ..db import LISTING_GEN_SCHEMA, lg, service_client

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/sessions/{session_id}")
async def chat_ws(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(..., min_length=10),
):
    # Validate JWT BEFORE accept — invalid tokens get refused at handshake.
    try:
        user = _verify(token)
    except Exception as exc:  # noqa: BLE001
        log.warning("ws auth failed: %s", exc)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    settings = get_settings()
    client = service_client()

    sess_q = (
        lg(client)
        .from_("sessions")
        .select("*")
        .eq("id", session_id)
        .single()
        .execute()
    )
    if not sess_q.data:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="session not found")
        return
    session = sess_q.data
    consultant_slug = session["consultant_slug"]
    consultant_folder: Path = settings.consultants_dir / consultant_slug
    if not consultant_folder.is_dir():
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="consultant folder missing")
        return

    await websocket.accept()
    log.info(
        "ws open session=%s consultant=%s user=%s resume=%s",
        session_id, consultant_slug, user.email, session.get("claude_session_id"),
    )

    try:
        await websocket.send_json({"type": "ready", "session_id": session_id})

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "invalid JSON"})
                continue
            if msg.get("type") != "user_message":
                await websocket.send_json({"type": "error", "message": "expected type='user_message'"})
                continue
            text = (msg.get("content") or "").strip()
            if not text:
                await websocket.send_json({"type": "error", "message": "empty content"})
                continue

            # Persist user message immediately (so a disconnect doesn't lose it).
            lg(client).from_("messages").insert({
                "session_id": session_id,
                "role": "user",
                "content": text,
            }).execute()

            assistant_text_parts: list[str] = []
            resume_id = session.get("claude_session_id")

            async for ev in stream_message(
                user_message=text,
                consultant_folder=consultant_folder,
                resume_session_id=resume_id,
            ):
                if isinstance(ev, StreamSummary):
                    full_text = "".join(assistant_text_parts)
                    # Persist assistant message + token usage.
                    lg(client).from_("messages").insert({
                        "session_id": session_id,
                        "role": "assistant",
                        "content": full_text,
                        "input_tokens": ev.input_tokens or 0,
                        "output_tokens": ev.output_tokens or 0,
                    }).execute()

                    # Bump running totals on the session row, and capture
                    # claude_session_id on the first turn so the next turn
                    # can --resume into the warm cache.
                    update: dict = {
                        "total_input_tokens": (
                            (session.get("total_input_tokens") or 0)
                            + (ev.input_tokens or 0)
                        ),
                        "total_output_tokens": (
                            (session.get("total_output_tokens") or 0)
                            + (ev.output_tokens or 0)
                        ),
                    }
                    if not resume_id and ev.session_id:
                        update["claude_session_id"] = ev.session_id
                        session["claude_session_id"] = ev.session_id
                    session["total_input_tokens"] = update["total_input_tokens"]
                    session["total_output_tokens"] = update["total_output_tokens"]
                    lg(client).from_("sessions").update(update).eq("id", session_id).execute()

                    await websocket.send_json({
                        "type": "result",
                        "summary": {
                            "session_id": ev.session_id,
                            "input_tokens": ev.input_tokens,
                            "output_tokens": ev.output_tokens,
                            "cache_creation_tokens": ev.cache_creation_tokens,
                            "cache_read_tokens": ev.cache_read_tokens,
                            "total_cost_usd": ev.total_cost_usd,
                            "is_error": ev.is_error,
                            "error_message": ev.error_message,
                            "return_code": ev.return_code,
                        },
                    })
                    break

                assert isinstance(ev, StreamEvent)
                if ev.text and ev.kind in ("text_delta", "text_full"):
                    assistant_text_parts.append(ev.text)
                await websocket.send_json({
                    "type": "event",
                    "kind": ev.kind,
                    "text": ev.text,
                    "session_id": ev.session_id,
                })
    except WebSocketDisconnect:
        log.info("ws disconnect session=%s", session_id)
    except Exception as exc:  # noqa: BLE001 — keep the socket alive contract simple
        log.exception("ws error session=%s: %s", session_id, exc)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            pass


# Re-export to keep app.py's include list flat.
__all__ = ["router"]
