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

Anything more specific — auth scheme, required headers, rate limits, property endpoints — read directly out of `openapi.yaml` rather than guessing.
