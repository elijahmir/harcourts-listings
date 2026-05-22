# Harcourts Listing Content Generator

System for generating property-listing content in each consultant's authentic voice for Harcourts Ulverstone & Penguin. Seven consultants, one shared knowledge base, five-phase guided workflow that ends in a Word document.

> **Status:** The system is being rebuilt around a polished browser chat UI hosted on the office MacBook, with shared local storage and no per-user sign-in. The previous FastAPI + Supabase + standalone uploader stack has been removed; only the prompt-layer (rules, commands, consultant personas) remains. See [ROADMAP.md](ROADMAP.md).

## What lives in this repo today

| Path | Purpose |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Master prompt — greets the user, picks a consultant, hands off |
| [BRIEF.md](BRIEF.md) | Full project vision and operating principles |
| [shared/rules/](shared/rules/) | Authoritative rules: security, writing, content formats, 5-phase workflow, Word-doc spec |
| [shared/library/buyer-avatars.md](shared/library/buyer-avatars.md) | Buyer personas referenced in Phase 2 and Phase 4 |
| [consultants/](consultants/) | One folder per consultant, plus a `_template` |
| [.claude/commands/](.claude/commands/) | Slash commands: `/new-listing`, `/onboard-consultant`, `/save-learning`, `/switch-consultant`, `/add-consultant` |
| [.claude/settings.json](.claude/settings.json) | Permission allow/deny lists for the agent |
| [scripts/create-listing.sh](scripts/create-listing.sh) | Terminal entry point — pick a consultant, launch Claude in their workspace |
| [scripts/add-consultant.sh](scripts/add-consultant.sh) | Clone the template to add a new consultant |
| [integrations/vaultre/](integrations/vaultre/) | OpenAPI spec + analysis for the future VaultRE integration |
| [outputs/](outputs/) | Where generated Word documents land |

## Running it today (terminal, single-user)

```bash
./scripts/create-listing.sh
```

Pick a consultant, enter your email, walk the five phases in the chat. The final Word document lands in `outputs/`.

## What's coming

A browser chat UI on the office MacBook that any teammate can use over Tailscale, with all the same prompt-layer logic. Tracked in [ROADMAP.md](ROADMAP.md).
