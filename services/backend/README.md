# Harcourts Backend

FastAPI service that brokers chat between teammates and the Claude Code CLI. Auth happens at the network layer (Tailscale) — this service has no per-user sign-in by design.

The Claude work is done by spawning the local `claude` CLI as a subprocess, which uses the office Mac's signed-in Claude Max subscription. **No Anthropic API key is involved.**

## Requirements

- Python 3.11+
- `claude` CLI on PATH, signed into the team's Claude Max account
- The repo checked out so `consultants/`, `shared/`, and `outputs/` are siblings of `services/`

## First-time setup

```bash
cd services/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
./scripts/dev.sh
```

Defaults to `http://127.0.0.1:3000`. Override with `HOST=0.0.0.0 PORT=4000 ./scripts/dev.sh`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Liveness; returns known consultant slugs |
| GET | `/docs` | OpenAPI Swagger UI |
| GET | `/api/sessions` | List recent sessions; `?consultant_slug=...` filter optional |
| GET | `/api/sessions/{id}/messages` | Replay a session's persisted messages |
| POST | `/api/sessions/{id}/upload` | Multipart photo / floor-plan upload |
| DELETE | `/api/sessions/{id}/uploads` | Wipe a session's photos folder |
| POST | `/api/learnings` | Append a voice rule to a consultant's `learnings.md` |
| GET | `/api/learnings/{consultant_slug}` | Audit list of saved rules |
| WS | `/ws/chat` | Streaming chat; persists messages + token totals to SQLite |

### WebSocket protocol

**Client → Server**

```json
{
  "type": "user_message",
  "session_id": null,
  "consultant_slug": "wendy-squibb",
  "user_name": "Sarah",
  "content": "Start a listing for 12 Smith St",
  "claude_session_id": null
}
```

`session_id` is `null` on the first turn; the server creates the row and echoes the id back in `done`. `claude_session_id` is `null` on the first turn and set to the previous `done` value on subsequent turns so Claude warm-caches.

**Server → Client**

```json
{"type": "ready"}
{"type": "chunk", "kind": "text_delta", "text": "...", "session_id": "..."}
{"type": "done", "session_id": "...", "claude_session_id": "...",
 "tokens": {...}, "cost_usd": 0.0, "return_code": 0,
 "is_error": false, "error_message": null}
{"type": "error", "message": "..."}
```

`chunk.kind` is one of `init | text_delta | text_full | tool_use | tool_result | rate_limit | turn_summary | result | error | raw`. For a polished chat UI you can ignore everything except `text_delta` / `text_full` (incremental and final assistant text).

## Persistence

- **SQLite** at `data/listings.db` (path overridable via `HARCOURTS_DATA_DIR`). Three tables: `sessions`, `messages`, `learnings`. Schema is created idempotently on startup.
- **Photos / floor plans** land under `consultants/{slug}/sessions/session-{short-id}/photos/` so the existing CLAUDE.md workflow can pick them up via the agent's `Read` tool.
- **Voice rules** are appended to `consultants/{slug}/knowledge/learnings.md` — the same markdown file the consultant's CLAUDE.md already reads at the start of every session.

The DB file is the team's audit trail. The markdown is the agent's behaviour file. Both are updated atomically on every save.

## Quick smoke test

With the server running, in another terminal:

```bash
python3 - <<'PY'
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:3000/ws/chat") as ws:
        print(await ws.recv())  # ready
        await ws.send(json.dumps({
            "type": "user_message",
            "session_id": None,
            "consultant_slug": "wendy-squibb",
            "user_name": "smoke-test",
            "content": "Say 'hi' in one word."
        }))
        while True:
            frame = json.loads(await ws.recv())
            print(frame.get("type"), frame.get("kind"), (frame.get("text") or "")[:60])
            if frame["type"] in ("done", "error"):
                break

asyncio.run(main())
PY
```

(Requires `pip install websockets`.)

## Deploying on the office Mac

Wrap `./scripts/dev.sh` in a launchd plist so the backend auto-starts on boot. Not done yet — tracked as a follow-up. For now, run it under `tmux` or leave a Terminal tab open. Tailscale handles reachability from teammates' devices.

## Configuration

Env vars (all optional):

| Var | Default | Notes |
|---|---|---|
| `HARCOURTS_PROJECT_ROOT` | Auto-detect (`../../..` from this file) | Where `consultants/` lives |
| `HARCOURTS_DATA_DIR` | `{project_root}/data` | SQLite + future runtime artefacts |
| `HARCOURTS_BACKEND_HOST` | `127.0.0.1` | Use `0.0.0.0` on the office Mac to expose via Tailscale |
| `HARCOURTS_BACKEND_PORT` | `3000` | — |
| `HARCOURTS_CLAUDE_BIN` | `claude` | Path to the CLI |
| `HARCOURTS_MAX_UPLOAD_BYTES` | `26214400` (25 MB) | Per-file size cap |
