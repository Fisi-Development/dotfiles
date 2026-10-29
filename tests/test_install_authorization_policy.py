import datetime
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'home/dot_agents/install-authorization-policy.py'
POLICY = SCRIPT.with_name('authorization-policy.md').read_text()
PREAMBLE = "# Royal's shared authorization policy (Codex auto-review)\n\nRoyal wrote this policy and installs it himself. Its grants are his standing authorization, given in advance: an action a grant covers needs no repeated approval in the transcript. Its limits, the Launch modes section and project gates still apply, and an action no grant covers gets your normal judgment.\n\n"
spec = importlib.util.spec_from_file_location('installer', SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name).resolve()
        self.write('.agents/authorization-policy.md', POLICY)
        self.state = self.home / 'agent-guard-updater/state.json'
        self.updater('0.4.1')
        self.guard = self.home / ('fake-guard.cmd' if os.name == 'nt' else 'fake-guard')
        self.guard.write_text('@echo agent-guard 0.4.1\n' if os.name == 'nt' else
                              '#!' + sys.executable + '\nprint("agent-guard 0.4.1")\n')
        self.guard.chmod(0o700)

    def write(self, name, text):
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
        return path

    def updater(self, considered, age=datetime.timedelta(minutes=5), **extra):
        ran = (datetime.datetime.now(datetime.timezone.utc) - age).isoformat()
        # The shape root_update.py writes after a run that found nothing newer to install.
        record = {'installed_version': '0.4.1', 'last_run': ran, 'reason': 'not_newer',
                  'release_considered': considered, 'result': 'current', **extra}
        self.write('agent-guard-updater/state.json', json.dumps(record))
        return record['last_run']

    def run_installer(self, *args):
        result = subprocess.run([sys.executable, str(SCRIPT), '--home', str(self.home),
                                 '--guard-bin', str(self.guard), '--updater-state', str(self.state), *args],
                                check=True, capture_output=True, text=True)
        self.assertNotIn('SECRET', result.stdout)
        self.assertEqual(result.stderr, '')
        return json.loads(result.stdout)

    def config(self, name='.telepathica/config.json', crlf=False):
        data = {'token': 'SECRET', 'label': 'synthetic', 't3_runtime_modes': {'grok': 'auto', 'codex': 'full-access'},
                'other': {'enabled': True}}
        text = json.dumps(data, indent=2)
        if crlf:
            text = text.replace('\n', '\r\n')
        return self.write(name, text)

    def test_current_preserves_config_and_preview_is_read_only(self):
        path = self.config()
        old = path.read_bytes()
        ran = self.updater('0.4.1')
        preview = self.run_installer()
        self.assertEqual(path.read_bytes(), old)
        self.assertEqual(preview['agent_guard'], {'installed': '0.4.1', 'latest': '0.4.1', 'updater_checked_at': ran, 'current': True})
        self.assertEqual(preview['telepathica']['before'], {'grok': 'auto', 'codex': 'full-access'})
        self.assertEqual(preview['launch_mode'], 'full-access')
        self.run_installer('--apply')
        new = path.read_bytes()
        # Only guarded harnesses follow the check; unguarded entries stay as they were.
        # Codex without the guard in hooks.json and OpenCode without the plugin have no
        # gate, so they get auto even though the fixture started Codex at full access.
        expected = {'grok': 'auto', 'codex': 'auto', 'claude': 'full-access', 'opencode': 'auto'}
        self.assertEqual(json.loads(new)['t3_runtime_modes'], expected)
        self.assertEqual(preview['telepathica']['after'], expected)
        for fragment in (b'  "token": "SECRET",', b'  "label": "synthetic",', b'  "other": {\n    "enabled": true\n  }'):
            self.assertIn(fragment, old)
            self.assertIn(fragment, new)
        self.assertEqual(list(json.loads(new)), list(json.loads(old)))
        self.assertEqual(self.run_installer()['changed_paths'], [])
        self.assertEqual(list(path.parent.glob('*before-shared-authorization*')), [])

    def test_newer_release_downgrades_modes(self):
        path = self.config()
        self.run_installer('--apply')
        # A newer main build the updater accepted but has not installed.
        ran = self.updater('0.4.2', result='failed', reason='artifact_expired')
        summary = self.run_installer('--apply')
        self.assertEqual(summary['agent_guard'], {'installed': '0.4.1', 'latest': '0.4.2', 'updater_checked_at': ran, 'current': False})
        self.assertEqual(summary['launch_mode'], 'auto')
        self.assertEqual(json.loads(path.read_bytes())['t3_runtime_modes'],
                         {'grok': 'auto', 'codex': 'auto', 'claude': 'auto', 'opencode': 'auto'})

    def test_opencode_follows_guard_only_with_plugin(self):
        path = self.config()
        self.write('.config/opencode/plugins/agent-guard.ts', '// synthetic plugin\n')
        self.run_installer('--apply')
        self.assertEqual(json.loads(path.read_bytes())['t3_runtime_modes']['opencode'], 'full-access')
        self.updater('0.4.2', result='failed', reason='artifact_expired')
        self.run_installer('--apply')
        self.assertEqual(json.loads(path.read_bytes())['t3_runtime_modes']['opencode'], 'auto')

    def test_codex_follows_guard_only_with_hook(self):
        path = self.config()
        self.write('.codex/hooks.json', json.dumps({'hooks': {'PreToolUse': [{'hooks': [
            {'type': 'command', 'command': 'agent-guard hook codex'}]}]}}))
        self.run_installer('--apply')
        self.assertEqual(json.loads(path.read_bytes())['t3_runtime_modes']['codex'], 'full-access')
        self.write('.codex/hooks.json', json.dumps({'hooks': {}}))
        self.run_installer('--apply')
        self.assertEqual(json.loads(path.read_bytes())['t3_runtime_modes']['codex'], 'auto')

    def test_overrides_refused_for_real_home(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--home', str(pathlib.Path.home()),
                                 '--updater-state', str(self.state)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('fixture --home', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_version_must_be_the_whole_output(self):
        self.guard.write_text('@echo not agent-guard 9.9.9 really\n' if os.name == 'nt' else
                              '#!/bin/sh\necho "not agent-guard 9.9.9 really"\n')
        self.assertIsNone(self.run_installer()['agent_guard']['installed'])

    def test_unusable_updater_record_is_not_current(self):
        # Runs that never reached a candidate (http_failed resets release_considered),
        # an updater that stopped running, and records that are not the updater's shape.
        cases = {'missing': None, 'not json': 'not json', 'list': '[]',
                 'no candidate': {'considered': None, 'result': 'failed', 'reason': 'http_failed'},
                 'stale': {'age': datetime.timedelta(hours=3)},
                 'future': {'age': -datetime.timedelta(hours=1)},
                 'naive time': {'last_run': '2026-10-18T22:38:14'},
                 'prerelease': {'considered': '0.5.0-rc1'}}
        for name, case in cases.items():
            with self.subTest(case=name):
                self.state.unlink(missing_ok=True)
                if isinstance(case, str):
                    self.write('agent-guard-updater/state.json', case)
                elif case is not None:
                    case = dict(case)
                    self.updater(case.pop('considered', '0.4.1'), case.pop('age', datetime.timedelta(minutes=5)), **case)
                summary = self.run_installer()
                self.assertEqual(summary['agent_guard'], {'installed': '0.4.1', 'latest': None, 'updater_checked_at': None, 'current': False})
                self.assertEqual(summary['launch_mode'], 'auto')

    def test_missing_guard_and_config(self):
        self.guard.unlink()
        ran = self.updater('0.4.1')
        summary = self.run_installer()
        self.assertEqual(summary['agent_guard'], {'installed': None, 'latest': '0.4.1', 'updater_checked_at': ran, 'current': False})
        self.assertEqual(summary['launch_mode'], 'auto')
        self.assertEqual(summary['telepathica'], {'path': None, 'before': None, 'after': None})
        self.assertFalse(any('config.json' in path for path in summary['changed_paths']))

    def test_crlf_legacy_config_and_no_final_newline(self):
        path = self.config('.agent-mailbox/config.json', crlf=True)
        summary = self.run_installer('--apply')
        self.assertEqual(summary['telepathica']['path'], str(path))
        data = path.read_bytes()
        self.assertIn(b'\r\n', data)
        self.assertNotIn(b'\n', data.replace(b'\r\n', b''))
        self.assertFalse(data.endswith(b'\n'))
        self.assertEqual(self.run_installer()['changed_paths'], [])

    def test_preferred_config_and_append_missing_map(self):
        legacy = self.config('.agent-mailbox/config.json')
        old = legacy.read_bytes()
        path = self.write('.telepathica/config.json', '{\n  "token": "SECRET"\n}')
        summary = self.run_installer('--apply')
        self.assertIsNone(summary['telepathica']['before'])
        self.assertEqual(summary['telepathica']['path'], str(path))
        self.assertEqual(list(json.loads(path.read_bytes())), ['token', 't3_runtime_modes'])
        self.assertEqual(legacy.read_bytes(), old)

    def test_retired_environment_entry_is_removed_and_others_kept(self):
        stale = '**Standing authorizations (AGENTS.md, 2026-10-01)**: opening an MR or merging needs a go'
        kept = '**Standing authorizations (AGENTS.md, 2026-11-01)**: a later entry stays'
        path = self.write('.claude/settings.json', json.dumps({'autoMode': {
            'environment': ['$defaults', 'custom env', stale, kept]}}))
        self.run_installer('--apply')
        env = json.loads(path.read_bytes())['autoMode']['environment']
        self.assertNotIn(stale, env)
        self.assertIn('custom env', env)
        self.assertIn(kept, env)
        self.assertEqual(self.run_installer()['changed_paths'], [])

    def test_claude_replaces_saved_entry_and_keeps_defaults(self):
        path = self.write('.claude/settings.json', json.dumps({'autoMode': {
            'allow': ['$defaults', 'custom', '[shared-authorization-policy] old allow'],
            'environment': ['$defaults', '[shared-authorization-policy] old environment']}}))
        self.write('.agents/authorization-adapter-state.json', json.dumps({str(path): {
            'allow': '[shared-authorization-policy] old allow',
            'environment': '[shared-authorization-policy] old environment'}}))
        self.run_installer('--apply')
        self.run_installer('--apply')
        auto = json.loads(path.read_bytes())['autoMode']
        launch = POLICY.split('## Launch modes\n\n', 1)[1].split('\n## ', 1)[0].strip()
        autonomous = POLICY.split('## Autonomous work\n\n', 1)[1].split('\n## ', 1)[0].strip()
        entries = [v for v in auto['allow'] if v.startswith('[shared-authorization-policy]')]
        self.assertEqual(len(entries), 1)
        self.assertIn(launch, entries[0])
        self.assertIn(autonomous, entries[0])
        self.assertIn('custom', auto['allow'])
        for key in ('allow', 'environment'):
            self.assertIn('$defaults', auto[key])
        self.assertEqual(self.run_installer()['changed_paths'], [])

    def test_codex_preamble_and_old_orphan_adoption(self):
        for name in ('.codex', '.codex-work'):
            with self.subTest(name=name):
                self.write(name + '/config.toml', 'model = "fixture"\n\n[auto_review]\nextra_policy = ' + json.dumps("# Royal's shared authorization policy\nold") + '\n\n[other]\nvalue = 1\n')
        self.run_installer('--apply')
        for name in ('.codex', '.codex-work'):
            data = tomllib.loads((self.home / name / 'config.toml').read_text())
            self.assertEqual(data['auto_review']['extra_policy'], PREAMBLE + POLICY)
            self.assertIn('## Launch modes', data['auto_review']['extra_policy'])
            self.assertEqual(data['other'], {'value': 1})
            self.assertEqual(data['model'], 'fixture')
        self.assertEqual(self.run_installer()['changed_paths'], [])

    def test_codex_dropped_only_the_end_marker(self):
        # Codex keeps the start comment above [auto_review] when it rewrites
        # config.toml but drops the trailing end comment.
        old = 'extra_policy = ' + json.dumps("# Royal's shared authorization policy\nold")
        tails = {'.codex': '\n', '.codex-work': '\n\n[later]\nvalue = 2\n'}
        for name, tail in tails.items():
            self.write(name + '/config.toml', 'model = "fixture"\n\n[other]\nvalue = 1\n\n'
                       + installer.TSTART + '\n[auto_review]\n' + old + tail)
        self.run_installer('--apply')
        for name, tail in tails.items():
            with self.subTest(name=name):
                text = (self.home / name / 'config.toml').read_text()
                self.assertEqual(text.count(installer.TSTART), 1)
                self.assertEqual(text.count(installer.TEND), 1)
                data = tomllib.loads(text)
                self.assertEqual(data['auto_review']['extra_policy'], PREAMBLE + POLICY)
                self.assertEqual(data['other'], {'value': 1})
                if 'later' in tail:
                    self.assertEqual(data['later'], {'value': 2})
        self.assertEqual(self.run_installer()['changed_paths'], [])

    def test_codex_dangling_start_marker_over_foreign_table_is_refused(self):
        self.write('.codex/config.toml', 'model = "fixture"\n\n' + installer.TSTART
                   + '\n[auto_review]\nextra_policy = "someone else"\n')
        result = subprocess.run([sys.executable, str(SCRIPT), '--home', str(self.home), '--guard-bin', str(self.guard),
                                 '--updater-state', str(self.state), '--apply'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unmanaged auto_review', result.stderr)

    def test_requested_chezmoi_rollout_reaches_all_adapters_with_limits(self):
        self.write('.claude/settings.json', '{}')
        for name in ('.codex', '.codex-work'):
            self.write(name + '/config.toml', 'model = "fixture"\n')
        preview = self.run_installer()
        self.assertEqual((self.home / '.claude/settings.json').read_text(), '{}')
        self.assertTrue(preview['changed_paths'])
        self.run_installer('--apply')
        auto = json.loads((self.home / '.claude/settings.json').read_bytes())['autoMode']
        policies = [auto['allow'][-1], auto['environment'][-1]]
        for name in ('.codex', '.codex-work'):
            policies.append(tomllib.loads((self.home / name / 'config.toml').read_text())
                            ['auto_review']['extra_policy'])
        for policy in policies:
            with self.subTest(adapter=policies.index(policy)):
                self.assertIn('When the task asks for a rollout, `chezmoi apply` and `chezmoi verify`', policy)
                self.assertIn('`~/.codex/rules`, `~/.codex-work/rules` and `~/.claude/rules`', policy)
                self.assertIn('rollout and are not Self-Modification.', policy)
                self.assertIn('permission settings outside that rollout.', policy)
                self.assertIn('Unasked widening of permissions\nstays denied.', policy)
        self.assertIn('Policy revision: 2026-10-18.', auto['environment'][-1])
        self.assertEqual(self.run_installer()['changed_paths'], [])


class GuardStatusTests(unittest.TestCase):
    NOW = datetime.datetime(2026, 10, 18, 22, 40, tzinfo=datetime.timezone.utc)
    RAN = '2026-10-18T22:38:14.713025+00:00'

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)

    def result(self, stdout):
        return subprocess.CompletedProcess([], 0, stdout, '')

    def state(self, considered):
        # The record a live updater wrote on 18 Oct 2026, with the version varied.
        path = self.root / 'agent-guard-updater/state.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'installed_version': considered, 'last_run': self.RAN, 'reason': 'not_newer',
                                    'release_considered': considered, 'result': 'current'}))
        return path

    def status(self, version, path, **kwargs):
        with mock.patch.object(installer.subprocess, 'run', side_effect=[self.result('agent-guard ' + version)]) as run:
            return installer.agent_guard_status('/guard', path, now=self.NOW, **kwargs), run

    def test_numeric_versions_and_installed_ahead(self):
        status, run = self.status('0.10.0', self.state('0.10.0'), fixture=True)
        self.assertEqual(status, {'installed': '0.10.0', 'latest': '0.10.0', 'updater_checked_at': self.RAN, 'current': True})
        self.assertEqual(run.call_args_list[0].args[0], ['/guard', '--version'])
        self.assertEqual(run.call_args_list[0].kwargs['timeout'], 10)
        self.assertNotIn('shell', run.call_args_list[0].kwargs)
        # Nothing else runs: the updater's record is the only source for the newest build.
        self.assertEqual(run.call_count, 1)
        self.assertTrue(self.status('0.10.0', self.state('0.9.12'), fixture=True)[0]['current'])
        self.assertFalse(self.status('0.9.9', self.state('0.10.0'), fixture=True)[0]['current'])

    def test_failures_are_unknown(self):
        path = self.state('0.4.1')
        for failure in (FileNotFoundError(), subprocess.TimeoutExpired('fixture', 10),
                        subprocess.CalledProcessError(1, 'fixture'), self.result('unparseable')):
            with self.subTest(failure=failure):
                with mock.patch.object(installer.subprocess, 'run', side_effect=[failure]):
                    status = installer.agent_guard_status('/guard', path, fixture=True, now=self.NOW)
                self.assertEqual((status['installed'], status['latest'], status['current']), (None, '0.4.1', False))

    def test_record_beside_the_installed_guard(self):
        # Each default binary pairs with the updater that installs it, under the same protected root.
        # Pure paths of each host's flavour, so both assertions hold on Windows and POSIX.
        self.assertEqual(installer.updater_state_path(pathlib.PurePosixPath(installer.GUARD_PATHS[0].as_posix())),
                         pathlib.PurePosixPath('/Library/Application Support/ClaudeCode/agent-guard-updater/state.json'))
        self.assertEqual(installer.updater_state_path(pathlib.PureWindowsPath(str(installer.GUARD_PATHS[1]))),
                         pathlib.PureWindowsPath(r'C:\Program Files\ClaudeCode\agent-guard-updater\state.json'))
        binary = self.root / 'agent-guard' / 'agent-guard.exe'
        binary.parent.mkdir()
        binary.touch()
        self.state('0.4.1')
        with mock.patch.object(installer, 'GUARD_PATHS', (self.root / 'absent', binary)), \
                mock.patch.object(installer, 'protected', return_value=True) as protected, \
                mock.patch.object(installer.subprocess, 'run', side_effect=[self.result('agent-guard 0.4.1')]) as run:
            status = installer.agent_guard_status(now=self.NOW)
        self.assertEqual(run.call_args_list[0].args[0][0], str(binary))
        self.assertEqual(protected.call_args.args[0], self.root / 'agent-guard-updater/state.json')
        self.assertEqual((status['latest'], status['current']), ('0.4.1', True))

    def test_real_home_requires_a_protected_record(self):
        with mock.patch.object(installer, 'protected', return_value=False):
            status = self.status('0.4.1', self.state('0.4.1'))[0]
        self.assertEqual((status['latest'], status['current']), (None, False))

    @unittest.skipIf(os.name == 'nt' or os.getuid() == 0, 'needs a non-root POSIX user')
    def test_user_owned_record_is_unprotected(self):
        # A record a user can write could claim any version; only root's counts.
        path = self.state('0.4.1')
        self.assertFalse(installer.protected(path))
        self.assertEqual(installer.updater_latest(path, now=self.NOW), (None, None))


if __name__ == '__main__':
    unittest.main()
