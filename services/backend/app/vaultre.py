"""VaultRE read-only client.

Scope (matched to the token's actual permissions: advertising.read,
contact.read, property.read):

  - search_by_address(term)       — fuzzy property lookup by address fragment
  - get_property(property_id)     — full record (description, brochureDescription,
                                    bed/bath/garages, headline, prices, …)
  - get_property_photos(...)      — splits the unified photos endpoint into
                                    (photographs, floor_plans) by VaultRE's
                                    `type` field
  - download_photo(url, dest)     — local mirror so Claude can Read with vision

The deeper API analysis lives in `integrations/vaultre/ANALYSIS.md`. The
big takeaway driving this module's shape: photos and floor plans share
the same endpoint, distinguished only by `type` ∈ {Photograph, Floorplan},
so callers don't pick the right URL per category — they ask for all and
split downstream.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import httpx

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes — what we pass back to callers. Deliberately a thin subset of
# what VaultRE returns; if you need more fields, widen here, don't dump raw.
# ---------------------------------------------------------------------------


@dataclass
class VaultAddress:
    street_number: str
    street: str
    suburb: str
    postcode: str
    state: str

    def one_liner(self) -> str:
        return (
            f"{self.street_number} {self.street}, "
            f"{self.suburb} {self.state} {self.postcode}"
        )


@dataclass
class VaultPropertySummary:
    """The shape returned by /search/properties/address — enough to disambiguate
    matches and pick the right property_id for a follow-up get_property call."""

    id: int
    address: VaultAddress
    status: str | None
    agent_name: str | None


@dataclass
class VaultPropertyDetail:
    """Full record — what fills the Sales Agent Briefing."""

    id: int
    address: VaultAddress
    bedrooms: int | None
    bathrooms: int | None
    garages: int | None
    land_area_sqm: float | None
    heading: str | None
    description: str | None  # the long marketing copy field
    brochure_description: str | None
    window_card_description: str | None
    search_price: int | None
    status: str | None
    agent_name: str | None
    raw: dict[str, Any]  # the full payload, for debugging or future fields


@dataclass
class VaultPhoto:
    id: int
    kind: str  # 'photograph' | 'floorplan'
    url: str
    description: str | None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class VaultRE:
    """Minimal sync HTTP client. Sync because the chat subprocess invokes
    this via a CLI wrapper (single request per command), so the async story
    isn't worth the complexity. Use httpx for connection pooling + timeouts."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        api_token: str | None = None,
        timeout_s: float = 20.0,
    ) -> None:
        self.base_url = (base_url or os.environ["VAULTRE_API_BASE"]).rstrip("/")
        self.api_key = api_key or os.environ["VAULTRE_API_KEY"]
        self.api_token = api_token or os.environ["VAULTRE_API_TOKEN"]
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout_s,
            headers={
                "X-Api-Key": self.api_key,
                "Authorization": f"Bearer {self.api_token}",
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    # -- public methods ------------------------------------------------------

    def search_by_address(self, term: str, limit: int = 10) -> list[VaultPropertySummary]:
        """Fuzzy address lookup. `term` is a free-text fragment; VaultRE
        handles partial matches well. Returns up to `limit` results."""
        r = self._client.get(
            "/search/properties/address",
            params={"term": term, "pagesize": limit},
        )
        r.raise_for_status()
        payload = r.json()
        items = payload if isinstance(payload, list) else payload.get("items", [])
        return [_parse_property_summary(p) for p in items[:limit]]

    def get_property(self, property_id: int) -> VaultPropertyDetail:
        """Full property record including the description fields. The
        token's `property.read` scope covers this."""
        r = self._client.get(f"/properties/{property_id}")
        r.raise_for_status()
        return _parse_property_detail(r.json())

    def get_property_photos(
        self, property_id: int
    ) -> tuple[list[VaultPhoto], list[VaultPhoto]]:
        """Returns (photographs, floor_plans). VaultRE's endpoint returns
        a single list mixing both kinds; this method splits."""
        r = self._client.get(f"/properties/{property_id}/photos")
        r.raise_for_status()
        payload = r.json()
        items = payload if isinstance(payload, list) else payload.get("items", [])
        photos = [_parse_photo(p) for p in items]
        return (
            [p for p in photos if p.kind == "photograph"],
            [p for p in photos if p.kind == "floorplan"],
        )


# ---------------------------------------------------------------------------
# Parsers — defensive against missing fields. VaultRE's spec uses null
# liberally and the token's scope further nulls some fields.
# ---------------------------------------------------------------------------


def _parse_address(d: dict[str, Any]) -> VaultAddress:
    suburb = (d or {}).get("suburb") or {}
    state = suburb.get("state") or (d or {}).get("state") or {}
    return VaultAddress(
        street_number=(d or {}).get("streetNumber") or "",
        street=(d or {}).get("street") or "",
        suburb=suburb.get("name") or "",
        postcode=suburb.get("postcode") or "",
        state=state.get("abbreviation") or state.get("name") or "",
    )


def _parse_property_summary(p: dict[str, Any]) -> VaultPropertySummary:
    return VaultPropertySummary(
        id=int(p["id"]),
        address=_parse_address(p.get("address") or {}),
        status=p.get("statusName") or p.get("status"),
        agent_name=p.get("agentName"),
    )


def _parse_property_detail(p: dict[str, Any]) -> VaultPropertyDetail:
    land = p.get("landArea") or {}
    return VaultPropertyDetail(
        id=int(p["id"]),
        address=_parse_address(p.get("address") or {}),
        bedrooms=p.get("bed") or p.get("bedrooms"),
        bathrooms=p.get("bath") or p.get("bathrooms"),
        garages=p.get("garages") or p.get("carSpaces"),
        land_area_sqm=land.get("value") if isinstance(land, dict) else None,
        heading=p.get("heading"),
        description=p.get("description"),
        brochure_description=p.get("brochureDescription"),
        window_card_description=p.get("windowCardDescription"),
        search_price=p.get("searchPrice"),
        status=p.get("statusName") or p.get("status"),
        agent_name=p.get("agentName"),
        raw=p,
    )


def _parse_photo(p: dict[str, Any]) -> VaultPhoto:
    raw_type = (p.get("type") or "").lower()
    kind = "floorplan" if "floor" in raw_type else "photograph"
    return VaultPhoto(
        id=int(p["id"]),
        kind=kind,
        url=p["url"],
        description=p.get("description"),
    )


# ---------------------------------------------------------------------------
# Photo download helper. Lives here (not on the client class) because it
# doesn't need API auth — photo URLs are public CDN links.
# ---------------------------------------------------------------------------


def download_photo(url: str, dest: Path, timeout_s: float = 30.0) -> int:
    """Stream the photo to `dest`. Returns bytes written."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": "harcourts-listings/1.0"})
    written = 0
    with urlopen(req, timeout=timeout_s) as resp, dest.open("wb") as out:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            out.write(chunk)
            written += len(chunk)
    return written
