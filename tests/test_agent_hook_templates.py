import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CHEZMOI = shutil.which('chezmoi')
CLAUDE = (
    'home/private_dot_claude/modify_settings.json',
    'home/private_dot_claude-hub-personal/modify_private_settings.json',
)
CODEX = ('home/dot_codex/modify_hooks.json', 'home/dot_codex-work/modify_hooks.json')
FROZEN_CLAUDE = (
    r'^(Bash|PowerShell|Monitor|ScheduleWakeup|Read|Grep|Glob|'
    r'mcp__t3-code__task_status|mcp__t3-code__delegate_task|'
    r'mcp__t3-code__watch_pull_request|Agent|Task|Edit|Write|MultiEdit|'
    r'NotebookEdit|mcp__t3-code__t3_thread_launch|mcp__t3-code__t3_thread_read)$'
)
FROZEN_CODEX = (
    r'^(Bash|PowerShell|exec_command|shell|shell_command|local_shell|unified_exec|'
    r'collaborationspawn_agent|mcp__t3_code__delegate_task|mcp__t3-code__delegate_task|'
    r'mcp__t3_code_direct__delegate_task|mcp__t3_code__watch_pull_request|'
    r'mcp__t3-code__watch_pull_request|apply_patch|mcp__t3_code__t3_thread_launch|'
    r'mcp__t3-code__t3_thread_launch|mcp__t3_code_direct__t3_thread_launch|'
    r'mcp__t3_code__t3_thread_read|mcp__t3-code__t3_thread_read|'
    r'mcp__t3_code_direct__t3_thread_read)$'
)
HIDDEN_HOOK = {
    'type': 'command',
    'command': 'python3 /b/skill-router/scripts/hidden_skills_context.py',
    'timeout': 10,
}

_HOME = tempfile.TemporaryDirectory()
unittest.addModuleCleanup(_HOME.cleanup)


def setUpModule():
    for path in (
        '.agents/skills/skill-router/scripts/library_steer.py',
        '.agents/skills/full-send/scripts/ship_verbs.py',
        '.harbor/current/tools/slow_turn_retro.py',
    ):
        script = pathlib.Path(_HOME.name) / path
        script.parent.mkdir(parents=True, exist_ok=True)
        script.touch()


def render(rel, stdin_text):
    env = {**os.environ, 'HOME': _HOME.name, 'USERPROFILE': _HOME.name}
    result = subprocess.run(
        [CHEZMOI, '--source', str(ROOT), 'execute-template', '--with-stdin',
         '-f', str(ROOT / rel)],
        input=stdin_text, capture_output=True, text=True, timeout=60, env=env,
    )
    if result.returncode != 0:
        raise AssertionError(f'{rel}: chezmoi exited {result.returncode}: {result.stderr}')
    return result.stdout


def steer_group(doc, event):
    group, = [
        group for group in doc['hooks'][event]
        if any('skill-router/scripts/library_steer.py' in hook.get('command', '')
               for hook in group['hooks'])
    ]
    return group


@unittest.skipUnless(CHEZMOI, 'chezmoi unavailable')
class AgentHookTemplatesTests(unittest.TestCase):
    def test_claude_matcher_is_frozen(self):
        for rel in CLAUDE:
            with self.subTest(template=rel):
                doc = json.loads(render(rel, '{}'))
                matcher = steer_group(doc, 'PreToolUse')['matcher']
                self.assertEqual(matcher, FROZEN_CLAUDE)
                for tool in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit',
                             'mcp__t3-code__t3_thread_launch', 'mcp__t3-code__t3_thread_read',
                             'Bash', 'Agent'):
                    self.assertIsNotNone(re.fullmatch(matcher, tool), tool)
                for tool in ('Skill', 'EditX'):
                    self.assertIsNone(re.fullmatch(matcher, tool), tool)

    def test_codex_matcher_is_frozen(self):
        for rel in CODEX:
            with self.subTest(template=rel):
                doc = json.loads(render(rel, '{}'))
                group = steer_group(doc, 'PreToolUse')
                matcher = group['matcher']
                self.assertEqual(matcher, FROZEN_CODEX)
                for tool in ('apply_patch', 'exec_command',
                             'mcp__t3_code_direct__t3_thread_launch',
                             'mcp__t3_code__t3_thread_read',
                             'mcp__t3-code__t3_thread_read',
                             'mcp__t3_code_direct__t3_thread_read'):
                    self.assertIsNotNone(re.fullmatch(matcher, tool), tool)
                self.assertEqual(len(group['hooks']), 1)
                hook = group['hooks'][0]
                self.assertEqual(hook['timeout'], 10)
                self.assertTrue(hook['command'].endswith('hook codex'), hook['command'])

    def test_codex_templates_are_identical(self):
        self.assertEqual((ROOT / CODEX[0]).read_bytes(), (ROOT / CODEX[1]).read_bytes())

    def test_hidden_skills_hook_is_stripped_hook_by_hook(self):
        herdr = {'type': 'command', 'command': 'herdr-agent-state codex', 'timeout': 5}
        mixed_hook = {
            'type': 'command',
            'command': 'python3 /a/skill-router/scripts/hidden_skills_context.py codex',
            'timeout': 10,
        }
        stdin_text = json.dumps({'hooks': {'SessionStart': [
            {'matcher': '', 'hooks': [herdr, mixed_hook]},
            {'matcher': '', 'hooks': [HIDDEN_HOOK]},
        ]}})
        for rel in CLAUDE + CODEX:
            with self.subTest(template=rel):
                output = render(rel, stdin_text)
                self.assertNotIn('hidden_skills_context', output)
                doc = json.loads(output)
                self.assertEqual(doc['hooks']['SessionStart'], [
                    {'matcher': '', 'hooks': [herdr]},
                    steer_group(doc, 'SessionStart'),
                ])

    def test_codex_strip_alone_rewrites_and_clean_file_passes_through(self):
        for rel in CODEX:
            with self.subTest(template=rel):
                clean = render(rel, '{}')
                self.assertEqual(render(rel, clean), clean)
                doc = json.loads(clean)
                doc['hooks']['SessionStart'].insert(0, {'matcher': '', 'hooks': [HIDDEN_HOOK]})
                output = render(rel, json.dumps(doc, indent=2))
                self.assertNotIn('hidden_skills_context', output)
                self.assertEqual(json.loads(output)['hooks']['SessionStart'],
                                 json.loads(clean)['hooks']['SessionStart'])

    def test_codex_existing_group_keeps_position(self):
        before = {
            'matcher': '^Bash$',
            'hooks': [{'type': 'command', 'command': 'tool-a', 'timeout': 5}],
        }
        after = {
            'matcher': '^Bash$',
            'hooks': [{'type': 'command', 'command': 'tool-b', 'timeout': 5}],
        }
        old = {
            'matcher': '^(Bash)$',
            'hooks': [{
                'type': 'command',
                'command': 'python3 "/old/.agents/skills/skill-router/scripts/library_steer.py" hook codex',
                'timeout': 10,
            }],
        }
        stdin_text = json.dumps({'hooks': {'PreToolUse': [before, old, after]}})
        for rel in CODEX:
            with self.subTest(template=rel):
                doc = json.loads(render(rel, stdin_text))
                groups = doc['hooks']['PreToolUse']
                self.assertEqual(len(groups), 4)
                self.assertEqual(groups[0], before)
                self.assertEqual(groups[1], steer_group(doc, 'PreToolUse'))
                self.assertEqual(groups[1]['matcher'], FROZEN_CODEX)
                self.assertEqual(groups[2], after)
                self.assertEqual(len(groups[3]['hooks']), 1)
                self.assertIn('full-send/scripts/ship_verbs.py', groups[3]['hooks'][0]['command'])

    def test_listing_fraction_is_point_one(self):
        for rel in CLAUDE:
            for stdin_text in ('{}', '{"skillListingBudgetFraction": 0.02}'):
                with self.subTest(template=rel, stdin=stdin_text):
                    doc = json.loads(render(rel, stdin_text))
                    self.assertEqual(doc.get('skillListingBudgetFraction'), 0.1)

    def test_synced_skills_hidden_but_hand_values_kept(self):
        hand_values = {'docs': 'on', 'morning': 'off', 'aws-iam': 'name-only'}
        stdin_text = json.dumps({'skillOverrides': hand_values})
        for rel in CLAUDE:
            with self.subTest(template=rel):
                overrides = json.loads(render(rel, stdin_text))['skillOverrides']
                for name in ('built-in-browser', 'chrome-browser', 'computer-use',
                             'deep-research', 'google-workspace', 'import-memory',
                             'skill-creator'):
                    self.assertEqual(overrides.get(name), 'user-invocable-only', name)
                for name, value in hand_values.items():
                    self.assertEqual(overrides[name], value, name)
                for name in ('pdf', 'docx', 'xlsx', 'pptx'):
                    self.assertNotIn(name, overrides)
                if rel == CLAUDE[0]:
                    self.assertEqual(overrides['amazon-bedrock'], 'off')

    def test_hub_empty_file_passes_through(self):
        self.assertEqual(render(CLAUDE[1], ''), '')

    def test_slow_turn_retro_stop_hook_registered_across_claude_and_codex(self):
        for rel in CLAUDE:
            with self.subTest(template=rel):
                doc = json.loads(render(rel, '{}'))
                groups = [
                    g for g in doc['hooks']['Stop']
                    if any('tools/slow_turn_retro.py' in h.get('command', '') for h in g['hooks'])
                ]
                self.assertEqual(len(groups), 1)
                self.assertEqual(groups[0]['matcher'], '')
                self.assertEqual(groups[0]['hooks'][0]['timeout'], 15)
                self.assertTrue(groups[0]['hooks'][0]['command'].endswith('hook claude'))
        for rel in CODEX:
            with self.subTest(template=rel):
                doc = json.loads(render(rel, '{}'))
                groups = [
                    g for g in doc['hooks']['Stop']
                    if any('tools/slow_turn_retro.py' in h.get('command', '') for h in g['hooks'])
                ]
                self.assertEqual(len(groups), 1)
                self.assertEqual(groups[0]['matcher'], '')
                self.assertEqual(groups[0]['hooks'][0]['timeout'], 15)
                self.assertTrue(groups[0]['hooks'][0]['command'].endswith('hook codex'))


if __name__ == '__main__':
    unittest.main()
