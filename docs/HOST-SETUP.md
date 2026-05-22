# Host Setup

End-to-end setup for a fresh Mac. Designed so a human OR a Claude Code agent reading this file can complete the whole thing top-to-bottom without external context. Every step lists the exact command, the expected outcome, and what to do if it doesn't.

> **TL;DR for someone who's done this before:** `git clone`, `./scripts/install.sh`, `claude login`, paste four lines into `.claude/settings.json`, `./scripts/install.sh launchd`, optional Tailscale, done.

---

## 1. Prereqs

Required on the host Mac before step 2:

- **macOS 13 or newer**
- **Homebrew** — installer at https://brew.sh if missing.
- **Python 3.11+** — install via `brew install python@3.12` if `python3.12 --version` doesn't work.
- **Node.js 20+ and npm** — `brew install node`.
- **git** — comes with Xcode CLT (`xcode-select --install` if needed).
- **Claude Code CLI** — the standalone one, not the version bundled inside Claude Desktop. Install from <https://docs.claude.com/en/docs/claude-code/setup>. Verify with `claude --version` (should print something like `2.1.x (Claude Code)`).

You can verify all of the above in one command after step 2:

```bash
./scripts/install.sh check
```

It prints a green/yellow/red line per prereq.

---

## 2. Clone the repo

Pick a path **outside** `~/Documents`, `~/Desktop`, and `~/Downloads` — macOS TCC blocks launchd-spawned processes from reading those without Full Disk Access per binary. `~/code/`, `~/work/`, or `~/Applications/` are fine.

```bash
mkdir -p ~/code && cd ~/code
git clone <REPO_URL> harcourts-listings
cd harcourts-listings
```

---

## 3. Run the bootstrap

One command does everything that can be scripted:

```bash
./scripts/install.sh
```

What it does:

1. Runs the preflight check.
2. Copies `.env.example` → `.env` if `.env` is missing (you'll edit it in step 7 if you have real VaultRE credentials).
3. Creates `data/` and `outputs/` directories.
4. Builds the backend venv at `services/backend/.venv` and `pip install -r requirements.txt`.
5. Runs `npm install` in `apps/web/`.
6. Builds the frontend production bundle (`npm run build` → `.next/`).
7. Prints the post-install checklist.

Re-running is safe — every step is idempotent. Re-run after a `git pull` to update deps and rebuild.

---

## 4. Sign in to Claude on this Mac

The chat agent runs by spawning the local `claude` CLI per turn. The CLI uses whichever Anthropic account is signed in.

```bash
claude login
```

A browser window opens. Use the **same Anthropic account** as the dev Mac (both are covered by the shared Max plan). You only do this once — the login persists in `~/.claude/`.

Verify:

```bash
claude --version
```

If you see the version string, you're good.

---

## 5. Approve the four extra Bash patterns in `.claude/settings.json`

The chat agent needs to be able to `mv`/`cp`/`ls`/`cat` files within the `consultants/` tree so it can route uploads into the right `knowledge/` subfolder when staff ask it to.

Open `.claude/settings.json` and add these four lines to the `permissions.allow` array (anywhere in that list):

```json
"Bash(mv ./consultants/**)",
"Bash(cp ./consultants/**)",
"Bash(ls ./consultants/**)",
"Bash(cat ./consultants/**)"
```

Result: the array looks like (other entries omitted for brevity):

```json
{
  "permissions": {
    "allow": [
      "Read(./consultants/**)",
      "Write(./consultants/**)",
      "Edit(./consultants/**)",
      "Bash(mkdir -p ./consultants/**)",
      "Bash(mv ./consultants/**)",
      "Bash(cp ./consultants/**)",
      "Bash(ls ./consultants/**)",
      "Bash(cat ./consultants/**)",
      "..."
    ],
    "deny": ["..."]
  }
}
```

This is the only manual edit to `settings.json` required. Without it, the chat-driven file routing flow (e.g. "Wendy, save this docx for future tone reference") falls back to telling the user to do it by hand.

---

## 6. Auto-start on boot (recommended)

Install the two launchd services so the backend (port 3000) and frontend (port 3010) come up automatically on every boot and restart on crash:

```bash
./scripts/install.sh launchd
```

This writes `~/Library/LaunchAgents/com.harcourts.{backend,web}.plist` and loads them. Logs go to `/tmp/harcourts-backend.log` and `/tmp/harcourts-web.log`.

Verify both came up:

```bash
sleep 4
curl -s http://127.0.0.1:3000/healthz | python3 -m json.tool   # backend
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3010/  # frontend (200 = good)
```

If something's broken: `tail -50 /tmp/harcourts-backend.log` or `/tmp/harcourts-web.log` will show the error. Restart with `./scripts/install.sh restart`.

---

## 7. (If you have real VaultRE keys) Update `.env`

Open `.env` (NOT `.env.example`) and paste in the actual `VAULTRE_API_KEY` and `VAULTRE_API_TOKEN` values. The VaultRE integration is roadmapped but the values being present doesn't break anything if it's not used yet.

Restart the backend so it picks up new env values:

```bash
./scripts/install.sh restart
```

---

## 8. Remote access via Tailscale Funnel (so teammates' phones can reach the chat)

Without Tailscale: only devices on the office Wi-Fi can hit `http://192.168.x.x:3010`. To let teammates connect from anywhere:

```bash
brew install tailscale
sudo brew services start tailscale
tailscale up           # opens a browser for first-time auth
tailscale funnel 3010  # exposes :3010 as https://harcourts-mac.tail-xxxxxx.ts.net
```

The funnel URL is public HTTPS (Tailscale handles certificates). Anyone with that URL can open the chat — that's intentional and matches the original "Tailscale perimeter = trust boundary" design. The chat itself has no per-user authentication; identity is captured by the "what's your name?" prompt on first visit.

To stop publishing the funnel: `tailscale funnel reset`.

---

## 9. Smoke test the whole stack

From the host Mac (or any device on the funnel URL):

1. Open `http://localhost:3010` (or the funnel URL).
2. Enter your name when prompted — saved to `localStorage` once.
3. Pick a consultant from the dropdown. The list comes from the on-disk `consultants/` folder.
4. Send "hi" — Wendy (or whoever is selected) should greet you in her voice (not the old "Hi! Which Property Sales Consultant…" master greeting).
5. Click 📎, pick a small file, send a message — your bubble should show the attachment header.
6. Click "History" in the header — should list past sessions for the selected consultant.
7. Click "New" — fresh chat; the previous session is preserved in History.

If any step fails, check the relevant log:

| Symptom | Where to look |
|---|---|
| Frontend won't load | `tail -50 /tmp/harcourts-web.log`; check port 3010 isn't already in use |
| Chat won't connect (red dot in header) | `tail -50 /tmp/harcourts-backend.log` |
| Wendy says "I need permission to…" | Confirm step 5 (the four Bash entries) is done |
| Wendy greets with all seven consultant names | The `--append-system-prompt` override wasn't picked up; restart with `./scripts/install.sh restart` |
| File appeared in `photos/` but Wendy didn't acknowledge | The `📎 Attached` header is in the user message — confirm it's visible in the user's bubble before her reply |

---

## What's running where

Once steps 1–6 are done:

| Service | Port | Logs | How to restart |
|---|---|---|---|
| `com.harcourts.backend` (FastAPI + WS) | `0.0.0.0:3000` | `/tmp/harcourts-backend.log` | `launchctl unload && load` of the plist, or `./scripts/install.sh restart` |
| `com.harcourts.web` (Next.js prod build) | `0.0.0.0:3010` | `/tmp/harcourts-web.log` | same |

The data:

| Path | Contents |
|---|---|
| `consultants/{slug}/knowledge/` | brand-guide.md, voice-rules.md, learnings.md — every session reads these |
| `consultants/{slug}/sessions/session-XXXXXXXX/` | per-chat session: `photos/` of attachments |
| `data/listings.db` | SQLite — every session, message, learning. Inspect with `sqlite3 data/listings.db` |
| `outputs/` | Generated Word documents from Phase 5 |
| `/tmp/harcourts-*.log` | Service logs (purged on reboot — copy out if you need them for debugging) |

---

## Updating the system

When you `git pull` to update:

```bash
git pull
./scripts/install.sh         # picks up new deps + rebuilds frontend
./scripts/install.sh restart # bounce the services
```

Total downtime: about 10 seconds.

---

## Uninstalling

```bash
./scripts/install.sh uninstall   # stops services + removes plists
```

The repo and `data/` are untouched — delete those manually if you want a full wipe.

---

## For a Claude agent reading this autonomously

If you've been asked to set up this system on a fresh Mac:

1. Confirm you're at the project root: `pwd` should end in `harcourts-listings`.
2. Run `./scripts/install.sh check` — read the output, install any RED prereqs via the suggested `brew install` lines.
3. Run `./scripts/install.sh` — wait for it to finish (1–3 minutes).
4. Tell the user: "I've finished the scripted bootstrap. Three things need a human: (a) run `claude login` to sign in, (b) edit `.claude/settings.json` to add four Bash patterns — I'll paste them — (c) decide whether to install launchd auto-start and/or Tailscale Funnel."
5. Paste the four `Bash(...)` lines from step 5 above. Wait for confirmation.
6. After confirmation, run `./scripts/install.sh launchd` if the user wants auto-start.
7. Run the smoke-test commands from step 9 and report results.
