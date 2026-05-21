# Webapp backend

FastAPI app that hosts the chat UI for the Harcourts listing generator. Spawns `claude --print --output-format stream-json` per session and streams output to browsers over WebSocket. Uses Supabase (HUP Database) for auth and metadata; uploaded files stay on the Mac filesystem under `consultants/{slug}/sessions/{session}/photos/`.

## Layout

```
services/webapp/backend/
├── app.py                 FastAPI entry point and router registration
├── config.py              Pydantic-Settings, loads from project-root .env
├── auth.py                Bearer-JWT verification (supabase.auth.get_user)
├── db.py                  service_client (service-role) + user_client (RLS)
├── claude_runner.py       (milestone 3b) subprocess wrapper for claude --print
├── routes/
│   ├── consultants.py     GET /api/consultants
│   ├── sessions.py        GET/POST/GET /api/sessions
│   ├── messages.py        (milestone 3c) GET /api/sessions/{id}/messages
│   ├── uploads.py         (milestone 3d) POST /api/sessions/{id}/upload, GET /media
│   └── ws.py              (milestone 3c) WS /ws/sessions/{id}
└── requirements.txt
```

## Running locally

```sh
cd services/webapp/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# From the project root (so .env is found)
cd ../../..
python -m services.webapp.backend.app
```

The server binds `0.0.0.0:3000` by default. Override via `WEBAPP_HOST` / `WEBAPP_PORT` env vars.

## Smoke test

```sh
curl -fsS http://localhost:3000/healthz
# expect { "ok": true, "service": "webapp", ... }

curl -fsS http://localhost:3000/api/consultants \
  -H "Authorization: Bearer $YOUR_USER_JWT"
# expect a list of 7 consultants
```

## Configuration

All runtime config lives in the project-root `.env` (gitignored). Required keys:

| Key | Notes |
| --- | --- |
| `SUPABASE_URL` | HUP Database project URL |
| `SUPABASE_PUBLISHABLE_KEY` | `sb_publishable_...` for the user client |
| `SUPABASE_SERVICE_ROLE_KEY` | Service-role JWT. **Never** ship to the frontend. |
| `WEBAPP_HOST` | Default `0.0.0.0` (Tailnet-reachable) |
| `WEBAPP_PORT` | Default `3000` |

## Auth flow

1. Frontend signs the user in with Supabase Auth (Azure SSO).
2. Frontend stores the access token and sends it as `Authorization: Bearer <jwt>` on every request.
3. Backend's `require_user` dependency validates the token via `supabase.auth.get_user(token)`, caches the result for 60 seconds, and yields an `AuthUser`.
4. Service-role client is used for all DB writes; RLS is the second line of defence.
