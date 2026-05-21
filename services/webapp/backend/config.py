"""Typed environment-variable settings for the webapp backend.

Loads from process env first, falling back to the project-root .env file.
Never logs secret values. Fail-fast if any required value is missing —
the operator gets a clear startup error instead of a 500 mid-request.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

# Project root is two directories above this file (services/webapp/backend/).
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Supabase ---
    supabase_url: HttpUrl
    supabase_publishable_key: str
    supabase_service_role_key: str = Field(..., repr=False)

    # --- Host paths ---
    project_root: Path = PROJECT_ROOT
    consultants_dir: Path = PROJECT_ROOT / "consultants"

    # --- Server ---
    webapp_host: str = "0.0.0.0"
    webapp_port: int = 3000

    # --- CORS for dev (vite dev server on localhost:5173) ---
    cors_dev_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()  # type: ignore[call-arg]
    # Sanity log without leaking secrets.
    log.info(
        "config loaded: supabase=%s project_root=%s consultants_dir=%s",
        s.supabase_url,
        s.project_root,
        s.consultants_dir,
    )
    if not s.consultants_dir.is_dir():
        raise RuntimeError(
            f"consultants_dir does not exist at {s.consultants_dir!r}. "
            "Check that the webapp is being run from the project root."
        )
    return s
