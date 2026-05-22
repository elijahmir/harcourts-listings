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
| WS | `/ws/chat` | One user-turn per `user_message` frame; streams events back |

### WebSocket protocol

**Client → Server**

```json
{
  "type": "user_message",
  "consultant_slug": "wendy-squibb",
  "user_name": "Sarah",
  "content": "Start a listing for 12 Smith St",
  "claude_session_id": null
}
```

`user_name` is for display/audit only — there is no authentication. `claude_session_id` is `null` on the first turn and set to the value returned in the previous `done` event on subsequent turns (lets Claude warm-cache the conversation).

**Server → Client**

```json
{"type": "ready"}
{"type": "chunk", "kind": "text_delta", "text": "...", "session_id": "..."}
{"type": "chunk", "kind": "tool_use", "text": null, "session_id": "..."}
{"type": "done", "claude_session_id": "...", "tokens": {...}, "cost_usd": 0.0, "return_code": 0, "is_error": false, "error_message": null}
{"type": "error", "message": "..."}
```

`chunk.kind` is one of `init | text_delta | text_full | tool_use | tool_result | rate_limit | turn_summary | result | error | raw`. For a polished chat UI you can ignore everything except `text_delta` / `text_full` (incremental and final assistant text).

## Quick smoke test

With the server running, in another terminal:

```bash
python3 - <<'PY'
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:3000/ws/chat") as ws:
        print(await ws.recv())  # {"type": "ready"}
        await ws.send(json.dumps({
            "type": "user_message",
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

(Requires `pip install websockets` in your venv.)

## Deploying on the office Mac

Will be done via `launchctl` once the frontend ships. For now, run it under `tmux` or just leave a Terminal tab open. Tailscale handles reachability from teammates' devices.

## What's NOT here yet

- Persistence (SQLite for sessions/messages/learnings)
- File upload endpoint
- Frontend integration
- launchd service plist

All tracked in the rebuild ROADMAP.
