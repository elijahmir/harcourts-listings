# Host setup — for the office admin

This is the one-time setup for the shared MacBook that runs the system. Plan for 30–45 minutes the first time, mostly waiting for downloads.

You do this once. After that, day-to-day you don't touch the Mac — staff use it from their phones via the guide at [MOBILE-SETUP.md](MOBILE-SETUP.md).

---

## What you need before you start

- The MacBook that will be the host (Apple Silicon or Intel, macOS 13+).
- An Anthropic account with a Claude subscription that has Claude Code access. This is the account that all consultant chats will run under, and the one whose quota gets consumed.
- A Tailscale account. Free tier is enough for an office.
- Homebrew installed (https://brew.sh). One-liner from that page.

If anything in the list is missing, sort it before continuing — the rest of this guide assumes you have all four.

---

## Step 1 — Install Claude Code CLI

The whole system pivots around the `claude` command being available on the Mac and logged into your office Anthropic account.

```sh
npm install -g @anthropic-ai/claude-code
```

If you don't have Node.js, install it via Homebrew first: `brew install node`.

Verify:

```sh
claude --version
claude
```

The second command should open Claude Code's interactive prompt. Sign in when it asks. Pick the Claude account that owns your subscription. Type `/exit` to leave once you've confirmed it works.

If `claude` says you're using the API and not the subscription, sign out (`/logout`) and sign in again, choosing the subscription option.

---

## Step 2 — Clone the project and create `.env`

Pick a stable location on the Mac. The default in this guide is `~/harcourts-listings`.

```sh
cd ~
# If you already have it elsewhere, just cd into that directory.
git clone <your-repo-url> harcourts-listings || true
cd harcourts-listings
cp .env.example .env
```

Open `.env` in any text editor and fill in:

- `VAULTRE_API_KEY` and `VAULTRE_API_TOKEN` — supplied by the office's VaultRE admin.
- Leave `HARCOURTS_UPLOADER_BASE_URL` at `http://localhost:8080` for now. We update it after Tailscale is set up.

---

## Step 3 — Run the installer

```sh
./scripts/install-host.sh
```

This is idempotent. It:

- Verifies the Mac is set up correctly.
- Installs `ttyd` via Homebrew if missing.
- Creates a Python virtualenv for the uploader and installs its dependencies (FastAPI, Pillow, pillow-heif).
- Writes two LaunchAgent plists into `~/Library/LaunchAgents/` with paths discovered for this machine.
- Loads both services into `launchd` so they survive reboot and crashes.
- Verifies both services answer on `http://localhost:7681` (ttyd) and `http://localhost:8080` (uploader).

At the end it prints a "next steps" block. Read it — it summarises Steps 4 onwards.

If something fails, run `./scripts/install-host.sh check` to see which piece needs attention, fix it, then re-run.

### Open up the firewall (if asked)

On the first run, macOS may pop up a dialog asking whether `ttyd` and/or the Python interpreter should accept incoming network connections. Click **Allow** for both. If you click "Deny" by mistake, fix it in **System Settings → Network → Firewall → Options**.

---

## Step 4 — Test locally on the Mac itself

Before bringing in phones, confirm everything works from the host Mac's own browser.

1. Open Safari (or Chrome) on the Mac.
2. Visit `http://localhost:7681`. You should see the listing terminal in a browser tab, asking which consultant the listing is for.
3. Pick a consultant. The chat should respond as Claude. (If the chat refuses with an Anthropic auth error, go back to Step 1 and confirm `claude` is signed in.)
4. Open a second tab to `http://localhost:8080`. You should see the **Harcourts Photos** picker page.

If both work, the Mac is fully wired. The remaining steps make those URLs reachable from other devices.

---

## Step 5 — Sign in to Tailscale on the Mac

1. Click the Tailscale icon in the menu bar.
2. Click **Log in…**. Pick the account that owns your office Tailnet (use the same Google/Microsoft/email account each time so devices land in the same network).
3. Once you see the green "Connected" indicator and the Mac's name in the menu, you're done.

Take note of the Mac's Tailnet name. The easiest way:

1. Tailscale menu icon → "Network devices" → "This Machine".
2. Copy the line that ends in `.ts.net`. It looks like `harcourts-mac.tail-abc12.ts.net`.

If you don't see the name there, log into the Tailscale admin console at https://login.tailscale.com/admin/machines and find this machine in the list.

---

## Step 6 — Update `.env` with the real hostname

Edit `.env` again. Change:

```
HARCOURTS_UPLOADER_BASE_URL=http://localhost:8080
```

to:

```
HARCOURTS_UPLOADER_BASE_URL=http://<the-name-you-copied>:8080
```

For example: `HARCOURTS_UPLOADER_BASE_URL=http://harcourts-mac.tail-abc12.ts.net:8080`

Then restart the services so the change takes effect:

```sh
./scripts/install-host.sh restart
```

This isn't strictly required for the uploader (it picks up the URL from `.env` directly), but it's the simplest "did the config change land?" check.

---

## Step 7 — Invite each staff member to the Tailnet

In the Tailscale admin console at https://login.tailscale.com/admin/users:

1. Click **Invite users**.
2. Enter each staff member's email (the one they'll sign in with on their phone).
3. Send the invite.

They receive an email with a link. When they tap it on their phone, the Tailscale app prompts them to accept and join the Tailnet.

---

## Step 8 — Send the URLs to each staff member

Once a staff member is in the Tailnet, message them the two URLs plus the mobile guide. A WhatsApp message that works:

> Hi! Here are the two URLs for the new listing system, plus a guide. Setup takes about 10 minutes on your phone, then you only need to tap two icons.
>
> Listings: http://harcourts-mac.tail-abc12.ts.net:7681
> Photos: http://harcourts-mac.tail-abc12.ts.net:8080
>
> Guide: <paste the contents of docs/MOBILE-SETUP.md, or link to the file>

Adjust the two URLs to match what you actually copied in Step 5.

---

## Verifying everything works

Two checks worth doing the first time round.

### From the Mac (local loop)

```sh
curl -fsS http://localhost:8080/healthz
```

Expected: JSON with `"ok": true`, the project root path, and `"heic_conversion": true`.

```sh
curl -fsS -o /dev/null -w "%{http_code}\n" http://localhost:7681/
```

Expected: `200`.

### From your phone (remote loop)

Tap the **Photos** bookmark on your phone. You should see the same picker page. Tap the **Listings** bookmark. You should see the chat.

If the picker says "no consultants" or the chat doesn't answer, the Mac is reachable but something inside is broken — see Troubleshooting below.

---

## Restarting after configuration changes

After editing `.env` or pulling new code:

```sh
./scripts/install-host.sh restart
```

To stop everything (without removing it):

```sh
./scripts/install-host.sh stop
```

To start it again:

```sh
./scripts/install-host.sh
```

To remove everything:

```sh
./scripts/install-host.sh uninstall
```

This removes the launchd plists but keeps your code and `.env` intact.

---

## Troubleshooting

### "Phone says page won't load"

In order, check:

1. Tailscale is **Connected** on the phone.
2. Tailscale is **Connected** on the Mac (menu bar icon should be green).
3. The Mac is awake. Energy Saver should be configured to never sleep while plugged in.
4. `./scripts/install-host.sh check` from the Mac shows both services as loaded.

### "Chat works but uploader says Session folder does not exist"

The user opened the **Photos** link before starting a listing in the chat. They need to open the **Listings** chat first, get to the point where the assistant gives them a specific upload link, and tap *that* link rather than the bookmarked base URL.

### "Chat fails with Anthropic auth error"

The `claude` CLI on the Mac has been signed out. SSH or terminal into the Mac, run `claude`, sign back in. The ttyd service will pick up the new login on the next connection — no restart needed.

### "Uploader log shows HEIC conversion disabled"

`pillow-heif` failed to install. Usually means `libheif` is missing. Fix:

```sh
brew install libheif
cd services/uploader
.venv/bin/pip install --upgrade --force-reinstall pillow-heif
./scripts/install-host.sh restart
```

### "Two consultants connecting at once is slow"

Each connection spawns its own `claude` process, all hitting the same subscription. If you regularly have 3+ consultants working simultaneously and you're hitting Anthropic's per-minute rate limits, upgrade the subscription tier.

### "I can connect from one phone but not another"

The phone that can't connect probably hasn't been invited to the Tailnet, or hasn't accepted the invite. Check the Tailscale admin console at https://login.tailscale.com/admin/machines — both phones should appear in the device list.

### Logs

- ttyd: `tail -f services/ttyd/ttyd.log`
- Uploader: `tail -f services/uploader/uploader.log`

Both are gitignored so they won't accidentally get committed.

---

## Keeping it running

The launchd plists have `KeepAlive=true` and `RunAtLoad=true`. They will:

- Restart automatically if either process crashes.
- Start automatically when the Mac boots.

Two things will still take the system down:

- The Mac going to sleep. Make sure the host Mac is set to "Never sleep when plugged in" in **System Settings → Battery → Power Adapter**.
- macOS asking for the login password after a restart. Set the Mac to auto-login as the user that ran the installer.

If staff ever say "the system is down", first check the Mac is awake and on the office Wi-Fi, then check Tailscale on it is green. Those two are 95% of issues.
