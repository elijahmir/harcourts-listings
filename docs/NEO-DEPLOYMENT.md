# Mac Neo deployment notes — for Brad

> **One-line summary:** Pennys-MacBook-Neo (the Mac at `100.97.219.55` on
> your tailnet, hostname `pennys-macbook-neo.tail9cb076.ts.net`) is now
> serving the **CopyPro v2** backend that the live Sales App
> (`https://salesapp.hup.net.au`) talks to. Everything lives under
> **`/Users/eli`** — nothing else on the Mac is touched. SSH `eli@100.97.219.55`
> to look around.

---

## TL;DR — the bits that matter

| What | Where |
|---|---|
| **Public URL** the Sales App hits | `https://vertical-kangaroo-getaway.ngrok-free.dev` |
| **Backend code** | `/Users/eli/Documents/harcourts-listings/` |
| **Backend log** | `/tmp/harcourts-backend.log` |
| **ngrok log** | `/Users/eli/.local/log/ngrok.log` |
| **SQLite database** (chat history + token accounting) | `/Users/eli/Documents/harcourts-listings/data/listings.db` |
| **Generated Word docs / listing deliverables** | `/Users/eli/Documents/harcourts-listings/outputs/` |
| **Per-listing photo uploads + VaultRE images** | `/Users/eli/Documents/harcourts-listings/consultants/<slug>/sessions/session-*/` |

---

## What's running right now

Two long-lived processes under the `eli` user, both started by hand
(no launchd plist yet — see *Known gaps* below):

```
PID 38285  python -m uvicorn services.backend.app.main:app --host 0.0.0.0 --port 8787
PID 37822  ngrok http --domain=vertical-kangaroo-getaway.ngrok-free.dev 8787
```

- **uvicorn** is the FastAPI backend: it serves `/healthz`, `/api/*`,
  `/ws/chat`, and shells out to the `claude` CLI per chat turn. Listens
  on `*:8787`.
- **ngrok** is the free-tier tunnel that fronts the backend with a
  stable HTTPS URL. Holds an outbound TCP connection to Cloudflare-via-ngrok's
  edge; no inbound port-forwarding needed on your home router.

You can see them with:
```bash
ps -eo pid,user,command | grep -E "(uvicorn|ngrok http)" | grep -v grep
```

---

## What's installed on Neo (in `eli`'s home only)

Everything user-space — **no `sudo` was used, no system files touched,
no changes to `/opt/homebrew` (which is owned by `penny`)**.

### `/Users/eli/.local/bin/`
| Binary | What for |
|---|---|
| `uv` (47 MB) | Astral's Python toolchain. Used to install Python 3.12 in user-space. |
| `python3.12` (symlink) | → `/Users/eli/.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin/python3.12`. The Python the backend runs on. |
| `ngrok` (29 MB) | Tunnel client. |
| `cloudflared` (38 MB) | Cloudflare tunnel client. **Currently unused** — was installed as a backup before we picked ngrok. Safe to delete if you want the 38 MB back. |
| `uvx` | uv's runner — used occasionally for one-off Python tooling. |

### `/Users/eli/.local/share/uv/python/`
Portable Python 3.12.13 install (~150 MB). Used by the backend's
virtualenv at `~/Documents/harcourts-listings/services/backend/.venv/`.

### `~/.nvm/versions/node/v24.16.0/bin/claude`
The Claude CLI (Anthropic Code) v2.1.150. **Already on Neo before any of
this work** — was installed via nvm at some earlier point. Stays as-is.
Credentials at `~/.claude/.credentials.json`.

### `~/Library/Application Support/ngrok/ngrok.yml`
ngrok auth config. Contains the authtoken for the `eli`-owned free-tier
account. Do not share publicly.

---

## Configuration

### `.env` at the repo root (`/Users/eli/Documents/harcourts-listings/.env`)

**Contains secrets — never commit, never share, never paste in chat.**
Keys present (values intentionally not listed here):

```
VAULTRE_API_BASE          — VaultRE API base URL
VAULTRE_API_KEY           — VaultRE API key
VAULTRE_API_TOKEN         — VaultRE bearer token (read-only)
HARCOURTS_REQUIRE_AUTH    — set to "true" (prod mode; backend enforces Supabase JWT)
HARCOURTS_SUPABASE_JWT_SECRET — Supabase project's JWT signing secret (HS256)
HARCOURTS_CLAUDE_BIN      — absolute path to claude CLI (nvm-installed)
```

> **Known quirk:** `HARCOURTS_SUPABASE_JWT_SECRET` is listed twice. Both
> values are the same so behaviour is identical; cosmetic dedup can be done
> with a manual edit later.

> **`.env.bak`** is a `sed` backup from when I flipped `HARCOURTS_REQUIRE_AUTH=false → true`.
> Safe to delete (`rm .env.bak`).

### CORS allow-list (in `services/backend/app/main.py`)
Browsers from these origins can hit the backend:
- `localhost` / `127.0.0.1` (any port)
- RFC1918 private LAN IPs
- Tailscale CGNAT range (`100.64.0.0/10`)
- `*.tail*.ts.net` (Tailscale MagicDNS hostnames)
- `*.vercel.app` (Vercel preview deploys)
- `*.hup.net.au` (the production Sales App at `salesapp.hup.net.au`)

---

## How the pieces connect

```
[ Teammate's browser, anywhere ]
            │
            │ HTTPS to https://salesapp.hup.net.au
            ▼
[ Vercel — HUP-Sales-App ]
            │
            │ HTTPS fetch + WSS to https://vertical-kangaroo-getaway.ngrok-free.dev
            ▼
[ ngrok edge ]
            │
            │ private long-lived TCP connection
            ▼
[ ngrok agent on Neo, PID 37822 ]
            │
            │ localhost:8787
            ▼
[ uvicorn on Neo, PID 38285 ]
            │
            │ spawn subprocess per chat turn
            ▼
[ claude CLI, PID transient ]
            │
            │ HTTPS to api.anthropic.com
            ▼
[ Anthropic's Claude API ]
```

Auth gating: every request to `/api/*` and `/ws/chat` must carry a valid
Supabase JWT in the `Authorization: Bearer <jwt>` header. JWTs come from
the user's Supabase login on the Sales App. The backend verifies the
signature against `HARCOURTS_SUPABASE_JWT_SECRET`. No JWT → HTTP 401.
The only public endpoint is `/healthz` (used by the Sales App to fetch
the consultant list).

---

## What should NOT be touched

These will break the live Sales App for everyone:

1. **Don't stop / kill / restart these processes** without coordinating:
   - PID 38285 (uvicorn on :8787) → backend dies, all chats fail
   - PID 37822 (ngrok) → public URL goes down, Sales App can't reach backend
   - If you must restart, see *Restarting* below.

2. **Don't edit `/Users/eli/Documents/harcourts-listings/.env`** — it
   holds production secrets. Editing while the backend is running has no
   immediate effect (env is read once at startup), but next restart
   you'd inherit your changes.

3. **Don't delete `/Users/eli/Documents/harcourts-listings/data/listings.db`**
   — that's the chat history + token accounting database. Every
   conversation teammates have had is in there.

4. **Don't delete files under `consultants/*/sessions/session-*/`** —
   those are the per-listing photo uploads + VaultRE-pulled images that
   sessions are still actively referencing.

5. **Don't delete files in `outputs/`** — those are Word documents
   generated for teammates. The Sales App download links point at them
   by filename.

6. **Don't run `git push` from this repo on Neo** — Neo is a pull-only
   replica. Pushes happen from the dev Mac.

7. **Don't run `claude login` or change `~/.claude/.credentials.json`**
   — the backend's claude CLI subprocess is authed against the existing
   Anthropic session. Re-logging in would interrupt active chats.

---

## What IS safe to do

- **Read** any file under `/Users/eli/Documents/harcourts-listings/`
  (the code, the docs, the logs). Nothing sensitive in the code itself.
- **Tail the logs** to see what's happening live:
  ```bash
  tail -f /tmp/harcourts-backend.log         # backend
  tail -f /Users/eli/.local/log/ngrok.log    # tunnel
  ```
- **Query the SQLite** read-only:
  ```bash
  sqlite3 -readonly ~/Documents/harcourts-listings/data/listings.db \
    "SELECT consultant_slug, count(*) FROM sessions GROUP BY consultant_slug"
  ```
- **Check tunnel state**:
  ```bash
  curl -s http://127.0.0.1:4040/api/tunnels | python3 -m json.tool
  ```
- **Reboot the Mac if you need to** — but the services don't auto-start
  (no launchd plist yet), so I'll need to SSH in and restart them.
  Just tell me afterwards.

---

## Restarting (if Neo reboots or something hangs)

**Backend**:
```bash
cd ~/Documents/harcourts-listings
./scripts/start-backend.sh
```

**ngrok tunnel** (run manually for now):
```bash
nohup ~/.local/bin/ngrok http \
  --domain=vertical-kangaroo-getaway.ngrok-free.dev \
  --log=/Users/eli/.local/log/ngrok.log \
  --log-format=logfmt --log-level=info \
  8787 > /dev/null 2>&1 &
disown
```

Verify after both are up:
```bash
curl -sf https://vertical-kangaroo-getaway.ngrok-free.dev/healthz | python3 -m json.tool
```
Should return a JSON object with `"ok": true` and the list of consultants.

---

## Known gaps / future improvements

- **No launchd plist** for either service yet. If Neo reboots they don't
  come back automatically. Adding a system-level `LaunchDaemon` would
  fix this but needs `sudo`. Acceptable for now since Neo is presumably
  a long-lived server.
- **ngrok free-tier limits** (~40 connections/min). With a team of
  5–10 active users it's fine. If we hit ngrok's rate limit, we'd see
  `ERR_NGROK_3200` in the logs and the Sales App would intermittently
  fail. Upgrade path: ngrok paid ($8/mo) or Cloudflare Tunnel with a
  domain on Cloudflare DNS.
- **Single point of failure**: if Neo's internet drops or the Mac
  sleeps, the Sales App can't reach the backend. The Sales App will
  show a "Reconnect" badge and retry.
- **No off-Mac backup of `listings.db`**. If Neo's disk dies, chat
  history + token accounting are lost. Worth setting up a periodic
  rsync to another box.
- **`.env` duplicate `HARCOURTS_SUPABASE_JWT_SECRET`** (cosmetic).

---

## If you see something weird

Ping Elijah. Don't kill processes you don't recognise; everything
unfamiliar under `eli`'s home is part of this stack.

Quick triage commands:

```bash
# is the backend up?
curl -sf http://127.0.0.1:8787/healthz | head -3

# is the tunnel up?
curl -sf https://vertical-kangaroo-getaway.ngrok-free.dev/healthz | head -3

# is anything failing recently?
tail -50 /tmp/harcourts-backend.log

# is ngrok hitting rate limits?
grep -i "error\|warn\|rate" /Users/eli/.local/log/ngrok.log | tail -20
```
