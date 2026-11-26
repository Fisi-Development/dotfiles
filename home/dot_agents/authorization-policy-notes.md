# Notes on Royal's shared authorization policy

Companion to `~/.agents/authorization-policy.md` (dotfiles
`home/dot_agents/authorization-policy.md`). The policy holds every rule: each
grant, limit, gate and reservation. This file holds what only explains them:
sources, dates, rationale and examples. Nothing here grants or limits anything,
and the classifier adapters do not install it. When the two seem to disagree,
the policy wins.

## Keeping the policy within its size limit

The policy has a 17,000-byte limit (Royal, 7 Nov 2026; dotfiles
`tests/test_context_budget.py`, Harbor `config/context-budget.json`), and the
same test fails once the policy is within 500 bytes of it. An addition that does
not fit is made by moving explanation from the policy to this file, never by
removing a rule. A rule is removed only on Royal's word.

On 18 Nov 2026 an addition (dotfiles `9c767ed`) cut five sentences to fit. Four
were rules whose other copies bind fewer readers (project files bind only
sessions in that project, and `~/AGENTS.md` is not fed to the classifiers), so
they were restored; the fifth, a citation, is under "Project action gates".

## Autonomous work

- Examples of device approvals: Windows Hello, Touch ID and UAC.
- Examples of first-time harness trust: Codex `/hooks` approval or OAuth login.
- See the policy's "Project action gates" for company gates.
- Examples of a short handover: "go fix X", "roll that out", "clean that up".
- Raising a Windows Hello or Touch ID request: Royal's part is the approval on
  his own device.
- Examples for ladder step 2, "Take another route": a `mesh.py request` instead
  of paste-commands, the logged-in browser instead of click-through steps,
  `mesh.py run <host> -- <command>` instead of a key path, a subagent on
  whichever host is awake.

## Authorized company GLM review

- A GPT coordinator dispatching the GLM executor: the coordinator's model does
  not determine the reviewer's destination (the policy's opening paragraph has
  executor and destination evaluated separately).
- FireRouter uses the `scout` role in `~/.agents/model-policy.toml`.
- FireRouter grant: Royal, 2026-11-10, for scouting. Its executor trial
  (2026-11-10) ended 2026-11-20, when Royal moved implementers back to Sol.
- Royal has no Claude work account, which is why unavailable GLM is reported
  rather than replaced with an invented work login.

## Review of Royal's own tools

- Royal recorded the Opus and GPT cross-family review decision on 27 Oct 2026.

## Project action gates

- Required approvals can include CODEOWNERS, cross-pod approval and any
  other applicable rule.
- Examples of decisions reserved to Royal: a fee number, the FX freeze choice,
  the load or the work split among people.
- Shared Vercel Board: Royal recorded the broad Board write gate on 23 Nov 2026.
- Own ip-fe MRs merge on the same terms since 2026-11-14 (Mark). Own apcx-pods
  MRs since 2026-11-18, Mark: "yes merge 354 and why are you waiting on me for a
  one word fix?", scope as read by the advisor thread
  (claude:7131c0c5@burnbutu); Mark may narrow it.
- The ip-gitops dev-pin grant dates from 2026-11-14.
- The default-branch retry grant: Royal, 17 Nov 2026, "one or two shots on goal
  is fine as a standing policy". The full rule, with its two-retry cap and
  red-release limit, is in infinituspay-meta `AGENTS.md`, "Outward actions".

## Royal's GitHub repositories

- Royal is an admin of github.com/Fisi-Development.
- Harbor `docs/authorizations.md` lists the repositories that moved from
  royalaid to Fisi-Development. Their old royalaid URLs redirect.

## Chezmoi rollout

- Examples of chezmoi-managed rule files: `~/.codex/rules`,
  `~/.codex-work/rules`, `~/.claude/rules`.

## Launch modes

- OpenCode has no auto reviewer. In lower modes T3 asks Royal before each
  command, edit and fetch, which stops unattended work.
- How the mode reaches a launch: `install-authorization-policy.py` writes it
  into the host's Telepathica config as `t3_runtime_modes`, one entry per
  harness, and Telepathica's handoff text names the mode it launched in.
- A native subagent is Claude's Agent tool or Codex's subagents.

## Telepathica

- Examples of results requested in a reply: command output, versions, paths,
  revisions, status and blockers.
- Harbor `docs/authorizations.md` records the Telepathica release grant on
  9 Oct 2026.
- Examples of read-only release diagnostics: `git status`, `log`, `diff`,
  `show`, `branch --show-current`, `rev-parse` and `config --get`, as well as
  `cat`, `tail`, `grep` and `ls` of release logs, the checkout and its hooks
  directory, and `telepathica choir`.
- Telepathica is Royal's own system for handing work between his agent
  sessions.
- Example of an archive request: "archive everything that's done". Archiving
  several threads in one loop is covered because `archive --undo` reverses each
  one.

