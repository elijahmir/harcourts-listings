# CopyPro launchd jobs (Neo)

Three LaunchAgents keep CopyPro self-healing on Neo (`eli` account). They are
version-controlled here and deployed to `~/Library/LaunchAgents/` on Neo.

| Job | What it does | Cadence |
|---|---|---|
| `com.copypro.backend` | Starts the backend at login; restarts it if it crashes (`KeepAlive`). Survives reboot. | continuous |
| `com.copypro.keepwarm` | Runs `claude --print` so the Max login token refreshes before its ~8h expiry. Logs `ALERT` if auth breaks. | every 4h |
| `com.copypro.healthcheck` | Checks `/healthz` + console user + tunnel; logs failures to `logs/healthcheck.log`. | every 30 min |

The ngrok tunnel uses the pre-existing `com.harcourts.ngrok.plist` already in
`~/Library/LaunchAgents/` on Neo (it has the reserved domain). Just enable it.

## Deploy (run on Neo as eli, from an SSH session where eli is the console user)

```bash
cd ~/srv/harcourts-listings
git pull                                   # gets these files
chmod +x scripts/launchd/*.sh
mkdir -p ~/Library/LaunchAgents logs

# copy the three CopyPro plists into place
cp scripts/launchd/com.copypro.*.plist ~/Library/LaunchAgents/

# load them (bootstrap into the GUI session — works because eli is the console user)
UID_NUM=$(id -u)
for L in com.copypro.backend com.copypro.keepwarm com.copypro.healthcheck; do
  launchctl bootout  gui/$UID_NUM ~/Library/LaunchAgents/$L.plist 2>/dev/null
  launchctl bootstrap gui/$UID_NUM ~/Library/LaunchAgents/$L.plist
done

# enable the existing ngrok tunnel job (it ships as .disabled)
[ -f ~/Library/LaunchAgents/com.harcourts.ngrok.plist.disabled ] && \
  mv ~/Library/LaunchAgents/com.harcourts.ngrok.plist.disabled ~/Library/LaunchAgents/com.harcourts.ngrok.plist
launchctl bootstrap gui/$UID_NUM ~/Library/LaunchAgents/com.harcourts.ngrok.plist 2>/dev/null

# verify
launchctl list | grep -E "copypro|ngrok"
curl -sS http://127.0.0.1:8787/healthz
```

## Notes

- If `launchctl bootstrap` says "Bootstrap failed: 5: Input/output error", the job
  is already loaded — `bootout` then `bootstrap` again, or ignore.
- These run in `eli`'s GUI session. **Keep `eli` as the console user on Neo** or the
  keep-warm refresh stops firing (see `docs/RUNBOOK-auth-recovery.md`).
- To stop a job: `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/<label>.plist`.
