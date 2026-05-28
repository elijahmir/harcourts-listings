"""SQLite persistence for sessions, messages, and learnings.

Three small tables, plain sqlite3, no ORM. Operations are sync — at the
office's expected concurrency this is comfortably below 1 ms per call,
and avoiding an async driver keeps the dependency surface tiny.

The DB file lives at ``<data_dir>/listings.db``. Admins can inspect it
with the ``sqlite3`` CLI or any GUI like TablePlus / DB Browser.
"""
from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id                   TEXT PRIMARY KEY,
    claude_session_id    TEXT,
    consultant_slug      TEXT NOT NULL,
    user_name            TEXT NOT NULL,
    started_at           TEXT NOT NULL DEFAULT (datetime('now')),
    last_active_at       TEXT NOT NULL DEFAULT (datetime('now')),
    total_input_tokens   INTEGER NOT NULL DEFAULT 0,
    total_output_tokens  INTEGER NOT NULL DEFAULT 0,
    total_cost_usd       REAL    NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sessions_consultant
    ON sessions(consultant_slug, last_active_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role          TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content       TEXT NOT NULL,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_session
    ON messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS learnings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    consultant_slug TEXT NOT NULL,
    title           TEXT NOT NULL,
    trigger         TEXT NOT NULL,
    rule            TEXT NOT NULL,
    saved_by        TEXT NOT NULL,
    session_id      TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    scope           TEXT NOT NULL DEFAULT 'team',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_learnings_consultant
    ON learnings(consultant_slug, created_at DESC);
"""


class Database:
    """Thin sqlite3 wrapper. One connection, guarded by a lock for thread safety."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        # check_same_thread=False because uvicorn's worker may dispatch us
        # from different threads. The Lock below serialises writes.
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._lock = Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
            self._migrate()
        log.info("sqlite ready at %s", path)

    def _migrate(self) -> None:
        """Idempotent column migrations for pre-existing databases.

        Fresh DBs get every column from _SCHEMA; older DBs (e.g. Neo's live
        listings.db) predate later columns and need an ALTER. Each step
        checks PRAGMA table_info first so re-running is a no-op.
        """
        cols = {
            r["name"] for r in self._conn.execute("PRAGMA table_info(learnings)")
        }
        if "scope" not in cols:
            # Default 'team' backfills existing rows — they were global
            # before per-user scoping existed.
            self._conn.execute(
                "ALTER TABLE learnings ADD COLUMN scope TEXT NOT NULL "
                "DEFAULT 'team'"
            )
            self._conn.commit()
            log.info("migrated: added learnings.scope")

    # --- sessions -----------------------------------------------------------

    def create_session(
        self, *, consultant_slug: str, user_name: str
    ) -> dict[str, Any]:
        sid = str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (id, consultant_slug, user_name) "
                "VALUES (?, ?, ?)",
                (sid, consultant_slug, user_name),
            )
            self._conn.commit()
        row = self.get_session(sid)
        assert row is not None
        return row

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete_session(self, session_id: str) -> bool:
        """Hard-delete a session row and every message attached to it.

        Returns True if the session existed and was removed, False if it
        was already gone. Deletion runs inside a single transaction so a
        crash mid-cascade leaves the database consistent — we don't end
        up with orphaned messages whose parent session has vanished.

        Filesystem cleanup (the session's photos folder) is the caller's
        job — keeps the DB layer ignorant of disk paths.

        Learnings are intentionally NOT cascaded: a voice rule that came
        out of a session is a durable thing (it lives in the consultant's
        knowledge/learnings.md too) and should survive the session it
        was born from.
        """
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("BEGIN")
                cur.execute(
                    "DELETE FROM messages WHERE session_id = ?", (session_id,),
                )
                result = cur.execute(
                    "DELETE FROM sessions WHERE id = ?", (session_id,),
                )
                deleted = result.rowcount > 0
                self._conn.commit()
                return deleted
            except Exception:
                self._conn.rollback()
                raise

    def update_session_after_turn(
        self,
        *,
        session_id: str,
        claude_session_id: str | None,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE sessions
                SET claude_session_id = COALESCE(?, claude_session_id),
                    total_input_tokens = total_input_tokens + ?,
                    total_output_tokens = total_output_tokens + ?,
                    total_cost_usd = total_cost_usd + ?,
                    last_active_at = datetime('now')
                WHERE id = ?
                """,
                (
                    claude_session_id,
                    input_tokens,
                    output_tokens,
                    cost_usd,
                    session_id,
                ),
            )
            self._conn.commit()

    def list_sessions(
        self,
        *,
        consultant_slug: str | None = None,
        user_name: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List sessions, optionally filtered by consultant and/or owner.

        `user_name` is the email of the session creator (matches the
        `user_name` column populated from the Supabase JWT at create
        time). When passed, only sessions belonging to that user come
        back — that's how the API layer prevents one teammate from
        seeing another's chats. Passing `None` returns every session
        (used by the dev-user "admin" view).
        """
        sql = "SELECT * FROM sessions"
        clauses: list[str] = []
        params: list[Any] = []
        if consultant_slug:
            clauses.append("consultant_slug = ?")
            params.append(consultant_slug)
        if user_name:
            clauses.append("user_name = ?")
            params.append(user_name)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY last_active_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # --- messages -----------------------------------------------------------

    def insert_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: float | None = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO messages
                  (session_id, role, content, input_tokens, output_tokens, cost_usd)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, role, content, input_tokens, output_tokens, cost_usd),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def list_messages(
        self, *, session_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE session_id = ? "
                "ORDER BY created_at, id LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- learnings ----------------------------------------------------------

    def insert_learning(
        self,
        *,
        consultant_slug: str,
        title: str,
        trigger: str,
        rule: str,
        saved_by: str,
        session_id: str | None,
        scope: str = "user",
    ) -> dict[str, Any]:
        """Insert a voice rule. scope='user' (default) keeps it private to
        saved_by — only that teammate's sessions read it, and it is NOT
        written to the shared learnings.md. scope='team' is the promoted,
        everyone-reads-it state (also appended to learnings.md by the API)."""
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO learnings
                  (consultant_slug, title, trigger, rule, saved_by,
                   session_id, scope)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (consultant_slug, title, trigger, rule, saved_by,
                 session_id, scope),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM learnings WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        assert row is not None
        return dict(row)

    def list_learnings(
        self,
        *,
        consultant_slug: str,
        scope: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List learnings for a consultant, optionally filtered by scope
        ('user' = all teammates' private rules, for the admin review page;
        'team' = promoted rules; None = both)."""
        sql = "SELECT * FROM learnings WHERE consultant_slug = ?"
        params: list[Any] = [consultant_slug]
        if scope:
            sql += " AND scope = ?"
            params.append(scope)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def list_user_learnings(
        self,
        *,
        consultant_slug: str,
        saved_by: str,
        scope: str = "user",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """A single teammate's private voice rules for a consultant — what
        the runner injects into that teammate's sessions."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM learnings WHERE consultant_slug = ? "
                "AND saved_by = ? AND scope = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (consultant_slug, saved_by, scope, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_learning(self, learning_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM learnings WHERE id = ?", (learning_id,)
            ).fetchone()
        return dict(row) if row else None

    def promote_learning(self, learning_id: int) -> dict[str, Any] | None:
        """Flip a private rule to team scope. The API also appends it to
        learnings.md so every session reads it from then on."""
        with self._lock:
            self._conn.execute(
                "UPDATE learnings SET scope = 'team' WHERE id = ?",
                (learning_id,),
            )
            self._conn.commit()
        return self.get_learning(learning_id)


_instance: Database | None = None


def get_db() -> Database:
    """Lazily open the singleton database connection."""
    global _instance
    if _instance is None:
        from .config import get_settings

        s = get_settings()
        _instance = Database(s.data_dir / "listings.db")
    return _instance


# --- Helpers ----------------------------------------------------------------


def now_iso() -> str:
    """ISO8601 UTC timestamp matching the format SQLite emits."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
