"""Supabase JWT verification.

The chat is fronted by Tailscale Funnel (a public HTTPS URL). Without
authentication, anyone who learns the URL could hit the backend. We
piggyback on HUP-Sales-App's existing Supabase auth: every API and
WebSocket request must carry a valid Supabase-signed JWT.

Supabase signs session JWTs with the project's JWT_SECRET (HS256). The
same secret HUP-Sales-App's @supabase/supabase-js uses to verify tokens
on the server side. We share that secret with the Neo backend via env
var HARCOURTS_SUPABASE_JWT_SECRET — symmetric HMAC, no network round
trip needed to verify.

Operating modes:

  HARCOURTS_REQUIRE_AUTH=true   (production / shared-URL Funnel)
    - All /api/* and /ws/chat require a valid token.
    - Missing or invalid → 401 (REST) / WS close code 4401.
    - /healthz is public — needed by install.sh verify and basic monitoring.

  HARCOURTS_REQUIRE_AUTH=false  (local dev on Elijah's Mac)
    - Token is not required. Calls go through with a synthesised stub
      user whose email comes from HARCOURTS_DEV_USER_NAME (default
      "dev@local"). Lets you keep using the standalone Funnel/localhost
      surface without setting up a real Supabase session.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import jwt   # PyJWT

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config — read once at import time so a misconfig fails loudly at startup.
# ---------------------------------------------------------------------------


def _require_auth() -> bool:
    return os.environ.get("HARCOURTS_REQUIRE_AUTH", "true").lower() == "true"


def _jwt_secret() -> str:
    s = os.environ.get("HARCOURTS_SUPABASE_JWT_SECRET", "")
    if _require_auth() and not s:
        # Don't crash here (lets dev mode work without the secret), but
        # log a loud warning so prod misconfig is obvious in `journalctl`
        # / launchd stderr.
        log.warning(
            "HARCOURTS_REQUIRE_AUTH=true but HARCOURTS_SUPABASE_JWT_SECRET "
            "is empty — all authed requests will be rejected. Set the "
            "secret from Supabase admin → Project Settings → API → JWT "
            "Secret."
        )
    return s


def _jwt_aud() -> str:
    # Supabase defaults to "authenticated" for the session token audience.
    return os.environ.get("HARCOURTS_SUPABASE_JWT_AUD", "authenticated")


def _dev_user_name() -> str:
    return os.environ.get("HARCOURTS_DEV_USER_NAME", "dev@local")


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class AuthedUser:
    """The identity attached to a request after JWT verification."""
    sub: str           # Supabase user UUID (or 'dev-user' in dev mode)
    email: str         # display identity — what we persist as user_name
    role: str | None   # Supabase role claim ('authenticated' for logged-in)


class AuthError(Exception):
    pass


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def verify_token(token: str) -> AuthedUser:
    """Decode + verify a Supabase JWT. Raises AuthError on any failure."""
    secret = _jwt_secret()
    if not secret:
        raise AuthError("backend not configured: jwt secret missing")
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=_jwt_aud(),
        )
    except jwt.PyJWTError as e:
        raise AuthError(f"invalid token: {e}") from e
    sub = payload.get("sub")
    if not sub:
        raise AuthError("token missing 'sub'")
    return AuthedUser(
        sub=str(sub),
        email=str(payload.get("email") or "unknown@harcourts.com.au"),
        role=payload.get("role"),
    )


def authed_or_raise(token: str | None) -> AuthedUser:
    """Public entry point used by the FastAPI dependency + the WS handler."""
    if not _require_auth():
        return AuthedUser(
            sub="dev-user",
            email=_dev_user_name(),
            role="authenticated",
        )
    if not token:
        raise AuthError("missing token")
    return verify_token(token)


def extract_bearer(authorization_header: str | None) -> str | None:
    """Pull the token out of `Authorization: Bearer <token>`. Returns None
    if the header is missing or malformed."""
    if not authorization_header:
        return None
    parts = authorization_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def extract_ws_bearer(subprotocol_header: str | None) -> str | None:
    """Pull the token out of a Sec-WebSocket-Protocol header value.

    Browsers can't set Authorization on a WebSocket handshake — the
    standard escape hatch is the subprotocol header. Client sends:

        new WebSocket(url, ["harcourts.v1", "bearer." + token])

    which becomes:

        Sec-WebSocket-Protocol: harcourts.v1, bearer.<jwt>

    We extract the bearer. The server is responsible for echoing back
    `harcourts.v1` (the non-bearer protocol) on `websocket.accept`.
    """
    if not subprotocol_header:
        return None
    for raw in subprotocol_header.split(","):
        sp = raw.strip()
        if sp.startswith("bearer."):
            return sp[len("bearer."):].strip() or None
    return None
