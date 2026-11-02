# Set up subscription hub profiles

The installer creates separate client homes for the personal and work hubs without changing default clients or T3 selections. Profiles are staged until hub OAuth works. Claude subscriptions must use Claude Code; the Claude T3 instance remains disabled.

The personal hub is `https://burnbutu.royal-burbot.ts.net:8317`; the work hub uses port `8318`. Each lane has its own account and key. Royal accepted the proxy suspension risk for this setup.

## Provision and install

The parent rollout provisions keys locally over the authenticated Harbor mesh on burnbutu, bouncehouse, desktop, and Mercury. Keep credentials out of shell history, documentation, and git. The installer reads these files and never prints their values:

- `~/.config/cliproxy/personal/access-key`
- `~/.config/cliproxy/work/access-key`

Run with Python 3.11 or later:

```sh
python3 ~/.agents/bin/subscription-hub-profiles.py
```

`--home PATH` selects a different home, including a temporary test home. Without `--t3-settings PATH`, the installer creates only profiles. To stage T3 instances, pass the actual server settings JSON path:

```sh
python3 ~/.agents/bin/subscription-hub-profiles.py --t3-settings /absolute/path/to/server-settings.json
```

Once OAuth works, repeat with `--register-codex --enable-codex` to enable only `codex_hub_personal` and `codex_hub_work`. Omitting this flag stages both as disabled again. `claude_hub_personal` always stays disabled. Existing default selections, other instances, and settings are preserved. Each settings change creates a unique sibling backup before an atomic replacement; no database is changed.

## Launch a separate profile

On POSIX:

```sh
env CODEX_HOME="$HOME/.codex-hub-personal" codex
env CODEX_HOME="$HOME/.codex-hub-work" codex
env CLAUDE_CONFIG_DIR="$HOME/.claude-hub-personal" claude
```

In PowerShell, use a separate terminal for each profile. These environment variables affect that terminal's later launches:

```powershell
$env:CODEX_HOME = Join-Path $HOME '.codex-hub-personal'
codex
```

```powershell
$env:CODEX_HOME = Join-Path $HOME '.codex-hub-work'
codex
```

```powershell
$env:CLAUDE_CONFIG_DIR = Join-Path $HOME '.claude-hub-personal'
claude
```

No wrapper is required. Close the profile terminal when finished.

## Preservation and reruns

Codex profiles inherit `.codex/config.toml`; the work profile uses `.codex-work/config.toml` when available. The installer preserves source TOML except the root `model_provider` setting, then adds `model_providers.subscription_hub` with Responses transport, WebSocket support, and the lane's private bearer token. Existing `subscription_hub` source providers are rejected. It bootstraps `AGENTS.md`, `rules`, `skills`, and `hooks.json` when present.

Claude inherits `.claude/settings.json`, including hooks and permissions. Only `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` in `env` are replaced, and `ANTHROPIC_API_KEY` is removed from this profile to prevent conflicting API billing. `CLAUDE.md` and `rules` are bootstrapped when present.

OAuth auth files and session databases are not copied. With `--register-codex`, Codex stores the hub access key in its own credential cache, so T3 can recognize the profile as authenticated. The command removes `forced_login_method` and `forced_chatgpt_workspace_id` only from generated hub profiles; Royal authorized this exception for hub-key authentication. The original work config and administrator-enforced requirements stay intact. The work hub routes exclusively to its verified work account. Generated files use mode `0600`; on Windows, filesystem ACLs also determine access. Base files stay unchanged. Existing support files remain untouched on reruns. An incompatible profile config or T3 instance ID causes validation to fail before writes. Source config edits or key rotation can therefore require reconciliation of an existing profile before rerunning; the installer never overwrites those configs.
