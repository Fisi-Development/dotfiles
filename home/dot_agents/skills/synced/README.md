# Placeholder: keep this folder empty

This folder exists so Codex's Claude Code importer leaves it alone.

Claude Code keeps the claude.ai account skills in `~/.claude/skills/synced`. Codex Desktop's importer copies each folder in `~/.claude/skills` into `~/.agents/skills` when no folder of that name exists there yet. A copy of `synced` here put thirteen claude.ai skills, some with descriptions over 900 characters, into every Codex session's skill list, past the 30,000 character listing ceiling. That happened on the desktop on 25 Nov 2026 at 21:59 PST, after the old copy was set aside.

With this folder present, the importer skips it. It holds no `SKILL.md`, so no harness lists anything from it, and skill-router's index check counts nothing here.

Managed by chezmoi (royalaid/dotfiles, `home/dot_agents/skills/synced/README.md`). Do not put skills in this folder.
