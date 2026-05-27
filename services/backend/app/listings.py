"""CopyPro listings repo — persists completed listings to Supabase.

A row in ``copypro_listings`` is the canonical artefact a CopyPro chat
produces. The Word doc is now a downstream export, not the source of
truth.

Endpoints
---------
* ``POST   /api/listings``         — save a new listing (chat → save)
* ``GET    /api/listings``         — list caller's listings (or all if admin)
* ``GET    /api/listings/{id}``    — one listing (with optional revisions)
* ``PATCH  /api/listings/{id}``    — update; trigger snapshots the prior
                                     state into ``copypro_listing_revisions``

Auth + ownership
----------------
Every endpoint requires a Supabase JWT. user_id (UUID) and user_email
come from the JWT and are written into the row at create time. Reads are
filtered by user_email except for admins (``profiles.is_copypro_admin``),
who see everything.

We use the service-role key on the backend so writes succeed even though
RLS is on; per-user isolation is enforced application-side by always
filtering by user_email. RLS remains active as a defence-in-depth layer
in case anyone ever talks to Supabase from the Sales App directly.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .auth import AuthedUser, AuthError, authed_or_raise, extract_bearer
from .supabase_client import get_supabase, is_admin_email

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/listings", tags=["listings"])


def require_auth(
    authorization: str | None = Header(default=None),
) -> AuthedUser:
    token = extract_bearer(authorization)
    try:
        return authed_or_raise(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ListingCreate(BaseModel):
    """Inbound shape for POST /api/listings.

    Field caps are generous because real listings can run long; we just
    don't want a runaway megabyte payload sneaking into Postgres.
    """
    chat_session_id: str = Field(..., min_length=1, max_length=64)
    consultant_slug: str = Field(..., min_length=1, max_length=64)
    address: str = Field(..., min_length=3, max_length=500)
    address_slug: str = Field(..., min_length=3, max_length=200)
    headline: str | None = Field(None, max_length=500)
    body_md: str = Field(..., min_length=10, max_length=200_000)
    social_caption: str | None = Field(None, max_length=4_000)
    signboard_blurb: str | None = Field(None, max_length=2_000)
    docx_filename: str | None = Field(None, max_length=300)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ListingUpdate(BaseModel):
    """Inbound shape for PATCH /api/listings/{id}. Every field optional;
    only provided fields are updated. The DB trigger handles snapshotting
    the old state into copypro_listing_revisions when any text field
    changes — no need to mention revisions here.
    """
    headline: str | None = Field(None, max_length=500)
    body_md: str | None = Field(None, min_length=10, max_length=200_000)
    social_caption: str | None = Field(None, max_length=4_000)
    signboard_blurb: str | None = Field(None, max_length=2_000)
    status: str | None = Field(None, pattern="^(final|archived)$")
    docx_filename: str | None = Field(None, max_length=300)
    metadata: dict[str, Any] | None = None
    edit_summary: str | None = Field(
        None, max_length=400,
        description=(
            "Optional human-friendly note explaining the change — gets "
            "stored alongside the revision row so admins can see why "
            "something changed without diffing markdown."
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_uuid_user_sub(user: AuthedUser) -> UUID:
    """Best-effort UUID parse of the JWT.sub claim.

    Listings only make sense for real authed users (we attribute every
    row to an auth.users.id). Dev-user (HARCOURTS_REQUIRE_AUTH=false)
    has sub='dev-user' which can't be a UUID, so we 400 cleanly instead
    of crashing with a Pydantic error somewhere downstream.
    """
    if user.sub == "dev-user":
        raise HTTPException(
            status_code=400,
            detail=(
                "listings require a real authenticated user; the dev-user "
                "stub can't own a listing. Sign into the Sales App via "
                "Supabase first."
            ),
        )
    try:
        return UUID(user.sub)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="bad user identifier in token",
        ) from exc


def _caller_sees_all(user: AuthedUser) -> bool:
    """True if the caller should see other users' listings.

    Mirrors the Postgres copypro_is_admin() function: looks up the
    caller's email in profiles.is_copypro_admin. Cached miss/network
    failures fail closed (return False) — strict by default.
    """
    return is_admin_email(user.email)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=dict)
def create_listing(
    payload: ListingCreate,
    user: AuthedUser = Depends(require_auth),
) -> dict:
    """Save a CopyPro chat's final listing to Supabase. Returns the new row."""
    user_id = _require_uuid_user_sub(user)
    sb = get_supabase()
    row = {
        "user_id": str(user_id),
        "user_email": user.email,
        "consultant_slug": payload.consultant_slug,
        "chat_session_id": payload.chat_session_id,
        "address": payload.address,
        "address_slug": payload.address_slug,
        "headline": payload.headline,
        "body_md": payload.body_md,
        "social_caption": payload.social_caption,
        "signboard_blurb": payload.signboard_blurb,
        "docx_filename": payload.docx_filename,
        "metadata": payload.metadata,
    }
    try:
        resp = sb.table("copypro_listings").insert(row).execute()
    except Exception as exc:  # noqa: BLE001 — surface to caller
        log.exception("listings.create failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"insert failed: {exc}") from exc
    if not resp.data:
        raise HTTPException(status_code=500, detail="insert returned no row")
    log.info(
        "listings.create: id=%s user=%s consultant=%s address=%s",
        resp.data[0].get("id"), user.email, payload.consultant_slug,
        payload.address,
    )
    return resp.data[0]


@router.get("", response_model=list[dict])
def list_listings(
    consultant_slug: str | None = Query(default=None, max_length=64),
    q: str | None = Query(
        default=None, max_length=200,
        description="Fuzzy address substring (uses pg_trgm).",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    user: AuthedUser = Depends(require_auth),
) -> list[dict]:
    """List listings the caller can see, newest first.

    Default: only the caller's own. Admins see all.
    """
    sb = get_supabase()
    query = (
        sb.table("copypro_listings")
        .select(
            "id,user_email,consultant_slug,chat_session_id,address,"
            "address_slug,headline,status,docx_filename,metadata,"
            "created_at,updated_at"
        )
        .order("created_at", desc=True)
        .limit(limit)
    )
    if consultant_slug:
        query = query.eq("consultant_slug", consultant_slug)
    if q:
        # ilike for substring — pg_trgm index speeds it up
        query = query.ilike("address", f"%{q}%")
    if not _caller_sees_all(user):
        query = query.eq("user_email", user.email)
    try:
        resp = query.execute()
    except Exception as exc:  # noqa: BLE001
        log.exception("listings.list failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"list failed: {exc}") from exc
    return resp.data or []


@router.get("/{listing_id}", response_model=dict)
def get_listing(
    listing_id: UUID,
    include_revisions: bool = Query(default=False),
    user: AuthedUser = Depends(require_auth),
) -> dict:
    """Fetch one listing. 404 if not found or not owned by caller (and
    they're not admin). Optionally includes the full revision history.
    """
    sb = get_supabase()
    try:
        resp = (
            sb.table("copypro_listings")
            .select("*")
            .eq("id", str(listing_id))
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("listings.get failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"get failed: {exc}") from exc
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="not found")
    listing = rows[0]
    if listing.get("user_email") != user.email and not _caller_sees_all(user):
        # Don't leak existence — 404 not 403.
        raise HTTPException(status_code=404, detail="not found")
    if include_revisions:
        try:
            rev = (
                sb.table("copypro_listing_revisions")
                .select("*")
                .eq("listing_id", str(listing_id))
                .order("created_at", desc=True)
                .execute()
            )
            listing["revisions"] = rev.data or []
        except Exception as exc:  # noqa: BLE001
            log.warning("listings.get revisions failed: %s", exc)
            listing["revisions"] = []
    return listing


@router.patch("/{listing_id}", response_model=dict)
def update_listing(
    listing_id: UUID,
    payload: ListingUpdate,
    user: AuthedUser = Depends(require_auth),
) -> dict:
    """Update a listing's fields. The DB trigger automatically inserts
    the old state into copypro_listing_revisions when any text field
    changes — no manual revision bookkeeping here.

    Ownership: same as get_listing. Owner or admin only.
    """
    sb = get_supabase()
    # Confirm the row exists + caller can see it (same logic as GET).
    try:
        existing = (
            sb.table("copypro_listings")
            .select("user_email")
            .eq("id", str(listing_id))
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("listings.patch precheck failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"update failed: {exc}") from exc
    if not existing.data:
        raise HTTPException(status_code=404, detail="not found")
    owner_email = existing.data[0].get("user_email")
    if owner_email != user.email and not _caller_sees_all(user):
        raise HTTPException(status_code=404, detail="not found")

    # Build the partial update dict (skip unset / explicitly-None fields).
    updates: dict[str, Any] = {}
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "edit_summary":
            continue  # not a column on the listings table; see below
        updates[key] = value
    if not updates:
        raise HTTPException(
            status_code=400,
            detail="no fields to update",
        )

    try:
        resp = (
            sb.table("copypro_listings")
            .update(updates)
            .eq("id", str(listing_id))
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("listings.patch failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"update failed: {exc}") from exc
    if not resp.data:
        raise HTTPException(status_code=500, detail="update returned no row")

    # If the caller provided an edit_summary, attach it to the latest
    # revision the trigger just wrote. Best-effort — failures are
    # logged but not surfaced because the actual update already
    # succeeded.
    if payload.edit_summary:
        try:
            latest = (
                sb.table("copypro_listing_revisions")
                .select("id")
                .eq("listing_id", str(listing_id))
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if latest.data:
                sb.table("copypro_listing_revisions").update(
                    {"edit_summary": payload.edit_summary},
                ).eq("id", latest.data[0]["id"]).execute()
        except Exception as exc:  # noqa: BLE001 — best-effort
            log.warning("attach edit_summary failed: %s", exc)

    log.info(
        "listings.patch: id=%s user=%s changed=%s",
        listing_id, user.email, list(updates.keys()),
    )
    return resp.data[0]
