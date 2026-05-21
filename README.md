# Harcourts Listing Content Generator

A shared system on one MacBook that helps the consultants at Harcourts Ulverstone & Penguin produce property-listing content in their own voice. Staff pick a consultant, walk through a guided conversation, and the system outputs a Word document with the listing description, brochure text, window card, RealEstateVIEW guide, and social media caption. Each consultant has their own knowledge folder that starts empty and gets richer over time as the system learns from feedback.

---

## For staff: how to start a listing

There are two ways in:

- **From your phone or laptop (recommended).** See [docs/MOBILE-SETUP.md](docs/MOBILE-SETUP.md) — about ten minutes of one-time setup per device, then two icons on your home screen do the rest.
- **Directly on the office Mac.** Open Terminal, run `./scripts/create-listing.sh`, pick a consultant, enter your email, answer the questions in the chat.

Either way, the system walks you through five phases: collect inputs, sales agent briefing, listing description, ancillary content, then the final Word document. After each phase it pauses and asks you to approve before continuing.

If a consultant's profile has not been set up yet, the system will say so and offer to interview you. Plan for fifteen to twenty minutes the first time you use a new consultant.

---

## For the developer

### Folder structure

```
harcourts-listings/
├── CLAUDE.md            # Master prompt. Greets the user, picks a consultant, hands off.
├── ROADMAP.md           # Future stages (VaultRE, Canva, remote access).
├── .claude/
│   ├── settings.json    # Permission allow/deny lists.
│   └── commands/        # Slash commands (/new-listing, /onboard-consultant, ...).
├── shared/
│   ├── rules/           # Authoritative rules: security, writing, formats, workflow, word-doc spec.
│   └── library/         # Cross-consultant resources (buyer-avatars.md).
├── consultants/
│   ├── _template/       # Source-of-truth template. Copied when adding a new consultant.
│   └── {slug}/          # One folder per consultant.
│       ├── CLAUDE.md
│       ├── knowledge/
│       │   ├── brand-guide.md
│       │   ├── voice-rules.md
│       │   ├── learnings.md
│       │   └── sample-listings/
│       └── sessions/    # One folder per listing session. Gitignored except .gitkeep.
├── scripts/
│   ├── create-listing.sh
│   └── add-consultant.sh
└── outputs/             # Generated Word documents land here.
```

The authoritative rules live in `shared/rules/`. The buyer personas live in `shared/library/buyer-avatars.md`. Everything else is consultant-specific or generated.

### Onboarding mode

When a session starts inside a consultant folder, the consultant CLAUDE.md inspects `knowledge/brand-guide.md` and `knowledge/voice-rules.md`. If they still hold placeholder content, the system stops the listing workflow and offers to run `/onboard-consultant`. That command walks the user through a focused interview about voice identity, tone, signature moves, hard nos, vocabulary, structure, and past samples. Answers are written back into the knowledge files, and any pasted sample listings are saved under `knowledge/sample-listings/`.

Onboarding only needs to happen once per consultant. After that the system runs in working mode.

### Continuous learning

During any session, if the user gives directional feedback about how the consultant writes (not a one-off edit), the system runs `/save-learning`. That appends a dated rule to `knowledge/learnings.md` and commits it. Future sessions for that consultant read learnings first and treat them as voice overrides — they take precedence over the brand guide and voice rules.

To roll back a bad learning, edit `consultants/{slug}/knowledge/learnings.md` directly and commit. The git history shows every rule that was ever added.

### Adding a new consultant

Two options:

- Tell the system inside a session: `"add a new consultant called Jane Smith"` — it will run `/add-consultant` and walk you through it.
- Or from the shell: `./scripts/add-consultant.sh "Jane Smith"`. This copies the template, fills the name in, and prints the next steps.

Either way, remember to add the new name and number to the consultant list in the root `CLAUDE.md` so the master prompt offers them on the next session.

### Where the authoritative documents live

- **Security policy:** [shared/rules/security-policy.md](shared/rules/security-policy.md)
- **Writing rules (No-Robot Rulebook):** [shared/rules/writing-rules.md](shared/rules/writing-rules.md)
- **Ancillary content formats:** [shared/rules/content-formats.md](shared/rules/content-formats.md)
- **5-phase listing workflow:** [shared/rules/workflow.md](shared/rules/workflow.md)
- **Word document spec:** [shared/rules/word-doc-spec.md](shared/rules/word-doc-spec.md)
- **Buyer avatars:** [shared/library/buyer-avatars.md](shared/library/buyer-avatars.md)

Do not paraphrase or split these documents. If a change is needed, edit the file in place and commit. Every consultant prompt references them by path.

---

## Troubleshooting

### "The system says the profile is empty when it should not be"

Open `consultants/{slug}/knowledge/brand-guide.md` and `voice-rules.md` in a text editor. If they still contain the "to be filled" placeholders or are mostly empty, the system is correct: that consultant needs onboarding. If they look populated but the system still treats them as empty, check that the placeholder phrase "to be filled" was not left behind — the onboarding command replaces it.

### "Word document generation failed"

Make sure `python-docx` is installed in whatever Python environment the system is using. The Word spec lives at [shared/rules/word-doc-spec.md](shared/rules/word-doc-spec.md). If emojis in the Social Media Caption are not rendering, the issue is usually a missing colour-emoji font on the host machine.

### "I want to roll back a learning that was a mistake"

Open `consultants/{slug}/knowledge/learnings.md`, delete the offending dated section, save, and commit. The full git history is preserved on the branch, so the rule is never truly lost — you can always look it up if it turns out to have been right after all.

---

## What is out of scope today

See [ROADMAP.md](ROADMAP.md). VaultRE integration, Canva graphics, push-back into VaultRE, and remote access are tracked there.
