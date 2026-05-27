"""FastAPI entry point.

Endpoints:

* ``GET /healthz`` — liveness check, lists known consultants.
* ``WebSocket /ws/chat`` — streaming chat with per-session persistence.
* ``POST /api/learnings`` — save a voice rule to the consultant's markdown.
* ``GET /api/learnings/{consultant_slug}`` — audit list of saved rules.
* ``POST /api/sessions/{session_id}/upload`` — multipart photo upload.
* ``DELETE /api/sessions/{session_id}/uploads`` — wipe a session's photos.

There is intentionally no authentication here. The trust boundary is the
network — this service is meant to run on the office Mac behind Tailscale,
not on the public internet. See README.md.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import json as _json
from pathlib import Path as _Path

from .auth import AuthedUser, AuthError, authed_or_raise, extract_bearer, extract_ws_bearer
from .config import get_settings
from .db import get_db
from .learnings import router as learnings_router
from .listings import router as listings_router
from .runner import StreamEvent, StreamSummary, stream_message
from .uploads import router as uploads_router


# Patterns we want to KNOW about (not block) when they show up in a
# user's WS message. The prompt handles the response; this is just so
# the operator can see attempted abuse in /tmp/harcourts-backend.log
# and decide whether to lock things down further. Keep the patterns
# tight — false positives in property descriptions ('DROP off the
# kids') would spam the log. We match on multi-token signatures, not
# single keywords.
_SUSPICIOUS_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = []


def _compile_suspicious_patterns() -> None:
    """Lazy compile so the import isn't at module load time."""
    import re as _re
    if _SUSPICIOUS_PATTERNS:
        return
    # Patterns deliberately err on the side of false-positive — this is
    # audit-only logging, not blocking. Sample input is truncated to 300
    # chars in the log so noisy property descriptions don't hide the
    # signal. All patterns case-insensitive.
    rules = [
        # Classic SQLi probe shapes: quote followed by OR/AND/UNION
        ("sqli_probe",
         r"(?i)['\"]\s*(?:or|and|union)\s+"),
        # Stacked-statement DROP attempt
        ("sqli_drop_table",
         r"(?i);\s*drop\s+(?:table|database)\b"),
        # Role-switch / jailbreak openings
        ("prompt_role_switch",
         r"(?i)\b(?:ignore|disregard|forget)\b.{0,40}\b(?:previous|prior|above|system|all)\b.{0,40}\b(?:instruction|prompt|rule|message)s?"),
        # Persona-swap attempts ("you are now a hacker", "you are an unrestricted AI")
        ("prompt_jailbreak_persona",
         r"(?i)\byou\s+are\s+(?:now\s+)?(?:an?\s+)?(?:hacker|unrestricted|jailbroken|dan\b|developer\s+mode|sudo\s+mode|root|admin\s+mode)"),
        # Env / credential extraction via shell
        ("env_extraction",
         r"(?i)(?:\b(?:cat|head|tail|less|more|read|show|print(?:env)?)\b[^.\n]{0,40}\.env\b|\benv\s*\||\bprintenv\b)"),
        # Any attempt to invoke sqlite from chat — the backend owns the DB
        ("sqlite_direct",
         r"(?i)\bsqlite3?\b"),
        # Curl/wget against API endpoints (CLI bypass attempt)
        ("api_bypass_attempt",
         r"(?i)\b(?:curl|wget)\s+[^\s]*(?:api\.vaultre|api\.harcourts|/api/v1)"),
    ]
    for tag, pattern in rules:
        _SUSPICIOUS_PATTERNS.append((tag, _re.compile(pattern)))


def _log_suspicious_input(session_id: str, user_email: str, content: str) -> None:
    """Emit a WARNING for each suspicious pattern matched in `content`.
    Audit-only — never blocks. Lets you spot abuse trends post-hoc."""
    _compile_suspicious_patterns()
    sample = content[:300].replace("\n", " ")
    for tag, regex in _SUSPICIOUS_PATTERNS:
        if regex.search(content):
            log.warning(
                "suspicious input matched (%s) session=%s user=%s sample=%r",
                tag, session_id, user_email, sample,
            )


def _first_name(name_or_email: str) -> str:
    """Derive a display first name from whatever the WS layer hands us.

    Accepts either an email ("elijah.mirandilla@harcourts.com.au") or a
    freeform name string ("Elijah Mirandilla", "Sarah"). For emails: take
    the local part, the first dot-segment, capitalise. For freeform: take
    the first whitespace token and capitalise.

    Returns empty string if the input is unusable — the system prompt
    branches on truthy so an empty value just suppresses the greeting
    line rather than producing "Hi ."
    """
    s = (name_or_email or "").strip()
    if not s:
        return ""
    # Email shape: local@domain → take local
    if "@" in s:
        s = s.split("@", 1)[0]
    # Take everything up to the first separator (dot, underscore, space).
    for sep in (".", "_", " "):
        if sep in s:
            s = s.split(sep, 1)[0]
            break
    return s.capitalize() if s else ""


def _summarise_tool_use(name: str | None, inp: dict | None) -> str:
    """Plain-English one-liner for a tool call. Drives the UI's activity
    ticker — what users see while Claude is mid-turn.

    Rules of thumb:
      - Speak about WHAT, never HOW. "Looking at files" not "Running ls".
      - Use filenames only — strip directories. The user doesn't need to
        see consultants/wendy-squibb/sessions/session-abc/photos/.
      - Truncate long inputs.
      - Never echo raw shell commands or paths back at the user.
    """
    name = (name or "").lower()
    inp = inp or {}

    def leaf(path: str) -> str:
        """basename, robust to backslashes too."""
        if not path:
            return ""
        return path.replace("\\", "/").rsplit("/", 1)[-1]

    if name == "read":
        path = inp.get("file_path") or inp.get("path") or ""
        return f"Reading {leaf(path) or 'a file'}"
    if name == "bash":
        cmd = (inp.get("command") or "").strip()
        # VaultRE wrapper — first-class friendly summary.
        if cmd.startswith("./scripts/vaultre.sh"):
            parts = cmd.split(None, 2)
            sub = parts[1] if len(parts) > 1 else ""
            arg = parts[2] if len(parts) > 2 else ""
            # Strip quotes around the search term.
            arg = arg.strip().strip("\"'")
            if sub == "search":
                return f"Searching VaultRE for {arg[:80]}" if arg else "Searching VaultRE"
            if sub == "photos":
                return "Looking up VaultRE photos"
            if sub == "get":
                return "Loading VaultRE property"
            if sub == "download":
                return "Downloading VaultRE photos"
            return "Talking to VaultRE"
        # Friendly verbs for common shell commands — never expose the
        # command itself in the activity line.
        head = cmd.split(None, 1)[0] if cmd else ""
        friendly = {
            "ls": "Looking at files",
            "find": "Searching for files",
            "cat": "Reading a file",
            "head": "Reading a file",
            "tail": "Reading a file",
            "less": "Reading a file",
            "wc": "Counting things",
            "mv": "Organising a file",
            "cp": "Copying a file",
            "mkdir": "Setting up folders",
            "rmdir": "Tidying up",
            "rm": "Cleaning up",
            "echo": "Jotting something down",
            "grep": "Searching for text",
            "awk": "Processing some text",
            "sed": "Processing some text",
            "git": "Checking the workspace",
            "python": "Running a script",
            "python3": "Running a script",
            "node": "Running a script",
        }.get(head)
        return friendly or "Working on it"
    if name == "write":
        return f"Saving {leaf(inp.get('file_path') or '') or 'a file'}"
    if name == "edit":
        return f"Updating {leaf(inp.get('file_path') or '') or 'a file'}"
    if name == "webfetch" or name == "web_fetch":
        return "Checking the web"
    if name == "websearch" or name == "web_search":
        q = (inp.get("query") or "")[:60]
        return f"Searching the web for {q}" if q else "Searching the web"
    if name == "grep":
        return "Searching for text"
    if name == "glob":
        return "Finding files"
    if name == "task" or name == "agent":
        return "Handing off to a helper"
    # Unknown / future tools — graceful generic.
    return "Working on it"


def _recover_assistant_text_from_jsonl(claude_session_id: str) -> str:
    """Last-resort recovery: read Claude Code's own session jsonl and
    extract the most recent assistant message's text.

    Claude Code persists every turn at ~/.claude/projects/<encoded>/{id}.jsonl.
    Each line is a JSON event. The `--resume` flag points at this exact
    file. If our stream-event parser misses the text for any reason, this
    is the canonical source — guaranteed to match what Claude itself
    "remembers" as having said.
    """
    matches = list(
        (_Path.home() / ".claude" / "projects").glob(f"*/{claude_session_id}.jsonl")
    )
    if not matches:
        return ""
    # Walk lines bottom-up looking for the most recent assistant text.
    try:
        lines = matches[0].read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:  # noqa: BLE001
        return ""
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            obj = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        # Claude Code's jsonl wraps events under a "message" key with role.
        msg = obj.get("message") or obj
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            joined = "".join(text_parts).strip()
            if joined:
                return joined
    return ""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("harcourts.backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    # Touching the DB here forces the file + schema to exist before the
    # first request, so any permission / disk error fails at boot.
    get_db()
    log.info(
        "backend starting on %s:%s, project_root=%s, %d consultants",
        s.host, s.port, s.project_root, len(s.known_consultants()),
    )
    yield
    log.info("backend shutting down")


app = FastAPI(
    title="Harcourts Listing Backend",
    version="0.3.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

# CORS for the chat UI. We need to accept:
#   - localhost / 127.0.0.1 (Mac browsing on the host itself)
#   - RFC1918 private LAN IPs (phone/laptop on the same Wi-Fi)
#   - Tailscale CGNAT range 100.64.0.0/10 (teammates hitting the host's
#     tailnet IP directly, e.g. http://100.89.167.17:3010 from an
#     iPhone on cellular). The /10 means second octet is 64-127.
#   - Tailscale MagicDNS hostnames (*.tail*.ts.net)
# WebSocket handshakes aren't subject to CORS, but the /healthz fetch is.
# Symptom of missing an origin here: WS connects (green dot) but the
# consultant dropdown stays empty because fetchConsultants() is blocked.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"^https?://("
        r"localhost"
        r"|127\.0\.0\.1"
        r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3}"
        r"|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}"
        r"|[a-z0-9-]+\.tail[0-9a-f]+\.ts\.net"
        r"|[a-z0-9-]+\.vercel\.app"  # HUP-Sales-App on Vercel
        r"|[a-z0-9-]+\.hup\.net\.au"  # Production HUP-Sales-App (salesapp.hup.net.au + future subdomains)
        r")(:\d+)?$"
    ),
    # Allow credentials so the browser can send the Authorization header
    # AND so any future cookie-based session would work. With credentials
    # on, the response's Access-Control-Allow-Origin can't be '*' — has
    # to be the specific origin echoed back, which the regex above lets
    # CORSMiddleware do automatically.
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PATCH"],
    allow_headers=["*"],
)

app.include_router(learnings_router)
app.include_router(listings_router)
app.include_router(uploads_router)


def require_auth(
    authorization: str | None = Header(default=None),
) -> AuthedUser:
    """FastAPI dependency for authed REST routes.

    Reads `Authorization: Bearer <jwt>`, verifies via Supabase HS256.
    In dev mode (HARCOURTS_REQUIRE_AUTH=false) returns a stub user so
    local Funnel/localhost testing still works without a real session.
    """
    token = extract_bearer(authorization)
    try:
        return authed_or_raise(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Session-cleanup helpers (used by DELETE /api/sessions/{id} and its preview
# endpoint). Kept here rather than in db.py because they touch the filesystem.
# ---------------------------------------------------------------------------

# Liberal match — same shape as the frontend chip-rendering regex so a
# bare filename "saved as foo.docx" (the friendly form the system prompt
# encourages) is counted as a session deliverable, not just the canonical
# "outputs/foo.docx" form. The cross-session collision risk is mitigated
# elsewhere: collection is restricted to ASSISTANT messages (user-typed
# filenames don't count), and each candidate must actually exist under
# outputs/ — so a mention without a corresponding file is a no-op.
import re as _re_cleanup  # local alias — re is reused in suspicious-input logger

_OUTPUTS_REF_RE = _re_cleanup.compile(
    r"(?:outputs/)?([A-Za-z0-9][A-Za-z0-9._\-/]*\.(?:docx|pdf|csv|txt|md|jpe?g|png|webp))",
    _re_cleanup.IGNORECASE,
)


def _collect_session_outputs(session_id: str) -> list[_Path]:
    """Walk a session's ASSISTANT messages and return resolved Paths to
    every output file the assistant mentioned that still exists in
    `outputs/`.

    Why assistant-only: the assistant is the only role that can actually
    GENERATE a deliverable. Restricting attribution to assistant messages
    means a user pasting a filename ("I have draft.docx on my desktop")
    can't trigger another session's deliverable to be deleted.

    Path-traversal defence: every match is resolved against the
    `outputs/` root and discarded if it doesn't sit under it.
    """
    db = get_db()
    messages = db.list_messages(session_id=session_id, limit=1000)

    s = get_settings()
    outputs_root = (s.project_root / "outputs").resolve()

    seen: set[str] = set()
    found: list[_Path] = []
    for m in messages:
        if m.get("role") != "assistant":
            continue
        content = m.get("content") or ""
        if not isinstance(content, str):
            continue
        for match in _OUTPUTS_REF_RE.finditer(content):
            rel = match.group(1)
            if rel in seen:
                continue
            seen.add(rel)
            ext = _Path(rel).suffix.lower()
            if ext not in DOWNLOADABLE_EXTENSIONS:
                continue
            candidate = (outputs_root / rel).resolve()
            try:
                candidate.relative_to(outputs_root)
            except ValueError:
                continue
            if candidate.is_file():
                found.append(candidate)
    return found


def _session_folder_candidates(
    consultant_slug: str | None, session_id: str
) -> list[_Path]:
    """Return every folder under `consultants/{slug}/sessions/` that
    belongs to this session.

    Discovery order (first non-empty wins, so we don't double-attribute):
      1. **Strict**: `session-{id[:8]}/` — the canonical convention
         enforced by the uploads route and the system prompt.
      2. **Time-based fallback**: any session folder whose contents'
         mtime falls inside this session's active window. Catches
         folders the assistant invented (e.g. when running
         `vaultre.sh download <id> <some-other-name>`), which would
         otherwise leak.

    Time-based attribution risks attaching to the wrong session ONLY if
    two sessions for the same consultant were active simultaneously and
    one wrote into a folder during the other's window. With a single
    operator (Wendy) on a single laptop, that doesn't happen.
    """
    if not consultant_slug:
        return []
    s = get_settings()
    sessions_root = (
        s.project_root / "consultants" / consultant_slug / "sessions"
    ).resolve()
    if not sessions_root.is_dir():
        return []

    # Strict path first.
    strict = (sessions_root / f"session-{session_id[:8]}").resolve()
    try:
        strict.relative_to(sessions_root)
    except ValueError:
        strict = None  # type: ignore[assignment]
    if strict and strict.is_dir():
        return [strict]

    # Fallback: time-based discovery.
    db = get_db()
    sess = db.get_session(session_id)
    if not sess:
        return []

    import datetime as _dt

    def _parse(ts: str | None) -> _dt.datetime | None:
        if not ts:
            return None
        try:
            iso = ts if "T" in ts else ts.replace(" ", "T") + "+00:00"
            return _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            return None

    started = _parse(sess.get("started_at"))
    last = _parse(sess.get("last_active_at"))
    if not started or not last:
        return []
    # 60-second slack on each side for clock skew between SQLite (CURRENT_TIMESTAMP)
    # and filesystem mtime (kernel).
    started_ts = started.timestamp() - 60
    last_ts = last.timestamp() + 60

    matched: list[_Path] = []
    for folder in sessions_root.iterdir():
        if not folder.is_dir():
            continue
        target = folder.resolve()
        try:
            target.relative_to(sessions_root)
        except ValueError:
            continue
        # Folder is in-scope if ANY file inside it was modified during
        # this session's window. We stop at the first match per folder.
        for f in target.rglob("*"):
            if not f.is_file():
                continue
            try:
                mtime = f.stat().st_mtime
            except OSError:
                continue
            if started_ts <= mtime <= last_ts:
                matched.append(target)
                break
    return matched


def _count_session_uploads(consultant_slug: str | None, session_id: str) -> int:
    """Count files recursively under any folder this session owns
    (strict canonical name OR time-based fallback). 0 if nothing is
    attributable.
    """
    total = 0
    for folder in _session_folder_candidates(consultant_slug, session_id):
        total += sum(1 for _ in folder.rglob("*") if _.is_file())
    return total


@app.get("/healthz")
def healthz() -> dict:
    """Public — needed by install.sh verify and basic monitoring. Does
    not expose anything sensitive; the consultant list is already
    enumerable by anyone who can clone the repo."""
    s = get_settings()
    return {
        "ok": True,
        "service": "harcourts-backend",
        "project_root": str(s.project_root),
        "consultants": s.known_consultants(),
    }


@app.get("/api/sessions")
def list_sessions(
    consultant_slug: str | None = None,
    limit: int = 50,
    user: AuthedUser = Depends(require_auth),
) -> list[dict]:
    """List sessions for the History dropdown. Returns only the caller's
    own sessions in prod mode — closes the IDOR where any teammate could
    see every other teammate's chats by listing this endpoint. The
    dev-user stub (HARCOURTS_REQUIRE_AUTH=false) sees everything, which
    is what local debugging needs.
    """
    db = get_db()
    if user.sub == "dev-user":
        return db.list_sessions(consultant_slug=consultant_slug, limit=limit)
    return db.list_sessions(
        consultant_slug=consultant_slug, user_name=user.email, limit=limit,
    )


@app.get("/api/sessions/{session_id}")
def get_session_info(
    session_id: str,
    user: AuthedUser = Depends(require_auth),
) -> dict:
    """Minimal session metadata (no messages). Used by the frontend to
    decide whether to render the 'viewing another user's session'
    banner before the chat starts. Same auth rules as the read
    endpoints: owner, dev-user, or CopyPro admin.
    """
    from .supabase_client import is_admin_email  # local import — supabase optional
    db = get_db()
    sess = db.get_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="not found")
    is_admin = (
        user.sub == "dev-user"
        or sess.get("user_name") == user.email
        or is_admin_email(user.email)
    )
    if not is_admin:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "id": sess.get("id"),
        "consultant_slug": sess.get("consultant_slug"),
        "user_name": sess.get("user_name"),
        "started_at": sess.get("started_at"),
        "last_active_at": sess.get("last_active_at"),
    }


@app.get("/api/sessions/{session_id}/messages")
def list_session_messages(
    session_id: str,
    user: AuthedUser = Depends(require_auth),
) -> list[dict]:
    """Replay a session's chat history. Owner, dev-user, or CopyPro
    admin sees the messages. Non-admin non-owner gets [] (rather than
    403) to avoid leaking session existence via status code.

    Admins seeing other-user sessions is a deliberate part of the
    'warn + allow' admin policy: they CAN read, but the frontend
    renders a banner over the chat so they don't accidentally write
    new messages into someone else's history thinking it's theirs.
    """
    from .supabase_client import is_admin_email  # local import — supabase optional
    db = get_db()
    sess = db.get_session(session_id)
    if not sess:
        return []
    is_owner = sess.get("user_name") == user.email
    is_dev = user.sub == "dev-user"
    is_admin = is_dev or is_admin_email(user.email)
    if not is_owner and not is_admin:
        log.warning(
            "list_session_messages refused: %s tried to read session %s "
            "owned by %s", user.email, session_id, sess.get("user_name"),
        )
        return []
    return db.list_messages(session_id=session_id)


@app.get("/api/sessions/{session_id}/cleanup-preview")
def cleanup_preview(
    session_id: str,
    user: AuthedUser = Depends(require_auth),
) -> dict:
    """Non-destructive preview of what `DELETE /api/sessions/{id}` will
    remove. The confirm modal calls this before showing "Delete this
    session?" so the user can see exactly how many files are about to
    be wiped — uploaded photos under the session folder, and any
    deliverables (Word docs / images / PDFs) the session generated
    under `outputs/`.

    Same auth + ownership rules as DELETE: anyone authed can preview
    their own session; in prod (non-dev-user) you can't preview
    someone else's. Returns:

        {
          "session_id": "...",
          "uploads": 5,                       # files under consultants/.../sessions/session-XX/
          "deliverables": 1,                  # files under outputs/ referenced by this session
          "deliverable_names": ["158.docx"],  # filenames only (no path) for the modal
        }
    """
    db = get_db()
    sess = db.get_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")

    # Same ownership check as delete_session — preview leaks file
    # counts, which is mildly sensitive (a malicious user could probe
    # other people's sessions for activity volume).
    if (
        user.sub != "dev-user"
        and sess.get("user_name")
        and sess["user_name"] != user.email
    ):
        raise HTTPException(
            status_code=403,
            detail="you can only preview your own sessions",
        )

    uploads = _count_session_uploads(sess.get("consultant_slug"), session_id)
    output_paths = _collect_session_outputs(session_id)
    return {
        "session_id": session_id,
        "uploads": uploads,
        "deliverables": len(output_paths),
        "deliverable_names": [p.name for p in output_paths],
    }


@app.delete("/api/sessions/{session_id}")
def delete_session(
    session_id: str,
    user: AuthedUser = Depends(require_auth),
) -> dict:
    """Hard-delete a session: DB rows + on-disk session folder.

    Ownership: in production (REQUIRE_AUTH=true, user.sub != 'dev-user')
    we only allow the session's owner to delete it. user_name on the
    session row is the email derived from the JWT at create time, so
    the comparison is JWT-email vs stored email. In dev mode the auth
    layer hands back the stub 'dev-user' identity and we skip the
    ownership check — keeps local testing frictionless.

    Cascade:
      - sessions row + all messages → deleted by db.delete_session
      - filesystem session folder → removed here (shutil.rmtree)
      - outputs/<file> referenced in messages → unlinked here (was
        previously kept; now we sweep them so "delete session" means
        delete everything the session produced). Conservative regex
        requires explicit `outputs/` prefix so a bare filename in chat
        text can't accidentally trigger another session's deliverable.
      - learnings → kept (durable voice rules, see db.delete_session)

    Returns {"deleted": true, "session_id": "...",
             "uploads_removed": N, "outputs_removed": M} on success;
    404 if the session doesn't exist; 403 if the caller doesn't own it.
    """
    import shutil

    db = get_db()
    sess = db.get_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")

    # Collect referenced outputs BEFORE deleting messages — _collect
    # reads message content to do the regex match. After
    # db.delete_session() those rows are gone.
    outputs_to_remove = _collect_session_outputs(session_id)

    # Ownership check. Skipped for the dev-user stub so local testing
    # without a real Supabase session continues to work.
    if user.sub != "dev-user" and sess.get("user_name") and sess["user_name"] != user.email:
        log.warning(
            "delete_session refused: %s tried to delete session %s owned by %s",
            user.email, session_id, sess["user_name"],
        )
        raise HTTPException(
            status_code=403,
            detail="you can only delete your own sessions",
        )

    # Filesystem first — if any rmtree fails we abort before touching
    # the DB so the on-disk + DB views stay consistent. Use the same
    # discovery rule as the preview endpoint (strict canonical folder,
    # then time-based fallback) so any folder the assistant invented
    # — e.g. `session-20260526-211635-158-preservation-drive` from a
    # vaultre.sh download — also gets cleaned up. Without the fallback
    # the DB row goes away but the photos sit on disk forever.
    slug = sess.get("consultant_slug")
    folders_to_remove = _session_folder_candidates(slug, session_id)
    for target in folders_to_remove:
        try:
            shutil.rmtree(target)
            log.info("removed session folder %s", target)
        except Exception as exc:  # noqa: BLE001
            log.exception("rmtree failed for %s: %s", target, exc)
            raise HTTPException(
                status_code=500,
                detail=f"could not remove session folder: {exc}",
            )

    # Unlink each referenced output. Per-file failures are warnings, not
    # 500s — folder wipe already succeeded, so partial-output cleanup is
    # something the user can mop up manually from outputs/. Returning 500
    # here would leave the DB row intact but the folder gone, which is
    # worse than logging and moving on.
    outputs_removed = 0
    for path in outputs_to_remove:
        try:
            path.unlink()
            outputs_removed += 1
            log.info("removed output %s", path)
        except FileNotFoundError:
            pass
        except Exception as exc:  # noqa: BLE001 — log and continue
            log.warning("could not unlink output %s: %s", path, exc)

    deleted = db.delete_session(session_id)
    log.info(
        "delete_session: id=%s user=%s deleted=%s outputs_removed=%d",
        session_id, user.email, deleted, outputs_removed,
    )
    return {
        "deleted": deleted,
        "session_id": session_id,
        "outputs_removed": outputs_removed,
    }


# Extensions Claude can put in outputs/ and have the UI auto-render
# a download chip for. Chosen for "safe to serve from a browser":
#   - Document formats: .docx, .pdf, .csv, .txt, .md
#   - Common image formats: .jpg, .jpeg, .png, .webp
# Deliberately EXCLUDED:
#   - .html, .svg → can carry inline scripts → XSS surface
#   - .exe, .sh, .app, .dmg → executable formats
# Add to this allow-list only after confirming the format can't be used
# to inject script content or trick a browser into auto-executing.
DOWNLOADABLE_EXTENSIONS = frozenset({
    ".docx", ".pdf", ".csv", ".txt", ".md",
    ".jpg", ".jpeg", ".png", ".webp",
})

# Content-Type per extension. Browsers infer this from the response,
# but being explicit means iOS Safari doesn't second-guess a .docx as
# text/plain (which it sometimes does on first download attempt).
_MEDIA_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf":  "application/pdf",
    ".csv":  "text/csv",
    ".txt":  "text/plain",
    ".md":   "text/markdown",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".webp": "image/webp",
}


@app.get("/api/outputs/{filename:path}")
def download_output(
    filename: str,
    user: AuthedUser = Depends(require_auth),
) -> FileResponse:
    """Serve a generated artefact from outputs/ for download.

    Workflow Phase 5 writes the listing's Word doc here; consultants can
    also save images / PDFs they want the user to grab. This route is
    the canonical "give me that file" endpoint — the chat UI auto-
    renders a download chip whenever Claude mentions one of the
    DOWNLOADABLE_EXTENSIONS by name in a reply.

    Hardening:
      - Path is resolved against settings.project_root / outputs and
        rejected if it escapes (path-traversal defence).
      - File extension must be in the allow-list (no arbitrary
        executable / scriptable formats served).
      - Only files that actually exist return 200; otherwise 404 with
        no information about adjacent files.
      - Ownership: in prod mode, the filename must be referenced in one
        of the caller's own session messages. Prevents a teammate who
        guessed or shoulder-surfed another teammate's filename from
        grabbing the document. Dev-user bypasses for local debugging.
    """
    s = get_settings()
    outputs_root = (s.project_root / "outputs").resolve()
    target = (outputs_root / filename).resolve()
    if not str(target).startswith(str(outputs_root) + "/") and target != outputs_root:
        raise HTTPException(status_code=400, detail="invalid path")
    suffix = target.suffix.lower()
    if suffix not in DOWNLOADABLE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"file type {suffix or '(none)'} isn't downloadable. "
                "Allowed: " + ", ".join(sorted(DOWNLOADABLE_EXTENSIONS))
            ),
        )
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not found")

    # Ownership gate: confirm THIS user has a session that references
    # this filename. _collect_session_outputs reads assistant messages
    # per session id and regex-extracts outputs/<file> mentions; we
    # iterate the caller's sessions and check membership.
    if user.sub != "dev-user":
        db = get_db()
        owns_it = False
        for sess in db.list_sessions(user_name=user.email, limit=500):
            paths = _collect_session_outputs(sess["id"])
            if any(p.resolve() == target for p in paths):
                owns_it = True
                break
        if not owns_it:
            log.warning(
                "download_output refused: %s tried to grab %s — not in their sessions",
                user.email, filename,
            )
            # 404 not 403: don't leak that the file exists for someone else.
            raise HTTPException(status_code=404, detail="not found")

    return FileResponse(
        path=target,
        media_type=_MEDIA_TYPES.get(suffix, "application/octet-stream"),
        filename=target.name,
        headers={
            "Content-Disposition": f'attachment; filename="{target.name}"',
            "Cache-Control": "no-store",
        },
    )


@app.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket) -> None:
    """Streaming chat WebSocket.

    Client → Server::

        {
          "type": "user_message",
          "session_id": null,                # null on first turn, else our id
          "consultant_slug": "wendy-squibb",
          "user_name": "Sarah",              # display only, not auth
          "content": "Start a listing for 12 Smith St",
          "claude_session_id": null          # null on first, else claude's id
        }

    Server → Client::

        {"type": "ready"}                                            # once
        {"type": "chunk", "text": "...", "kind": "...", ...}         # streaming
        {"type": "done", "session_id": "<our id>",
         "claude_session_id": "...", "tokens": {...},
         "cost_usd": F, "return_code": N, ...}
        {"type": "error", "message": "..."}

    First turn creates the SQLite session row. ``session_id`` in the
    ``done`` event is what the client should send on subsequent turns.
    """
    settings = get_settings()
    db = get_db()

    # ---- WS auth (before accept) -------------------------------------------
    # Browsers can't set Authorization on a WS handshake; the client passes
    # the Supabase access token via the Sec-WebSocket-Protocol header, in
    # the form:
    #
    #     new WebSocket(url, ["harcourts.v1", "bearer." + token])
    #
    # which arrives as:
    #
    #     Sec-WebSocket-Protocol: harcourts.v1, bearer.<jwt>
    #
    # If we ACCEPT the WS with a subprotocol arg, that arg MUST be one of
    # the protocols the client offered — picking 'harcourts.v1' echoes back
    # cleanly and hides the bearer from the response header.
    subprotocol_header = websocket.headers.get("sec-websocket-protocol", "")
    ws_token = extract_ws_bearer(subprotocol_header)
    try:
        authed = authed_or_raise(ws_token)
    except AuthError as exc:
        log.info("ws auth failed: %s", exc)
        # WebSocket close codes: 4401 is our convention for "unauthorized
        # at the application layer" (the spec reserves 4000-4999 for app use).
        await websocket.close(code=4401, reason="unauthorized")
        return
    # Pick the non-bearer subprotocol to echo. If the client only sent
    # bearer.* (no plain 'harcourts.v1'), accept without a subprotocol
    # so we don't echo back a secret-bearing value.
    chosen_subprotocol: str | None = None
    for raw_sp in subprotocol_header.split(","):
        sp = raw_sp.strip()
        if sp and not sp.startswith("bearer."):
            chosen_subprotocol = sp
            break
    await websocket.accept(subprotocol=chosen_subprotocol)
    await websocket.send_json({"type": "ready"})

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "invalid JSON"})
                continue

            if msg.get("type") != "user_message":
                await websocket.send_json(
                    {"type": "error", "message": "expected type='user_message'"}
                )
                continue

            slug = (msg.get("consultant_slug") or "").strip()
            content = (msg.get("content") or "").strip()
            # The authed email (from the verified JWT) is the source of
            # truth for who's chatting. The client-supplied user_name is
            # only honoured in dev mode (where authed.email is the stub).
            # This prevents impersonation: even if a logged-in user
            # supplies a different user_name in the WS payload, the
            # session row gets tagged with their actual Supabase email.
            user_name = authed.email if authed.sub != "dev-user" else (
                (msg.get("user_name") or authed.email).strip() or authed.email
            )
            # First-name for the consultant to greet by. Derived from the
            # email's local part, dot-segment one. "elijah.mirandilla@…"
            # becomes "Elijah". If the user_name doesn't look like an
            # email (dev-mode, freeform name typed in name-prompt), we
            # take the whole string and titlecase its first token.
            user_first_name = _first_name(user_name)
            # Audit-only: log obvious injection / prompt-jailbreak patterns
            # so we can see attempted abuse later. The system prompt is
            # what shapes Claude's response; this is purely visibility.
            # Read session_id directly from the inbound msg rather than
            # the local var assigned later — keeps the audit log close
            # to where content is parsed and avoids the ordering bug.
            _log_suspicious_input(
                msg.get("session_id") or "<new>", authed.email, content,
            )
            resume_id = msg.get("claude_session_id") or None
            session_id = msg.get("session_id") or None

            if not slug:
                await websocket.send_json(
                    {"type": "error", "message": "missing consultant_slug"}
                )
                continue
            if not content:
                await websocket.send_json(
                    {"type": "error", "message": "empty content"}
                )
                continue

            try:
                folder = settings.consultant_folder(slug)
            except (FileNotFoundError, ValueError) as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                continue

            # First turn: create the session row. Subsequent turns: verify the
            # row exists. If the client sends a stale session_id we drop and
            # create a fresh session rather than erroring — easier UX.
            session = db.get_session(session_id) if session_id else None
            if not session:
                session = db.create_session(
                    consultant_slug=slug, user_name=user_name
                )
                session_id = session["id"]
                # Cutting a new session ALSO means we can't honor a stale
                # claude_session_id from the client. If we did, claude
                # would --resume a jsonl on disk whose history doesn't
                # match our DB ("Hi again!" effect). Force a fresh
                # Claude CLI session too.
                resume_id = None

            log.info(
                "turn: session=%s consultant=%s user=%s len=%d resume=%s",
                session_id, slug, user_name, len(content), resume_id,
            )

            db.insert_message(
                session_id=session_id, role="user", content=content
            )

            # Per-block bubble state. A "block" is the text Wendy
            # produces between tool calls — each maps to its own
            # assistant bubble + its own row in the messages table.
            # current_block_text holds what's being typed RIGHT NOW.
            # blocks_committed is bumped once we INSERT a row for the
            # closed block, so token/cost can be attributed correctly
            # at end-of-turn (only the LAST committed row gets the
            # turn's tokens/cost — see flush_block below).
            current_block_text = ""
            blocks_committed = 0

            # The claude subprocess can take 15–30s for image-heavy turns.
            # If the WebSocket drops mid-stream (mobile Safari backgrounding,
            # cellular handoff, screen sleep), we must still consume the
            # full stream and persist the assistant message — otherwise the
            # work is lost and the user has no way to see Wendy's reply
            # when they come back. Strategy: ALWAYS iterate the stream to
            # completion; WS sends become best-effort, gated by a flag we
            # flip the first time a send raises.
            ws_alive = True

            async def _safe_send(payload: dict) -> None:
                nonlocal ws_alive
                if not ws_alive:
                    return
                try:
                    await websocket.send_json(payload)
                except Exception:  # noqa: BLE001 — WS closed mid-turn
                    ws_alive = False
                    log.info(
                        "ws dropped mid-turn (session=%s); continuing to consume "
                        "claude stream so the assistant message is persisted.",
                        session_id,
                    )

            async def flush_block(
                *,
                final: bool = False,
                input_tokens: int | None = None,
                output_tokens: int | None = None,
                cost_usd: float | None = None,
            ) -> None:
                """Commit the current_block_text as its own DB row +
                notify the frontend.

                - Intermediate blocks (called from a tool_use boundary):
                  no token/cost data on the row. The WS frame emitted
                  is `bubble_break` so the frontend finalises the live
                  bubble and starts a fresh placeholder for the next.
                - Final block (called from StreamSummary): carries the
                  whole turn's token/cost data on the row. WS frame is
                  the existing `done` event — emitted by the caller.

                No-op if there's no text to commit (defensive — empty
                bubbles add noise).
                """
                nonlocal current_block_text, blocks_committed
                text = current_block_text.strip()
                if not text:
                    log.info(
                        "flush_block skipped (empty): session=%s final=%s blocks_committed=%d",
                        session_id, final, blocks_committed,
                    )
                    return
                try:
                    row_id = db.insert_message(
                        session_id=session_id,
                        role="assistant",
                        content=text,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=cost_usd,
                    )
                except Exception as exc:  # noqa: BLE001 — log + re-raise
                    log.exception(
                        "flush_block INSERT failed: session=%s final=%s "
                        "len=%d err=%s",
                        session_id, final, len(text), exc,
                    )
                    raise
                blocks_committed += 1
                log.info(
                    "flush_block committed: session=%s final=%s row=%d "
                    "len=%d blocks_committed=%d",
                    session_id, final, row_id, len(text), blocks_committed,
                )
                if not final:
                    # Tell the frontend to seal the current live bubble
                    # and spawn a fresh placeholder for the next text.
                    await _safe_send({
                        "type": "bubble_break",
                        "message_id": str(row_id),
                        "session_id": session_id,
                    })
                # Reset for the next block.
                current_block_text = ""

            try:
                async for ev in stream_message(
                    user_message=content,
                    consultant_folder=folder,
                    resume_session_id=resume_id,
                    claude_bin=settings.claude_bin,
                    user_first_name=user_first_name,
                ):
                    if isinstance(ev, StreamSummary):
                        # End-of-turn safety net: if nothing landed in
                        # current_block_text AND no blocks were
                        # committed (so the chat would show empty),
                        # fall back to reading Claude's own jsonl —
                        # that's the canonical record `--resume` will
                        # read next turn. Without this an unusual
                        # stream-json shape could leave SQLite empty
                        # despite Claude having generated a reply.
                        if (
                            ev.session_id
                            and not current_block_text.strip()
                            and blocks_committed == 0
                        ):
                            jsonl_text = _recover_assistant_text_from_jsonl(
                                ev.session_id
                            ) or ""
                            if jsonl_text.strip():
                                log.info(
                                    "recovered %d chars from jsonl for session=%s",
                                    len(jsonl_text), session_id,
                                )
                                current_block_text = jsonl_text
                                # Push the recovered text to the UI so
                                # the frozen placeholder gets filled.
                                await _safe_send({
                                    "type": "chunk",
                                    "kind": "text_full",
                                    "text": current_block_text,
                                    "session_id": ev.session_id,
                                })
                            else:
                                log.warning(
                                    "no text after stream + jsonl fallback "
                                    "for session=%s claude=%s",
                                    session_id, ev.session_id,
                                )

                        # Flush the LAST block — this one carries the
                        # turn's token + cost on its row.
                        log.info(
                            "StreamSummary received: session=%s "
                            "current_block_text_len=%d blocks_committed=%d "
                            "input_tokens=%s output_tokens=%s",
                            session_id, len(current_block_text),
                            blocks_committed, ev.input_tokens,
                            ev.output_tokens,
                        )
                        await flush_block(
                            final=True,
                            input_tokens=ev.input_tokens,
                            output_tokens=ev.output_tokens,
                            cost_usd=ev.total_cost_usd,
                        )
                        db.update_session_after_turn(
                            session_id=session_id,
                            claude_session_id=ev.session_id,
                            input_tokens=ev.input_tokens or 0,
                            output_tokens=ev.output_tokens or 0,
                            cost_usd=ev.total_cost_usd or 0.0,
                        )
                        await _safe_send(
                            {
                                "type": "done",
                                "session_id": session_id,
                                "claude_session_id": ev.session_id,
                                "tokens": {
                                    "input": ev.input_tokens,
                                    "output": ev.output_tokens,
                                    "cache_creation": ev.cache_creation_tokens,
                                    "cache_read": ev.cache_read_tokens,
                                },
                                "cost_usd": ev.total_cost_usd,
                                "return_code": ev.return_code,
                                "is_error": ev.is_error,
                                "error_message": ev.error_message,
                            }
                        )
                        break

                    assert isinstance(ev, StreamEvent)
                    # Text events: the runner now emits ONLY the LATEST
                    # text block's text (not joined-across-blocks), so
                    # latest-wins is per-block. Block boundaries are
                    # signalled by tool_use events below — when one
                    # arrives, we flush the current text as its own DB
                    # row and reset.
                    if ev.text and ev.kind in ("text_delta", "text_full"):
                        current_block_text = ev.text

                    if ev.kind == "tool_use":
                        # Bubble boundary: commit whatever's currently
                        # in the live bubble as its own row + tell the
                        # frontend to seal it and spawn a new one.
                        # flush_block is no-op if current_block_text is
                        # empty (e.g. tools fired immediately with no
                        # preamble — no orphan empty bubble).
                        await flush_block(final=False)
                        # Live activity ticker — same behaviour as
                        # before. The ticker text shows in the NEW
                        # placeholder bubble while the tool runs.
                        await _safe_send(
                            {
                                "type": "activity",
                                "summary": _summarise_tool_use(
                                    ev.tool_name, ev.tool_input
                                ),
                                "tool": ev.tool_name,
                            }
                        )

                    await _safe_send(
                        {
                            "type": "chunk",
                            "kind": ev.kind,
                            "text": ev.text,
                            "session_id": ev.session_id,
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                log.exception("turn failed: %s", exc)
                await _safe_send({"type": "error", "message": str(exc)})

    except WebSocketDisconnect:
        log.info("ws client disconnected")
    except Exception as exc:  # noqa: BLE001 — keep socket-lifecycle simple
        log.exception("ws error: %s", exc)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            pass


def main() -> None:
    """Entry point for ``python -m app.main`` style invocation."""
    import uvicorn

    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, log_level="info")


if __name__ == "__main__":
    main()
