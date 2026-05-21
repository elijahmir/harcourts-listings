# VaultRE API: deep analysis for the listing workflow

Distilled from `openapi.yaml` (OpenAPI 3.0.1, v1.3) and confirmed against live calls on 2026-05-21. The aim is to lock the integration design before we write any tool code.

---

## Executive summary

Three findings change the design relative to the original brief:

1. **There is a first-class address search.** `GET /search/properties/address?term=…` takes a free-text address fragment and returns paginated property records with the assigned agent embedded. Phase 1 of the workflow no longer needs to ask the user for a VaultRE property ID — the consultant just types the address.

2. **VaultRE already stores `description`, `brochureDescription`, and `windowCardDescription` per property.** The fields we generate exist as first-class data on every record. That has two implications:
   - **Cold-start fuel:** when onboarding a consultant, we can pull every past listing they were the agent on and use their real descriptions as voice training data — no need to ask them to dig up samples.
   - **Push-back is trivial:** the roadmap item "VaultRE push-back" is a `PUT /properties/{id}` on these same fields, once we have a write-scoped token.

3. **Floor plans share the photos endpoint.** `PropertyPhoto.type` is an enum of `Photograph | Floorplan`. One call to `/properties/{id}/photos` returns both, distinguished by the `type` field. Phase 1's "share the floor plan" step can pull it directly when an automated flow is wanted.

A fourth finding is more of a gap than a capability: agents commonly load photos and floor plans into VaultRE but leave `description`, `brochureDescription`, `windowCardDescription`, `heading`, `searchPrice`, and `bed/bath/garages` empty (confirmed on 21 Crescent Street, an active Jodi Tunn listing with 29 photos and zero textual content). That gap is exactly what this generator fills — and is also why we can't rely on VaultRE for the structural data the briefing needs. We'll still have to either ask the consultant or extract from the floor plan.

---

## Auth and scopes

Both headers are required on every call:

```
X-Api-Key:    <api key>
Authorization: Bearer <token>
```

The current token is a third-party integration token. Confirmed scopes via `GET /scopes`:

```json
["advertising.read", "contact.read", "property.read"]
```

Endpoints to avoid because the token will refuse them:

| Endpoint            | Status | Code              | Why                                                   |
| ------------------- | -----: | ----------------- | ----------------------------------------------------- |
| `GET /user`         |    403 | `NO_THIRD_PARTY`  | Third-party tokens don't belong to a human user.     |
| `GET /account/users`|    403 | `INSUFFICIENT_SCOPE` | Needs an admin scope we don't have.               |

So the integration cannot enumerate staff by hitting `/account/users` to map consultant slugs to VaultRE user IDs. We discover those IDs the other way around: hit `/search/properties/address` for one of their known listings and read the `accessBy[].id` field.

---

## Confirmed consultant → VaultRE user mapping (partial)

Discovered from real records during this analysis:

| Consultant slug | VaultRE user ID | Notes                                |
| --------------- | --------------- | ------------------------------------ |
| `jodi-tunn`     | `201028`        | accessBy on 21 Crescent Street       |
| `colin-tunn`    | `201027`        | accessBy on 21 Crescent Street       |
| (Team Tunn)     | `201325`        | A VaultRE *team*, not an individual; joint Jodi+Colin listings include it |

The other five (`wendy-squibb`, `kurt-knowles`, `jakub-lehman`, `jarrod-burr`, `raymond-buitenhuis`) need one address-search call each to look up. The Python tool should resolve and cache these on first use.

Also seen incidentally in `accessBy` arrays from the search results: Michael Baxter (200993, "Principal & Owner/Director — Harcourts Penguin"), John Chilcott (200998), and an admin pseudo-user "HUP Admins" (201060). The account ID is `4897` ("Harcourts Ulverstone").

---

## Endpoint inventory mapped to the workflow

### Phase 1 — collect inputs (replace manual upload with pull)

| Capability | Endpoint | Notes |
| ---------- | -------- | ----- |
| Search by address | `GET /search/properties/address?term=…` | Free-text. Returns `PropertySearchResult` with `accessBy`/`editableBy` so we can immediately confirm it's the right consultant. |
| Suburb suggest | `GET /suggest/suburb?term=…` | Helpful if the address is ambiguous. |
| Address suggest (CoreLogic) | `GET /suggest/address/corelogic?term=…` | Validates against CoreLogic's address index. Useful when the agent has only a casual address fragment. |
| Full property record | `GET /properties/{id}` | Returns `PropertyExtended` — includes `accessBy`, `keys`, `saleHistory`, `leaseHistory`, plus all base Property fields. |
| Photos and floor plan | `GET /properties/{id}/photos` | Paginated. Filter client-side on `type == "Floorplan"` for the plan, `type == "Photograph"` for photos. |
| Other attached files | `GET /properties/{id}/files` | Contracts, inspection reports, etc. — not needed for listing generation but available. |

### Phase 2 — briefing data (enrichment)

| Capability | Endpoint | Notes |
| ---------- | -------- | ----- |
| Sale lifecycle | `GET /properties/{id}/sale/{lifeid}` (and many sub-resources) | Status, price qualifier, tenure, listed/withdrawn timeline. |
| Lease lifecycle | `GET /properties/{id}/lease/{lifeid}` | Same for leasing. |
| Open homes | `GET /properties/{id}/{salelease}/{lifeid}/openHomes` and `GET /openHomes` | Live open-home schedule — useful for the social media caption's "Open Home" line. |
| External stats | `GET /properties/{propertyid}/{salelease}/{lifeid}/externalStats` | Portal view counts, enquiry counts. Could surface for the briefing's "buyer demand" angle. |
| CoreLogic record | `GET /corelogic/properties/{id}` | Past sales, valuations, comparables. Needs the `corelogicId` from the property record. |

### Phase 3–5 — generation (no API calls)

Generation is local. The API only comes back in once we want to push results back into VaultRE — out of scope for this read-only token.

### Push-back (future, requires write scope)

| Capability | Endpoint |
| ---------- | -------- |
| Update listing copy | `PUT /properties/{id}` with `heading`, `description`, `brochureDescription`, `windowCardDescription`, `mobileMarketingDescription` |
| Upload photo  | `POST /properties/{id}/photos` (or `/photos/upload` for >5MB) |
| Adjust photo order | `POST /properties/{id}/photos/order` |

---

## Schema notes worth knowing now

### `Property` and friends

- The base `Property` has `heading`, `description`, `brochureDescription`, `windowCardDescription`, `landArea`, `frontage`, `yearBuilt`, `zoning`, `geolocation`, `displayPrice`/`searchPrice`, and `addressVisibility` (enum: `streetAndSuburb | suburb | fullAddress`).
- `ResidentialProperty` adds `bed`, `bath`, `garages`, `carports`, `openSpaces`, `ensuites`, `toilets`, `receptionRooms`, `floorArea`, `status` (enum: `prospect | appraisal | listing | conditional | unconditional | settled | management | withdrawn | withdrawnAppraisal`), `contactStaff`, `energyRating`, `isNewHome`, `isHouseLandPackage`.
- `ResidentialPropertyExtended` adds `highlights` (array of strings) — likely the bullet points already curated by the agent. Worth checking on real records when we get further along.
- The `discriminator` is `class` (`Residential | Commercial | Rural | Land | Business | HolidayRental | Livestock | ClearingSales`). Type-specific endpoints exist (`/properties/sale`, `/properties/lease`, etc.) but the generic `/properties/{id}` resolves the right shape automatically.

### `PropertyPhoto`

```
id, inserted, modified, filesize, width, height, caption,
type ("Photograph" | "Floorplan"),
url, filename, userFilename, published,
thumbnails: { thumb_180, thumb_1024 }
```

- The `url` field is a directly downloadable HTTPS URL — no auth needed on the photo CDN. Caveat: confirm with a small `HEAD` before relying on that for the production tool; the spec doesn't promise it.
- We can recover the floor plan with `[p for p in photos if p["type"] == "Floorplan"]`. If there are multiple Floorplan entries (e.g., level-by-level), they're all returned.

### `PropertySearchResult` (lighter than `Property`)

Returned by `/search/properties/address`. Includes `id`, `displayAddress`, `address`, `saleLifeId`/`leaseLifeId`, `saleLife.status`, `leaseLife.status`, `accessBy`, `editableBy`, `account`. Does **not** include `description`, photos, or structural fields — those need a follow-up `/properties/{id}` call. Plan for two round-trips per address lookup.

### `Access` (the `accessBy`/`editableBy` items)

Each entry has `id`, `name`, `firstName`, `lastName`, `role`, `position`, `photo`, `email`, `phoneNumbers[]`, and `account`. The `role` enum we've seen includes `residentialSales`. This is enough to auto-confirm "I'm writing for Jodi Tunn — VaultRE says Jodi Tunn is the listing agent, ✓".

---

## Pagination, filters, and gotchas

- **Default `pagesize` is unclear.** Always pass it explicitly. `pagesize=1` was used for smoke tests; `pagesize=20`–`50` is a sensible production default.
- **HTTP/1.1 is required** per the spec's `info.description`. Most clients do this by default, but if we ever switch to HTTP/2 the API will reject.
- **Region is locked into the URL:** `ap-southeast-2.api.vaultre.com.au`. Don't hardcode `api.vaultre.com.au` anywhere.
- **Filtering by agent** uses `accessBy` (array of integer user IDs, comma-separated when serialised, `-1` for "Everyone"). It's a query parameter on most list endpoints (`/properties`, `/properties/sale`, etc.) but NOT on `/search/properties/address` — that endpoint takes only `term`/`page`/`pagesize`. So agent-scoped browsing uses `/properties/sale?accessBy=…`, not the search endpoint.
- **Property records can be `prospect`s** with zero text fields populated but still 20+ photos. Plan accordingly: never assume `description` is non-empty.

---

## Recommended Python tool design

A single CLI at `integrations/vaultre/cli.py` with the subcommands below. It loads creds from project-root `.env` (already gitignored), uses `requests`, and prints JSON on stdout. Claude Code calls it from Bash during Phase 1.

```
vaultre search <address>             # GET /search/properties/address
                                     # Print id, displayAddress, agents, status

vaultre details <id>                 # GET /properties/{id}
                                     # Print the full record as JSON

vaultre photos <id> [--save-to DIR]  # GET /properties/{id}/photos
                                     # Print structured list; with --save-to,
                                     # download all photos and the floor plan

vaultre floorplan <id> --save-to DIR # Convenience: only Floorplan-typed photos

vaultre listings <consultant_slug>   # Look up user_id (cached), then
                                     # GET /properties/sale?accessBy=<id>&pagesize=50
                                     # Used for the onboarding voice-sample pull

vaultre resolve-agent <slug>         # Walk address search to find user_id
                                     # Cache result in integrations/vaultre/agents.json
                                     # (NOT in .env — agent IDs are not secrets)

vaultre scopes                       # Print current token's scopes — quick "is the
                                     # token still alive" probe
```

Phase 1 of the workflow would call `vaultre search "{address}"` → if exactly one match and the consultant's ID is in `accessBy`, hand off; if multiple matches, present them; if zero, fall back to manual upload.

A separate command (run during `/onboard-consultant`) does:

```
vaultre listings <slug> | jq '...' | save each description into knowledge/sample-listings/
```

— which replaces the brief's "ask the user for 5–10 samples" step with a one-button automated pull.

### Why CLI, not MCP

- Three commands cover 95% of what the workflow needs.
- Debugging is `python cli.py search "…"` in a terminal; with an MCP server it's restart-the-server-and-pray.
- The same Python code can be lifted into an MCP server later if we want it.

### Robustness checklist for the tool

- [ ] Surfaces VaultRE's own `code` field (`NO_THIRD_PARTY`, `INSUFFICIENT_SCOPE`, etc.) in error messages.
- [ ] Differentiates "no results" (empty `items`) from "permission denied" (HTTP 403).
- [ ] Retries 5xx with exponential backoff; never retries 4xx.
- [ ] Logs the API call (URL only, no headers) to a per-session log file under `consultants/{slug}/sessions/{session}/vaultre.log` so Claude can verify the source of pulled data.
- [ ] Never echoes the API key or token to stdout, even on `--verbose`.

---

## Open questions to put to VaultRE / the office admin

1. **Write scope.** When we want to push generated content back, we need `property.write` (and possibly `advertising.write` for portal-published fields). Confirmed needed before push-back work begins.
2. **Token lifetime.** The spec doesn't state TTL on third-party tokens. Worth asking — if it expires, the office admin needs a clear refresh path.
3. **Mapping all seven consultants.** I have Jodi (201028) and Colin (201027). The other five need a real listing to look up. If the office admin can hand over the VaultRE user IDs for Wendy Squibb, Kurt Knowles, Jakub Lehman, Jarrod Burr, and Raymond Buitenhuis directly, we avoid the address-search dance.
4. **`highlights` array.** Worth pulling on a real listing with curated bullets to see if it could replace or seed the Window Card and RealEstateVIEW Guide rather than us re-deriving them.

---

## What we proved live during this analysis

All against `https://ap-southeast-2.api.vaultre.com.au/api/v1.3` on 2026-05-21:

- `GET /scopes` → `["advertising.read", "contact.read", "property.read"]`
- `GET /user` → 403 `NO_THIRD_PARTY` (expected for third-party tokens)
- `GET /account/users` → 403 `INSUFFICIENT_SCOPE`
- `GET /properties?pagesize=1` → 200, total 6195 records, first hit is 66 Dial Road, Penguin
- `GET /search/properties/address?term=Dial Road&pagesize=3` → 200, 56 total matches
- `GET /properties/16882042` → 200, full record returned
- `GET /properties/16882042/photos` → 200, 2 photos, both `type=Photograph`
- `GET /properties/sale?accessBy=201028&pagesize=2` → 200, Jodi Tunn has 19 sale-side properties
- `GET /properties/29365473` → 200, Jodi Tunn active listing, 29 photos including `Floorplan`, zero text fields populated
