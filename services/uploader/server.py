"""
Harcourts mobile uploader.

A tiny FastAPI service that accepts photo/floor-plan uploads from a phone or
laptop and drops them into the right consultant's session folder on the host
Mac. Sits behind Tailscale, so authentication is the network layer's job.

Routes:
  GET  /                          → picker page (list consultants, recent sessions)
  GET  /u/{slug}/{session}        → session-specific upload page
  POST /u/{slug}/{session}        → accept multipart upload
  GET  /api/consultants           → JSON list of consultant slugs
  GET  /api/sessions/{slug}       → JSON list of session folders for a consultant
  GET  /healthz                   → liveness probe

Environment:
  HARCOURTS_PROJECT_ROOT   absolute path to the repo root.
                           Defaults to two directories above this file.
  HARCOURTS_UPLOADER_PORT  port to bind. Default 8080.
  HARCOURTS_UPLOADER_HOST  host to bind. Default 0.0.0.0 (Tailscale-reachable).
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

log = logging.getLogger("uploader")

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent.parent
PROJECT_ROOT = Path(os.environ.get("HARCOURTS_PROJECT_ROOT", str(DEFAULT_ROOT))).resolve()
CONSULTANTS_DIR = PROJECT_ROOT / "consultants"

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
MAX_NAME_LEN = 120
HEIC_SUFFIXES = {".heic", ".heif"}

# Try to enable HEIC support. If pillow-heif isn't installed, HEIC files are
# still accepted and stored verbatim — they just won't be readable by Claude's
# vision input until the operator runs `pip install -r requirements.txt` again.
try:
    from PIL import Image
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIC_CONVERSION_AVAILABLE = True
except Exception as exc:  # noqa: BLE001 — best-effort optional dependency
    HEIC_CONVERSION_AVAILABLE = False
    log.warning("HEIC conversion disabled: %s", exc)


def safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = SAFE_NAME.sub("_", base).strip("._-") or "upload"
    return cleaned[:MAX_NAME_LEN]


def maybe_convert_heic(path: Path) -> Path:
    """If `path` is a HEIC/HEIF file and conversion is available, replace it
    with a JPEG sibling and return the new path. Otherwise return `path`
    unchanged. Conversion failures leave the original in place."""
    if path.suffix.lower() not in HEIC_SUFFIXES:
        return path
    if not HEIC_CONVERSION_AVAILABLE:
        return path
    try:
        with Image.open(path) as img:
            new_path = path.with_suffix(".jpg")
            img.convert("RGB").save(new_path, "JPEG", quality=88, optimize=True)
        path.unlink(missing_ok=True)
        return new_path
    except Exception as exc:  # noqa: BLE001 — keep original on any failure
        log.warning("HEIC conversion failed for %s: %s", path.name, exc)
        return path


def list_consultant_slugs() -> list[str]:
    if not CONSULTANTS_DIR.is_dir():
        return []
    return sorted(
        p.name
        for p in CONSULTANTS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith((".", "_"))
    )


def session_dir_for(slug: str, session: str) -> Path:
    if slug not in list_consultant_slugs():
        raise HTTPException(status_code=404, detail=f"Unknown consultant '{slug}'")
    if "/" in session or session.startswith(".") or session in ("", "..", "."):
        raise HTTPException(status_code=400, detail="Invalid session name")
    target = CONSULTANTS_DIR / slug / "sessions" / session
    if not target.is_dir():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Session folder does not exist: {target.relative_to(PROJECT_ROOT)}. "
                "Start a listing in the chat first so the session is created."
            ),
        )
    return target


app = FastAPI(title="Harcourts Uploader", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")


@app.get("/healthz")
def healthz() -> dict:
    return {
        "ok": True,
        "project_root": str(PROJECT_ROOT),
        "consultants": list_consultant_slugs(),
        "heic_conversion": HEIC_CONVERSION_AVAILABLE,
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(HERE / "static" / "index.html")


@app.get("/u/{slug}/{session}")
def upload_page(slug: str, session: str) -> FileResponse:
    # Validate so a wrong URL fails fast instead of after the user picks files.
    session_dir_for(slug, session)
    return FileResponse(HERE / "static" / "upload.html")


@app.get("/api/consultants")
def api_consultants() -> JSONResponse:
    return JSONResponse({"items": list_consultant_slugs()})


@app.get("/api/sessions/{slug}")
def api_sessions(slug: str) -> JSONResponse:
    if slug not in list_consultant_slugs():
        raise HTTPException(status_code=404, detail=f"Unknown consultant '{slug}'")
    sessions_dir = CONSULTANTS_DIR / slug / "sessions"
    if not sessions_dir.is_dir():
        return JSONResponse({"items": []})
    sessions = [
        {"name": p.name, "modified": p.stat().st_mtime}
        for p in sessions_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    ]
    sessions.sort(key=lambda s: s["modified"], reverse=True)
    return JSONResponse({"items": sessions})


@app.post("/u/{slug}/{session}")
async def upload(slug: str, session: str, files: list[UploadFile]) -> JSONResponse:
    target_dir = session_dir_for(slug, session)
    photos_dir = target_dir / "photos"
    photos_dir.mkdir(exist_ok=True)

    saved: list[dict] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    for index, upload_file in enumerate(files):
        if not upload_file.filename:
            continue
        name = safe_filename(upload_file.filename)
        destination = photos_dir / f"{stamp}-{index:02d}-{name}"
        size = 0
        with destination.open("wb") as out:
            while True:
                chunk = await upload_file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                size += len(chunk)
        await upload_file.close()

        final_path = maybe_convert_heic(destination)
        converted = final_path != destination
        saved.append(
            {
                "saved_as": final_path.name,
                "bytes": final_path.stat().st_size if converted else size,
                "relative_path": str(final_path.relative_to(PROJECT_ROOT)),
                "converted_from_heic": converted,
            }
        )

    return JSONResponse(
        {
            "ok": True,
            "count": len(saved),
            "session_dir": str(target_dir.relative_to(PROJECT_ROOT)),
            "files": saved,
        }
    )


def main() -> None:
    import uvicorn

    host = os.environ.get("HARCOURTS_UPLOADER_HOST", "0.0.0.0")
    port = int(os.environ.get("HARCOURTS_UPLOADER_PORT", "8080"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
