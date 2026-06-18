# CopyPro keep-warm + health LaunchAgents (Neo)

> **Uptime (backend + tunnels) is NOT handled here.** That is already covered by
> the system LaunchDaemons installed via `~/srv/install-daemon.sh` (run as `eli`,
> `RunAtLoad` + `KeepAlive`, boot-independent of who is logged in): `com.copypro.backend`,
> `com.copypro.ngrok`, `com.harcourts.pm.backend`, `com.harcourts.pm.tunnel`. To
> reload those, use `~/srv/recover.sh`. **Do not** add per-user backend/tunnel agents —
> they collide with the system daemons by the same label.

These add the two things the system daemons don't: keep the Claude token fresh,
and notice when health/auth breaks. They run at **two different levels** on purpose.

| Job | Level | Why that level | Cadence |
|---|---|---|---|
| `com.copypro.keepwarm` | **per-user** LaunchAgent | Refreshing the Max token needs `eli`'s login-session keychain, which only exists inside `eli`'s GUI session. | every 4h |
| `com.copypro.healthcheck` | **system** LaunchDaemon | Pure `curl`/`stat` checks — no session needed — so it monitors **regardless of who is logged in**, matching the backend daemons. | every 30 min |

**Why keep-warm can't be system-level:** token refresh fundamentally requires `eli`
logged in. If `eli` logs out >8h, the token expires and *nothing* (system daemon
included) can refresh it — chats 401 until someone logs in / re-auths. The only
login-independent auth is an API key. **Keep `eli` as Neo's console user.** The
system health-check logs `console != eli` as the early warning. See
`docs/RUNBOOK-auth-recovery.md`.

## Deploy

**Keep-warm** (per-user — run as eli, while eli is the console user):
```bash
cd ~/srv/harcourts-listings
git pull
chmod +x scripts/launchd/keepwarm.sh scripts/launchd/healthcheck.sh
mkdir -p ~/Library/LaunchAgents logs
cp scripts/launchd/com.copypro.keepwarm.plist ~/Library/LaunchAgents/
UIDN=$(id -u)
launchctl bootout  gui/$UIDN ~/Library/LaunchAgents/com.copypro.keepwarm.plist 2>/dev/null
launchctl bootstrap gui/$UIDN ~/Library/LaunchAgents/com.copypro.keepwarm.plist
tail -1 logs/keepwarm.log    # expect "ok: pong"
```

**Health-check** (system — needs sudo; runs regardless of login):
```bash
cd ~/srv/harcourts-listings
# if it was previously installed as a per-user agent, remove that first:
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.copypro.healthcheck.plist 2>/dev/null
rm -f ~/Library/LaunchAgents/com.copypro.healthcheck.plist
# install as a system LaunchDaemon:
sudo cp scripts/launchd/com.copypro.healthcheck.plist /Library/LaunchDaemons/
sudo chown root:wheel /Library/LaunchDaemons/com.copypro.healthcheck.plist
sudo launchctl bootout system /Library/LaunchDaemons/com.copypro.healthcheck.plist 2>/dev/null
sudo launchctl bootstrap system /Library/LaunchDaemons/com.copypro.healthcheck.plist \
  || sudo launchctl load -w /Library/LaunchDaemons/com.copypro.healthcheck.plist
sudo launchctl list | grep copypro.healthcheck   # should appear
```

## Notes

- Nothing here restarts the backend or touches `.env` / `credentials.json` (except
  the token's own refresh, which is the point). Safe to add to a running system.
- Stop keep-warm: `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.copypro.keepwarm.plist`.
- Stop health-check: `sudo launchctl bootout system /Library/LaunchDaemons/com.copypro.healthcheck.plist`.
- Check `logs/keepwarm.log` the morning after the token first expires — every line
  should say `ok: pong`, never `ALERT`.
