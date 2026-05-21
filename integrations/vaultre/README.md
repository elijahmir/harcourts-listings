# VaultRE integration

This folder holds everything related to pulling property data from VaultRE into the listing workflow.

## What is here

- `openapi.yaml` — the authoritative VaultRE API specification (OpenAPI 3.0.1, v1.3), supplied by VaultRE directly. Use it as the reference for endpoints, request/response shapes, and field names. Do not search the web for VaultRE API details when this file is present.

## Status

Not yet wired into the listing workflow. Phase 1 of [shared/rules/workflow.md](../../shared/rules/workflow.md) still takes manual uploads only. The VaultRE pull is tracked in [ROADMAP.md](../../ROADMAP.md).

## Key facts from the spec

- **Server:** `https://ap-southeast-2.api.vaultre.com.au/api/v1.3`
- **Transport:** HTTP/1.1 required (per the spec's own note).
- **Code samples upstream:** https://github.com/VaultGroup/api-samples
- **Auth:** every protected endpoint requires both headers:
  - `X-Api-Key: <api key>`
  - `Authorization: Bearer <token>`

Anything more specific — rate limits, request shapes, response schemas — read directly out of `openapi.yaml` rather than guessing.

## Confirmed working (last smoke test)

- `GET /properties?pagesize=1` returned `HTTP 200` with a live record from account `Harcourts Ulverstone` (id `4897`). Total properties in scope at that time: **6,195**.
- Photos come back as URLs with `thumb_180`, `thumb_1024`, and full-size variants — no separate download call needed for the URL itself.

## Token quirk — read before debugging 403s

The current credentials are a **third-party token**. That means:

- "Who am I" endpoints like `GET /user` return `HTTP 403` with `code: NO_THIRD_PARTY` and `msg: "Third party access tokens cannot perform this action"`. This is expected, not a credential problem — third-party tokens belong to an integration, not a human user.
- Property, photo, and file endpoints work normally.

If a 403 ever shows up on a property endpoint, the cause is almost certainly that the endpoint is gated to logged-in users (not third-party tokens), not that the API key is wrong. Check the spec's `security:` block for that endpoint before assuming a credential issue.

## Credentials

Live credentials are kept in the project-root `.env` (gitignored) under `VAULTRE_API_KEY`, `VAULTRE_API_TOKEN`, and `VAULTRE_API_BASE`. Do not echo them into commits, logs, or chat output.
