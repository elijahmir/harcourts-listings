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
import os
import re
from datetime import datetime, timezone
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


class GradeIn(BaseModel):
    """Inbound shape for PUT /api/listings/{id}/grade.

    A grade is one teammate's thumbs up/down on a saved listing, plus an
    optional note. One grade per (listing, user) — re-grading upserts.
    The aggregate of these is what the admin review page will eventually
    read to spot the listings the team rates strongest.
    """
    grade: str = Field(..., pattern="^(up|down)$")
    comment: str | None = Field(None, max_length=2000)


class PublicReferenceIn(BaseModel):
    """Admin promote/demote of a listing as a public writing reference."""
    public: bool


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


def _grade_summary(sb: Any, listing_id: str, caller_email: str) -> dict:
    """Aggregate up/down counts for a listing plus the caller's own grade.

    Best-effort: any failure returns zeros and my_grade=None so a missing
    grades table or a transient error never breaks a listing read. The
    backend uses the service-role key, so this sees every grade regardless
    of RLS — counts are global, my_grade is the caller's row only.
    """
    try:
        resp = (
            sb.table("copypro_listing_grades")
            .select("grade,user_email")
            .eq("listing_id", listing_id)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        log.warning("grade summary failed for %s: %s", listing_id, exc)
        return {"up": 0, "down": 0, "my_grade": None}
    rows = resp.data or []
    up = sum(1 for r in rows if r.get("grade") == "up")
    down = sum(1 for r in rows if r.get("grade") == "down")
    mine = next(
        (r.get("grade") for r in rows if r.get("user_email") == caller_email),
        None,
    )
    return {"up": up, "down": down, "my_grade": mine}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=dict)
def create_listing(
    payload: ListingCreate,
    user: AuthedUser = Depends(require_auth),
) -> dict:
    """Save a CopyPro chat's final listing to Supabase. Returns the new row.

    Idempotent on (chat_session_id, address_slug, user_id): the chat's
    "Save as listing" button has only per-render state, so it resets on
    reload / navigation and a teammate can tap it again. Rather than
    insert a duplicate, we return the existing row — so a re-save is a
    safe no-op that lands the user back on the same listing.
    """
    user_id = _require_uuid_user_sub(user)
    sb = get_supabase()

    try:
        existing = (
            sb.table("copypro_listings")
            .select("*")
            .eq("chat_session_id", payload.chat_session_id)
            .eq("address_slug", payload.address_slug)
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 — dedup is best-effort
        log.warning("listings.create dedup precheck failed: %s", exc)
        existing = None
    if existing and existing.data:
        log.info(
            "listings.create dedup hit: session=%s address=%s -> existing id=%s",
            payload.chat_session_id, payload.address_slug,
            existing.data[0].get("id"),
        )
        return existing.data[0]

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


def _references_caller_email(
    authorization: str | None,
    x_internal_token: str | None,
    as_user: str | None,
) -> str:
    """Resolve who's asking for references.

    Two auth modes:
    - **Internal token** (the agent via scripts/references.sh): the chat
      subprocess has no user JWT, so the runner passes a shared secret
      (HARCOURTS_INTERNAL_TOKEN) + the chat user's email in `as_user`.
      A matching token is trusted to act as that email. The token never
      leaves Neo (env-only), mirroring how vaultre.sh holds its token.
    - **JWT** (any future UI caller): standard bearer verification.
    """
    internal = os.environ.get("HARCOURTS_INTERNAL_TOKEN")
    if x_internal_token and internal and x_internal_token == internal:
        if not as_user:
            raise HTTPException(
                status_code=400,
                detail="as_user is required with the internal token",
            )
        return as_user
    token = extract_bearer(authorization)
    try:
        return authed_or_raise(token).email
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/references", response_model=list[dict])
def list_references(
    consultant_slug: str = Query(..., max_length=64),
    q: str | None = Query(
        default=None, max_length=200,
        description="Place/environment keyword — matched against the address.",
    ),
    limit: int = Query(default=5, ge=1, le=20),
    as_user: str | None = Query(
        default=None, max_length=200,
        description="Email to scope to — only honoured with a valid internal token.",
    ),
    authorization: str | None = Header(default=None),
    x_internal_token: str | None = Header(default=None),
) -> list[dict]:
    """Thumbs-up listings the agent may use as writing references for a
    consultant.

    Pool = the caller's OWN up-voted listings + any admin-promoted public
    references (is_public_reference), for this consultant only. Newest
    first; full body_md included so the agent can study tone + structure.

    Per-user isolation is the whole point: a caller only ever sees their
    own up-votes plus the shared public set — never another teammate's
    private up-votes. Ungraded and down-voted listings never appear.

    MUST stay declared before GET /{listing_id} — otherwise the UUID path
    captures "references" and 422s.
    """
    caller_email = _references_caller_email(
        authorization, x_internal_token, as_user,
    )
    sb = get_supabase()
    # The caller's own up-voted listing ids.
    try:
        graded = (
            sb.table("copypro_listing_grades")
            .select("listing_id")
            .eq("user_email", caller_email)
            .eq("grade", "up")
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 — degrade to public-only
        log.warning("references: grade lookup failed: %s", exc)
        graded = None
    up_ids = [g["listing_id"] for g in (graded.data or [])] if graded else []

    query = (
        sb.table("copypro_listings")
        .select(
            "id,consultant_slug,address,headline,body_md,"
            "is_public_reference,created_at"
        )
        .eq("consultant_slug", consultant_slug)
    )
    # Reference pool: caller's own up-votes OR any public reference.
    if up_ids:
        query = query.or_(
            f"id.in.({','.join(up_ids)}),is_public_reference.eq.true"
        )
    else:
        query = query.eq("is_public_reference", True)
    # Fetch a generous recent pool, then rank in Python. We deliberately do
    # NOT filter by q in SQL: q describes the SETTING (e.g. "highland lake
    # fishing cabin"), which lives in body_md — a whole-phrase ilike on the
    # address matched nothing, so an environment search wrongly returned 0
    # even when a perfect reference existed.
    pool_limit = max(limit * 4, 30)
    query = query.order("created_at", desc=True).limit(pool_limit)
    try:
        rows = query.execute().data or []
    except Exception as exc:  # noqa: BLE001
        log.exception("references: query failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"references failed: {exc}") from exc

    if q:
        keywords = [w for w in re.split(r"[^a-z0-9]+", q.lower()) if len(w) > 2]

        def _score(r: dict) -> int:
            hay = (
                (r.get("address") or "") + " " + (r.get("body_md") or "")
            ).lower()
            return sum(1 for kw in keywords if kw in hay)

        ranked = sorted(
            rows,
            key=lambda r: (_score(r), r.get("created_at") or ""),
            reverse=True,
        )
        matched = [r for r in ranked if _score(r) > 0]
        # Prefer keyword matches; if none match, fall back to recent so the
        # agent always gets something to anchor on rather than an empty set.
        rows = (matched or ranked)[:limit]
    else:
        rows = rows[:limit]

    log.info(
        "listings.references: user=%s consultant=%s q=%r -> %d",
        caller_email, consultant_slug, q, len(rows),
    )
    return rows


@router.get("/admin-overview", response_model=list[dict])
def admin_overview(
    consultant_slug: str = Query(..., max_length=64),
    user: AuthedUser = Depends(require_auth),
) -> list[dict]:
    """Admin-only: every listing for a consultant with up/down grade
    counts and its public-reference flag, newest first — the data the
    admin review page ranks for promotion decisions. Non-admins 403.

    Declared before GET /{listing_id} so the UUID route doesn't shadow it.
    """
    if not _caller_sees_all(user):
        raise HTTPException(status_code=403, detail="admin only")
    sb = get_supabase()
    try:
        listings = (
            sb.table("copypro_listings")
            .select(
                "id,address,headline,user_email,is_public_reference,"
                "created_at,updated_at"
            )
            .eq("consultant_slug", consultant_slug)
            .order("created_at", desc=True)
            .limit(200)
            .execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        log.exception("admin_overview listings failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"overview failed: {exc}") from exc
    if not listings:
        return []
    ids = [l["id"] for l in listings]
    try:
        grades = (
            sb.table("copypro_listing_grades")
            .select("listing_id,grade")
            .in_("listing_id", ids)
            .execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001 — counts are best-effort
        log.warning("admin_overview grades failed: %s", exc)
        grades = []
    counts: dict[str, dict[str, int]] = {}
    for g in grades:
        c = counts.setdefault(g["listing_id"], {"up": 0, "down": 0})
        if g.get("grade") == "up":
            c["up"] += 1
        elif g.get("grade") == "down":
            c["down"] += 1
    for l in listings:
        l["grade_summary"] = counts.get(l["id"], {"up": 0, "down": 0})
    return listings


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
    listing["grade_summary"] = _grade_summary(sb, str(listing_id), user.email)
    # Lets the UI decide whether to show admin-only controls (the
    # "Make public reference" toggle) without a separate /me round-trip.
    listing["viewer_is_admin"] = _caller_sees_all(user)
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


def _listing_visible_or_404(sb: Any, listing_id: UUID, user: AuthedUser) -> str:
    """Confirm the listing exists and the caller may see it; return its
    owner email. 404 (not 403) on miss so existence never leaks. Shared
    by the grade routes — same ownership rule as get/patch."""
    try:
        existing = (
            sb.table("copypro_listings")
            .select("user_email")
            .eq("id", str(listing_id))
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("listing visibility check failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"grade failed: {exc}") from exc
    if not existing.data:
        raise HTTPException(status_code=404, detail="not found")
    owner_email = existing.data[0].get("user_email")
    if owner_email != user.email and not _caller_sees_all(user):
        raise HTTPException(status_code=404, detail="not found")
    return owner_email


@router.put("/{listing_id}/grade", response_model=dict)
def grade_listing(
    listing_id: UUID,
    payload: GradeIn,
    user: AuthedUser = Depends(require_auth),
) -> dict:
    """Set (or change) the caller's thumbs up/down on a listing.

    Upserts on (listing_id, user_id) so re-grading overwrites the caller's
    prior vote rather than stacking. Returns the fresh grade summary
    (global up/down counts + the caller's grade) so the UI can update in
    one round-trip.
    """
    user_id = _require_uuid_user_sub(user)
    sb = get_supabase()
    _listing_visible_or_404(sb, listing_id, user)

    row = {
        "listing_id": str(listing_id),
        "user_id": str(user_id),
        "user_email": user.email,
        "grade": payload.grade,
        "comment": payload.comment,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        sb.table("copypro_listing_grades").upsert(
            row, on_conflict="listing_id,user_id",
        ).execute()
    except Exception as exc:  # noqa: BLE001
        log.exception("listings.grade upsert failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"grade failed: {exc}") from exc

    log.info(
        "listings.grade: id=%s user=%s grade=%s",
        listing_id, user.email, payload.grade,
    )
    return _grade_summary(sb, str(listing_id), user.email)


@router.delete("/{listing_id}/grade", response_model=dict)
def clear_grade(
    listing_id: UUID,
    user: AuthedUser = Depends(require_auth),
) -> dict:
    """Remove the caller's grade on a listing (un-vote / toggle off).

    Idempotent: deleting a grade that doesn't exist still returns the
    (now grade-free) summary rather than 404, so a double-tap is harmless.
    """
    user_id = _require_uuid_user_sub(user)
    sb = get_supabase()
    _listing_visible_or_404(sb, listing_id, user)
    try:
        (
            sb.table("copypro_listing_grades")
            .delete()
            .eq("listing_id", str(listing_id))
            .eq("user_id", str(user_id))
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("listings.grade delete failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"clear grade failed: {exc}") from exc
    log.info("listings.grade cleared: id=%s user=%s", listing_id, user.email)
    return _grade_summary(sb, str(listing_id), user.email)


@router.post("/{listing_id}/public-reference", response_model=dict)
def set_public_reference(
    listing_id: UUID,
    payload: PublicReferenceIn,
    user: AuthedUser = Depends(require_auth),
) -> dict:
    """Admin-only: promote (or demote) a listing as a PUBLIC writing
    reference. Once public, any teammate writing this consultant can have
    the agent draw on it; until then it's a reference only for whoever
    up-voted it. Non-admins get 403."""
    if not _caller_sees_all(user):
        raise HTTPException(status_code=403, detail="admin only")
    sb = get_supabase()
    try:
        resp = (
            sb.table("copypro_listings")
            .update({"is_public_reference": payload.public})
            .eq("id", str(listing_id))
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("listings.public-reference failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"update failed: {exc}") from exc
    if not resp.data:
        raise HTTPException(status_code=404, detail="not found")
    log.info(
        "listings.public-reference: id=%s admin=%s public=%s",
        listing_id, user.email, payload.public,
    )
    return resp.data[0]
