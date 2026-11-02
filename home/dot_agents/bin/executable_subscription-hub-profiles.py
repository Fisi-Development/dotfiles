#!/usr/bin/env python3
"""Bootstrap isolated subscription hub homes without changing default clients."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib

# One hub pools every account, work included (Royal's choice, 2026-11-02).
LANES = ('personal',)
RETIRED_INSTANCES = ('codex_hub_work',)
# Support paths a hub home links to rather than copies, so later changes in
# the base home (new skills, chezmoi updates to AGENTS.md, CLAUDE.md, rules
# and hooks, hook scripts settings.json reaches through the config dir) reach
# hub sessions too. Codex keeps its own skills copy, because it writes its
# .system skills there and reads ~/.agents/skills whatever CODEX_HOME is.
CLAUDE_LINKS = ('CLAUDE.md', 'skills', 'rules', 'hooks', 'agents', 'commands', 'output-styles')
CODEX_LINKS = ('AGENTS.md', 'rules', 'hooks.json')


def is_link(path):
    isjunction = getattr(os.path, 'isjunction', None)
    return path.is_symlink() or bool(isjunction and isjunction(path))


def links_to(dest, src):
    try:
        return os.path.samefile(dest, src)
    except OSError:
        return False


def check_links(target, base, names):
    """Fail before any write when a hub support link points somewhere else."""
    for name in names:
        dest = target / name
        if is_link(dest) and (base / name).exists() and not links_to(dest, base / name):
            raise ValueError('support link points outside its base: ' + str(dest))


def set_aside(dest):
    """Keep an older run's copy beside the link rather than delete it."""
    backup = dest.with_name(dest.name + '.before-link-' + time.strftime('%Y%m%dT%H%M%S'))
    dest.rename(backup)
    print('Moved copied support path aside: ' + str(backup), file=sys.stderr)


def ensure_links(target, base, names):
    for name in names:
        src, dest = base / name, target / name
        if not src.exists() or is_link(dest):
            continue
        if src.is_dir():
            if dest.is_dir() and not any(dest.iterdir()):
                dest.rmdir()
            elif dest.exists():
                set_aside(dest)
            if os.name == 'nt':
                # A junction needs neither Developer Mode nor elevation.
                import _winapi
                _winapi.CreateJunction(str(src), str(dest))
            else:
                os.symlink(src, dest, target_is_directory=True)
            continue
        # Link files beside the target first, so a host that cannot make file
        # symlinks (Windows without Developer Mode) keeps its working copy.
        temporary = dest.with_name('.' + name + '.link')
        if is_link(temporary) or temporary.exists():
            temporary.unlink()
        try:
            os.symlink(src, temporary)
        except OSError:
            print('Kept a copy, file symlinks unavailable: ' + str(dest), file=sys.stderr)
            if not dest.exists():
                atomic(dest, src.read_bytes())
            continue
        if dest.exists() and dest.read_bytes() != src.read_bytes():
            set_aside(dest)
        os.replace(temporary, dest)


def statements(text):
    """Yield TOML statement spans, respecting strings, comments and containers."""
    start = i = depth = 0
    quote = None
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\" and quote[0] == '"':
                i += 2
                continue
            if text.startswith(quote, i):
                i += len(quote)
                quote = None
                continue
        elif c in "\"'":
            quote = c * 3 if text.startswith(c * 3, i) else c
            i += len(quote)
            continue
        elif c == '#':
            end = text.find('\n', i)
            i = len(text) if end < 0 else end
            continue
        elif c in '[{':
            depth += 1
        elif c in ']}':
            depth -= 1
        elif c == '\n' and depth == 0:
            yield start, i + 1
            start = i + 1
        i += 1
    if start < len(text):
        yield start, len(text)


def without_login_restrictions(source):
    spans = []
    for start, end in statements(source):
        statement = source[start:end].lstrip()
        if statement.startswith('['):
            break
        if statement and not statement.startswith('#'):
            item = tomllib.loads(statement)
            if any(k in item for k in ('forced_login_method', 'forced_chatgpt_workspace_id')):
                spans.append((start, end))
    for start, end in reversed(spans):
        source = source[:start] + source[end:]
    return source


def codex_config(source, url, key):
    parsed = tomllib.loads(source)
    if 'subscription_hub' in parsed.get('model_providers', {}):
        raise ValueError('source already declares subscription_hub provider')
    replacement = 'model_provider = "subscription_hub"\n'
    rendered = source
    for start, end in statements(source):
        statement = source[start:end].lstrip()
        if statement.startswith('['):
            break
        # Parse a statement to also recognize quoted root keys.
        if statement and not statement.startswith('#'):
            item = tomllib.loads(statement)
            if 'model_provider' in item:
                raw = source[start:end]
                equals = raw.index('=')
                value_start = equals + 1
                while raw[value_start].isspace():
                    value_start += 1
                for value_end in range(value_start + 1, len(raw) + 1):
                    try:
                        value = tomllib.loads('value = ' + raw[value_start:value_end])['value']
                    except tomllib.TOMLDecodeError:
                        continue
                    if value == parsed['model_provider']:
                        rendered = (source[:start] + raw[:value_start] + '"subscription_hub"'
                                    + raw[value_end:] + source[end:])
                        break
                else:
                    raise ValueError('cannot locate root provider value')
                break
    if 'model_provider' not in parsed:
        rendered = replacement + source
    provider = dict(name='Burnbutu Hub', base_url=url + '/v1', wire_api='responses',
                    requires_openai_auth=False, supports_websockets=True,
                    experimental_bearer_token=key)
    rendered += '\n[model_providers.subscription_hub]\n'
    for name, value in provider.items():
        rendered += name + ' = ' + (str(value).lower() if isinstance(value, bool)
                                     else json.dumps(value, ensure_ascii=False)) + '\n'
    expected = dict(parsed)
    expected['model_provider'] = 'subscription_hub'
    expected['model_providers'] = dict(parsed.get('model_providers', {}), subscription_hub=provider)
    if tomllib.loads(rendered) != expected:
        raise ValueError('rendered TOML failed preservation check')
    return rendered.encode('utf-8')


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--t3-settings', type=Path)
    parser.add_argument('--enable-codex', action='store_true')
    parser.add_argument('--enable-claude', action='store_true')
    parser.add_argument('--codex-binary', type=Path, help='Absolute Codex executable for restricted PATHs')
    parser.add_argument('--register-codex', action='store_true',
                        help='Use hub-key auth in hub homes and register keys with Codex')
    parser.add_argument('--support-only', action='store_true',
                        help='Only add missing support links to existing hub homes')
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    links = [(home / '.claude-hub-personal', home / '.claude', CLAUDE_LINKS)]
    links += [(home / ('.codex-hub-' + lane), home / '.codex', CODEX_LINKS) for lane in LANES]
    if args.support_only:
        present = [link for link in links if link[0].is_dir() and not is_link(link[0])]
        for link in present:
            check_links(*link)
        for link in present:
            ensure_links(*link)
        print('Hub support links verified in ' + str(len(present)) + ' existing home(s).')
        return
    # Complete validation of every profile and T3 entry before any write.
    keys = {}
    for lane in LANES:
        keys[lane] = (home / '.config/cliproxy' / lane / 'access-key').read_text().strip()
        if not keys[lane] or any(c in keys[lane] for c in '\r\n'):
            raise ValueError('missing or invalid local hub access key')
    plans = []
    migrations = {}
    codex_binary = (str(args.codex_binary.expanduser().resolve()) if args.codex_binary
                    else shutil.which('codex')) if args.register_codex else None
    if args.codex_binary and not args.codex_binary.expanduser().is_file():
        raise ValueError('Explicit Codex executable does not exist')
    if args.register_codex and not codex_binary:
        raise ValueError('Codex executable is required for hub-key registration')
    instances = {}
    for lane in LANES:
        base = home / '.codex'
        target = home / ('.codex-hub-' + lane)
        # Decode explicitly to preserve CRLF bytes, rather than universal newlines.
        source = (base / 'config.toml').read_bytes().decode('utf-8')
        url = 'https://burnbutu.royal-burbot.ts.net:8317'
        original_data = codex_config(source, url, keys[lane])
        data = codex_config(without_login_restrictions(source) if args.register_codex else source,
                            url, keys[lane])
        existing_config = target / 'config.toml'
        if args.register_codex and existing_config.is_file():
            existing_data = existing_config.read_bytes()
            existing_text = existing_data.decode('utf-8')
            existing = tomllib.loads(existing_text)
            provider = existing.get('model_providers', {}).get('subscription_hub', {})
            if (existing.get('model_provider') != 'subscription_hub'
                    or provider.get('base_url') != url + '/v1'
                    or provider.get('experimental_bearer_token') != keys[lane]
                    or provider.get('wire_api') != 'responses'
                    or provider.get('requires_openai_auth') is not False):
                raise ValueError('existing profile does not match this hub lane')
            data = without_login_restrictions(existing_text).encode('utf-8')
            migrations[existing_config] = existing_data
        elif args.register_codex and data != original_data:
            migrations[existing_config] = original_data
        plans.append((target, 'config.toml', data, base, ('skills',)))
        instances['codex_hub_' + lane] = dict(driver='codex', displayName='Hub ' + lane.title(),
            enabled=args.enable_codex, config=dict(homePath=str(target), setupMode='existing'))
    base = home / '.claude'
    target = home / '.claude-hub-personal'
    settings = json.loads((base / 'settings.json').read_text()) if (base / 'settings.json').exists() else {}
    env = settings.setdefault('env', {})
    env['ANTHROPIC_BASE_URL'] = 'https://burnbutu.royal-burbot.ts.net:8317'
    env['ANTHROPIC_AUTH_TOKEN'] = keys['personal']
    env.pop('ANTHROPIC_API_KEY', None)
    claude_config = target / 'settings.json'
    if args.register_codex and claude_config.is_file():
        existing_claude = json.loads(claude_config.read_bytes())
        existing_env = existing_claude.get('env', {})
        if (existing_env.get('ANTHROPIC_BASE_URL') != env['ANTHROPIC_BASE_URL']
                or existing_env.get('ANTHROPIC_AUTH_TOKEN') != keys['personal']):
            raise ValueError('existing Claude profile does not match this hub lane')
        claude_data = claude_config.read_bytes()
    else:
        claude_data = encoded(settings)
    plans.append((target, 'settings.json', claude_data, base, ()))
    instances['claude_hub_personal'] = dict(driver='claudeAgent', displayName='Hub Claude',
                                           enabled=args.enable_claude, config=dict(homePath=str(target)))
    for target, name, data, base, extras in plans:
        config = target / name
        if config.is_symlink() or target.is_symlink():
            raise ValueError('refusing symlink profile/config')
        if (config.exists() and config.read_bytes() != data
                and config.read_bytes() != migrations.get(config)):
            raise ValueError('incompatible existing profile config: ' + str(config))
        for extra in extras:
            dest = target / extra
            if dest.is_symlink():
                raise ValueError('refusing symlink profile support path')
    for link in links:
        check_links(*link)
    t3path = args.t3_settings.expanduser().resolve() if args.t3_settings else None
    original = merged = None
    if t3path:
        original = t3path.read_bytes()
        t3 = json.loads(original)
        current = t3.setdefault('providerInstances', {})
        for name, desired in instances.items():
            if name in current:
                existing = current[name]
                existing_config = existing.get('config', {})
                expected_home = Path(desired['config']['homePath']).resolve()
                if (existing.get('driver') != desired['driver']
                        or not isinstance(existing_config, dict)
                        or Path(existing_config.get('homePath', '')).expanduser().resolve() != expected_home
                        or existing_config.get('setupMode', 'existing') != 'existing'):
                    raise ValueError('incompatible T3 instance: ' + name)
                # Retain user metadata; only our enabled flags are managed.
                existing['enabled'] = desired['enabled']
                if existing.get('displayName') == 'Hub Personal (staged)':
                    existing['displayName'] = desired['displayName']
            else:
                current[name] = desired
        for name in RETIRED_INSTANCES:
            if name in current:
                current[name]['enabled'] = False
        if t3 != json.loads(original):
            merged = encoded(t3)
    for target, name, data, base, extras in plans:
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        config = target / name
        if config.exists() and config in migrations and config.read_bytes() != data:
            fd, backup = tempfile.mkstemp(prefix='config.toml.before-hub-key-', dir=target)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(config.read_bytes())
            atomic(config, data)
        elif not config.exists():
            atomic(config, data)
        os.chmod(target / name, 0o600)
        for extra in extras:
            src, dest = base / extra, target / extra
            if dest.exists():
                continue
            try:
                # Windows can refuse to traverse a linked source (WinError 448).
                if not src.exists():
                    continue
                if src.is_dir():
                    shutil.copytree(src, dest)
                else:
                    atomic(dest, src.read_bytes())
            except OSError:
                print('Skipped unreadable support path: ' + str(src), file=sys.stderr)
    for link in links:
        ensure_links(*link)
    if args.register_codex:
        for lane in LANES:
            result = subprocess.run(
                [codex_binary, 'login', '--with-api-key'],
                input=keys[lane] + '\n', text=True, capture_output=True, timeout=30,
                env=dict(os.environ, CODEX_HOME=str(home / ('.codex-hub-' + lane))))
            if result.returncode:
                raise ValueError('Codex rejected the hub access key')
    if merged is not None:
        fd, backup = tempfile.mkstemp(prefix=t3path.name + '.backup-', dir=t3path.parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(original)
        atomic(t3path, merged)
    print('Hub profiles verified; ' + ('T3 instances updated.' if merged else 'no T3 changes.'))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, TypeError, KeyError) as error:
        # Parser errors may contain input values, so never print their text.
        detail = str(error) if type(error) is ValueError else type(error).__name__
        print('Hub profile setup failed: ' + detail, file=sys.stderr)
        sys.exit(1)
