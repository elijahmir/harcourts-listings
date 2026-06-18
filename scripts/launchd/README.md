# CopyPro keep-warm + health LaunchAgents (Neo)

> **Uptime (backend + tunnels) is NOT handled here.** That is already covered by
> the system LaunchDaemons installed via `~/srv/install-daemon.sh` (run as `eli`,
> `RunAtLoad` + `KeepAlive`, boot-independent of who is logged in): `com.copypro.backend`,
> `com.copypro.ngrok`, `com.harcourts.pm.backend`, `com.harcourts.pm.tunnel`. To
> reload those, use `~/srv/recover.sh`. **Do not** add per-user backend/tunnel agents —
> they collide with the system daemons by the same label.

These two **per-user LaunchAgents** add the one thing the system daemons don't do:
keep the Claude subscription token fresh, and notice when auth/health breaks.

| Agent | What it does | Cadence |
|---|---|---|
| `com.copypro.keepwarm` | Runs `claude --print` so the Max login token refreshes before its ~8h expiry. Logs `ALERT` + notifies if auth has broken. | every 4h |
| `com.copypro.healthcheck` | Checks `/healthz` + console user + tunnel; logs failures to `logs/healthcheck.log`. | every 30 min |

They are **per-user** (not system) on purpose: the token refresh needs `eli`'s GUI
login-session keychain, so these must run inside `eli`'s session. **Keep `eli` as the
console user on Neo** or the refresh stops firing (see `docs/RUNBOOK-auth-recovery.md`).

## Deploy (on Neo as eli, while eli is the console user)

```bash
cd ~/srv/harcourts-listings
git pull
chmod +x scripts/launchd/keepwarm.sh scripts/launchd/healthcheck.sh
mkdir -p ~/Library/LaunchAgents logs
cp scripts/launchd/com.copypro.keepwarm.plist   ~/Library/LaunchAgents/
cp scripts/launchd/com.copypro.healthcheck.plist ~/Library/LaunchAgents/
UIDN=$(id -u)
for L in com.copypro.keepwarm com.copypro.healthcheck; do
  launchctl bootout  gui/$UIDN ~/Library/LaunchAgents/$L.plist 2>/dev/null
  launchctl bootstrap gui/$UIDN ~/Library/LaunchAgents/$L.plist
done
launchctl list | grep copypro          # both should appear
tail -1 logs/keepwarm.log              # expect "ok: pong"
```

## Notes

- These never restart the backend or touch `.env` / `credentials.json` (except the
  token's own refresh, which is the point). Safe to add to a running system.
- To stop one: `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/<label>.plist`.
- First real refresh test is whenever the token next expires; check `logs/keepwarm.log`
  the morning after — every line should say `ok: pong`, never `ALERT`.
