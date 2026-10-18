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
        self.skills = self.home / 'git/skills'
        self.skills.mkdir(parents=True)
        self.git('init', '-q')
        for version in ('0.4.0', '0.4.1'):
            self.git('tag', 'agent-guard-v' + version, self.git('hash-object', '-w', '--stdin', input='fixture').strip())
        # The checkout is its own origin unless a test points origin elsewhere.
        self.git('remote', 'add', 'origin', str(self.skills))
        self.guard = self.home / ('fake-guard.cmd' if os.name == 'nt' else 'fake-guard')
        self.guard.write_text('@echo agent-guard 0.4.1\n' if os.name == 'nt' else
                              '#!' + sys.executable + '\nprint("agent-guard 0.4.1")\n')
        self.guard.chmod(0o700)

    def write(self, name, text):
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
        return path

    def git(self, *args, **kwargs):
        return subprocess.run(['git', '-C', str(self.skills), *args], check=True,
                              capture_output=True, text=True, **kwargs).stdout

    def run_installer(self, *args):
        result = subprocess.run([sys.executable, str(SCRIPT), '--home', str(self.home),
                                 '--guard-bin', str(self.guard), *args],
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
        preview = self.run_installer()
        self.assertEqual(path.read_bytes(), old)
        self.assertEqual(preview['agent_guard'], {'installed': '0.4.1', 'latest': '0.4.1', 'origin_checked': True, 'current': True})
        self.assertEqual(preview['telepathica']['before'], {'grok': 'auto', 'codex': 'full-access'})
        self.assertEqual(preview['launch_mode'], 'full-access')
        self.run_installer('--apply')
        new = path.read_bytes()
        # Only the guarded harness follows the check; unguarded entries stay as they were.
        expected = {'grok': 'auto', 'codex': 'full-access', 'claude': 'full-access'}
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
        self.git('tag', 'agent-guard-v0.4.2', self.git('rev-parse', 'agent-guard-v0.4.1').strip())
        summary = self.run_installer('--apply')
        self.assertEqual(summary['agent_guard'], {'installed': '0.4.1', 'latest': '0.4.2', 'origin_checked': True, 'current': False})
        self.assertEqual(summary['launch_mode'], 'auto')
        self.assertEqual(json.loads(path.read_bytes())['t3_runtime_modes'],
                         {'grok': 'auto', 'codex': 'full-access', 'claude': 'auto'})
        self.assertNotIn('opencode', json.loads(path.read_bytes())['t3_runtime_modes'])

    def test_overrides_refused_for_real_home(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--home', str(pathlib.Path.home()),
                                 '--guard-bin', str(self.guard)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('fixture --home', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_version_must_be_the_whole_output(self):
        self.guard.write_text('@echo not agent-guard 9.9.9 really\n' if os.name == 'nt' else
                              '#!/bin/sh\necho "not agent-guard 9.9.9 really"\n')
        self.assertIsNone(self.run_installer()['agent_guard']['installed'])

    def test_deleted_local_tag_is_restored_from_origin(self):
        origin = self.home / 'origin'
        subprocess.run(['git', 'clone', '-q', str(self.skills), str(origin)], check=True, capture_output=True)
        blob = subprocess.run(['git', '-C', str(origin), 'hash-object', '-w', '--stdin'], input='newer',
                              check=True, capture_output=True, text=True).stdout.strip()
        subprocess.run(['git', '-C', str(origin), 'tag', 'agent-guard-v0.4.2', blob], check=True)
        self.git('remote', 'set-url', 'origin', str(origin))
        status = self.run_installer()['agent_guard']
        self.assertEqual((status['latest'], status['current']), ('0.4.2', False))

    def test_no_origin_answer_is_not_current(self):
        self.git('remote', 'remove', 'origin')
        summary = self.run_installer()
        self.assertEqual(summary['agent_guard'], {'installed': '0.4.1', 'latest': '0.4.1', 'origin_checked': False, 'current': False})
        self.assertEqual(summary['launch_mode'], 'auto')

    def test_missing_guard_and_config(self):
        self.guard.unlink()
        summary = self.run_installer()
        self.assertEqual(summary['agent_guard'], {'installed': None, 'latest': '0.4.1', 'origin_checked': True, 'current': False})
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
        entries = [v for v in auto['allow'] if v.startswith('[shared-authorization-policy]')]
        self.assertEqual(len(entries), 1)
        self.assertIn(launch, entries[0])
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
    def result(self, stdout):
        return subprocess.CompletedProcess([], 0, stdout, '')

    def test_numeric_versions_and_installed_ahead(self):
        with mock.patch.object(installer.subprocess, 'run', side_effect=[self.result('agent-guard 0.10.0'), self.result('agent-guard-v0.9.9\nagent-guard-v0.10.0\nagent-guard-v99.0.0-rc1'), self.result('abc\trefs/tags/agent-guard-v0.10.0\nabc\trefs/tags/agent-guard-v0.10.0^{}')]) as run:
            self.assertEqual(installer.agent_guard_status(pathlib.Path('/fixture'), pathlib.Path('/guard')),
                             {'installed': '0.10.0', 'latest': '0.10.0', 'origin_checked': True, 'current': True})
            self.assertEqual(run.call_args_list[0].args[0], [str(pathlib.Path('/guard')), '--version'])
            self.assertEqual(run.call_args_list[0].kwargs['timeout'], 10)
            self.assertNotIn('shell', run.call_args_list[0].kwargs)
            # The release list comes from the release repository, not the checkout's own remote.
            self.assertEqual(run.call_args_list[2].args[0][:3], ['gh', 'api', 'repos/royalaid/skills/git/matching-refs/tags/agent-guard-v'])
        with mock.patch.object(installer.subprocess, 'run', side_effect=[self.result('agent-guard 1.0.0'), self.result('agent-guard-v0.4.1'), self.result('x\trefs/tags/agent-guard-v0.4.1')]):
            self.assertTrue(installer.agent_guard_status('/fixture', '/guard')['current'])

    def test_failures_are_unknown(self):
        for failure in (FileNotFoundError(), subprocess.TimeoutExpired('fixture', 10),
                        subprocess.CalledProcessError(1, 'fixture'), self.result('unparseable')):
            for index in (0, 1, 2):
                with self.subTest(failure=failure, index=index):
                    effects = [self.result('agent-guard 0.4.1'), self.result('agent-guard-v0.4.1'), self.result('x\trefs/tags/agent-guard-v0.4.1')]
                    effects[index] = failure
                    with mock.patch.object(installer.subprocess, 'run', side_effect=effects):
                        status = installer.agent_guard_status('/fixture', '/guard')
                    if index == 0:
                        self.assertIsNone(status['installed'])
                    # Origin alone settles the release list when the local read fails.
                    self.assertEqual(status['current'], index == 1)

    def test_first_existing_default_binary(self):
        with mock.patch.object(pathlib.Path, 'exists', side_effect=[False, True]), mock.patch.object(installer.subprocess, 'run', side_effect=[self.result('agent-guard 0.4.1'), self.result('agent-guard-v0.4.1'), self.result('x\trefs/tags/agent-guard-v0.4.1')]) as run:
            self.assertTrue(installer.agent_guard_status('/fixture')['current'])
            self.assertEqual(run.call_args_list[0].args[0][0], str(installer.GUARD_PATHS[1]))


if __name__ == '__main__':
    unittest.main()
