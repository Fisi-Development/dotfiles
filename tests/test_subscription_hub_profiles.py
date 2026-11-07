import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'home/dot_agents/bin/executable_subscription-hub-profiles.py'


class HubSupportLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.temp.name)
        key = self.home / '.config/cliproxy/personal/access-key'
        key.parent.mkdir(parents=True)
        key.write_text('fixture-key\n')
        codex = self.home / '.codex'
        (codex / 'rules').mkdir(parents=True)
        (codex / 'config.toml').write_text('model = "fixture"\n')
        (codex / 'AGENTS.md').write_text('agreement v1\n')
        (codex / 'hooks.json').write_text('{"hooks": {}}\n')
        (codex / 'rules/base.rules').write_text('rule v1\n')
        (codex / 'skills/.system/own').mkdir(parents=True)
        claude = self.home / '.claude'
        (claude / 'rules').mkdir(parents=True)
        (claude / 'hooks').mkdir()
        (claude / 'settings.json').write_text(json.dumps({'env': {}}))
        (claude / 'CLAUDE.md').write_text('claude v1\n')
        (claude / 'rules/base.md').write_text('rule v1\n')
        (claude / 'hooks/session-end.sh').write_text('#!/bin/sh\n')
        self.add_skill('first')
        self.claude_hub = self.home / '.claude-hub-personal'
        self.codex_hub = self.home / '.codex-hub-personal'

    def tearDown(self):
        self.temp.cleanup()

    def add_skill(self, name):
        skill = self.home / '.claude/skills' / name / 'SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text('---\nname: ' + name + '\n---\n')

    def run_script(self, *args):
        return subprocess.run([sys.executable, '-I', str(SCRIPT), '--home', str(self.home), *args],
                              capture_output=True, text=True, timeout=60)

    def backups(self, home, name):
        return sorted(p.name for p in home.glob(name + '.before-link-*'))

    def test_fresh_profiles_follow_later_base_changes(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        # Copies would miss every one of these later changes in the base homes.
        self.add_skill('later')
        (self.home / '.claude/CLAUDE.md').write_text('claude v2\n')
        (self.home / '.claude/rules/added.md').write_text('new rule\n')
        (self.home / '.codex/AGENTS.md').write_text('agreement v2\n')
        (self.home / '.codex/rules/added.rules').write_text('new rule\n')
        self.assertTrue((self.claude_hub / 'skills/later/SKILL.md').is_file())
        self.assertEqual((self.claude_hub / 'CLAUDE.md').read_text(), 'claude v2\n')
        self.assertTrue((self.claude_hub / 'rules/added.md').is_file())
        self.assertTrue((self.claude_hub / 'hooks/session-end.sh').is_file())
        self.assertEqual((self.codex_hub / 'AGENTS.md').read_text(), 'agreement v2\n')
        self.assertTrue((self.codex_hub / 'rules/added.rules').is_file())
        self.assertEqual((self.codex_hub / 'hooks.json').read_text(), '{"hooks": {}}\n')
        # Codex writes its own .system skills per home, so that stays a real copy.
        self.assertFalse((self.codex_hub / 'skills').is_symlink())
        self.assertTrue((self.codex_hub / 'skills/.system/own').is_dir())

    def test_support_only_migrates_old_copies_without_losing_them(self):
        # The layout earlier installer runs left behind.
        (self.claude_hub / 'rules').mkdir(parents=True)
        (self.claude_hub / 'rules/base.md').write_text('stale rule\n')
        (self.claude_hub / 'settings.json').write_text('{"kept": true}\n')
        (self.claude_hub / 'CLAUDE.md').write_text('claude v1\n')
        self.codex_hub.mkdir()
        (self.codex_hub / 'config.toml').write_text('kept = true\n')
        (self.codex_hub / 'AGENTS.md').write_text('agreement v0\n')
        (self.codex_hub / 'hooks.json').write_text('{"hooks": {}}\n')
        result = self.run_script('--support-only')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.claude_hub / 'rules/base.md').read_text(), 'rule v1\n')
        self.assertTrue((self.claude_hub / 'skills/first/SKILL.md').is_file())
        self.assertEqual((self.codex_hub / 'AGENTS.md').read_text(), 'agreement v1\n')
        # Differing copies are kept aside; identical ones need no backup.
        self.assertEqual(len(self.backups(self.claude_hub, 'rules')), 1)
        self.assertEqual(len(self.backups(self.codex_hub, 'AGENTS.md')), 1)
        self.assertEqual(self.backups(self.claude_hub, 'CLAUDE.md'), [])
        self.assertEqual(self.backups(self.codex_hub, 'hooks.json'), [])
        backup = self.codex_hub / self.backups(self.codex_hub, 'AGENTS.md')[0]
        self.assertEqual(backup.read_text(), 'agreement v0\n')
        self.assertEqual((self.claude_hub / 'settings.json').read_text(), '{"kept": true}\n')
        self.assertEqual((self.codex_hub / 'config.toml').read_text(), 'kept = true\n')
        again = self.run_script('--support-only')
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(len(self.backups(self.claude_hub, 'rules')), 1)

    def test_support_only_skips_missing_profiles(self):
        result = self.run_script('--support-only')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.claude_hub.exists())
        self.assertFalse(self.codex_hub.exists())

    def run_without_file_symlinks(self, *args):
        # A Windows host without Developer Mode: directory links work, file symlinks fail.
        shim = self.home / 'no_file_symlinks.py'
        shim.write_text(
            'import os, runpy, sys\n'
            'real = os.symlink\n'
            'def deny(src, dst, target_is_directory=False, **kw):\n'
            '    if not target_is_directory:\n'
            '        raise OSError("file symlinks unavailable")\n'
            '    return real(src, dst, target_is_directory, **kw)\n'
            'os.symlink = deny\n'
            'sys.argv = sys.argv[1:]\n'
            'runpy.run_path(sys.argv[0], run_name="__main__")\n')
        return subprocess.run([sys.executable, '-I', str(shim), str(SCRIPT), '--home', str(self.home), *args],
                              capture_output=True, text=True, timeout=60)

    def test_copy_without_file_symlinks_follows_its_original(self):
        # The hub CLAUDE.md copy an earlier run left, before the original changed.
        self.claude_hub.mkdir()
        (self.claude_hub / 'CLAUDE.md').write_text('claude v0\n')
        result = self.run_without_file_symlinks('--support-only')
        self.assertEqual(result.returncode, 0, result.stderr)
        hub_md = self.claude_hub / 'CLAUDE.md'
        self.assertFalse(hub_md.is_symlink())
        self.assertEqual(hub_md.read_text(), 'claude v1\n')
        backups = self.backups(self.claude_hub, 'CLAUDE.md')
        self.assertEqual(len(backups), 1)
        self.assertEqual((self.claude_hub / backups[0]).read_text(), 'claude v0\n')
        # A current copy is left alone, with no new backup.
        again = self.run_without_file_symlinks('--support-only')
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(len(self.backups(self.claude_hub, 'CLAUDE.md')), 1)
        # A later change to the original reaches the copy on the next run.
        (self.home / '.claude/CLAUDE.md').write_text('claude v2\n')
        later = self.run_without_file_symlinks('--support-only')
        self.assertEqual(later.returncode, 0, later.stderr)
        self.assertEqual(hub_md.read_text(), 'claude v2\n')

    def test_link_to_another_directory_fails_before_writes(self):
        elsewhere = self.home / 'elsewhere'
        elsewhere.mkdir()
        self.claude_hub.mkdir()
        (self.claude_hub / 'skills').symlink_to(elsewhere, target_is_directory=True)
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn('support link points outside its base', result.stderr)
        self.assertFalse((self.claude_hub / 'settings.json').exists())
        self.assertFalse(self.codex_hub.exists())


if __name__ == '__main__':
    unittest.main()
