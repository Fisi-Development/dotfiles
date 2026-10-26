"""Pin top-level Codex settings in ~/.codex*/config.toml on this host.

chezmoi runs this after every apply (run_after_codex-settings.*). Codex owns
config.toml and chezmoi only seeds it (create_config.toml), so a setting that
must reach existing hosts is patched here instead. It is idempotent and touches
only the keys in SETTINGS, leaving the rest of the file byte for byte.

- project_doc_max_bytes = 131072: Codex reads at most 32 KiB of AGENTS.md per
  session by default (budget shared across the root-to-cwd chain), so it saw
  only the first 536 of 1,784 lines of the Hermes repo's 81-96 KB AGENTS.md and
  none of apps/desktop/AGENTS.md. Claude Code loads the whole file. Raising the
  cap took Astra from 0/3 to 2/3 on the PF-002 composer replay (h113), with Sol
  unchanged at 3/3 (prompt-flexibility-pf001, pf002/rounds.md round 11).

`--check` prints each setting per config and exits 1 when one is missing or
wrong.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

SETTINGS = {'project_doc_max_bytes': 131072}
HOME = Path.home()


def patch(path, check):
    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    # Top-level keys end at the first table header.
    top = next((i for i, line in enumerate(lines) if line.lstrip().startswith('[')), len(lines))
    found, changed = {}, False
    for key, want in SETTINGS.items():
        pattern = re.compile(rf'^\s*{re.escape(key)}\s*=\s*(\S+)')
        hit = next((i for i in range(top) if pattern.match(lines[i])), None)
        got = pattern.match(lines[hit]).group(1) if hit is not None else None
        found[f'{path.parent.name} {key}'] = (got, str(want))
        if check or got == str(want):
            continue
        if hit is not None:
            lines[hit] = f'{key} = {want}\n'
        else:
            if top and not lines[top - 1].endswith('\n'):
                lines[top - 1] += '\n'
            lines.insert(top, f'{key} = {want}\n')
            top += 1
        changed = True
    if changed:
        path.write_text(''.join(lines), encoding='utf-8')
        print(f'codex-settings: set {", ".join(SETTINGS)} in {path}')
    return found


def main():
    check = '--check' in sys.argv[1:]
    found = {}
    for home in ('.codex', '.codex-work'):
        path = HOME / home / 'config.toml'
        if path.is_file():
            found.update(patch(path, check))
    if not check:
        return 0
    bad = 0
    for key, (got, want) in sorted(found.items()):
        ok = got == want
        bad += not ok
        print(f'{"ok " if ok else "BAD"} {key} = {got} (want {want})')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
