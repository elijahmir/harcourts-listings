"""FastAPI entry point for the Harcourts listing webapp.

Boot order is intentional: settings load first so any missing env var fails
fast at process start, not on the first request.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routes import consultants, sessions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("webapp")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()  # fail-fast on missing env
    log.info("webapp starting on %s:%s", settings.webapp_host, settings.webapp_port)
    yield
    log.info("webapp shutting down")


app = FastAPI(
    title="Harcourts Listing Webapp",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

# Dev CORS for the SvelteKit vite dev server. In production the frontend is
# served by FastAPI itself, so CORS is moot.
_settings_at_import = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings_at_import.cors_dev_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(consultants.router)
app.include_router(sessions.router)


@app.get("/healthz")
def healthz() -> dict:
    s = get_settings()
    return {
        "ok": True,
        "service": "webapp",
        "supabase_url": str(s.supabase_url),
        "consultants_dir": str(s.consultants_dir),
        "consultants_dir_exists": s.consultants_dir.is_dir(),
    }


def main() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "services.webapp.backend.app:app",
        host=s.webapp_host,
        port=s.webapp_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
