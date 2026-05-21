# 5-Phase Listing Workflow

Run these phases in order. Do not skip ahead. After each phase, present the result to the user and wait for approval before continuing.

## Phase 1 — Collect inputs

Ask: "What is the full property address?" Wait for the answer.

Create a session folder at consultants/{slug}/sessions/{YYYY-MM-DD}_{address-slug}/.

Ask: "Now please share the property photos and floor plan. You can drop the files into the session folder I just created, or paste image links. Let me know when they are ready." Confirm receipt of all materials before proceeding.

(If VaultRE integration becomes available — see ROADMAP.md — offer the user a choice between automatic pull from VaultRE and manual upload. For now, manual only.)

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
