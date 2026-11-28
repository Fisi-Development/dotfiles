"""Regression checks for MCP timeout configuration readback and apply safety."""

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'home/dot_agents/bin/mcp_timeouts.py'
SERVER = 'chrome-devtools'


class MCPTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        spec = importlib.util.spec_from_file_location('mcp_timeouts', SCRIPT)
        self.script = importlib.util.module_from_spec(spec)
        with patch.object(Path, 'home', return_value=self.home):
            spec.loader.exec_module(self.script)

        plugins = self.home / '.claude/plugins'
        install = plugins / 'fixture'
        self.manifest = install / '.mcp.json'
        self.claude_config = self.home / '.claude.json'
        self.codex_config = self.home / '.codex/config.toml'
        self.entry = {'type': 'stdio', 'command': 'fixture-server'}
        self.write_json(plugins / 'installed_plugins.json', {
            'plugins': {'fixture': [{'installPath': str(install)}]},
        })
        self.write_server(self.manifest)
        self.write_server(self.claude_config)
        self.write_codex()
        self.enterContext(patch.object(self.script, 'claude_exe', return_value='fixture-claude'))
        self.enterContext(patch.object(self.script, 'run', side_effect=self.claude_cli))

    def write_json(self, path, document):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding='utf-8')

    def write_server(self, path, timeout=None):
        entry = dict(self.entry)
        if timeout is not None:
            entry['timeout'] = timeout
        self.write_json(path, {'mcpServers': {SERVER: entry}})

    def write_codex(self, timeout=None):
        self.codex_config.parent.mkdir(parents=True, exist_ok=True)
        config = f'[mcp_servers.{SERVER}]\ncommand = "fixture-server"\n'
        if timeout is not None:
            config += f'tool_timeout_sec = {timeout}\n'
        self.codex_config.write_text(config, encoding='utf-8')

    def claude_cli(self, args):
        stdout = ''
        if args == ['fixture-claude', 'mcp', 'get', SERVER]:
            stdout = 'Scope: User config\n  Type: stdio\n  Command: fixture-server\n'
        elif args == ['fixture-claude', 'mcp', 'remove', '-s', 'user', SERVER]:
            self.write_json(self.claude_config, {'mcpServers': {}})
        else:
            self.assertEqual(args[:-1], ['fixture-claude', 'mcp', 'add-json', '-s', 'user', SERVER])
            self.write_json(self.claude_config, {'mcpServers': {SERVER: json.loads(args[-1])}})
        return subprocess.CompletedProcess(args, 0, stdout=stdout)

    def run_script(self, *args):
        with patch.object(sys, 'argv', [str(SCRIPT), *args]), redirect_stdout(io.StringIO()) as stdout:
            status = self.script.main()
        return status, stdout.getvalue().splitlines()

    def test_check_reads_applied_timeouts(self):
        self.assertEqual(self.run_script()[0], 0)
        self.assertEqual(self.run_script('--check'), (0, [
            'ok  .codex chrome-devtools: 120.0 (want 120)',
            'ok  claude plugin chrome-devtools (fixture): 120000 (want 120000)',
            'ok  claude user chrome-devtools: 120000 (want 120000)',
        ]))

    def test_check_names_missing_or_drifted_timeouts(self):
        self.assertEqual(self.run_script()[0], 0)
        cases = [
            (self.manifest, None, 'BAD claude plugin chrome-devtools (fixture): None (want 120000)'),
            (self.claude_config, 120, 'BAD claude user chrome-devtools: 120 (want 120000)'),
            (self.codex_config, None, 'BAD .codex chrome-devtools: None (want 120)'),
            (self.codex_config, 120000, 'BAD .codex chrome-devtools: 120000.0 (want 120)'),
        ]
        for path, value, expected in cases:
            with self.subTest(path=path.name, timeout=value):
                original = path.read_bytes()
                try:
                    if path == self.codex_config:
                        self.write_codex(value)
                    else:
                        self.write_server(path, value)
                    broken = path.read_bytes()
                    status, lines = self.run_script('--check')
                    self.assertEqual(status, 1)
                    self.assertEqual(
                        [line for line in lines if line.startswith('BAD')],
                        [expected],
                    )
                    self.assertEqual(path.read_bytes(), broken)
                finally:
                    path.write_bytes(original)

    def test_fractional_timeout_and_codex_work_config(self):
        codex_work = self.home / '.codex-work' / 'config.toml'
        codex_work.parent.mkdir(parents=True, exist_ok=True)
        codex_work.write_text(f'[mcp_servers.{SERVER}]\ncommand = "npx"\n', encoding='utf-8')
        with patch.dict(self.script.TIMEOUTS, {SERVER: 0.5}):
            self.assertEqual(self.run_script()[0], 0)
            status, lines = self.run_script('--check')
        self.assertEqual(status, 0)
        for path in (self.codex_config, codex_work):
            config = tomllib.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(config['mcp_servers'][SERVER]['tool_timeout_sec'], 0.5)
        self.assertIn('ok  .codex-work chrome-devtools: 0.5 (want 0.5)', lines)

    def test_user_server_with_env_block_is_not_removed(self):
        calls = []

        def fake_run(args):
            calls.append(args)
            if args[1:3] == ['mcp', 'get']:
                return subprocess.CompletedProcess(
                    args, 0,
                    stdout='Scope: User config\n  Type: stdio\n  Command: npx\n  Args: -y server\n  Environment:\n    API_KEY=secret\n',
                    stderr='',
                )
            return subprocess.CompletedProcess(args, 0, stdout='', stderr='')

        with patch.object(self.script, 'claude_exe', return_value='claude'), \
                patch.object(self.script, 'run', side_effect=fake_run):
            self.script.claude_user_servers(check=False)
        self.assertFalse(any(cmd[1:3] == ['mcp', 'remove'] for cmd in calls))
