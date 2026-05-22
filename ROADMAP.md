# Roadmap

Stages explicitly out of scope for the initial build. Track them here so they do not get folded into day-to-day listing work.

## VaultRE integration

A custom MCP server will be built later to search properties, fetch details, and download images directly from VaultRE. When done, Phase 1 of the listing workflow will offer staff a choice between automatic pull from VaultRE and manual upload.

## Canva graphics generation

Once Canva API access is configured, the system will generate brochure graphics, social tiles, and window-card visuals from approved listing copy.

## VaultRE push-back

Approved listing content will be pushed back into VaultRE as a draft listing for the consultant to review and publish.

## Multi-user chat UI

A polished browser-based chat interface running on the office MacBook, reachable by every teammate over Tailscale. One shared source of truth (the office Mac's filesystem + local SQLite), no per-user sign-in, learnings written back to `consultants/{slug}/knowledge/learnings.md` benefit everyone immediately. Replaces the earlier FastAPI + Supabase stack that was removed during the rebuild.

## Additional shared library content

Suburb/area guides, market context, brand handbook PDFs, and shared sample listings can be added to `shared/library/` as the team builds them.
