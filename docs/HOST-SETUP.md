# Host Setup

End-to-end setup for a fresh Mac. Designed so a human OR a Claude Code agent reading this file can complete the whole thing top-to-bottom without external context. Every step lists the exact command, the expected outcome, and what to do if it doesn't.

> **TL;DR for someone who's done this before:** complete the [one-time tailnet bootstrap](#0-one-time-tailscale-tailnet-bootstrap-do-this-once-ever) (3 admin-console clicks) if not done, then on the host: `git clone`, `./scripts/install.sh`, `claude login`, paste four lines into `.claude/settings.json`, `./scripts/install.sh verify`, `./scripts/install.sh launchd`, `tailscale up --authkey=$TS_AUTHKEY`, `./scripts/install.sh funnel`, done. Teammates use the public HTTPS URL — no install on their devices.

---

## 0. One-time Tailscale tailnet bootstrap (do this once, ever)

**Read this even if you are Claude-on-Neo.** Three settings in the Tailscale admin console MUST be enabled before `./scripts/install.sh funnel` will succeed on any host. They are **tailnet-level, not node-level** — done once for the whole organization, persisting forever — but **two of them cannot be set via the Tailscale REST API**, because enabling HTTPS Certificates is a legal opt-in to having your `.ts.net` hostnames published in Let's Encrypt's public Certificate Transparency log. The CLI commands will fail with `"Serve is not enabled on your tailnet"` until these are done.

**If you are Claude reading this on Neo: STOP and ask the user to perform steps 0.1–0.3 in their browser before proceeding to step 1.** You cannot do these yourself. Don't try.

### 0.1 Enable MagicDNS and HTTPS Certificates

Open <https://login.tailscale.com/admin/dns>. Sign in as a tailnet Owner or Admin.

- Confirm **MagicDNS** is enabled (toggle at top).
- Scroll to **HTTPS Certificates** and click **Enable HTTPS** (accept the Let's Encrypt CT-log opt-in).

### 0.2 Grant Funnel capability via the ACL policy file

Open <https://login.tailscale.com/admin/acls/file>. Add this block at the top level of the JSON (alongside `acls`), then click **Save**:

```json
"nodeAttrs": [
  {
    "target": ["autogroup:member"],
    "attr":   ["funnel"]
  }
]
```

(If you have tagged hosts and prefer least-privilege, swap `autogroup:member` for the relevant `tag:` selector.)

### 0.3 (Optional but recommended) Generate a pre-auth key for unattended host bringup

For Neo and any future host where you want `tailscale up` to run via SSH without a browser prompt:

- Open <https://login.tailscale.com/admin/settings/keys>.
- Click **Generate auth key**. Make it **reusable** (if you'll add multiple hosts), **ephemeral=off**, and **pre-approved** if your tailnet requires device approval.
- Copy the resulting `tskey-auth-...` value.

Export it in the shell before running `install.sh` on the new host:

```bash
export TS_AUTHKEY=tskey-auth-XXXXXXXXXXXXX
```

Without this key, `tailscale up` prompts for a browser login on the host — fine when you're sitting at the machine, blocking when Claude is running it over SSH.

### Verify the bootstrap

From any host already on the tailnet:

```bash
tailscale funnel --bg --yes --set-path=/_probe 8787
tailscale funnel reset
```

If that runs silently and exits 0, the bootstrap is complete. If it prints `Serve is not enabled on your tailnet`, redo step 0.1.

---

## Trust model — what gets approved once, by whom

Before you start: **permissions in this system are per host Mac, not per user.** Setting up the production Mac once makes the chat work identically for every teammate — there is no per-session approval, no per-user policy, no in-chat "click Allow" dialog. The single source of trust is:

1. **The signed-in Anthropic account** on this Mac (one `claude login` covers it).
2. **`.claude/settings.json`** at the project root — allow/deny rules read by every spawned `claude` subprocess.
3. **`services/backend/app/runner.py`** — per-spawn flags (`--permission-mode bypassPermissions`, `--add-dir consultants/{slug}/`, `--add-dir shared/`, `--add-dir outputs/`).

The chat UI captures a "user name" in `localStorage` for audit attribution (so you can see who saved which voice rule), but Claude Code itself has no awareness of who's chatting. Every teammate's session goes through the same binary, same account, same settings, same flags.

This is the right architectural simplification for an office of 7–10 staff sharing one Claude Max plan, but worth being explicit: **anyone who can reach the chat URL has identical effective permissions.** The Tailscale Funnel URL (step 8) IS the access boundary; the `.claude/settings.json` deny list is the destructive-action safety net.

(Technical detail: the subprocess invokes `claude --print`, which per the Claude Code 2.1.x help text **skips the workspace trust dialog in non-interactive mode**. So even the one-time "do you trust this folder?" prompt that ordinarily fires on first `claude` invocation in a new directory is bypassed in our setup.)

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

## 6. Verify the chat permissions are in place

Run the one-shot verifier:

```bash
./scripts/install.sh verify
```

It spawns a minimal `claude --print` with the exact flags `runner.py` uses in production, sends a one-word prompt, and confirms the response is sane. Consumes ~10 tokens from your Claude Max plan.

Expected output:

```
==> Verify chat permissions
    using consultant: colin-tunn
    spawning a minimal `claude --print` to confirm everything's in place…
  ✓ claude responded cleanly. This Mac is ready.
```

If it fails, the script prints the most likely causes. Almost always it's missing `claude login` or missing settings.json entries.

---

## 7. Auto-start on boot (recommended)

Install the two launchd services so the backend (port 3000) and frontend (port 3010) come up automatically on every boot and restart on crash:

```bash
./scripts/install.sh launchd
```

This writes `~/Library/LaunchAgents/com.harcourts.{backend,web}.plist` and loads them. Logs go to `/tmp/harcourts-backend.log` and `/tmp/harcourts-web.log`.

Verify both came up:

```bash
sleep 4
curl -s http://127.0.0.1:8787/healthz | python3 -m json.tool   # backend
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3010/  # frontend (200 = good)
```

If something's broken: `tail -50 /tmp/harcourts-backend.log` or `/tmp/harcourts-web.log` will show the error. Restart with `./scripts/install.sh restart`.

---

## 8. (If you have real VaultRE keys) Update `.env`

Open `.env` (NOT `.env.example`) and paste in the actual `VAULTRE_API_KEY` and `VAULTRE_API_TOKEN` values. The VaultRE integration is roadmapped but the values being present doesn't break anything if it's not used yet.

Restart the backend so it picks up new env values:

```bash
./scripts/install.sh restart
```

---

## 9. Publish to teammates — Tailscale Funnel (required for production)

This is what teammates actually use. The Funnel URL is public HTTPS (Tailscale handles certificates) and **requires nothing installed on their phones/laptops** — they just open the URL in a browser. Anyone who has the URL can use the chat; trust is bounded by URL secrecy + the `.claude/settings.json` deny list.

### 9a. Install Tailscale CLI on the host Mac

Pick one:

```bash
# Option A — brew (preferred if you don't already have the App Store version)
brew install tailscale
sudo brew services start tailscale

# Option B — if you already have the App Store Tailscale GUI running, expose its CLI:
sudo ln -sf /Applications/Tailscale.app/Contents/MacOS/Tailscale /usr/local/bin/tailscale
```

Then sign in once:

```bash
tailscale up   # opens a browser, sign in with the team's Tailscale account
```

You also need to **enable Funnel for your tailnet** once in the admin console:
1. Visit <https://login.tailscale.com/admin/dns>
2. Toggle "Funnel" / "HTTPS Certificates" on
3. (Per-machine enablement happens automatically when `install.sh funnel` runs)

### 9b. One command to publish

```bash
./scripts/install.sh funnel
```

What it does (so you can debug if it fails):

1. Verifies `tailscale` is on PATH and logged in.
2. Resets any previous `tailscale serve` / `tailscale funnel` state.
3. Sets up path-based routing through one HTTPS endpoint:
   | Path | Backend |
   |---|---|
   | `/` | Next.js frontend on `127.0.0.1:3010` |
   | `/api/*` | FastAPI on `127.0.0.1:8787` |
   | `/healthz` | FastAPI on `127.0.0.1:8787` |
   | `/ws/*` | FastAPI WebSocket on `127.0.0.1:8787` |
4. Enables `tailscale funnel` on port 443.
5. Prints the public URL (e.g. `https://your-mac.tail-xxxxxx.ts.net`).

### 9c. Why this works for both backend AND frontend on one URL

The frontend's runtime URL-derive (in `apps/web/src/app/page.tsx`) detects when the browser is on an explicit port (3010 → dev/LAN mode → talk to `:3000`) vs. no port (Funnel URL on port 443 → same-origin mode → talk to the proxy in front). Tailscale Serve routes paths to the right backend. Browsers see one origin; CORS is irrelevant.

### 9d. To stop publishing

```bash
./scripts/install.sh funnel-off
```

Reverts to "only the office tailnet can reach the Mac". Useful when troubleshooting or taking the service down for maintenance.

---

## 10. Smoke test the whole stack

From any device, any network, on the public Funnel URL printed by step 9b:

1. Open `https://<your-mac>.tail-xxxxxx.ts.net` (in Safari on your phone over cellular is the strongest test — that's exactly what teammates will do).
2. Enter your name when prompted — saved to `localStorage` once.
3. Pick a consultant from the dropdown. The list comes from the on-disk `consultants/` folder.
4. Send "hi" — Wendy (or whoever is selected) should greet you in her voice (not the old "Hi! Which Property Sales Consultant…" master greeting).
5. Click 📎, pick a small file, send a message — your bubble should show the attachment header.
6. Click "History" in the header — should list past sessions for the selected consultant.
7. Click "New" — fresh chat; the previous session is preserved in History.

Also confirm with curl from anywhere:

```bash
curl -s https://<your-mac>.tail-xxxxxx.ts.net/healthz | python3 -m json.tool
```

Should print the consultant list and `"ok": true`.

If any step fails, check the relevant log:

| Symptom | Where to look |
|---|---|
| Frontend won't load | `tail -50 /tmp/harcourts-web.log`; check port 3010 isn't already in use |
| Chat won't connect (red dot in header) | `tail -50 /tmp/harcourts-backend.log` |
| Wendy says "I need permission to…" | Confirm step 5 (the four Bash entries) is done |
| Wendy greets with all seven consultant names | The `--append-system-prompt` override wasn't picked up; restart with `./scripts/install.sh restart` |
| File appeared in `photos/` but Wendy didn't acknowledge | The `📎 Attached` header is in the user message — confirm it's visible in the user's bubble before her reply |
| Funnel URL gives 404 on `/api/...` or `/ws/...` | Path routing isn't set. Re-run `./scripts/install.sh funnel`. If still broken, `tailscale serve status` shows current routes. |
| Funnel URL connects but chat WS shows red dot | Tailscale Serve's WebSocket support — check `tailscale version` is 1.50 or newer. Upgrade via `brew upgrade tailscale`. |
| `./scripts/install.sh funnel` says "Funnel needs to be enabled for this account" | Visit <https://login.tailscale.com/admin/dns> and toggle Funnel on. |

---

## What's running where

Once steps 1–6 are done:

| Service | Port | Logs | How to restart |
|---|---|---|---|
| `com.harcourts.backend` (FastAPI + WS) | `0.0.0.0:8787` | `/tmp/harcourts-backend.log` | `launchctl unload && load` of the plist, or `./scripts/install.sh restart` |
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

If you've been asked to set up this system on a fresh Mac, follow these steps in order. Stop at each point that requires the human and ask before proceeding.

1. Confirm you're at the project root: `pwd` should end in `harcourts-listings`.
2. Run `./scripts/install.sh check`. Install any RED prereqs via the suggested `brew install` lines. If `tailscale` is missing, suggest installing it now (Funnel is required for production).
3. Run `./scripts/install.sh`. Wait for it to finish (1–3 minutes).
4. **Ask the human to do these three:**
   - `claude login` (signs into the Anthropic Max account)
   - `tailscale up` (signs into the team's Tailscale account)
   - paste these four lines into `.claude/settings.json`'s `permissions.allow` array — read them out:
     ```json
     "Bash(mv ./consultants/**)",
     "Bash(cp ./consultants/**)",
     "Bash(ls ./consultants/**)",
     "Bash(cat ./consultants/**)"
     ```
   Wait for confirmation that all three are done.
5. **Definitive permissions check:** run `./scripts/install.sh verify`. Must print `✓ claude responded cleanly. This Mac is ready.` If it fails, follow the printed remedies and re-run.
6. **Auto-start on boot:** run `./scripts/install.sh launchd`. Verify both services come up with `curl -s http://127.0.0.1:8787/healthz` and `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3010/`.
7. **Publish to teammates:** run `./scripts/install.sh funnel`. The script prints the public HTTPS URL (e.g. `https://your-mac.tail-xxxxxx.ts.net`). If the script fails because Funnel isn't enabled for the tailnet, ask the human to visit <https://login.tailscale.com/admin/dns> and toggle Funnel on, then re-run.
8. **Smoke test from outside:** run `curl -s https://<funnel-url>/healthz`. Must return JSON with `"ok": true` and the consultant list. Then ask the human to open the URL on their phone over cellular (Wi-Fi off) and confirm the chat works.
9. **Hand off:** report the public URL, confirm it's been smoke-tested, and tell the human to share it only with the trusted team.
