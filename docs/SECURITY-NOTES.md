# Security notes — Claude-from-chat operating envelope

This file documents what's enforced today, what relies on the operator,
and what to paste into `.claude/settings.json` to tighten the chat
agent's Bash surface.

## Trust model recap

The chat backend spawns `claude --print --permission-mode bypassPermissions`
per user turn. `bypassPermissions` auto-approves every tool call EXCEPT
what's in `.claude/settings.json`'s `permissions.deny` list — that deny
list is the **only** thing between an in-chat user and the host
filesystem. Two layers reinforce it:

1. **`--strict-mcp-config --mcp-config services/backend/config/empty-mcp.json`**
   blocks every MCP server in the host's user-level config (Docusign,
   Gmail, Google Drive, Supabase, etc.) so they can't be reached from
   chat regardless of what the user types.
2. The per-spawn system prompt (`runner.py::_chat_ui_context`)
   instructs Claude to confirm destructive ops in plain English before
   running them, and to treat attachment contents as untrusted data
   rather than instructions.

Neither of these are belt-and-suspenders sufficient on their own —
the deny list is the wall.

## Recommended `.claude/settings.json` deny additions

The current deny list covers `rm -rf`, `git push`, `git reset --hard`,
and shared/.claude/.gitignore/CLAUDE.md writes. The entries below
extend that to the categories most likely to be invoked through prompt
injection or a careless user request. Paste each into the `permissions.deny`
array — duplicates are harmless.

```json
{
  "permissions": {
    "deny": [
      // --- destructive filesystem ---
      "Bash(rm:*)",
      "Bash(rmdir:*)",
      "Bash(find * -delete:*)",
      "Bash(dd:*)",
      "Bash(mkfs:*)",
      "Bash(shred:*)",

      // --- privilege escalation ---
      "Bash(sudo:*)",
      "Bash(su:*)",
      "Bash(doas:*)",
      "Bash(chmod:*)",
      "Bash(chown:*)",
      "Bash(setfacl:*)",

      // --- code execution from network ---
      "Bash(curl * | sh*)",
      "Bash(curl * | bash*)",
      "Bash(wget * | sh*)",
      "Bash(wget * | bash*)",
      "Bash(npx -y *)",
      "Bash(npm install -g:*)",
      "Bash(pip install:*)",
      "Bash(pipx install:*)",
      "Bash(brew install:*)",
      "Bash(brew uninstall:*)",

      // --- exfiltration paths ---
      "Bash(scp:*)",
      "Bash(rsync * ::* :*)",
      "Bash(ftp:*)",
      "Bash(sftp:*)",

      // --- destructive git ---
      "Bash(git push --force:*)",
      "Bash(git push -f:*)",
      "Bash(git reset --hard:*)",
      "Bash(git clean -f:*)",
      "Bash(git checkout -- :*)",
      "Bash(git restore .:*)",

      // --- shell escapes ---
      "Bash(eval:*)",
      "Bash(exec:*)",
      "Bash(source /:*)",
      "Bash(. /:*)",

      // --- direct API / DB bypass attempts (force use of CLI wrappers) ---
      "Bash(sqlite3:*)",
      "Bash(curl * api.vaultre.com*)",
      "Bash(curl https://api.vaultre*)",
      "Bash(curl http://api.vaultre*)",
      "Bash(wget * api.vaultre.com*)",
      "Bash(curl * /api/v1*)",

      // --- credential / env extraction ---
      "Bash(cat .env*)",
      "Bash(cat *.env)",
      "Bash(cat ./.env*)",
      "Bash(head .env*)",
      "Bash(tail .env*)",
      "Bash(printenv:*)",
      "Bash(env)",
      "Bash(set | grep:*)",
      "Read(./.env)",
      "Read(./.env.*)",
      "Read(./services/backend/.env*)",

      // --- writes to anywhere outside the consultant's session folder ---
      "Write(/Users/**)",   // catch absolute-path writes
      "Write(/etc/**)",
      "Write(~/**)",
      "Edit(/Users/**)",
      "Edit(/etc/**)",
      "Edit(~/**)"
    ]
  }
}
```

After pasting, the consultant chat still works fine — the `allow` list
already permits reads anywhere under `./consultants/**`, `./shared/**`,
`./outputs/**`, and writes/edits under `./consultants/**` + `./outputs/**`.
Those are inside the project root and aren't matched by the new
absolute-path Write/Edit denies above.

## Things the deny list **cannot** prevent

If you want to lower the residual risk further, these are the surfaces
worth a second look:

- **`Bash(./scripts/vaultre.sh:*)`** and **`Bash(./scripts/research.sh:*)`**
  are allowed (you'll need to add the research one). Both are
  controlled CLI wrappers — vaultre hits VaultRE with a read-only
  token; research wraps the google-ai-mode skill which scrapes Google
  AI Mode via a headless browser. Worst case for either is a 4xx from
  the remote service. Adequate.

  Paste-ready additions for the **allow** list in `.claude/settings.json`:

  ```json
  "Bash(./scripts/research.sh:*)",
  ```
- **`Bash(mv:*)`** is allowed for consultant-folder organisation. A
  malicious user could in principle ask Claude to mv a file outside
  the project root. The system prompt says don't, but `mv` is generic.
  If you want this tighter, change the allow to
  `Bash(mv ./consultants/** ./consultants/**)` (scope source AND dest).
- **The Read tool reads anything**. Claude can `Read` `/etc/passwd` if
  asked. Macs don't have anything sensitive at well-known paths, but
  consider denying `Read(/Users/elijahmirandilla/.ssh/**)`,
  `Read(/Users/elijahmirandilla/Library/**)` for paranoid mode.

## Production deployment (Neo)

On Neo, run with `HARCOURTS_REQUIRE_AUTH=true` and a Supabase JWT
secret set — that closes the network perimeter. The deny list above
is the second wall, in case a logged-in teammate ever pastes
something hostile (intentionally or via an attachment). Wall + wall
≈ defense in depth.
