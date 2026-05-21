"""Message history endpoint — used by the chat UI to rehydrate a session
on reconnect or page reload."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..auth import CurrentUser
from ..db import lg, service_client

router = APIRouter(prefix="/api/sessions", tags=["messages"])

Role = Literal["user", "assistant", "system", "tool"]


class MessageOut(BaseModel):
    id: str
    session_id: str
    role: Role
    content: str | None
    input_tokens: int | None
    output_tokens: int | None
    created_at: datetime


@router.get("/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(session_id: str, user: CurrentUser, limit: int = 200):
    if limit < 1 or limit > 1000:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "limit out of range")
    client = service_client()
    # Verify the session exists (RLS does the rest)
    exists_q = lg(client).from_("sessions").select("id").eq("id", session_id).single().execute()
    if not exists_q.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    result = (
        lg(client)
        .from_("messages")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at")
        .limit(limit)
        .execute()
    )
    return [MessageOut(**row) for row in result.data]
