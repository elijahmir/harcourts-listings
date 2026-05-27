"""Singleton Supabase client for backend → CopyPro listings repo.

Only used by app/listings.py. The rest of the backend talks to the local
SQLite via app/db.py.

Auth model
----------
The backend uses the **service-role key** (not the anon key) so writes
succeed even when RLS would otherwise block them. We re-implement the
per-user filter in the application layer (every query passes the
caller's user_id) so the same isolation guarantees still apply. RLS
remains on as a defence-in-depth layer in case the Sales App ever
queries Supabase directly.

Failure mode
------------
If HARCOURTS_SUPABASE_URL or HARCOURTS_SUPABASE_SERVICE_KEY is missing,
get_supabase() raises HTTPException(503). Callers should let that
bubble; the chat backend itself still works, only listings endpoints
become 503.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import HTTPException
from supabase import Client, create_client

from .config import get_settings

log = logging.getLogger("harcourts.supabase")


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Return a cached service-role Supabase client.

    Raises 503 if the project's URL or service key isn't configured.
    Cached for the lifetime of the process; the supabase-py client is
    safe to share across asyncio tasks.
    """
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_key:
        log.warning(
            "Supabase listings disabled: HARCOURTS_SUPABASE_URL or "
            "HARCOURTS_SUPABASE_SERVICE_KEY missing. Set both in .env "
            "to enable the listings repo.",
        )
        raise HTTPException(
            status_code=503,
            detail="listings repo not configured on this backend",
        )
    return create_client(settings.supabase_url, settings.supabase_service_key)


def is_admin_email(email: str) -> bool:
    """Cheap mirror of the Postgres copypro_is_admin() helper.

    Asks Supabase whether the given email's profile row has the
    is_copypro_admin flag set. CopyPro admin is intentionally narrower
    than the general profiles.role='admin' (the latter includes 7 users
    who admin OTHER Sales App features but should not necessarily see
    everyone's CopyPro listings).

    Used by the listings handlers to short-circuit "show all" queries.
    Returns False on any failure (lookup miss, network error, etc.) —
    fail-closed.
    """
    if not email:
        return False
    try:
        client = get_supabase()
    except HTTPException:
        return False
    try:
        resp = (
            client.table("profiles")
            .select("is_copypro_admin")
            .eq("email", email)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return bool(rows) and bool(rows[0].get("is_copypro_admin"))
    except Exception as exc:  # noqa: BLE001 — fail-closed on any error
        log.warning("is_admin_email lookup failed for %s: %s", email, exc)
        return False
