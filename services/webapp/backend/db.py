"""Supabase clients used by the backend.

Two distinct clients on purpose:

* ``service_client`` uses the service-role JWT and bypasses RLS. Use it for
  all backend-initiated writes (inserting messages, recording uploads).
* ``user_client(jwt)`` is a per-request client tied to a logged-in user's
  JWT, so RLS applies as if the user themself were querying. Use it any
  time you want defence-in-depth that a user cannot read another user's
  rows even via a backend bug.

Both target the ``listing_generator`` schema by default. PostgREST routing
sends the request to the right schema via the ``Accept-Profile`` and
``Content-Profile`` headers under the hood.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from supabase import Client, create_client

from .config import get_settings

log = logging.getLogger(__name__)

LISTING_GEN_SCHEMA = "listing_generator"


@lru_cache(maxsize=1)
def service_client() -> Client:
    s = get_settings()
    client = create_client(str(s.supabase_url), s.supabase_service_role_key)
    log.info("service_client initialised for %s", s.supabase_url)
    return client


def user_client(jwt: str) -> Client:
    """Per-request client with the user's JWT applied. Not cached — RLS must
    be evaluated under the calling user, not a previous caller."""
    s = get_settings()
    client = create_client(str(s.supabase_url), s.supabase_publishable_key)
    client.postgrest.auth(jwt)
    return client


def lg(client: Client):
    """Shortcut: ``lg(client).from_('sessions').select(...)``."""
    return client.schema(LISTING_GEN_SCHEMA)
