"""Read-only list of consultants for the session-create dropdown."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from ..auth import CurrentUser
from ..db import lg, service_client

router = APIRouter(prefix="/api/consultants", tags=["consultants"])


class ConsultantOut(BaseModel):
    slug: str
    full_name: str
    vaultre_user_id: int | None
    active: bool
    created_at: datetime


@router.get("", response_model=list[ConsultantOut])
async def list_consultants(user: CurrentUser):
    client = service_client()
    result = (
        lg(client)
        .from_("consultants")
        .select("*")
        .eq("active", True)
        .order("full_name")
        .execute()
    )
    return [ConsultantOut(**row) for row in result.data]
