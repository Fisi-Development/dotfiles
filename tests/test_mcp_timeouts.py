"""Regression checks for MCP timeout configuration and a bounded stdio call."""

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
import tempfile
from threading import Event, Thread
import time
import tomllib
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'home/dot_agents/bin/mcp_timeouts.py'
SERVER = 'chrome-devtools'
MCP_SERVER = """
import json
import sys
from threading import Event

for line in sys.stdin:
    message = json.loads(line)
    method = message['method']
    if method == 'initialize':
        result = {
            'protocolVersion': message['params']['protocolVersion'],
            'capabilities': {'tools': {}},
            'serverInfo': {'name': 'test-server', 'version': '1'},
        }
    elif method == 'notifications/initialized':
        continue
    elif method == 'tools/call':
        if message['params']['name'] == 'hang':
            print(json.dumps({
                'jsonrpc': '2.0',
                'method': 'notifications/progress',
                'params': {
                    'progressToken': message['params']['_meta']['progressToken'],
                    'progress': 0,
                },
            }), flush=True)
            Event().wait()
        result = {'content': [{'type': 'text', 'text': 'done'}]}
    else:
        raise ValueError(method)
    print(json.dumps({'jsonrpc': '2.0', 'id': message['id'], 'result': result}), flush=True)
"""


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

    def test_stdio_caller_aborts_hanging_tool_at_configured_timeout(self):
        with patch.dict(self.script.TIMEOUTS, {SERVER: 0.5}):
            self.assertEqual(self.run_script()[0], 0)
        config = tomllib.loads(self.codex_config.read_text(encoding='utf-8'))
        timeout = config['mcp_servers'][SERVER]['tool_timeout_sec']
        self.assertEqual(timeout, 0.5)

        with subprocess.Popen(
            [sys.executable, '-I', '-u', '-c', MCP_SERVER],
            cwd=self.home,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding='utf-8',
        ) as process:
            messages = Queue()
            hanging_handler_started = Event()

            def read_messages():
                for line in process.stdout:
                    message = json.loads(line)
                    if message.get('method') == 'notifications/progress':
                        hanging_handler_started.set()
                    else:
                        messages.put(message)

            def send(method, params=None, request_id=None):
                message = {'jsonrpc': '2.0', 'method': method}
                if params is not None:
                    message['params'] = params
                if request_id is not None:
                    message['id'] = request_id
                process.stdin.write(json.dumps(message) + '\n')
                process.stdin.flush()

            reader = Thread(target=read_messages)
            reader.start()
            try:
                send('initialize', {
                    'protocolVersion': '2024-11-05',
                    'capabilities': {},
                    'clientInfo': {'name': 'timeout-test', 'version': '1'},
                }, request_id=1)
                self.assertEqual(messages.get(timeout=5)['id'], 1)
                send('notifications/initialized')

                send('tools/call', {'name': 'fast'}, request_id=2)
                self.assertEqual(messages.get(timeout=timeout), {
                    'jsonrpc': '2.0', 'id': 2,
                    'result': {'content': [{'type': 'text', 'text': 'done'}]},
                })

                started = time.monotonic()
                send('tools/call', {
                    'name': 'hang', '_meta': {'progressToken': 'hang'},
                }, request_id=3)
                with self.assertRaises(Empty):
                    messages.get(timeout=max(0, timeout - (time.monotonic() - started)))
                elapsed = time.monotonic() - started
                self.assertTrue(hanging_handler_started.is_set(), 'server did not enter the hanging tool')
                self.assertIsNone(process.poll(), 'server exited before the timeout')
                self.assertGreaterEqual(elapsed, timeout)
                self.assertLess(elapsed, timeout + 1)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                reader.join(timeout=5)
            self.assertFalse(reader.is_alive())
