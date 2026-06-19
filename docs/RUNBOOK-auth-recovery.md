# Runbook — CopyPro is down / "Failed to authenticate" (401)

**When to use this:** CopyPro chat connects (you see the green dot, the message streams) but every reply ends with
`API Error: 401 Invalid authentication credentials` or `Invalid bearer token`,
**or** the chat shows "Reconnect" and never responds.

This is almost always one of two things: the backend died (reboot), or the Claude login token expired. Both are fixed below in ~2 minutes.

---

## TL;DR fix (do this first)

From any Mac's Terminal:

```bash
ssh eli@pennys-macbook-neo.tail9cb076.ts.net
cd ~/srv/harcourts-listings

# 1. Re-login to Claude (the part that usually breaks)
claude
#   → "Yes, I trust this folder"
#   → choose "Claude account"  (NOT the API key option)
#   → copy the https://claude.com/... URL it prints
#   → open it in a browser signed into the MAX-subscription account, click Authorize
#   → copy the code, paste it back at the "Paste code here" prompt, Enter
#   → "Login successful"
#   → press Ctrl+C twice to exit

# 2. Confirm auth works
claude --print "say OK"          # must print: OK   (not a 401)

# 3. Restart the backend (only if it was down)
nohup ./run-copypro-backend.sh > logs/daemon-backend.log 2>&1 &
sleep 6
curl -sS http://127.0.0.1:8787/healthz     # expect {"ok":true,...}
```

CopyPro works the moment `claude --print` returns `OK` — the ngrok tunnel stays up on its own.

---

## Why it breaks (so you know what you're fixing)

- CopyPro's backend runs on Neo as the **`eli`** service account and spawns the `claude` CLI for every chat turn.
- `claude` authenticates with a **claude.ai Max-subscription login** stored at `~/.claude/.credentials.json`. This token has a short (~8 hour) life and **auto-refreshes only when `eli` is the logged-in GUI user** on Neo (refresh needs the login-session keychain).
- It dies when: **Neo reboots** (backend + tunnel don't auto-start), or the **token expires while nobody is using `claude` as `eli`** (or the console user isn't `eli`).

## Two things to check if the TL;DR didn't fully fix it

```bash
# Is eli the GUI/console user? (must be 'eli' for token refresh to work)
stat -f "%Su" /dev/console        # want: eli

# Is the tunnel up?
pgrep -fl ngrok || echo "tunnel down — see Prevention below to load the launchd job"
```

---

## What does NOT work (don't waste time on these)

Driving auth headless over SSH fails — confirmed the hard way:

- **`claude setup-token`** → mints an `sk-ant-at01-` token, but the server **rejects it at inference** ("Invalid bearer token"). It only requests the narrow `user:inference` scope, and its token must go in env `CLAUDE_CODE_OAUTH_TOKEN`, not `credentials.json`.
- **`claude auth login`** → requests an `org:create_api_key` scope this org can't grant → the token exchange **400s**.

Only the **plain interactive `claude` login** ("Claude account" picker) requests the correct classic scopes and writes the credential that actually works. That's why the TL;DR uses `claude`, not those subcommands.

---

## Prevention (already set up)

1. **Auto-restart on reboot/crash/sleep** — handled by the **system LaunchDaemons** in `/Library/LaunchDaemons` (installed via `~/srv/install-daemon.sh`): `com.copypro.backend`, `com.copypro.ngrok`, `com.harcourts.pm.backend`, `com.harcourts.pm.tunnel`. They run as `eli`, `RunAtLoad` + `KeepAlive`, **independent of who is logged in**. To reload them: `sudo bash ~/srv/recover.sh`.
2. **Keep-warm token refresh** — `com.copypro.keepwarm` (per-user LaunchAgent) runs `claude --print` every ~4 hours as `eli`, refreshing the login token before its ~8-hour expiry so it never dies idle. Logs to `logs/keepwarm.log` (every line should say `ok: pong`).
3. **Health monitor** — `com.copypro.healthcheck` (**system** LaunchDaemon, runs regardless of login) checks `/healthz` + console user + tunnel every 30 min; logs failures to `logs/healthcheck.log`. A `console != eli` line is the early warning that the token is about to fail.
4. **Keep `eli` as the console user** on Neo. The keep-warm refresh needs `eli`'s login-session keychain; if Neo switches to another user, refresh stops working and you're back to a manual login.

Deploy details for the two per-user agents: `scripts/launchd/README.md`.

## Diagnostic error codes (what users send you)

When the `claude` CLI fails, both apps now show the user a calm notice with a
copyable code instead of the raw error — e.g. `CP-AUTH-01 · session 6f3a2c ·
2026-06-19 10:14`. `CP` = CopyPro/Sales App, `PM` = Copilot/PM App. The real
error is in the backend log; grep it by the session prefix:
`grep 6f3a2c ~/srv/harcourts-listings/logs/daemon-backend.log`.

| Code | Means | What to do |
|---|---|---|
| `*-AUTH-01` | Claude login token invalid / expired / missing | Re-login on Neo (the TL;DR fix above) |
| `*-BILL-01` | Subscription credit / quota exhausted | Check the Claude plan / Agent-SDK pool |
| `*-LOAD-01` | Anthropic overloaded (529 / 5xx) | Transient — ask the user to retry in a minute |
| `*-NET-01` | Backend / tunnel unreachable or timing out | Check the system daemon + ngrok/cloudflare tunnel |
| `*-UNK-01` | Unclassified failure | grep the log by the session prefix for the full error |

Classifier + code builder: CopyPro `services/backend/app/main.py` (`_classify_fatal`
/ `_fatal_notice`), PM `harcourts-docusign/backend/app/live.py`. The codes are
the same scheme across both apps.

## The zero-expiry alternative

If subscription auth keeps being fragile, switch the `claude` auth to an **API key**: create one at `console.anthropic.com`, put `ANTHROPIC_API_KEY=sk-ant-...` in `~/srv/harcourts-listings/.env`, restart the backend. It never expires and needs no GUI/keychain — the right fit for a headless service account. Trade-off: it bills against the Anthropic Console (per-token), separate from the Claude Max subscription.
