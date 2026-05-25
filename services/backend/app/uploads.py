"""Photo + floor-plan uploads keyed to a chat session.

Files land in the same per-session folder layout the old uploader used
so the rest of the workflow (Phase 1) keeps working unchanged:

    consultants/{slug}/sessions/{YYYY-MM-DD_HHMMSS}_session-{short-id}/photos/

The session row in SQLite gets the folder name on first upload (we don't
create empty folders for sessions that never receive a file).
"""
from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, status
from pydantic import BaseModel

from .auth import AuthedUser, AuthError, authed_or_raise, extract_bearer
from .config import get_settings
from .db import get_db


def require_auth(
    authorization: str | None = Header(default=None),
) -> AuthedUser:
    token = extract_bearer(authorization)
    try:
        return authed_or_raise(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sessions", tags=["uploads"])

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
MAX_NAME_LEN = 120
HEIC_SUFFIXES = {".heic", ".heif"}

# HEIC is iPhone's default photo format. Try to load conversion deps lazily
# so the service still starts on machines where Pillow / pillow-heif aren't
# installed — files just won't be auto-converted to JPEG.
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
    session_id: str
    original_filename: str
    stored_filename: str
    relative_path: str
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


def _session_photos_dir(session_id: str, consultant_slug: str) -> Path:
    settings = get_settings()
    consultant_folder = settings.consultant_folder(consultant_slug)
    # One per-session folder; reused across uploads in the same chat.
    folder = consultant_folder / "sessions" / f"session-{session_id[:8]}"
    photos = folder / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    return photos


@router.post("/{session_id}/upload", response_model=list[UploadOut])
async def upload(
    session_id: str,
    files: list[UploadFile],
    _user: AuthedUser = Depends(require_auth),
) -> list[UploadOut]:
    settings = get_settings()
    sess = get_db().get_session(session_id)
    if not sess:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")

    try:
        photos_dir = _session_photos_dir(session_id, sess["consultant_slug"])
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    # Path-traversal defence: the resolved photos dir must live under
    # consultants_dir. Cheap insurance against future slug-handling bugs.
    if settings.consultants_dir.resolve() not in photos_dir.resolve().parents:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "photos dir escapes consultants tree"
        )

    saved: list[UploadOut] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

    for index, f in enumerate(files):
        if not f.filename:
            continue
        original = f.filename
        safe = _safe_filename(original)
        destination = photos_dir / f"{stamp}-{index:02d}-{safe}"

        size = 0
        try:
            with destination.open("wb") as out:
                while True:
                    chunk = await f.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        out.close()
                        destination.unlink(missing_ok=True)
                        raise HTTPException(
                            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"file exceeds {settings.max_upload_bytes} bytes",
                        )
                    out.write(chunk)
        finally:
            await f.close()

        final_path, converted = _maybe_convert_heic(destination)
        final_size = final_path.stat().st_size if converted else size
        rel = final_path.relative_to(settings.project_root)

        saved.append(
            UploadOut(
                session_id=session_id,
                original_filename=original,
                stored_filename=final_path.name,
                relative_path=str(rel),
                kind=_classify(final_path.name, f.content_type),
                bytes=final_size,
                converted_from_heic=converted,
            )
        )

    log.info("uploaded %d files to %s", len(saved), photos_dir)
    return saved


@router.delete("/{session_id}/uploads")
async def clear_uploads(
    session_id: str,
    _user: AuthedUser = Depends(require_auth),
) -> dict:
    """Wipe the session's photos folder. Used when a user wants a clean Phase 1
    restart. The folder itself is recreated on next upload."""
    sess = get_db().get_session(session_id)
    if not sess:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    try:
        photos_dir = _session_photos_dir(session_id, sess["consultant_slug"])
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    shutil.rmtree(photos_dir, ignore_errors=True)
    return {"ok": True}
