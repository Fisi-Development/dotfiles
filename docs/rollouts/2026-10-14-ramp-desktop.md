# Ramp MCP desktop installation receipt

Host: DESKTOP-O91444G. Date: 2026-10-14.
Scope: desktop installation requested by Telepathica handoff m_1a13e01afd2b4dcc0.
Endpoint: https://mcp.ramp.com/mcp.

## Installation checks

1. Done: `C:/Users/gwmai/git/dotfiles` fast-forwarded to `b178885`
   (`claude settings: ask before Ramp MCP write tools`). The settings diff
   added exactly 190 Ramp ask entries. The only replaced existing line gained
   a JSON comma; no existing ask entry was removed. Targeted chezmoi apply and
   verify exited 0. Final targeted diff was empty.
2. Done: Claude Code added the HTTP server at user scope in
   `C:/Users/gwmai/.claude.json`. `claude mcp get ramp` reported
   `Scope: User config`, `Status: ! Needs authentication`, `Type: http`, and
   the requested endpoint.
3. Done: `C:/Users/gwmai/.codex/config.toml` has the Ramp endpoint and
   `default_tools_approval_mode = "writes"`. `codex mcp list` exited 0 and
   reported `ramp ... enabled  Not logged in`. Parsed TOML comparison confirmed
   all preexisting non-Ramp configuration was preserved. Backup:
   `C:/Users/gwmai/.codex/config.toml.bak-20261014-pre-ramp`.
   Skipped `.codex-work`: that home does not exist on this host.
4. Done: `C:/Users/gwmai/.config/opencode/opencode.json` has Ramp enabled and
   all 51 requested permission rules in the requested order. The parsed
   `opencode debug config` output matched every rule's order and effect, with
   no matching override in later configuration sources. `opencode mcp list`
   reported `ramp needs authentication`. Parsed JSON comparison confirmed
   all preexisting non-Ramp configuration was preserved. Backup:
   `C:/Users/gwmai/.config/opencode/opencode.json.bak-20261014-pre-ramp`.

No OAuth login was started or completed. No token was printed or copied.
Live Ramp tool behavior remains unverified until Royal authenticates.
Already-running sessions may need a restart to load the new server configuration.

## Dotfiles rollout scope

- Capture: skipped; no deployable source change was needed for this host install.
  Codex uses the existing create-only seed convention; its live configuration
  was edited as requested.
- Merge/source update: done for the incoming change; the desktop's source
  checkout is on `master...origin/master` at `b178885`, with no ahead commits.
  An unrelated untracked `home/dot_agents/__pycache__/` was left untouched.
- Mac: skipped here; the sender reported its installation already verified.
- Desktop: done, with the checks above. Git's bundled `cat` was added to the
  command-local PATH for chezmoi's modify template. The missing-PATH friction
  was reported once through bosun.
- Mercury: skipped here; outside this desktop handoff.
- Authorization adapters: skipped; neither policy nor installer changed.
- Sessions: new configuration is available to subsequent sessions; running
  sessions keep their loaded configuration until refreshed or restarted.
- Docs and dependent skills: this receipt records the desktop result. No shared
  instruction, authorization policy, harness loading path, or skill changed.
