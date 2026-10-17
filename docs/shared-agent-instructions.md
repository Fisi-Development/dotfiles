# Maintain shared agent instructions

Edit `~/AGENTS.md` for shared working preferences. Codex and OpenCode use symlinks to that file, and `~/.claude/CLAUDE.md` imports it with `@~/AGENTS.md`.

## Why Claude imports `~/AGENTS.md` by its real path

Claude Code (checked on 2.1.302) has an `instructionFiles` setting whose default, `claude-md-or-agents-md`, loads AGENTS.md files as project instructions when no CLAUDE.md exists in the cwd's ancestors. Almost every session runs under the home folder, so in a repo without its own CLAUDE.md (Harbor, scratch folders) it picks up `~/AGENTS.md` too. It skips a file whose path is already loaded, but compares paths without resolving symlinks, and it compares content only against project files, not the user CLAUDE.md's imports.

The import used to be `@~/.codex/AGENTS.md`, a symlink to the same file, so those sessions loaded the agreement twice (about 4.8k tokens extra). Importing `@~/AGENTS.md` makes the paths match and the walk-up copy is dropped. Keep the import rather than relying on the walk-up load: sessions outside the home folder (`C:\ProgramData\...`, `C:\hfi-green`) and repos with their own CLAUDE.md get the agreement only through it.

To check, run a one-shot session from a folder under home with no CLAUDE.md and ask it to list its `Contents of` headers; `~/AGENTS.md` should appear once.

## Source layout

`.chezmoiroot` selects `home/` as the deployable source directory. The repository's root `AGENTS.md`, `CLAUDE.md`, and `docs/` stay outside that directory.

| Source entry | Deployed path | Purpose |
| --- | --- | --- |
| `home/encrypted_AGENTS.md.age` | `~/AGENTS.md` | Shared working agreement |
| `home/dot_codex/symlink_AGENTS.md.tmpl` | `~/.codex/AGENTS.md` | Link to the shared agreement |
| `home/dot_config/opencode/symlink_AGENTS.md.tmpl` | `~/.config/opencode/AGENTS.md` | Link to the shared agreement |
| `home/private_dot_claude/encrypted_CLAUDE.md.age` | `~/.claude/CLAUDE.md` | Shared import and Claude-specific notes |

The symlink templates use `.chezmoi.homeDir`, so they resolve against each machine's home directory. Changes to the live agreement reach both symlinks immediately, but chezmoi stores a snapshot until the next `add`.

## Capture local edits

After editing the agreement, update its encrypted source:

```sh
chezmoi add --encrypt ~/AGENTS.md
```

To capture changes to either symlink, preserve its type and template the home path:

```sh
chezmoi add --template-symlinks ~/.codex/AGENTS.md ~/.config/opencode/AGENTS.md
```

Review the source diff before committing. Keep decrypted instruction snapshots outside the repository.

## Apply on another machine

Restore the existing age identity before applying encrypted files. Windows also needs permission to create symbolic links, such as Developer Mode or an elevated shell.

Review and apply only the instruction targets:

```sh
chezmoi diff ~/AGENTS.md ~/.codex/AGENTS.md ~/.config/opencode/AGENTS.md ~/.claude/CLAUDE.md
chezmoi apply --parent-dirs --dry-run --verbose ~/AGENTS.md ~/.codex/AGENTS.md ~/.config/opencode/AGENTS.md ~/.claude/CLAUDE.md
chezmoi apply --parent-dirs ~/AGENTS.md ~/.codex/AGENTS.md ~/.config/opencode/AGENTS.md ~/.claude/CLAUDE.md
chezmoi verify ~/AGENTS.md ~/.codex/AGENTS.md ~/.config/opencode/AGENTS.md ~/.claude/CLAUDE.md
```

Use the equivalent home paths in the active host's shell. A broad apply also changes unrelated managed configuration.

OpenCode refreshes global instructions before the next model request. Start a new Codex session to load the updated agreement. Repository-specific instructions still apply.

## Migration from the previous layout

The September 2026 refactor moved deployable files into `home/` without changing their destination paths. The Codex path became a symlink to the shared `home/encrypted_AGENTS.md.age`. The Git history retains the earlier instruction versions and the September 5 rebuild notes.

The first shared snapshot (`98b0b08`) was a refactor of the Mac's `~/AGENTS.md`, not of the Windows-authored `dot_codex/encrypted_AGENTS.md.age` it replaced, so it dropped rules that the September 5 rebuild had kept on purpose. The next commit restored them in the new style: the `:(` fix request, skill precedence, push and merge authorization, PR check follow-through, the Windows host section, and the Codex-specific section. When merging instruction changes from another host, compare against the snapshot being replaced as well as the live file on the host doing the edit.

The HTML before-and-after board is saved as `docs/agents-refactor-board.html.age`. It embeds instruction text, so it uses the same encryption as the source snapshots. From the repository root, decrypt it to a local file:

```sh
chezmoi decrypt docs/agents-refactor-board.html.age --output ~/agents-refactor-board.html
```

Open the resulting HTML file in a browser.
