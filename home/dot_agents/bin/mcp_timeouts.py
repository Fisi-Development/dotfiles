"""Pin per-server MCP tool timeouts for Claude Code and Codex on this host.

chezmoi runs this after every apply (run_after_mcp-timeouts.*). It is idempotent
and touches only the servers in TIMEOUTS:

- Claude Code plugin servers: sets "timeout" (ms) on the server entry in the
  installed plugin's manifest. A plugin update replaces the cache, so the next
  apply puts it back.
- Claude Code user-scope servers: re-adds the entry with "timeout" through
  `claude mcp add-json -s user`, once per definition (state in
  ~/.agents/state/mcp-timeouts.json). Entries with an env block are skipped.
- Codex: sets tool_timeout_sec in [mcp_servers.<name>] of ~/.codex*/config.toml.

Claude Code's per-server "timeout" also caps the 1,800 s no-progress idle
abort (Claude Code 2.1.303: idle = min(max(1800 s, timeout), timeout)), which is
what the 2026-10-18 tool-call audit hit on chrome-devtools new_page and
context-mode ctx_execute.

`--check` prints the effective timeout of each server it can find and exits 1
when one is missing or wrong. It reads only those numbers.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

TIMEOUTS = {'chrome-devtools': 120, 'context-mode': 300}  # seconds
HOME = Path.home()
PLUGINS = HOME / '.claude' / 'plugins'
STATE = HOME / '.agents' / 'state' / 'mcp-timeouts.json'


def plugin_manifests():
    try:
        installed = json.loads((PLUGINS / 'installed_plugins.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return
    for entries in installed.get('plugins', {}).values():
        for entry in entries if isinstance(entries, list) else [entries]:
            root = Path(entry.get('installPath', ''))
            for rel in ('.claude-plugin/plugin.json', '.mcp.json'):
                path = root / rel
                if path.is_file():
                    yield path


def server_table(doc):
    servers = doc.get('mcpServers')
    return servers if isinstance(servers, dict) else {}


def claude_plugins(check):
    found = {}
    for path in plugin_manifests():
        try:
            doc = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        servers = server_table(doc)
        changed = False
        for name, seconds in TIMEOUTS.items():
            entry = servers.get(name)
            if not isinstance(entry, dict):
                continue
            want = seconds * 1000
            if entry.get('timeout') != want and not check:
                entry['timeout'] = want
                changed = True
            found[f'claude plugin {name} ({path.parent.parent.name if path.parent.name == ".claude-plugin" else path.parent.name})'] = (entry.get('timeout'), want)
        if changed:
            path.write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
            print(f'mcp-timeouts: set plugin server timeouts in {path}')
    return found


def claude_exe():
    return shutil.which('claude')


def claude_user_servers(check):
    """User-scope servers: written through the CLI, read back from ~/.claude.json (numbers only)."""
    found = {}
    exe = claude_exe()
    if exe is None:
        return found
    try:
        state = json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        state = {}
    for name, seconds in TIMEOUTS.items():
        want = seconds * 1000
        if check:
            got = user_timeout(name)
            if got is not None:
                found[f'claude user {name}'] = (got, want)
            continue
        if state.get(name, {}).get('timeout') == want:
            continue
        spec, has_env = user_spec(exe, name)
        if spec is None:
            state[name] = {'timeout': want, 'skipped': 'not user scope'}
            continue
        if has_env:
            print(f'mcp-timeouts: {name} has an env block; set its timeout by hand', file=sys.stderr)
            continue
        spec['timeout'] = want
        run([exe, 'mcp', 'remove', '-s', 'user', name])
        if run([exe, 'mcp', 'add-json', '-s', 'user', name, json.dumps(spec)]).returncode == 0:
            state[name] = {'timeout': want}
            print(f'mcp-timeouts: re-added user server {name} with timeout {want} ms')
    if not check:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    return found


def run(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=120)


def user_spec(exe, name):
    out = run([exe, 'mcp', 'get', name]).stdout
    if 'Scope: User config' not in out:
        return None, False
    fields = dict(re.findall(r'^\s{2}(Type|Command|Args):[ \t]*(.*)$', out, re.M))
    has_env = re.search(r'^\s{2}Environment:[ \t]*\r?\n\s{4}\S', out, re.M) is not None
    if fields.get('Type') != 'stdio' or not fields.get('Command'):
        return None, False
    return {'type': 'stdio', 'command': fields['Command'], 'args': fields.get('Args', '').split()}, has_env


def user_timeout(name):
    try:
        doc = json.loads((HOME / '.claude.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    entry = server_table(doc).get(name)
    return entry.get('timeout') if isinstance(entry, dict) else None


TABLE = re.compile(r'^\[mcp_servers\.("?)([A-Za-z0-9_-]+)\1\]\s*$')


def codex_configs(check):
    found = {}
    for home in ('.codex', '.codex-work'):
        path = HOME / home / 'config.toml'
        if not path.is_file():
            continue
        lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
        changed = False
        i = 0
        while i < len(lines):
            m = TABLE.match(lines[i])
            name = m.group(2) if m else None
            if name not in TIMEOUTS:
                i += 1
                continue
            want = TIMEOUTS[name]
            end = i + 1
            while end < len(lines) and not lines[end].lstrip().startswith('['):
                end += 1
            got = None
            for j in range(i + 1, end):
                kv = re.match(r'^\s*tool_timeout_sec\s*=\s*([0-9.]+)', lines[j])
                if kv:
                    got = float(kv.group(1))
                    if got != want and not check:
                        lines[j] = f'tool_timeout_sec = {want}\n'
                        changed = True
            if got is None and not check:
                lines.insert(i + 1, f'tool_timeout_sec = {want}\n')
                changed = True
                end += 1
            found[f'{home} {name}'] = (got if check else want, want)
            i = end
        if changed:
            path.write_text(''.join(lines), encoding='utf-8')
            print(f'mcp-timeouts: set tool_timeout_sec in {path}')
    return found


def main():
    check = '--check' in sys.argv[1:]
    found = {**claude_plugins(check), **claude_user_servers(check), **codex_configs(check)}
    if not check:
        return 0
    bad = 0
    for key, (got, want) in sorted(found.items()):
        ok = got is not None and float(got) == float(want)
        bad += not ok
        print(f'{"ok " if ok else "BAD"} {key}: {got} (want {want})')
    if not found:
        print('no chrome-devtools or context-mode server configured on this host')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
