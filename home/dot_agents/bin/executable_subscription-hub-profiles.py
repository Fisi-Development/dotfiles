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
import tomllib


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
    parser.add_argument('--register-codex', action='store_true',
                        help='Use hub-key auth in hub homes and register keys with Codex')
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    # Complete validation of every profile and T3 entry before any write.
    keys = {}
    for lane in ('personal', 'work'):
        keys[lane] = (home / '.config/cliproxy' / lane / 'access-key').read_text().strip()
        if not keys[lane] or any(c in keys[lane] for c in '\r\n'):
            raise ValueError('missing or invalid local hub access key')
    plans = []
    migrations = {}
    codex_binary = shutil.which('codex') if args.register_codex else None
    if args.register_codex and not codex_binary:
        raise ValueError('Codex executable is required for hub-key registration')
    instances = {}
    for lane in ('personal', 'work'):
        base = home / '.codex'
        if lane == 'work' and (home / '.codex-work/config.toml').is_file():
            base = home / '.codex-work'
        target = home / ('.codex-hub-' + lane)
        # Decode explicitly to preserve CRLF bytes, rather than universal newlines.
        source = (base / 'config.toml').read_bytes().decode('utf-8')
        url = 'https://burnbutu.royal-burbot.ts.net:' + ('8317' if lane == 'personal' else '8318')
        original_data = codex_config(source, url, keys[lane])
        data = codex_config(without_login_restrictions(source) if args.register_codex else source,
                            url, keys[lane])
        if args.register_codex and data != original_data:
            migrations[target / 'config.toml'] = original_data
        plans.append((target, 'config.toml', data, base, ('AGENTS.md', 'rules', 'skills', 'hooks.json')))
        instances['codex_hub_' + lane] = dict(driver='codex', displayName='Hub ' + lane.title(),
            enabled=args.enable_codex, config=dict(homePath=str(target), setupMode='existing'))
    base = home / '.claude'
    target = home / '.claude-hub-personal'
    settings = json.loads((base / 'settings.json').read_text()) if (base / 'settings.json').exists() else {}
    env = settings.setdefault('env', {})
    env['ANTHROPIC_BASE_URL'] = 'https://burnbutu.royal-burbot.ts.net:8317'
    env['ANTHROPIC_AUTH_TOKEN'] = keys['personal']
    env.pop('ANTHROPIC_API_KEY', None)
    plans.append((target, 'settings.json', encoded(settings), base, ('CLAUDE.md', 'rules')))
    instances['claude_hub_personal'] = dict(driver='claudeAgent', displayName='Hub Personal (staged)',
                                           enabled=False, config=dict(homePath=str(target)))
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
    t3path = args.t3_settings.expanduser().resolve() if args.t3_settings else None
    original = merged = None
    if t3path:
        original = t3path.read_bytes()
        t3 = json.loads(original)
        current = t3.setdefault('providerInstances', {})
        for name, desired in instances.items():
            if name in current:
                existing = current[name]
                if (existing.get('driver') != desired['driver'] or existing.get('config') != desired['config']):
                    raise ValueError('incompatible T3 instance: ' + name)
                # Retain user metadata; only our enabled flags are managed.
                existing['enabled'] = desired['enabled']
            else:
                current[name] = desired
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
            if src.exists() and not dest.exists():
                if src.is_dir():
                    shutil.copytree(src, dest)
                else:
                    atomic(dest, src.read_bytes())
    if args.register_codex:
        for lane in ('personal', 'work'):
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
        print('Hub profile setup failed (' + type(error).__name__ + '); check local inputs and conflicts.', file=sys.stderr)
        sys.exit(1)
