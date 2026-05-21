The user has given directional feedback about the active consultant's voice, style, or workflow. Persist it.

1. Identify the active consultant from the current working directory.
2. Distil the feedback into a single durable rule (one or two sentences). It must be actionable: a future session can apply it without needing the original context.
3. Append to consultants/{slug}/knowledge/learnings.md in this format:

       ## YYYY-MM-DD HH:MM — {short title}
       Trigger: {brief context from this session}
       Rule going forward: {actionable rule}

4. Confirm to the user: "Saved as a {consultant} voice rule."
5. Stage and commit: git add consultants/{slug}/knowledge/learnings.md && git commit -m "learning: {short title} for {consultant}"

Do not save trivial one-off edits. If unsure whether something is durable or trivial, ask the user.
