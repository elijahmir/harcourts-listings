"""Subprocess wrapper for the local ``claude`` CLI.

We shell out to the Claude Code CLI rather than calling the Anthropic API
directly. That's deliberate: the office Mac is signed into the team's
Claude Max subscription, so every chat turn is covered by the flat
monthly plan instead of metered API tokens.

Per-message subprocess invocation is restart-safe — killing the backend
mid-turn won't orphan a long-lived child. claude itself persists session
state at ``~/.claude/projects/.../{id}.jsonl``, so passing
``--resume {session_id}`` on subsequent turns picks up the conversation
with cache reuse.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

log = logging.getLogger(__name__)


def _chat_ui_context(consultant_slug: str) -> str:
    """System-prompt override telling Claude the chat UI has already handled
    consultant selection. Prevents the root CLAUDE.md's master greeting from
    firing on every first turn.

    Also carries the attachment-inspection invariant — added after a real
    session reported "no floor plan" when 33 phone photos arrived (one was
    a phone-shot of a printed floor plan, but all were named IMG_XXXX.jpeg
    so a filename-only scan missed it). This is reinforced here, on every
    turn, because relying on shared/rules/workflow.md alone failed."""
    return (
        "You're being invoked from the team's browser chat UI, not the "
        "terminal launcher. The user has already chosen the consultant "
        f"'{consultant_slug}' from a dropdown and given their name; treat "
        "that as a settled fact. Do NOT run the root CLAUDE.md greeting "
        "flow that asks 'Hi! Which Property Sales Consultant is this "
        "listing for?' and lists all seven consultants — that flow only "
        "applies to terminal-launched sessions and does not apply here. "
        f"Operate directly as {consultant_slug} per "
        f"consultants/{consultant_slug}/CLAUDE.md and respond to the "
        "user's message. If their first message is a casual greeting "
        "like 'hi', respond briefly in this consultant's voice — don't "
        "kick straight into Phase 1 of the workflow until they actually "
        "ask for a listing. "
        ""
        "ATTACHMENT INVARIANT — non-negotiable: if the user's message "
        "starts with a `📎 Attached N file(s)` header, you MUST use the "
        "Read tool to open EVERY file in the list before answering ANY "
        "question about what was sent. Phone cameras name floor plans, "
        "contracts, and property photos identically (IMG_XXXX.jpeg), so "
        "classifying by filename alone is wrong and has caused real "
        "failures — 'no floor plan yet' answered when the floor plan was "
        "in the batch as IMG_4001.jpeg. After opening each file, classify "
        "by visual content: interior photo, exterior photo, aerial shot, "
        "floor plan (line drawing OR phone-shot of a printed plan), "
        "contract/legal page, or other. Then summarise back with explicit "
        "counts AND name any floor plan's actual filename. If the user "
        "later asks 'is there X?' — re-open files if unsure; never answer "
        "from filename memory."
    )


@dataclass
class StreamEvent:
    """A single parsed event off claude's stream-json stdout."""

    kind: str  # 'init', 'text_delta', 'text_full', 'tool_use', 'tool_result',
               # 'rate_limit', 'turn_summary', 'result', 'error', 'raw'
    raw: dict[str, Any] = field(repr=False)
    session_id: str | None = None
    # Populated for kind in {'text_delta', 'text_full'}
    text: str | None = None
    # Populated for kind='result'
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None
    total_cost_usd: float | None = None
    is_error: bool = False
    error_message: str | None = None


@dataclass
class StreamSummary:
    """Aggregate stats produced after the subprocess exits."""

    session_id: str | None = None
    return_code: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_cost_usd: float = 0.0
    is_error: bool = False
    error_message: str | None = None
    stderr_tail: str = ""


async def stream_message(
    *,
    user_message: str,
    consultant_folder: Path,
    resume_session_id: str | None = None,
    claude_bin: str = "claude",
) -> AsyncIterator[StreamEvent | StreamSummary]:
    """Async-iterate claude's stream-json events for one user turn.

    Yields zero or more :class:`StreamEvent`s followed by exactly one
    :class:`StreamSummary` once the subprocess exits.
    """
    # The consultant folder is the *only* directory Claude can write
    # freely. Shared rules and the outputs/ tree are also needed at
    # read/write time — `shared/` for the workflow/security/writing
    # rule docs, `outputs/` for the Phase 5 Word document. The deny
    # rules in .claude/settings.json still block edits to shared/.
    project_root = consultant_folder.parent.parent
    shared_dir = project_root / "shared"
    outputs_dir = project_root / "outputs"
    # Empty MCP config + --strict-mcp-config disables ALL MCP servers
    # for this subprocess. Without these two flags, the host's global
    # MCP config (Docusign / Gmail / Google Calendar / Google Drive /
    # Supabase, etc. — whatever the user has configured in Claude
    # Desktop or Claude Code at the user level) leaks into the chat
    # stream as "tool-permission prompts" that the WebSocket has no
    # surface to render. Result in today's session: the user typed
    # "what happen?" twice because the chat went silent while these
    # prompts piled up off-screen. We don't need any MCP servers for
    # the listing workflow — local file ops via Read/Write/Bash plus
    # the VaultRE CLI wrapper cover everything.
    empty_mcp_config = (
        project_root / "services" / "backend" / "config" / "empty-mcp.json"
    )

    args = [
        claude_bin,
        "--print",
        "--output-format", "stream-json",
        "--input-format", "text",
        "--include-partial-messages",
        "--verbose",
        "--add-dir", str(consultant_folder),
        "--add-dir", str(shared_dir),
        "--add-dir", str(outputs_dir),
        # Chat-UI environment: there is no surface to display per-tool
        # permission prompts (the WebSocket protocol doesn't carry them).
        # `bypassPermissions` auto-approves all tools EXCEPT what's in
        # the project's `.claude/settings.json` deny list — so rm -rf,
        # `git push`, writes to `shared/`, etc. are still blocked.
        # That deny list IS the safety net here; it gets to do the work
        # the interactive prompt would've done.
        "--permission-mode", "bypassPermissions",
        # Suppress all MCP servers in this subprocess (see comment above
        # the empty_mcp_config Path). --strict-mcp-config forces the CLI
        # to ignore user/system MCP config and use only what --mcp-config
        # provides, which is an empty {"mcpServers": {}}.
        "--strict-mcp-config",
        "--mcp-config", str(empty_mcp_config),
        # Tell Claude the chat UI already did consultant selection, so it
        # skips the master CLAUDE.md greeting that asks the user to pick
        # one of seven consultants. Without this the first turn is always
        # noise.
        "--append-system-prompt", _chat_ui_context(consultant_folder.name),
    ]
    if resume_session_id:
        args.extend(["--resume", resume_session_id])

    log.info("spawning: %s", shlex.join(args))

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(consultant_folder),
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None

    proc.stdin.write(user_message.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    summary = StreamSummary()

    try:
        async for raw_line in proc.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                log.warning("non-JSON line from claude: %r", line[:200])
                continue
            event = _parse(obj)
            if event.session_id and not summary.session_id:
                summary.session_id = event.session_id
            if event.kind == "result":
                summary.input_tokens = event.input_tokens or 0
                summary.output_tokens = event.output_tokens or 0
                summary.cache_creation_tokens = event.cache_creation_tokens or 0
                summary.cache_read_tokens = event.cache_read_tokens or 0
                summary.total_cost_usd = event.total_cost_usd or 0.0
                summary.is_error = event.is_error
                summary.error_message = event.error_message
            yield event
    finally:
        rc = await proc.wait()
        stderr_bytes = await proc.stderr.read()
        summary.return_code = rc
        summary.stderr_tail = stderr_bytes.decode("utf-8", "replace")[-2000:]
        if rc != 0 and not summary.is_error:
            summary.is_error = True
            summary.error_message = (
                summary.error_message or f"claude exited with code {rc}"
            )
        yield summary


def _parse(obj: dict[str, Any]) -> StreamEvent:
    kind = obj.get("type") or "raw"
    sid = obj.get("session_id")
    ev = StreamEvent(kind="raw", raw=obj, session_id=sid)

    if kind == "system":
        subtype = obj.get("subtype")
        if subtype == "init":
            ev.kind = "init"
        elif subtype == "post_turn_summary":
            ev.kind = "turn_summary"
        else:
            ev.kind = f"system:{subtype or 'unknown'}"
        return ev

    if kind == "rate_limit_event":
        ev.kind = "rate_limit"
        return ev

    if kind == "assistant":
        # --include-partial-messages emits incremental chunks AND a final full
        # message. Both arrive as "assistant" events; partials have
        # stop_reason=None.
        msg = obj.get("message") or {}
        for block in msg.get("content") or []:
            if block.get("type") == "text":
                ev.text = block.get("text", "")
                break
        ev.kind = "text_delta" if msg.get("stop_reason") is None else "text_full"
        return ev

    if kind == "tool_use" or kind == "tool_result":
        ev.kind = kind
        return ev

    if kind == "result":
        ev.kind = "result"
        usage = obj.get("usage") or {}
        ev.input_tokens = usage.get("input_tokens")
        ev.output_tokens = usage.get("output_tokens")
        ev.cache_creation_tokens = usage.get("cache_creation_input_tokens")
        ev.cache_read_tokens = usage.get("cache_read_input_tokens")
        ev.total_cost_usd = obj.get("total_cost_usd")
        ev.is_error = bool(obj.get("is_error"))
        if ev.is_error:
            ev.error_message = (
                obj.get("api_error_status")
                or obj.get("result")
                or "claude reported an error"
            )
        return ev

    if kind == "error":
        ev.kind = "error"
        ev.is_error = True
        ev.error_message = obj.get("message") or json.dumps(obj)[:200]
        return ev

    return ev  # kind='raw' fallback
