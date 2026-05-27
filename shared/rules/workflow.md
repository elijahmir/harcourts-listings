# 5-Phase Listing Workflow

Run these phases in order. Do not skip ahead. After each phase, present the result to the user and wait for approval before continuing.

## Phase 1 — Collect inputs

This phase has two parts: confirm the address, and verify the property photos and floor plan have been uploaded. Move to Phase 2 only after the files exist in the session folder.

> **About this flow.** The chat UI handles uploads via the paperclip button under the message input. The backend creates the session folder on first upload and converts HEIC → JPEG automatically. You do **not** construct an upload URL, mkdir the session folder yourself, or write a `session.json` — the backend takes care of those.

### Step 1.1 — Confirm the address

Ask: "What is the full property address?" Wait for the answer.

When the user replies, repeat the address back in one short sentence so they can catch a typo. Example: "Got it — 22 Dial Road, Penguin TAS 7316. Correct?"

### Step 1.2 — Ask for photos and floor plan via the chat's attachment button

Tell the user, calibrated to this consultant's voice, something like:

> "Great. To put the listing together I need property photos (interior + exterior + any aerials) and the floor plan if you have it. Use the **paperclip button** below the message input to attach them — multiple files in one go is fine, or send them across in batches. Let me know once you're done."

Then wait. Do not press ahead until the user has attached files.

### Step 1.3 — Verify files arrived

When the user attaches files via the chat UI, their next message will arrive with a header at the top like:

    📎 Attached N file(s) to `consultants/{slug}/sessions/session-XXXXXXXX/photos/`:
    • photo-1.jpg
    • floorplan.pdf

That is your signal. Read the file list straight from the header — no need to `ls` the folder yourself. For each file:

- `.jpg`, `.jpeg`, `.png`, `.webp` → property photo.
- `.pdf` → likely floor plan or contract attachment.
- Anything with `floor`, `plan`, or `fp` in the name → the floor plan.
- `.heic` files should not appear — the backend converts to JPEG. If you see one, the conversion fell through; flag it to the operator after the session.

Acknowledge in plain language, in this consultant's voice. Examples:

> "Got it — 8 photos and a floor plan in your session folder. Ready to brief?"
> "I see 6 photos but no floor plan yet — happy to proceed without it, or do you want to grab one first?"

If the user says "done" but no `📎 Attached` header arrived, reply: "I haven't received any files yet — try attaching via the paperclip again, or tell me if the upload isn't cooperating and I'll suggest a workaround."

### Step 1.4 — Fallbacks if the chat upload won't work

If the user can't attach via the paperclip (mobile flake, network issue, locked browser), use one of these:

1. **AirDrop (iPhone, in the office).** "AirDrop the photos to the Mac — they'll land in your Downloads folder. Tell me when they're there and I'll move them into the session." Then move with `Bash(mv ~/Downloads/IMG_*.jpg <session-folder>/photos/)` (requires `Bash(mv ./consultants/**)` in `.claude/settings.json`).
2. **Drag into the session folder.** "Open `consultants/{slug}/sessions/<session-folder>/photos/` in Finder on the Mac and drop the files there." Then `ls -la` that folder to confirm.
3. **Paste image URLs.** Accept publicly accessible image URLs and download them with `curl -L -o` into the photos folder.

The session-folder name is whatever appeared in the most recent `📎 Attached` header. If no files have been uploaded yet, you can ask the user to send a single file via the paperclip first so the backend creates the folder — or `mkdir -p consultants/{slug}/sessions/session-<short-id>/photos/` yourself and tell the user the path.

After any fallback, run the Step 1.3 verification before continuing.

### Step 1.5 — Future: VaultRE pull

When the VaultRE integration is wired in (see ROADMAP.md and integrations/vaultre/ANALYSIS.md), offer a third path: "I can pull the photos straight from VaultRE — what is the property's reference ID or address?" For now the chat upload and the manual fallback are the only routes.

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

## Phase 5 — Hand the listing off to the user

Once Phase 4 is approved, do NOT auto-generate a Word document. The Word document is now an on-demand export, not a default step. Instead:

1. Present a single consolidated assistant message containing the final listing in this exact shape, so the Sales App can parse it and the user can save it to the listings repo with one click:

       **Address:** {full address}

       **Headline:** {scroll-stopping heading}

       ## Listing
       {Listing body, over 500 words, with the call-to-action and disclaimer per Phase 3.}

       ## Brochure Text
       {Listing without disclaimer.}

       ## Window Card
       {3 dot points, 20 words each.}

       ## RealEstateVIEW Guide
       {5 dot points, 14 words each.}

       ## Social Media Caption
       {50–150 words, emojis, uses the 5 dot points.}

2. End the message with this exact prompt to the user, on its own line:

       Tap "Save as listing" below to add this to your listings repo, or tell me what to change.

3. STOP. Do not generate the .docx file unless the user explicitly asks ("give me the Word doc", "export as docx", "send the .docx").

If the user later asks for a Word document, generate it at outputs/{YYYY-MM-DD}_{consultant-slug}_{address-slug}.docx per shared/rules/word-doc-spec.md and mention the filename so the chat's download chip renders. The saved listing in Supabase is the source of truth; the .docx is a downstream export.
