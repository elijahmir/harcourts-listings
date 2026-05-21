Add a new consultant to the system.

1. Ask for the full name.
2. Generate a slug in kebab-case.
3. Confirm the slug is unique under consultants/.
4. Copy consultants/_template/ to consultants/{new-slug}/.
5. Replace every {CONSULTANT_NAME} placeholder in the new folder with the full name.
6. Update the master CLAUDE.md to add the new consultant to the numbered list.
7. Commit: "feat: add consultant {full name}".
8. Ask the user: "Want to onboard {name} now? I can walk you through it." If yes, run /onboard-consultant.
