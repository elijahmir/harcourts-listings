"""JWT verification for incoming requests.

The frontend sends ``Authorization: Bearer <supabase_jwt>``. We call
Supabase Auth's ``getUser`` endpoint to validate the token and return the
authenticated user record. Tokens are cached in-process for 60 seconds to
keep per-request latency low.

Why not verify locally? HUP Database is on legacy HS256 JWTs whose secret
we don't want to require in this codebase. ``getUser`` is the official,
revocation-aware path. The 60s cache makes repeated calls effectively free
without breaking sign-out or password rotation by more than a minute.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from .db import service_client

log = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60
_user_cache: dict[str, tuple[float, "AuthUser"]] = {}


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str | None
    role: str | None  # Supabase role: "authenticated", "anon", etc.


def _bearer(request: Request) -> str:
    raw = request.headers.get("authorization", "")
    if not raw.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or malformed Authorization header",
            headers={"WWW-Authenticate": 'Bearer realm="harcourts-webapp"'},
        )
    token = raw[7:].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="empty bearer token",
        )
    return token


def _verify(token: str) -> AuthUser:
    now = time.monotonic()
    cached = _user_cache.get(token)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    # Drop stale entries opportunistically so the cache doesn't grow without
    # bound. Cheap because dict is small.
    if len(_user_cache) > 1024:
        cutoff = now - _CACHE_TTL_SECONDS
        for k in [k for k, (t, _) in _user_cache.items() if t < cutoff]:
            _user_cache.pop(k, None)

    client = service_client()
    try:
        result = client.auth.get_user(token)
    except Exception as exc:
        log.warning("auth.get_user raised: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
        ) from exc

    if not result or not result.user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token did not resolve to a user",
        )
    user = AuthUser(
        id=str(result.user.id),
        email=result.user.email,
        role=getattr(result.user, "role", None),
    )
    _user_cache[token] = (now, user)
    return user


async def require_user(request: Request) -> AuthUser:
    return _verify(_bearer(request))


CurrentUser = Annotated[AuthUser, Depends(require_user)]
