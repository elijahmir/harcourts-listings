# Moving the project

There are two times you'd want to move the project folder:

1. **It's currently in `~/Documents`, `~/Desktop`, or `~/Downloads`.** macOS TCC silently blocks launchd-spawned services from reading those folders. ttyd and the uploader will start but never respond. The installer (`./scripts/install-host.sh`) refuses to set up services from there.
2. **You're reorganising your workspace.** Same recipe applies.

The challenge: by default, an active Claude Code chat session is bound to the folder's absolute path. Move the folder and the chat loses its reference. The official answer is to migrate via `claude-mv` and restart — fine when you're between sessions, painful mid-conversation. This doc covers both paths.

---

## Option A — move via symlink (keeps a live session alive)

This is the trick we used to get out of `~/Documents` without restarting Claude.

### Why it works

- macOS TCC operates on the **resolved (real)** path, not the symlink path.
- A live Claude Code session keeps file references in memory; if `~/old/path` still resolves (via a symlink) to the moved files, the session keeps working without a restart.
- The Antigravity IDE / Claude Desktop "project pointer" stays valid because the old path still exists as a symlink.

### Steps

```sh
# 1. Move the folder to its TCC-safe home. Keep the folder name; only the
#    parent path changes.
mv "$HOME/Documents/Claude Workstation" "$HOME/Claude Workstation"

# 2. Leave a symlink at the old location pointing at the new one. This is the
#    bit that keeps the IDE and the live session happy.
ln -s "$HOME/Claude Workstation" "$HOME/Documents/Claude Workstation"

# 3. Inside the project, blow away the stale Python venv (it hardcodes absolute
#    paths to the old location).
find services/uploader/.venv -depth -delete

# 4. Re-run the installer FROM THE REAL PATH (or from inside the symlinked
#    path — install-host.sh resolves to the real path either way).
cd "$HOME/Claude Workstation/harcourts-listings"
./scripts/install-host.sh
```

### Verifying

After the install completes, both should work from this Mac and from any Tailnet device:

```sh
curl -fsS http://localhost:8080/healthz
curl -fsS -o /dev/null -w "%{http_code}\n" http://localhost:7681/
```

Both should return success. From any other Tailnet device, replace `localhost` with the Mac's Tailnet hostname.

### Tradeoffs

- **Pro:** preserves the live chat, no restart, no metadata migration.
- **Pro:** Finder still shows the project at its old location for muscle-memory.
- **Con:** there's a hidden symlink, which can confuse some tooling (mostly things that try to `realpath` the project root expecting it to match a specific string).
- **Con:** the session metadata in `~/.claude/projects/{old-encoded-path}/` keeps growing under the old encoding. When you eventually retire the symlink, you'd also want to migrate that metadata (see Option B below).

---

## Option B — move properly with metadata migration (clean, requires restart)

Use this when you're between sessions and want everything pointing at the new location end-to-end.

### Tooling

[`claude-mv`](https://curiouslychase.com/posts/rescuing-your-claude-conversations-when-you-rename-projects/) automates the migration. It:

- Renames `~/.claude/projects/{old-encoded}` → `{new-encoded}` BEFORE moving the directory.
- Rewrites absolute path references inside the `.jsonl` session files.
- Moves the directory itself.
- Patches `~/.claude/history.jsonl` with the new paths.

Install once:

```sh
# via npm if available
npm i -g claude-mv

# or grab the bash script
curl -fsSL https://raw.githubusercontent.com/skydiver/claude-code-project-mover/main/claude-mv -o ~/.local/bin/claude-mv
chmod +x ~/.local/bin/claude-mv
```

Use:

```sh
claude-mv "$HOME/old/path/to/project" "$HOME/new/path/to/project"
```

Then in a new shell:

```sh
cd "$HOME/new/path/to/project"
claude --resume   # pick up the migrated conversation
```

### When to use this over Option A

- You don't have a live session to preserve.
- You want a single canonical path going forward (no symlink artifact).
- You're decommissioning the symlink left over from a prior Option A move.

---

## Don't bother

These don't help:

- **Granting Full Disk Access** to ttyd and the venv's Python in System Settings → Privacy & Security. Fragile (Python venv is a symlink chain; FDA grants don't follow consistently), needs re-granting after macOS updates, and a security footgun.
- **Adding `"sessionStorage": "local"` to `.claude/settings.json`.** Not shipped. Requested as a feature ([issue #22387](https://github.com/anthropics/claude-code/issues/22387)) and closed as duplicate. Don't depend on it until Anthropic ships it.
- **Hard links.** Don't work on directories.
- **Bind mounts.** macOS doesn't really support these without third-party tools.

---

## Future-proofing

If you're cloning fresh, clone outside `~/Documents`, `~/Desktop`, and `~/Downloads` from the start. Good defaults:

- `~/Code/harcourts-listings`
- `~/Projects/harcourts-listings`
- `~/Claude Workstation/harcourts-listings` (our current real path)
- `~/harcourts-listings`

The installer's `cmd_check` will refuse to set up services from any TCC-protected folder, with a clear error pointing you here.
