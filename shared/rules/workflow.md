# 5-Phase Listing Workflow

Run these phases in order. Do not skip ahead. After each phase, present the result to the user and wait for approval before continuing.

## Phase 1 — Collect inputs

This phase has three parts: capture the address, create the session, and get the property's photos and floor plan onto the Mac so you can analyse them. Run the steps in order. Do not move on to Phase 2 until you have visually verified files exist on disk.

### Step 1.1 — Confirm the address

Ask: "What is the full property address?" Wait for the answer.

When the user replies, repeat the address back in one short sentence so they can catch a typo before you create a folder named after it. Example: "Got it — 22 Dial Road, Penguin TAS 7316. Correct?"

### Step 1.2 — Create the session folder

The launcher (`scripts/create-listing.sh`) exports these environment variables. Read them via `Bash` (e.g. `echo $HARCOURTS_CONSULTANT_SLUG`):

| Variable                       | Used for                                                  |
| ------------------------------ | --------------------------------------------------------- |
| `HARCOURTS_CONSULTANT_SLUG`    | The slug of the active consultant (e.g. `wendy-squibb`).  |
| `HARCOURTS_CONSULTANT_NAME`    | Full name for messages and metadata.                       |
| `HARCOURTS_USER_EMAIL`         | The staff member's email captured at session start.        |
| `HARCOURTS_UPLOADER_BASE_URL`  | Base URL of the mobile uploader.                          |

If any required variable is empty (the user ran `claude` directly instead of the launcher), ask the user for the missing value before continuing.

Make a session folder at:

    consultants/{HARCOURTS_CONSULTANT_SLUG}/sessions/{YYYY-MM-DD}_{address-slug}/

…where `{address-slug}` is a short kebab-case form of the street address — lowercase, ASCII letters and digits only, hyphens between words, no street type if it makes the slug too long. Example: `22-dial-road-penguin`. Also create an empty `photos/` subfolder inside it.

Drop a small `session.json` at the root of the session folder so the rest of the system has the context:

```json
{
  "consultant_slug": "...",
  "consultant_name": "...",
  "user_email": "...",
  "address": "<the confirmed address>",
  "started_at": "<ISO-8601 UTC, e.g. 2026-05-21T14:33:00Z>"
}
```

### Step 1.3 — Hand the user the upload link

Construct the link by concatenating the base URL, the slug, and the session folder name:

    {HARCOURTS_UPLOADER_BASE_URL}/u/{HARCOURTS_CONSULTANT_SLUG}/{session-folder-name}

Send the URL in plain language. Calibrate the tone to the consultant's voice, but the substance is:

> "Session is ready. Open this on your phone, laptop, or desktop to drop in the photos and the floor plan:
>
>     {the full URL}
>
> Photos and floor plan together is fine — pick everything in one go. The page will say 'Done' when it has them. Let me know here once you're back."

Then wait for the user to come back.

### Step 1.4 — Verify the files actually arrived

When the user says they're done, do NOT trust their word alone. Look on disk yourself with `Bash` (`ls -la consultants/{slug}/sessions/{session}/photos/`). For each file:

- Anything ending `.jpg`, `.jpeg`, `.png`, `.webp` → property photo.
- Anything ending `.pdf` → likely floor plan or contract attachment.
- Any filename containing `floor`, `plan`, `fp`, or with unusual aspect ratio → likely the floor plan.
- HEIC files should not appear — the uploader converts them to JPEG automatically. If you see one, the conversion fell through (libheif missing); flag this to the operator after the session.

Report back to the user. Examples:

> "Got it. I see **8 photos** and **1 floor plan** in your session folder. Ready to brief?"
>
> "I see **6 photos** but no floor plan yet — was that intentional, or should I wait?"
>
> "The folder still looks empty. Open the link again and make sure the page shows 'Done' before switching back."

### Step 1.5 — Fallbacks if the upload page is unreachable

If `HARCOURTS_UPLOADER_BASE_URL` is empty, or the user reports the page won't load, give them the manual paths in this order:

1. **AirDrop (iPhone, in the office).** "AirDrop the photos to the Mac. They'll land in your Downloads folder; tell me when they're there and I'll move them into the session." Then move them with `mv ~/Downloads/IMG_*.jpg consultants/{slug}/sessions/{session}/photos/`.
2. **Drag into the session folder.** "Open the session folder on the Mac at this path: `consultants/{slug}/sessions/{session}/photos/`. Drop the files in." Then list the folder to confirm.
3. **Paste image URLs.** Accept publicly accessible image URLs and download them with `curl -L -o` into the photos folder.

After fallback, run Step 1.4 to verify on disk before continuing.

### Step 1.6 — Future: VaultRE pull

When the VaultRE integration is wired in (see ROADMAP.md and integrations/vaultre/ANALYSIS.md), offer a fourth path: "I can pull the photos straight from VaultRE — what's the property's reference ID or address?" For now the uploader and the manual paths are the only routes.

## Phase 2 — Analyse and brief

Tell the user: "Files received. Preparing the Sales Agent Briefing now."

Review the address and all materials. For each of these areas, write what you find or explicitly state that the information is not available:

- Property type and any research-worthy facts about the address
- Exterior style, materials, condition, kerb appeal
- Interior rooms, style, finishes
- Surrounding area, environment, landscaping, privacy
- Floor plan: room count, layout, flow

When writing the "Potential buyer objections" section below, consult shared/library/buyer-avatars.md. Identify which avatar(s) are most likely to consider this property based on type, price point, and location, then draw the objections from those avatars' "Objections and Barriers" sections.

Present this exact structure and nothing else:

    Sales Agent Briefing
    
    1. Property Snapshot
    - Type: ...
    - Key features identified: ...
    - Overall impression: ...
    
    2. Key selling points for the buyer
    - Feature plus benefit
    - Feature plus benefit
    - Feature plus benefit
    
    3. Potential buyer objections and agent responses
    - Likely avatar(s): ...
    - Objection: ...
      Response: ...
    - Objection: ...
      Response: ...

Ask: "Does this briefing meet your expectations? Approve to proceed to the listing description."

Do not continue until the user approves.

## Phase 3 — Write the listing description

Acknowledge approval. Read the active consultant's brand guide, voice rules, and learnings carefully and let them shape every sentence. Choose a single narrative angle for the property based on what you have learned.

Do not consult buyer-avatars.md for this phase. The listing description is voice-driven, not avatar-driven.

Display this pre-flight plan first:

    [✓] Persona locked to {consultant name}.
    [✓] Narrative angle: {brief statement of the angle}.
    [✓] Word count: >500 words for the body.
    [✓] Structure: scroll-stopping heading, body, call to action, disclaimer.
    [✓] No-Robot Rulebook confirmed. Banned words and phrases avoided. Australian English.

Then produce the listing using this exact template. Formatting notes:

- Do not bold or style the word "Disclaimer:". Plain text only.
- Do not write "Call to action:" as a label. Just write the call-to-action sentence on its own line.
- Do not bold any labels unless this template shows them bolded.

Template:

    [Scroll-stopping heading]
    
    [Listing body. Over 500 words. Story-rich and value-driven. Calibrated to the consultant's voice. No-Robot Rulebook applied.]
    
    For more information or to book a private inspection please call the listing agent {consultant name} today!
    
    Disclaimer: While Harcourts Ulverstone & Penguin has taken every care to verify the accuracy of the details in this advertisement, we cannot guarantee its correctness. Prospective buyers need to take such action as is necessary, to satisfy themselves of any pertinent matters.

Ask: "Here is the listing description. Approve to move on to ancillary content, or tell me what to change."

If the user gives directional feedback about the consultant's voice (not just a one-off edit), apply the change and run the /save-learning command before continuing.

## Phase 4 — Ancillary content

Generate all four pieces per shared/rules/content-formats.md based on the approved listing description:

- Brochure Text (the listing without the disclaimer)
- Window Card (3 dot points, 20 words each)
- RealEstateVIEW Guide (5 dot points, 14 words each)
- Social Media Caption (50 to 150 words, emojis required, uses the 5 RealEstateVIEW dot points, consult shared/library/buyer-avatars.md to tailor tone)

Present them together. Ask: "Approve all ancillary content, or tell me what to change."

## Phase 5 — Compile the Word document

Once everything is approved, generate a Word document at outputs/{YYYY-MM-DD}_{consultant-slug}_{address-slug}.docx per shared/rules/word-doc-spec.md. Tell the user where it has been saved. Stop.
