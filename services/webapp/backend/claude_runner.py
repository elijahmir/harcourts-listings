"""Subprocess wrapper for the local ``claude`` CLI.

Spawns ``claude --print --output-format stream-json --include-partial-messages``
per user message, streams the events out as Python objects, and yields a final
summary with tokens and cost so the frontend can show usage and the backend
can update ``listing_generator.sessions.total_*_tokens``.

Why per-message and not per-session?

* Stateless, restart-safe: the backend can be killed at any time without
  orphaning long-lived subprocesses.
* claude itself persists session history at ``~/.claude/projects/.../{id}.jsonl``;
  passing ``--resume {session_id}`` on the second message picks up the full
  context with cache reuse, so cost stays low after the first turn.
* Simpler error semantics: each call returns or raises; no zombie processes.

If profiling later shows the per-turn cold-start matters, swap this for a
long-lived per-session worker.
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

CLAUDE_BIN = "claude"  # resolved via PATH; install-host.sh ensures /opt/homebrew/bin/claude


@dataclass
class StreamEvent:
    """A single parsed event off claude's stream-json stdout."""
    kind: str  # 'init', 'text_delta', 'text_full', 'tool_use', 'tool_result',
               # 'rate_limit', 'turn_summary', 'result', 'error', 'raw'
    raw: dict[str, Any] = field(repr=False)
    session_id: str | None = None
    # Populated for kind='text_delta' / 'text_full'
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
    claude_bin: str = CLAUDE_BIN,
) -> AsyncIterator[StreamEvent | StreamSummary]:
    """Async-iterate over claude's stream-json events for a single user turn.

    Yields zero or more ``StreamEvent``s followed by exactly one
    ``StreamSummary`` once the subprocess exits.
    """
    args = [
        claude_bin,
        "--print",
        "--output-format", "stream-json",
        "--input-format", "text",
        "--include-partial-messages",
        "--verbose",
        "--add-dir", str(consultant_folder),
        "--permission-mode", "acceptEdits",
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
                summary.error_message
                or f"claude exited with code {rc}"
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
        # message. Both arrive as "assistant" events; we detect partial by the
        # presence of stop_reason=None.
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
