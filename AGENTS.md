# dotfiles (chezmoi source repo)

This repo manages dotfiles for Windows, macOS, and Linux. `.chezmoiroot` selects `home/` as the deployable source state. This root `AGENTS.md` contains repo-specific guidance and stays outside the deployment tree.

Shared conventions live in `~/AGENTS.md`, stored as `home/encrypted_AGENTS.md.age`. Codex and OpenCode use symlinks to that file. Claude imports `~/AGENTS.md` directly, not through the Codex symlink, so Claude Code's walk-up AGENTS.md load dedupes against it by path. Read `docs/shared-agent-instructions.md` when changing these files or their loading paths.

## chezmoi gotchas

- **Source filenames determine target paths.** Under `home/`, `dot_x` maps to `~/.x`, `private_*` sets private permissions, and `encrypted_*.age` decrypts on apply. Renaming a source entry can move a real dotfile on the next apply.
- **Keep repo docs outside `home/`.** Root `AGENTS.md`, `CLAUDE.md`, and `docs/` stay local to this repo. Unprefixed deployable files belong under `home/`. Check `chezmoi status` and a targeted `chezmoi apply --dry-run` before applying.
- **Age encryption:** `home/.chezmoi.toml.tmpl` pins the public recipient. Restore the private identity at `~/.config/chezmoi/key.txt` out of band before `chezmoi init`.
- **Fish plugin files stay untracked.** `home/dot_config/private_fish/fish_plugins` is the source of truth. The `run_onchange` script reconciles plugins through fisher. Tracking generated plugin files caused "file already exists" failures. Preserve the exclusions in `home/.chezmoiignore`.

## Landmine: tracked agent-config snapshots drift from the live files

`home/encrypted_AGENTS.md.age` and `home/private_dot_claude/encrypted_CLAUDE.md.age` are snapshots of the live instructions. Edits on a host do not update those snapshots automatically. Compare source and live content before applying. After editing the live shared agreement, use `chezmoi add --encrypt ~/AGENTS.md` to capture it.

Codex and OpenCode entry points are symlink templates. Preserve the links when adding them with `--template-symlinks`. Claude settings remain machine-local and excluded in `home/.chezmoiignore`.

The authorization installer writes `~/.agents/authorization-policy.md`, a home-relative path, into both snapshots, so they are identical on every host. Keep it home-relative: an absolute path makes the other host's apply show drift.

`home/dot_codex/create_config.toml` seeds a fresh host only. Codex rewrites its config constantly (runtime paths, hook hashes, the installer's `auto_review` block), so chezmoi never overwrites or diffs an existing one. Refresh the seed with `chezmoi add` on the `create_` source when a fresh host should start from newer settings.

## Shell config portability

These configs deploy to macOS as well as Windows/Linux, so anything added to `home/dot_bashrc`, `home/dot_zshrc`, `home/dot_zprofile`, or the fish config has to work against **BSD userland**: avoid GNU-only flags (`head -n -2`, `sed -i` without a backup arg, `date -d`), or guard on `gtail`/`gsed` from coreutils.

## Commits here

Short imperative subjects, and **no AI co-author / attribution trailers** — for Claude Code and Codex alike. This overrides the default harness behavior, which appends a `Co-Authored-By` trailer.

## Rollout

A change reaches a host only when that host's source checkout has it and chezmoi applies it there. Each host keeps its own checkout: the Mac (`bouncehouse`) at `~/.local/share/chezmoi`, the PC (`DESKTOP-O91444G`) and the laptop (Mercury) at `~/git/dotfiles` (Windows, set in `home/.chezmoi.toml.tmpl`). WSL on the PC is retired as a client host (2026-10-08) and gets no rollout. Run these steps in order. A step that does not apply to the change is skipped, and the receipt says why. Each step is done when its check passes.

`<targets>` below means the deployed paths the change touches. List them from the merged range with `git diff --name-only <old>..<new> -- home/`, then map each with `chezmoi target-path <source file>`.

1. **Capture.** A change made in a live file goes into the source first: `chezmoi add --encrypt ~/AGENTS.md` or `chezmoi add --encrypt ~/.claude/CLAUDE.md` for the encrypted snapshots, `chezmoi add <path>` for a plain file. From a branch worktree, add `--source <worktree>/home`, since chezmoi otherwise writes into the host's checkout. Check: `chezmoi diff <targets>` prints nothing on the editing host.
2. **Merge.** Commit without attribution trailers. Merge the PR with `gh pr merge <PR> -R royalaid/dotfiles --squash --delete-branch`, or push `master` directly. Check: `git -C <source checkout> status -sb` shows `## master...origin/master` with nothing ahead, and `git log -1 origin/master` is the change.
3. **Apply on the Mac.** Apply only `<targets>`: a broad `chezmoi apply` also rewrites unrelated files that drift on purpose (`chezmoi status` lists them).
   ```sh
   git -C ~/.local/share/chezmoi pull --ff-only
   chezmoi diff <targets>
   chezmoi apply --parent-dirs <targets>
   chezmoi verify <targets>
   ```
   Read the `chezmoi diff` before applying. It must show only the incoming change; a hunk that removes text means the live file holds edits nobody captured (see the landmine above), so stop and report it. Check: `chezmoi verify <targets>` exits 0.
4. **Apply on the PC.** Hand step 3 to `codex@dotfiles@desktop-o91444g` over Telepathica, with the checkout at `~/git/dotfiles`. Creating the Codex and OpenCode symlinks needs Developer Mode or an elevated shell. Check: `chezmoi verify <targets>` exits 0 there.
5. **Apply on Mercury.** Mercury's client updater (Harbor `ops/clients/mercury-tools.json`, every 15 minutes while awake) pulls `~/git/dotfiles` and applies safe target changes, as own-tools-sync does on the other hosts. Hand the check, and any target it reports as drift, to `claude@dotfiles@mercury` over Telepathica, with the checkout at `~/git/dotfiles`. Mercury sleeps often: send it and do not wait. Some targets are deliberately desktop-only (paths under `C:/Users/gwmai`, Hermes): `chezmoi diff` must show only the incoming change, and a target Mercury does not use is skipped and named in the receipt. Check: `chezmoi verify <targets>` exits 0 there.
6. **Authorization adapters.** Applies when `home/dot_agents/authorization-policy.md` or `home/dot_agents/install-authorization-policy.py` changed. On each host, after step 3, 4 or 5, run `python3 ~/.agents/install-authorization-policy.py` to preview, then the same with `--apply` (`docs/shared-authorization-policy.md`). Check: a second preview reports no changes.
7. **Sessions.** Codex and Claude Code read the shared agreement at session start; OpenCode rereads it before each request. Check: none; say in the receipt that sessions already running keep the old text.
8. **Docs and dependent skills.** `docs/shared-agent-instructions.md` and `docs/shared-authorization-policy.md` still describe the layout. A skill that restates or points at the changed rule still matches it: `grep -rl '<phrase>' ~/git/skills --include='*.md' --exclude-dir=docs`, then that repo's Rollout section. `~/git/apcx-agent-workspace/royalaid/config/` holds a dated, redacted snapshot of some harness config; it is edited by hand, not synced, and needs an edit only when the change alters something it shows. Check: each hit was read and still holds, or its fix rolled out.

Finish with a receipt: each step marked done with its check output, skipped with the reason, or blocked with the failing output.
