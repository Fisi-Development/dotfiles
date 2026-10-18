import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASH = (str(pathlib.Path(os.environ.get('ProgramFiles', 'C:/Program Files')) /
            'Git/bin/bash.exe') if os.name == 'nt' else shutil.which('bash'))


class RolloutSourcesTests(unittest.TestCase):
    def test_mac_handoff_names_reachable_repo_and_real_source(self):
        instructions = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
        step = instructions.split('3. **Apply on the Mac.**', 1)[1].split('\n4. ', 1)[0]
        self.assertIn('`claude@harbor@bouncehouse`', step)
        self.assertIn('work in `~/.local/share/chezmoi`', step)

    @unittest.skipUnless(BASH and pathlib.Path(BASH).exists(), 'Bash unavailable')
    def test_noninteractive_cargo_path_is_idempotent_and_preserves_path(self):
        source = ROOT / 'home/dot_zshenv'
        self.assertTrue(source.is_file(), 'every zsh invocation needs the cargo PATH setup')
        with tempfile.TemporaryDirectory() as temp:
            home = pathlib.Path(temp)
            cargo = home / '.cargo/bin/cargo'
            cargo.parent.mkdir(parents=True)
            cargo.write_text('#!/bin/sh\nprintf cargo-fixture\n')
            cargo.chmod(0o700)
            for initial in ('/usr/bin:/bin', '', 'existing'):
                with self.subTest(initial=initial):
                    result = self.shell(home, source, initial)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    lines = result.stdout.splitlines()
                    self.assertEqual(lines[0], 'cargo-fixture')
                    self.assertTrue(lines[1].endswith('/.cargo/bin/cargo'))
                    components = lines[2].split(':')
                    self.assertEqual(components.count(lines[1].removesuffix('/cargo')), 1)
                    self.assertEqual(components[1:], initial.split(':') if initial else [])

    @unittest.skipUnless(BASH and pathlib.Path(BASH).exists(), 'Bash unavailable')
    def test_absent_cargo_directory_preserves_path(self):
        source = ROOT / 'home/dot_zshenv'
        self.assertTrue(source.is_file())
        with tempfile.TemporaryDirectory() as temp:
            result = self.shell(pathlib.Path(temp), source, '/usr/bin:/bin', missing=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), '/usr/bin:/bin')

    def shell(self, home, source, initial, missing=False):
        setup = ('HOME=$(cygpath -u "$1"); source_path=$(cygpath -u "$2"); '
                 if os.name == 'nt' else 'HOME=$1; source_path=$2; ')
        script = setup + 'export HOME; PATH=$3; . "$source_path"; . "$source_path"; '
        script += ('printf "%s\\n" "$PATH"' if missing else
                   'cargo; printf "\\n"; command -v cargo; printf "%s\\n" "$PATH"')
        return subprocess.run([BASH, '--noprofile', '--norc', '-c', script,
                               'cargo-check', str(home), str(source), initial],
                              capture_output=True, text=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
