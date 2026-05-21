"""File upload + media-serving endpoints.

Photos and floor plans land on the host Mac under
``consultants/{slug}/sessions/{session_folder}/photos/`` so claude can read
them as multimodal input via its Read tool. We also insert a row into
``listing_generator.uploads`` so the chat UI can list and display what's been
attached to a session.

HEIC files (default iPhone format) are converted to JPEG on the way in,
matching the older services/uploader behaviour. If pillow-heif isn't
available the file is stored verbatim and a warning is logged.
"""
from __future__ import annotations

import logging
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ..auth import CurrentUser
from ..config import get_settings
from ..db import lg, service_client

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sessions", tags=["uploads"])

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
MAX_NAME_LEN = 120
HEIC_SUFFIXES = {".heic", ".heif"}

try:
    from PIL import Image  # type: ignore
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
    HEIC_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    HEIC_AVAILABLE = False
    log.warning("HEIC conversion disabled: %s", exc)


Kind = Literal["photo", "floorplan", "pdf", "other"]


class UploadOut(BaseModel):
    id: str
    session_id: str
    original_filename: str
    stored_filename: str
    local_path: str
    kind: Kind
    bytes: int
    converted_from_heic: bool


def _safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = SAFE_NAME.sub("_", base).strip("._-") or "upload"
    return cleaned[:MAX_NAME_LEN]


def _classify(name: str, content_type: str | None) -> Kind:
    lower = name.lower()
    if any(k in lower for k in ("floor", "plan", "fp")) and not lower.endswith(".jpg"):
        return "floorplan"
    if lower.endswith(".pdf") or content_type == "application/pdf":
        return "pdf"
    if content_type and content_type.startswith("image/"):
        return "photo"
    return "other"


def _maybe_convert_heic(path: Path) -> tuple[Path, bool]:
    if path.suffix.lower() not in HEIC_SUFFIXES or not HEIC_AVAILABLE:
        return path, False
    try:
        with Image.open(path) as img:
            new_path = path.with_suffix(".jpg")
            img.convert("RGB").save(new_path, "JPEG", quality=88, optimize=True)
        path.unlink(missing_ok=True)
        return new_path, True
    except Exception as exc:  # noqa: BLE001
        log.warning("HEIC conversion failed for %s: %s", path.name, exc)
        return path, False


def _resolve_session_folder(session_row: dict) -> Path:
    settings = get_settings()
    rel = session_row.get("session_folder")
    if not rel:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "session has no session_folder assigned",
        )
    folder = (settings.project_root / rel).resolve()
    # Defence in depth: stay inside the project's consultants tree
    if settings.consultants_dir.resolve() not in folder.parents:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "session_folder escapes consultants directory",
        )
    folder.mkdir(parents=True, exist_ok=True)
    photos = folder / "photos"
    photos.mkdir(exist_ok=True)
    return photos


@router.post("/{session_id}/upload", response_model=list[UploadOut])
async def upload(session_id: str, files: list[UploadFile], user: CurrentUser):
    client = service_client()
    sess_q = (
        lg(client)
        .from_("sessions")
        .select("id, consultant_slug, session_folder, status")
        .eq("id", session_id)
        .single()
        .execute()
    )
    if not sess_q.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    photos_dir = _resolve_session_folder(sess_q.data)

    saved: list[dict] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    for index, f in enumerate(files):
        if not f.filename:
            continue
        original = f.filename
        safe = _safe_filename(original)
        destination = photos_dir / f"{stamp}-{index:02d}-{safe}"
        size = 0
        with destination.open("wb") as out:
            while True:
                chunk = await f.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                size += len(chunk)
        await f.close()

        final_path, converted = _maybe_convert_heic(destination)
        final_size = final_path.stat().st_size if converted else size
        kind = _classify(final_path.name, f.content_type)
        rel_path = str(final_path.relative_to(get_settings().project_root))

        ins = lg(client).from_("uploads").insert({
            "session_id": session_id,
            "original_filename": original,
            "stored_filename": final_path.name,
            "local_path": rel_path,
            "kind": kind,
            "bytes": final_size,
            "converted_from_heic": converted,
        }).execute()
        if ins.data:
            saved.append(ins.data[0])

    return [UploadOut(**row) for row in saved]


@router.get("/{session_id}/uploads", response_model=list[UploadOut])
async def list_uploads(session_id: str, user: CurrentUser):
    client = service_client()
    result = (
        lg(client)
        .from_("uploads")
        .select("*")
        .eq("session_id", session_id)
        .order("uploaded_at")
        .execute()
    )
    return [UploadOut(**row) for row in result.data]


@router.get("/{session_id}/media/{filename}")
async def get_media(session_id: str, filename: str, user: CurrentUser):
    """Serve an uploaded file. Path traversal blocked via filename
    canonicalisation + parent-of-photos check."""
    client = service_client()
    sess_q = (
        lg(client)
        .from_("sessions")
        .select("id, session_folder")
        .eq("id", session_id)
        .single()
        .execute()
    )
    if not sess_q.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")

    # Confirm the file is recorded in our DB (don't serve random files even
    # if they happen to exist in the session folder).
    rec_q = (
        lg(client)
        .from_("uploads")
        .select("local_path, stored_filename")
        .eq("session_id", session_id)
        .eq("stored_filename", filename)
        .single()
        .execute()
    )
    if not rec_q.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found for this session")

    settings = get_settings()
    file_path = (settings.project_root / rec_q.data["local_path"]).resolve()
    if settings.consultants_dir.resolve() not in file_path.parents:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "path escapes consultants")
    if not file_path.is_file():
        raise HTTPException(status.HTTP_410_GONE, "file no longer on disk")

    media_type, _ = mimetypes.guess_type(file_path.name)
    return FileResponse(
        file_path,
        media_type=media_type or "application/octet-stream",
        filename=rec_q.data["stored_filename"],
    )
