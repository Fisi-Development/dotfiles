# Shared authorization policy

`home/dot_agents/authorization-policy.md` is the canonical policy. Deploy only
that file and `home/dot_agents/install-authorization-policy.py` with chezmoi,
then run `python3 ~/.agents/install-authorization-policy.py` to preview and
`python3 ~/.agents/install-authorization-policy.py --apply` to merge adapters
into existing machine-local settings. Requires Python 3.11 or newer (standard-library TOML parser). Windows may use
`python` or `py -3`.
Use a fresh session after installation. A second preview must have no changes.

The machine-local `~/.agents/authorization-adapter-state.json` records the exact
Claude entries the installer owns, so regeneration removes only those entries.
Existing custom arrays without `$defaults` stop for reconciliation instead of
being silently changed. Existing OpenCode JSON permission entries retain their
effect; a JSONC layer above existing JSON permissions stops for reconciliation.
Malformed marker blocks stop before any write, with one exception: Codex
rewrites `config.toml` and may drop the end marker or both markers, and the
installer adopts an `[auto_review]` table that holds only the shared policy
text. File replacement preserves links
and is atomic per file, with concurrent-edit checks before application and before each replacement.
Coordinate a single config writer: filesystem replacement is not a compare-and-
swap against an uncooperative editor in the final check/replace interval. The
multi-file update is not transactional; rerun after an interrupted application.

The installer embeds the same Markdown in Codex's additive
`auto_review.extra_policy` after a fixed authorization preamble, and Claude's
top-level `autoMode.environment` with `$defaults`. Claude's `allow` entry is
extracted from the authorized-review, "Royal's GitHub repositories",
"Telepathica commands", "Chezmoi rollout" and "Launch modes" sections, since
`allow` entries are the classifier's exceptions to its soft blocks (External System Writes,
Create Public Surface, Production Deploy).
Shared agent entry points reference the canonical file.

The installer writes `t3_runtime_modes` from the agent-guard current check into
`~/.telepathica/config.json`, or `~/.agent-mailbox/config.json` when only that
file exists. Only harnesses agent-guard hooks follow the check: Claude, and
OpenCode where `~/.config/opencode/plugins/agent-guard.ts` exists (OpenCode is
set to `auto` without it). It leaves the Codex entry as it is. It prints only that map
from the config and keeps no backup copy of that file, which holds the hub
token. `--guard-bin` and `--updater-state` are refused for the real home. An astropath from
Telepathica agent-mailbox#146 on re-reads the map each scan; an older one
needs a restart.

Since 0.5.0 agent-guard ships only as successful `main` push builds of
`.github/workflows/agent-guard.yml` in Fisi-Development/harbor, which the root
updater installs (Harbor `skills/agent-guard/references/rollout.md`,
"Automatic rollout"); the `agent-guard-v*` tags stop at 0.4.4. So the newest
version comes from the updater's own record, `agent-guard-updater/state.json`
beside the guard (`C:\Program Files\ClaudeCode` or
`/Library/Application Support/ClaudeCode`). Each updater run, every 15
minutes, writes there as `release_considered` the version of the newest run it
accepts (actor `royalaid`, conclusion success, head on `main`, version from
`Cargo.toml` at that commit), before it decides whether to install it. Only
SYSTEM or root can write that file, so a user process cannot fake it, and it
needs no GitHub login of its own. The guard counts as current when the live
binary's `--version` is at least that version. A missing or unreadable record,
one older than two hours or dated in the future, a run that never reached a
candidate (for example `http_failed`), or on macOS a record or folder not owned
by root or writable by others, gives no answer, and the mode is auto.

Two chezmoi-managed rule layers sit beside the adapters for Telepathica's
commands that carry no message body (`find`, `inbox`, `thread`, `whoami`,
`ack`, `archive`): `home/private_dot_claude/modify_settings.json` adds
`permissions.allow` prefix rules (Bash and PowerShell), which Claude resolves
before the auto-mode classifier, and `home/.chezmoitemplates/telepathica.rules`
installs a Codex `prefix_rule` allow (outside the sandbox) in `~/.codex/rules`
and, where it exists, `~/.codex-work/rules`. Codex splits only `bash`/`zsh`/`sh
-c` scripts for rules, so on Windows, where it wraps commands in `pwsh -Command`,
Telepathica still reaches the astronomican through sandbox escalation that
auto-review judges against the policy. `send`, `notify`, `reply`, and
`release` always go through the classifier or auto-review, which apply the
policy's payload limits. Existing
settings, providers, hooks, and deny/ask rules remain intact. Existing unmanaged
Codex auto-review or OpenCode JSONC instruction/permission settings require
manual reconciliation; the installer stops rather than overwrite them.

OpenCode loads the file through global `instructions`. Its native URL prompts
cover direct `webfetch` requests to OpenRouter/Fireworks inference endpoints.
They cannot enforce model-provider routing, arbitrary shell HTTP requests,
wrapper commands, payload classification, or project merge/deploy semantics.
OpenCode has no equivalent semantic approval classifier. Inspect the effective
GLM agent and provider base URL before review. Never substitute an advertised
OpenRouter model for the authorized company alias.

The installer changes only homes that exist and Codex configs already present.
Discover the homes used by T3 and environment variables on each host. Its
standard home names are not proof of the loaded paths. Backups preserve the
pre-install files; they remain machine-local and may contain credentials.
Do not commit or print them. Capture changed shared instruction snapshots with
`chezmoi add --encrypt`; machine-local adapter settings stay untracked. Run the
installer again after policy updates or changes to loaded homes.

Verify effective Codex `config/read` and `configRequirements/read`, Claude
`auto-mode config` (no model invocation), and OpenCode `debug config` / agent
metadata. Hash loaded policy text. Verify actual fresh parent/child instruction
loading separately. Semantic model checks with inert requests are separate from
config validation; do not call either a production classifier verdict. Never
execute negative-control requests. Claude model probes remain unavailable while
the personal subscription is exhausted.

References: [Codex config](https://learn.chatgpt.com/docs/config-file/config-reference),
[Claude auto mode](https://code.claude.com/docs/en/auto-mode-config),
[OpenCode permissions](https://opencode.ai/docs/permissions/),
[OpenCode rules](https://opencode.ai/docs/rules/).
