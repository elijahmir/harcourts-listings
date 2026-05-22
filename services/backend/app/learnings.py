"""Persist a voice-rule learning for a consultant.

Two things happen on save:

1. The new rule is appended to
   ``consultants/{slug}/knowledge/learnings.md`` in the dated format the
   consultant's CLAUDE.md prompt expects to read at the start of every
   session. This is the file that actually changes the agent's behaviour.

2. A row is inserted into the SQLite ``learnings`` table for audit — who
   saved what, when, from which session.

The markdown file is the source of truth for the agent. The SQLite table
is the source of truth for the team's history.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from .config import get_settings
from .db import get_db

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/learnings", tags=["learnings"])


class LearningIn(BaseModel):
    consultant_slug: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=200)
    trigger: str = Field(..., min_length=1, max_length=2000)
    rule: str = Field(..., min_length=1, max_length=4000)
    saved_by: str = Field(..., min_length=1, max_length=120)
    session_id: str | None = Field(None, max_length=64)


class LearningOut(BaseModel):
    id: int
    consultant_slug: str
    title: str
    trigger: str
    rule: str
    saved_by: str
    session_id: str | None
    created_at: str


def _append_to_markdown(slug: str, title: str, trigger: str, rule: str) -> None:
    settings = get_settings()
    folder = settings.consultant_folder(slug)  # raises if slug is unknown
    knowledge = folder / "knowledge"
    knowledge.mkdir(exist_ok=True)
    target = knowledge / "learnings.md"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    block = (
        f"\n## {timestamp} — {title.strip()}\n"
        f"Trigger: {trigger.strip()}\n"
        f"Rule going forward: {rule.strip()}\n"
    )
    # Append-only — every save is preserved, including ones the user later
    # decides were wrong. Roll-backs are done by editing the file directly
    # and committing, exactly per the original /save-learning command.
    with target.open("a", encoding="utf-8") as f:
        if target.stat().st_size == 0:
            f.write(
                "# Learnings\n\n"
                "Dated voice rules saved during chat sessions. "
                "Future sessions read these first and treat them as voice "
                "overrides above brand-guide.md and voice-rules.md.\n"
            )
        f.write(block)


@router.post("", response_model=LearningOut, status_code=status.HTTP_201_CREATED)
async def save_learning(payload: LearningIn) -> LearningOut:
    # Validate the consultant exists before writing anything.
    try:
        get_settings().consultant_folder(payload.consultant_slug)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))

    _append_to_markdown(
        slug=payload.consultant_slug,
        title=payload.title,
        trigger=payload.trigger,
        rule=payload.rule,
    )

    row = get_db().insert_learning(
        consultant_slug=payload.consultant_slug,
        title=payload.title,
        trigger=payload.trigger,
        rule=payload.rule,
        saved_by=payload.saved_by,
        session_id=payload.session_id,
    )
    log.info(
        "learning saved: consultant=%s by=%s title=%r",
        payload.consultant_slug, payload.saved_by, payload.title,
    )
    return LearningOut(**row)


@router.get("/{consultant_slug}", response_model=list[LearningOut])
async def list_learnings_for_consultant(consultant_slug: str) -> list[LearningOut]:
    rows = get_db().list_learnings(consultant_slug=consultant_slug)
    return [LearningOut(**r) for r in rows]
