"""Audit tests construct actual runner archives with synthetic HTTP responses."""
import copy
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from werewolf import providers as p
from werewolf.runner import Runner

AUDIT = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts' / 'audit_tools.py'),
                      run_name='tool_audit_tests')['audit']


def native_call(name, arguments, call_id):
    return {'id': call_id, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(arguments)}}


def response(calls):
    return {'model': 'synthetic-tool-model', 'usage': {'prompt_tokens': 10, 'completion_tokens': 3},
            'choices': [{'finish_reason': 'tool_calls',
                         'message': {'role': 'assistant', 'content': None, 'tool_calls': calls}}]}


class ToolAuditTests(unittest.TestCase):
    def archive(self, *, invalid_read=False, partial=False, prompt_version=None):
        configs = [p.deepseek_flash_config(i, f'Player {i}') for i in range(1, 13)]
        with patch.object(p, 'check_credentials'):
            runner = Runner(configs)
        if prompt_version is not None:
            runner._tool_prompt_version = prompt_version
        failed_seat = runner.game.pending()[0]['seat']

        def send(config, body, **kwargs):
            if len(body['messages']) == 2:
                if invalid_read and config.seat == failed_seat:
                    calls = [native_call('read_public_log', {'seat': 2}, 'invalid-read')]
                    if partial:
                        calls = [native_call('read_my_notes', {}, 'valid-read'), *calls,
                                 native_call('read_rules', {'section': 'overview'}, 'not-executed')]
                    return response(calls)
                return response([native_call('read_my_notes', {}, 'read-notes')])
            action = next(t['function'] for t in body['tools'] if t['function']['name'].startswith('action_'))
            arguments = {}
            for name in action['parameters']['required']:
                schema = action['parameters']['properties'][name]
                arguments[name] = schema['enum'][0] if 'enum' in schema else 'A synthetic game statement.'
            return response([native_call(action['name'], arguments, 'action')])

        with patch.object(p, '_send_http', side_effect=send), \
             patch.object(p.http, 'urlopen', side_effect=AssertionError('No real network permitted')):
            runner.step()
        return json.loads(json.dumps(runner.export()))

    def test_valid_archive_counts_reads_actions_hops_and_usage(self):
        report = AUDIT(self.archive())
        self.assertEqual(4, report['decisions'])
        self.assertEqual(4, report['accepted'])
        self.assertEqual(8, report['model_requests'])
        self.assertEqual(4, report['read_calls'])
        self.assertEqual(0, report['invalid_read_calls'])
        self.assertEqual(4, report['action_calls'])
        self.assertEqual(80, report['prompt_tokens'])
        self.assertEqual(24, report['completion_tokens'])
        self.assertEqual(2, report['max_hops_per_decision'])

    def test_invalid_read_is_audited_as_explicit_failure_not_success(self):
        archive = self.archive(invalid_read=True)
        report = AUDIT(archive)
        self.assertEqual(4, report['decisions'])
        self.assertEqual(0, report['accepted'])
        self.assertEqual(1, report['failed_attempts'])
        self.assertEqual(7, report['model_requests'])
        self.assertEqual(3, report['read_calls'])
        self.assertEqual(1, report['invalid_read_calls'])
        self.assertEqual(3, report['action_calls'])  # Cached responses, not committed actions.
        self.assertNotIn('read_public_log', report['calls_by_name'])

    def test_partial_reads_before_failure_are_a_valid_executed_prefix(self):
        report = AUDIT(self.archive(invalid_read=True, partial=True))
        self.assertEqual(4, report['read_calls'])
        self.assertEqual(1, report['invalid_read_calls'])
        self.assertEqual(1, report['failed_attempts'])
        self.assertNotIn('read_rules', report['calls_by_name'])

    def test_invalid_read_requires_failed_record_failed_hop_and_exact_category(self):
        original = self.archive(invalid_read=True)
        failed = next(i for i, r in enumerate(original['inference']) if r.get('error'))
        variants = []
        a = copy.deepcopy(original)
        a['inference'][failed].pop('error')
        variants.append(a)
        a = copy.deepcopy(original)
        a['inference'][failed]['tool_trace'][-1].pop('error')
        variants.append(a)
        a = copy.deepcopy(original)
        a['inference'][failed]['validation_details']['category'] = 'other_error'
        variants.append(a)
        a = copy.deepcopy(original)
        a['inference'][failed]['tool_trace'][-1]['tool_results'][0]['result'] = {'error': 'Leaked diagnostic'}
        variants.append(a)
        for archive in variants:
            with self.subTest(case=variants.index(archive)), self.assertRaises(AssertionError):
                AUDIT(archive)

    def test_whole_wire_comparison_rejects_model_settings_and_extra_context(self):
        original = self.archive()
        for field, value in [('model', 'DIFFERENT_MODEL'), ('temperature', 1.9),
                             ('tool_choice', 'auto'), ('unexpected_context', {'private': 'NOT_ALLOWED'})]:
            archive = copy.deepcopy(original)
            archive['inference'][0]['tool_trace'][0]['wire_request'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(AssertionError, 'Wire body'):
                AUDIT(archive)

    def test_terminal_result_must_match_actual_native_name_and_arguments(self):
        original = self.archive()
        for field, value in [('name', 'action_vote'), ('arguments', '{"text":"Different model output"}')]:
            archive = copy.deepcopy(original)
            archive['inference'][0]['tool_trace'][-1]['assistant']['tool_calls'][0]['function'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(AssertionError, 'actual assistant call'):
                AUDIT(archive)

    def test_successful_hop_cannot_drop_a_tool_result_or_execute_extra_action(self):
        original = self.archive()
        changed = copy.deepcopy(original)
        changed['inference'][0]['tool_trace'][0]['tool_results'].clear()
        with self.assertRaises(AssertionError):
            AUDIT(changed)
        changed = copy.deepcopy(original)
        hop = changed['inference'][0]['tool_trace'][-1]
        extra = copy.deepcopy(hop['assistant']['tool_calls'][0])
        extra['id'] = 'extra-action'
        hop['assistant']['tool_calls'].append(extra)
        hop['tool_results'].append(copy.deepcopy(hop['tool_results'][0]))
        with self.assertRaises(AssertionError):
            AUDIT(changed)

    def test_legacy_v1_auto_is_explicitly_supported_but_v2_auto_rejected(self):
        archive = self.archive(prompt_version='player-tools-v1')
        self.assertTrue(all(hop['wire_request']['tool_choice'] == 'auto'
                            for record in archive['inference'] for hop in record['tool_trace']))
        self.assertEqual(4, AUDIT(archive)['accepted'])
        for record in archive['inference']:
            record['request']['prompt_version'] = 'player-tools-v2'
        with self.assertRaisesRegex(AssertionError, 'Wire body'):
            AUDIT(archive)


if __name__ == '__main__':
    unittest.main()
