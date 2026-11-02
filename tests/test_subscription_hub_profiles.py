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
        (self.home / '.codex').mkdir()
        (self.home / '.codex/config.toml').write_text('model = "fixture"\n')
        (self.home / '.claude').mkdir()
        (self.home / '.claude/settings.json').write_text(json.dumps({'env': {}}))
        self.add_skill('first')

    def tearDown(self):
        self.temp.cleanup()

    def add_skill(self, name):
        skill = self.home / '.claude/skills' / name / 'SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text('---\nname: ' + name + '\n---\n')

    def run_script(self, *args):
        return subprocess.run([sys.executable, '-I', str(SCRIPT), '--home', str(self.home), *args],
                              capture_output=True, text=True, timeout=60)

    def hub_skill(self, name):
        return self.home / '.claude-hub-personal/skills' / name / 'SKILL.md'

    def test_fresh_profile_sees_skills_installed_after_setup(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.hub_skill('first').is_file())
        # A copy would miss a skill installed later; the hub home must track the base.
        self.add_skill('later')
        self.assertTrue(self.hub_skill('later').is_file())

    def test_support_only_repairs_existing_profile_without_touching_config(self):
        hub = self.home / '.claude-hub-personal'
        hub.mkdir()
        (hub / 'settings.json').write_text('{"kept": true}\n')
        (hub / 'skills').mkdir()  # an empty directory Claude may have created
        result = self.run_script('--support-only')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.hub_skill('first').is_file())
        self.assertEqual((hub / 'settings.json').read_text(), '{"kept": true}\n')
        self.assertFalse((self.home / '.codex-hub-personal').exists())
        again = self.run_script('--support-only')
        self.assertEqual(again.returncode, 0, again.stderr)

    def test_support_only_skips_missing_profile(self):
        result = self.run_script('--support-only')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.home / '.claude-hub-personal').exists())

    def test_link_to_another_directory_fails_before_writes(self):
        elsewhere = self.home / 'elsewhere'
        elsewhere.mkdir()
        hub = self.home / '.claude-hub-personal'
        hub.mkdir()
        (hub / 'skills').symlink_to(elsewhere, target_is_directory=True)
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn('support link points outside its base', result.stderr)
        self.assertFalse((hub / 'settings.json').exists())

    def test_populated_directory_is_kept(self):
        hub = self.home / '.claude-hub-personal'
        (hub / 'skills/local').mkdir(parents=True)
        result = self.run_script('--support-only')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Kept existing support directory', result.stderr)
        self.assertTrue((hub / 'skills/local').is_dir())


if __name__ == '__main__':
    unittest.main()
