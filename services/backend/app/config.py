"""Runtime configuration for the backend.

Resolved from env vars at import time. Paths fall back to the repo layout
so a fresh checkout runs without configuration.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

# This file lives at services/backend/app/config.py — repo root is three levels up.
_HERE = Path(__file__).resolve().parent
_DEFAULT_PROJECT_ROOT = _HERE.parent.parent.parent


class Settings:
    """Lazy-loaded settings. Use get_settings() to access."""

    def __init__(self) -> None:
        self.project_root: Path = Path(
            os.environ.get("HARCOURTS_PROJECT_ROOT", str(_DEFAULT_PROJECT_ROOT))
        ).resolve()
        self.consultants_dir: Path = self.project_root / "consultants"
        # SQLite + future runtime artefacts. Gitignored.
        self.data_dir: Path = Path(
            os.environ.get(
                "HARCOURTS_DATA_DIR", str(self.project_root / "data")
            )
        ).resolve()
        self.host: str = os.environ.get("HARCOURTS_BACKEND_HOST", "127.0.0.1")
        # 8787 was picked over the common 3000 to avoid collisions with
        # Obsidian's Local REST API plugin and other dev servers that
        # default to 3000. Override with HARCOURTS_BACKEND_PORT if the
        # host needs something else.
        self.port: int = int(os.environ.get("HARCOURTS_BACKEND_PORT", "8787"))
        # Path to the `claude` CLI binary. PATH lookup by default; override if
        # the office Mac uses a non-standard install location.
        self.claude_bin: str = os.environ.get("HARCOURTS_CLAUDE_BIN", "claude")
        # Per-file upload size cap. 25 MB is plenty for property photos and
        # floor plans; rejects pathological uploads cheaply.
        self.max_upload_bytes: int = int(
            os.environ.get("HARCOURTS_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))
        )
        # Supabase project for the CopyPro listings repo. URL is the
        # `https://<ref>.supabase.co` form. Service-role key bypasses RLS
        # for backend writes; per-user isolation is then enforced in
        # application code by always filtering by user_email/user_id.
        # Both unset = listings feature disabled (backend boots, /api
        # endpoints that need Supabase return 503).
        self.supabase_url: str = os.environ.get("HARCOURTS_SUPABASE_URL", "")
        self.supabase_service_key: str = os.environ.get(
            "HARCOURTS_SUPABASE_SERVICE_KEY", ""
        )

    def consultant_folder(self, slug: str) -> Path:
        """Return the on-disk folder for a consultant slug, or raise if missing.

        The slug must match a directory in consultants/ — we don't auto-create.
        """
        folder = (self.consultants_dir / slug).resolve()
        # Path-traversal guard: the resolved folder must sit inside consultants_dir.
        if self.consultants_dir.resolve() not in folder.parents:
            raise ValueError(f"slug escapes consultants directory: {slug!r}")
        if not folder.is_dir():
            raise FileNotFoundError(f"no consultant folder for slug: {slug!r}")
        return folder

    def known_consultants(self) -> list[str]:
        """Slugs of every consultant folder on disk (excluding _template and dotfiles)."""
        if not self.consultants_dir.is_dir():
            return []
        return sorted(
            p.name
            for p in self.consultants_dir.iterdir()
            if p.is_dir() and not p.name.startswith((".", "_"))
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
