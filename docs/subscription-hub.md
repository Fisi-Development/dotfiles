# Set up subscription hub profiles

The installer creates client homes that send Codex and Claude through the hub without changing default clients or T3 selections. Profiles are staged until hub OAuth works. Claude subscriptions must use Claude Code; the Claude T3 instance stays disabled until its live Claude Code check passes.

There is one hub, `https://burnbutu.royal-burbot.ts.net:8317` (systemd user unit `cliproxyapi-personal`). It pools every account, the work Codex account included, so personal requests can use work quota and the reverse; Royal chose this on 2026-11-02. The former work hub (`cliproxyapi-work`, port `8318`) is stopped and disabled, and its files remain for a rollback. Royal accepted the proxy suspension risk for this setup.

## Provision and install

The parent rollout provisions keys locally over the authenticated Harbor mesh on burnbutu, bouncehouse, desktop, and Mercury. Keep credentials out of shell history, documentation, and git. The installer reads these files and never prints their values:

- `~/.config/cliproxy/personal/access-key`

Run with Python 3.11 or later:

```sh
python3 ~/.agents/bin/subscription-hub-profiles.py
```

`--home PATH` selects a different home, including a temporary test home. Without `--t3-settings PATH`, the installer creates only profiles. To stage T3 instances, pass the actual server settings JSON path:

```sh
python3 ~/.agents/bin/subscription-hub-profiles.py --t3-settings /absolute/path/to/server-settings.json
```

Once OAuth works, repeat with `--register-codex --enable-codex` to enable `codex_hub_personal`. Omitting this flag stages it as disabled again. Every run turns off the retired `codex_hub_work` instance. Add `--enable-claude` after the Claude subscription is connected and a real request through Claude Code passes. Omit it to stage Claude as disabled. Existing default selections, other instances, and settings are preserved. Each settings change creates a unique sibling backup before an atomic replacement; no database is changed.

## Launch a separate profile

On POSIX:

```sh
env CODEX_HOME="$HOME/.codex-hub-personal" codex
env CLAUDE_CONFIG_DIR="$HOME/.claude-hub-personal" claude
```

In PowerShell, use a separate terminal for each profile. These environment variables affect that terminal's later launches:

```powershell
$env:CODEX_HOME = Join-Path $HOME '.codex-hub-personal'
codex
```

```powershell
$env:CLAUDE_CONFIG_DIR = Join-Path $HOME '.claude-hub-personal'
claude
```

No wrapper is required. Close the profile terminal when finished.

## Preservation and reruns

Codex profiles inherit `.codex/config.toml`; the work profile uses `.codex-work/config.toml` when available. The installer preserves source TOML except the root `model_provider` setting, then adds `model_providers.subscription_hub` with Responses transport, WebSocket support, and the lane's private bearer token. Existing `subscription_hub` source providers are rejected. `AGENTS.md`, `rules` and `hooks.json` are links to the `.codex` originals, so chezmoi updates reach hub sessions; `skills` is copied once, because Codex writes its own `.system` skills there.

Claude inherits `.claude/settings.json`, including hooks and permissions. Only `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` in `env` are replaced, and `ANTHROPIC_API_KEY` is removed from this profile to prevent conflicting API billing. `CLAUDE.md`, `skills`, `rules`, `hooks`, `agents`, `commands` and `output-styles` are links to the matching `.claude` paths rather than copies (a symlink on POSIX; on Windows a junction for directories and a symlink for files), so new skills, chezmoi rule updates and hook scripts that `settings.json` reaches through the config directory appear in the hub profile without another run. Codex needs no link, because it reads `~/.agents/skills` whatever `CODEX_HOME` is.

To add missing support links to hub homes that already exist, without touching their configs, keys or T3 settings, run:

```sh
python3 ~/.agents/bin/subscription-hub-profiles.py --support-only
```

An existing link that points somewhere else fails the run before any write. An empty directory, or a file identical to its original, is replaced by the link. Anything else, such as a stale `rules` copy from an earlier run, is renamed to `<name>.before-link-<timestamp>` first, so nothing is deleted. A Windows host without Developer Mode cannot make file symlinks; there the file copy stays and the run says so.

OAuth auth files and session databases are not copied. With `--register-codex`, Codex stores the hub access key in its own credential cache, so T3 can recognize the profile as authenticated. The command removes `forced_login_method` and `forced_chatgpt_workspace_id` only from generated hub profiles; Royal authorized this exception for hub-key authentication. The original work config and administrator-enforced requirements stay intact. The work hub routes exclusively to its verified work account. Generated files use mode `0600`; on Windows, filesystem ACLs also determine access. Base files stay unchanged. Reruns replace a copied support path with its link only as described above, never deleting it. An incompatible profile config or T3 instance ID causes validation to fail before writes. Source config edits or key rotation can therefore require reconciliation of an existing profile before rerunning; the installer never overwrites those configs.

For an approval process with a restricted PATH, pass `--codex-binary /absolute/path/to/codex.exe`. Verify that exact executable with `--version` before requesting approval. The installer fails before changing profiles if the executable is missing.

## Unified T3 layout

On every host, T3 shows the hub instances as **Codex** (`codex_hub_personal`) and **Claude** (`claude_hub_personal`). The built-in `codex` and `claudeAgent` instances stay as disabled entries, because T3 recreates a missing built-in instance as enabled; the retired `codex_hub_work`, `codex_work` and `claudeAgent_personal` instances are removed. The default model points at `claude_hub_personal`.

**Usage → Limits** reads pooled quotas from the usage source `burnbutu_hub` on the desktop, Mercury and bouncehouse, and `burnbutu_personal` on burnbutu. Both use `https://burnbutu.royal-burbot.ts.net:8317` and the management key in `~/cliproxyapi/personal/management-key` on burnbutu. T3 moves an inline key into its secret store when it loads settings.

## Windows file permissions

Files that Codex created in the hub homes while running from a Harbor mesh session ended up with empty access lists on both Windows hosts. The T3 probe then failed with "failed to initialize sqlite state runtime" or "Access is denied". To fix it, reset every entry under the hub home to inherit the folder's permissions (`icacls <entry> /reset /T /C`), except `config.toml` and `settings.json`, which keep their owner-only access lists.

## Account order

Codex requests use the work account first and fall back to the personal account. The hub chooses from the ready accounts with the highest `priority`, so the work auth file carries `"priority": 10` and the personal one keeps the default 0. An account at its quota limit cools down and stops counting as ready, which sends new requests to the next priority until the work quota resets. Change it in the management dashboard (**Auth Files**, then the account's Priority) or with `PATCH /v0/management/auth-files/fields` and `{"name": "<auth file>", "priority": <n>}`. The value is stored in the auth file and survives restarts.
