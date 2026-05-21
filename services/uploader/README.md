# Harcourts uploader

A tiny FastAPI service that lets staff upload property photos and floor plans from a phone or laptop straight into the active listing session on the host Mac. Sits behind Tailscale, so no auth layer of its own — the network handles identity.

## What it does

- `GET /` — pick a consultant + session, then continue to the upload page.
- `GET /u/{slug}/{session}` — the upload page (mobile-friendly).
- `POST /u/{slug}/{session}` — accepts multipart uploads. Each file lands in `consultants/{slug}/sessions/{session}/photos/` with a timestamped, sanitised filename.
- `GET /healthz` — liveness check.

The chat (Claude Code) creates the session folder during Phase 1 of the workflow. The uploader will not accept files for a session that does not exist yet — it returns a clear error pointing back at the chat.

## How Claude knows the URL

`scripts/create-listing.sh` exports `HARCOURTS_UPLOADER_BASE_URL` into the environment. The listing workflow ([shared/rules/workflow.md](../../shared/rules/workflow.md)) tells the assistant to construct `${HARCOURTS_UPLOADER_BASE_URL}/u/{slug}/{session}` and offer that link to the user in Phase 1.

## Running it locally

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run pointing at the repo root
HARCOURTS_PROJECT_ROOT="$(cd ../.. && pwd)" python server.py
```

The server binds `0.0.0.0:8080` by default (override with `HARCOURTS_UPLOADER_HOST` / `HARCOURTS_UPLOADER_PORT`).

## Smoke test

```
# create a stub session in your repo
mkdir -p consultants/wendy-squibb/sessions/2026-05-21_test

# upload a file
curl -F "files=@/path/to/photo.jpg" \
  http://localhost:8080/u/wendy-squibb/2026-05-21_test
```

Expected: JSON with `ok: true` and the saved relative path.

## Running it as a service on the Mac

`launchd/com.harcourts.uploader.plist` is a LaunchAgent that keeps the uploader running. Copy it to `~/Library/LaunchAgents/`, edit the paths inside to match your install, and load it:

```
launchctl load ~/Library/LaunchAgents/com.harcourts.uploader.plist
```

Logs go to `services/uploader/uploader.log` (relative to the project root).

## What lives here

- `server.py` — the FastAPI application
- `static/` — the picker page, the upload page, and shared CSS
- `requirements.txt` — pinned-minimum versions
- `launchd/` — macOS LaunchAgent plist
