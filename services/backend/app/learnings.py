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

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from .auth import AuthedUser, AuthError, authed_or_raise, extract_bearer
from .config import get_settings
from .db import get_db
from .supabase_client import is_admin_email


def require_auth(
    authorization: str | None = Header(default=None),
) -> AuthedUser:
    token = extract_bearer(authorization)
    try:
        return authed_or_raise(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

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
    scope: str = "user"
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
async def save_learning(
    payload: LearningIn,
    _user: AuthedUser = Depends(require_auth),
) -> LearningOut:
    """Save a voice rule PRIVATE to the saver (scope='user').

    It is NOT written to the shared learnings.md — only this teammate's
    own sessions pick it up (the runner injects their private rules). An
    admin later promotes the good ones to team scope via /promote, which
    is when it lands in learnings.md for everyone.
    """
    # Validate the consultant exists before writing anything.
    try:
        get_settings().consultant_folder(payload.consultant_slug)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))

    row = get_db().insert_learning(
        consultant_slug=payload.consultant_slug,
        title=payload.title,
        trigger=payload.trigger,
        rule=payload.rule,
        saved_by=payload.saved_by,
        session_id=payload.session_id,
        scope="user",
    )
    log.info(
        "learning saved (private): consultant=%s by=%s title=%r",
        payload.consultant_slug, payload.saved_by, payload.title,
    )
    return LearningOut(**row)


@router.post("/{learning_id}/promote", response_model=LearningOut)
async def promote_learning(
    learning_id: int,
    user: AuthedUser = Depends(require_auth),
) -> LearningOut:
    """Admin-only: promote a private rule to team scope. Flips scope to
    'team' AND appends it to the consultant's learnings.md, so from then
    on every teammate's session reads it. Non-admins get 403."""
    if user.sub != "dev-user" and not is_admin_email(user.email):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    db = get_db()
    existing = db.get_learning(learning_id)
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "learning not found")
    if existing.get("scope") != "team":
        _append_to_markdown(
            slug=existing["consultant_slug"],
            title=existing["title"],
            trigger=existing["trigger"],
            rule=existing["rule"],
        )
    row = db.promote_learning(learning_id)
    assert row is not None
    log.info(
        "learning promoted to team: id=%s consultant=%s by_admin=%s",
        learning_id, existing["consultant_slug"], user.email,
    )
    return LearningOut(**row)


@router.get("/{consultant_slug}", response_model=list[LearningOut])
async def list_learnings_for_consultant(
    consultant_slug: str,
    scope: str | None = None,
    _user: AuthedUser = Depends(require_auth),
) -> list[LearningOut]:
    """List a consultant's learnings. scope='user' returns every
    teammate's private rules (the admin review queue); 'team' the
    promoted ones; omitted returns both."""
    rows = get_db().list_learnings(consultant_slug=consultant_slug, scope=scope)
    return [LearningOut(**r) for r in rows]
