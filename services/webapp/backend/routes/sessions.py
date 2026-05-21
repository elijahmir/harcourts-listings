"""Session CRUD endpoints.

A *session* in this context is a single listing chat — one consultant, one
property address, many messages. The session row holds the absolute file
path on the Mac where photos and the eventual Word document live, plus
running token totals so the UI can show how much of the Agent SDK credit
the office has burned.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..auth import CurrentUser
from ..config import get_settings
from ..db import lg, service_client

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sessions", tags=["sessions"])

SLUG_RE = re.compile(r"[^a-z0-9]+")
PhaseStatus = Literal[
    "phase_1", "phase_2", "phase_3", "phase_4", "phase_5",
    "completed", "abandoned",
]


def slugify(text: str, *, max_len: int = 64) -> str:
    cleaned = SLUG_RE.sub("-", text.lower()).strip("-")
    return cleaned[:max_len] or "untitled"


class SessionCreate(BaseModel):
    consultant_slug: str = Field(..., min_length=1, max_length=64)
    address: str | None = Field(None, max_length=300)


class SessionOut(BaseModel):
    id: str
    consultant_slug: str
    user_id: str
    user_email: str
    address: str | None
    address_slug: str | None
    session_folder: str | None
    status: PhaseStatus
    word_doc_path: str | None
    started_at: datetime
    completed_at: datetime | None
    total_input_tokens: int
    total_output_tokens: int


@router.get("", response_model=list[SessionOut])
async def list_sessions(user: CurrentUser, limit: int = 50):
    """All sessions visible to the user. RLS already allows office-wide
    reads, so this returns everyone's sessions for the audit view."""
    if limit < 1 or limit > 200:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "limit out of range")
    client = service_client()
    result = (
        lg(client)
        .from_("sessions")
        .select("*")
        .order("started_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [SessionOut(**row) for row in result.data]


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(payload: SessionCreate, user: CurrentUser):
    settings = get_settings()

    # Validate consultant exists and is active.
    client = service_client()
    consultant_q = (
        lg(client)
        .from_("consultants")
        .select("slug, active")
        .eq("slug", payload.consultant_slug)
        .single()
        .execute()
    )
    if not consultant_q.data or not consultant_q.data.get("active"):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"unknown or inactive consultant: {payload.consultant_slug}",
        )

    # Compute the on-disk session folder. The folder gets physically created
    # the first time the user actually uploads a file or sends a message —
    # we don't want empty directories piling up for abandoned sessions.
    now = datetime.now(timezone.utc)
    address_slug = slugify(payload.address) if payload.address else None
    folder_name = (
        f"{now.strftime('%Y-%m-%d')}_{address_slug}"
        if address_slug
        else f"{now.strftime('%Y-%m-%d_%H%M%S')}_pending-address"
    )
    folder_path = (
        settings.consultants_dir / payload.consultant_slug / "sessions" / folder_name
    )

    insert_q = (
        lg(client)
        .from_("sessions")
        .insert(
            {
                "consultant_slug": payload.consultant_slug,
                "user_id": user.id,
                "user_email": user.email or "",
                "address": payload.address,
                "address_slug": address_slug,
                "session_folder": str(folder_path.relative_to(settings.project_root)),
                "status": "phase_1",
            }
        )
        .execute()
    )
    if not insert_q.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "failed to insert session"
        )
    return SessionOut(**insert_q.data[0])


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: str, user: CurrentUser):
    client = service_client()
    result = (
        lg(client)
        .from_("sessions")
        .select("*")
        .eq("id", session_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return SessionOut(**result.data)
