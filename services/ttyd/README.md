# ttyd — the chat over a browser

[`ttyd`](https://github.com/tsl0922/ttyd) is a small C program that turns a terminal command into a web URL. We use it to serve `scripts/create-listing.sh` so any device with a browser (phone, laptop, desktop) can start a listing session as if they were sitting at the host Mac.

## Why this matters for cost

Every chat goes through the `claude` CLI running on the host Mac, which is signed into the office Anthropic subscription. The browser is just a viewer for that terminal — no API tokens are spent. That's the whole reason this stack exists instead of a "real" webapp.

## Configuration

ttyd is configured by `scripts/install-host.sh`, which writes `~/Library/LaunchAgents/com.harcourts.ttyd.plist` with paths discovered on the running machine. The plist:

- runs `ttyd -p 7681 -W -t titleFixed=...Harcourts Listings... scripts/create-listing.sh`
- restarts on crash (`KeepAlive`) and on Mac reboot (`RunAtLoad`)
- writes a combined stdout/stderr log to `services/ttyd/ttyd.log`

Each browser connection spawns a fresh `bash → create-listing.sh → claude` chain, so two consultants connecting from two devices each get their own private session, but both use the same Mac's subscription quota.

## Operations

- **Install or reinstall:** `./scripts/install-host.sh`
- **Restart after `.env` changes:** `./scripts/install-host.sh restart`
- **Stop:** `./scripts/install-host.sh stop`
- **Logs:** `tail -f services/ttyd/ttyd.log`

## Files

- `ttyd.log` — runtime log, gitignored.
- This README.

The plist itself lives outside the repo on each host machine (in `~/Library/LaunchAgents/`) because the absolute paths differ per install.
