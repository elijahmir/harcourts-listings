# Harcourts Listing Content Generator

System for generating property-listing content in each consultant's authentic voice for Harcourts Ulverstone & Penguin. Seven consultants, one shared knowledge base, five-phase guided workflow that ends in a Word document.

The system runs as a browser chat hosted on one office MacBook. Teammates connect from their phones, laptops, or desktops over Tailscale; identity is captured by a one-time "what's your name?" prompt — no sign-in. The Claude work uses the office Mac's signed-in Claude Max subscription, so per-turn cost is flat.

---

## Setting up a fresh Mac

See **[docs/HOST-SETUP.md](docs/HOST-SETUP.md)**. The short version:

```bash
git clone <repo-url> ~/code/harcourts-listings
cd ~/code/harcourts-listings
./scripts/install.sh          # bootstrap deps + build
claude login                  # sign in (one-time, browser opens)
# … paste 4 lines into .claude/settings.json (HOST-SETUP step 5)
./scripts/install.sh launchd  # auto-start backend + frontend on boot
```

That doc is structured so a Claude Code agent on the production Mac can follow it autonomously after `git clone`.

---

## What lives in this repo

| Path | Purpose |
|---|---|
| [docs/HOST-SETUP.md](docs/HOST-SETUP.md) | **Start here on a fresh Mac.** Step-by-step setup. |
| [CLAUDE.md](CLAUDE.md) | Master prompt — greets the user, picks a consultant, hands off (used by the terminal entry; the browser chat skips the greeting) |
| [BRIEF.md](BRIEF.md) | Full project vision and operating principles |
| [shared/rules/](shared/rules/) | Authoritative rules: security, writing (No-Robot Rulebook), content formats, 5-phase workflow, Word-doc spec |
| [shared/library/buyer-avatars.md](shared/library/buyer-avatars.md) | Buyer personas referenced in Phase 2 and Phase 4 |
| [consultants/](consultants/) | One folder per consultant, plus a `_template` |
| [.claude/commands/](.claude/commands/) | Slash commands: `/new-listing`, `/onboard-consultant`, `/save-learning`, `/switch-consultant`, `/add-consultant` |
| [.claude/settings.json](.claude/settings.json) | Permission allow/deny lists for the agent |
| [services/backend/](services/backend/) | FastAPI + WebSocket backend; spawns `claude` subprocess per turn |
| [apps/web/](apps/web/) | Next.js + Tailwind chat UI |
| [scripts/install.sh](scripts/install.sh) | One-shot Mac bootstrap (`check`, `install`, `launchd`, `restart`, `uninstall`) |
| [scripts/create-listing.sh](scripts/create-listing.sh) | Legacy terminal entry — still works for dev/admin without the browser UI |
| [scripts/add-consultant.sh](scripts/add-consultant.sh) | Clone the template to add a new consultant |
| [integrations/vaultre/](integrations/vaultre/) | OpenAPI spec + analysis for the future VaultRE integration |
| [outputs/](outputs/) | Where generated Word documents land |
| [data/](data/) | SQLite + runtime artefacts (gitignored) |

---

## Day-to-day use

After setup, teammates open the chat URL in their browser (typically the Tailscale Funnel URL — see HOST-SETUP step 8) and:

1. Enter their name once.
2. Pick a consultant from the dropdown.
3. Type the property address and walk through the five-phase workflow with the chat.
4. Attach photos / floor plan via the paperclip; Wendy/Colin/etc. picks them up automatically.
5. Save voice rules from any assistant message — those persist for the whole office.
6. Final Word document lands in `outputs/`.

---

## Updating

```bash
git pull
./scripts/install.sh         # picks up new deps + rebuilds frontend
./scripts/install.sh restart # bounce the launchd services
```

---

## Out-of-scope items

See [ROADMAP.md](ROADMAP.md): VaultRE auto-pull, Canva integration, VaultRE push-back of approved listings.
