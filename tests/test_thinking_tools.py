"""Thinking passback is ephemeral, bounded, auditable, and seat/decision scoped."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from werewolf import providers as p
from werewolf.runner import Runner
from werewolf.server import parse_setup

AUDIT = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/audit_tools.py'),
                      run_name='thinking_audit')['audit']


def response(name, args, reasoning):
    return {'model': 'synthetic', 'choices': [{'finish_reason': 'tool_calls', 'message': {
        'content': None, 'reasoning_content': reasoning, 'tool_calls': [
            {'id': 'call', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 5,
                  'completion_tokens_details': {'reasoning_tokens': 4}}}


class ThinkingToolsTests(unittest.TestCase):
    def config(self, seat=1):
        return replace(p.deepseek_flash_config(seat, f'Player {seat}'), thinking='enabled',
                       reasoning_effort='high', temperature=None, max_tokens=32768)

    def assembled(self, config):
        observation = {'seat': config.seat, 'role': 'wolf', 'language': 'en', 'day': 1,
                       'phase': 'discussion', 'players': [{'seat': config.seat, 'alive': True}],
                       'history': [], 'wolf_teammates': [config.seat]}
        return p.build_request(config, observation, {'kind': 'explosion',
                               'options': [{'type': 'pass'}, {'type': 'explode'}]}, f'own-notes-{config.seat}')

    def test_setup_preserves_thinking_tools_and_larger_output_budget(self):
        configs = [self.config(i) for i in range(1, 13)]
        from dataclasses import asdict
        parsed, _, _ = parse_setup({'players': [asdict(c) for c in configs]})
        self.assertEqual(configs, parsed)

    def test_concurrent_seats_and_subsequent_decisions_never_share_reasoning(self):
        def send(config, body, **kwargs):
            self.assertEqual({'attempts': 1}, kwargs)
            self.assertEqual({'type': 'enabled'}, body['thinking'])
            self.assertEqual('high', body['reasoning_effort'])
            self.assertEqual('auto', body['tool_choice'])
            assistants = [m for m in body['messages'] if m['role'] == 'assistant']
            for index, message in enumerate(assistants):
                self.assertEqual(f'PRIVATE_REASONING_SEAT_{config.seat}_HOP_{index}', message['reasoning_content'])
            if len(assistants) == 0:
                return response('read_my_notes', {}, f'PRIVATE_REASONING_SEAT_{config.seat}_HOP_0')
            if len(assistants) == 1:
                return response('read_rules', {'section': 'victory'}, f'PRIVATE_REASONING_SEAT_{config.seat}_HOP_1')
            return response('action_pass', {}, f'PRIVATE_REASONING_SEAT_{config.seat}_HOP_2')
        def decide(seat):
            config = self.config(seat)
            return p.decide(config, self.assembled(config))
        with patch.object(p, '_send_http', side_effect=send):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(decide, [1, 2, 1]))
        for result in results:
            self.assertEqual('pass', result['type'])
            self.assertEqual(12, result.usage['reasoning_tokens'])
            serialized = json.dumps(result.tool_trace)
            self.assertNotIn('PRIVATE_REASONING_SEAT_', serialized)
            self.assertNotIn('reasoning_content', serialized)
            self.assertEqual([], result.tool_trace[0]['reasoning_passback'])
            self.assertEqual(2, len(result.tool_trace[-1]['reasoning_passback']))

    def test_empty_reasoning_is_passed_as_empty_and_not_dropped(self):
        config = self.config()
        def send(_, body, **kwargs):
            assistants = [m for m in body['messages'] if m['role'] == 'assistant']
            if not assistants:
                return response('read_my_notes', {}, None)
            self.assertEqual('', assistants[0]['reasoning_content'])
            return response('action_pass', {}, '')
        with patch.object(p, '_send_http', side_effect=send):
            result = p.decide(config, self.assembled(config))
        self.assertEqual(0, result.tool_trace[0]['assistant_reasoning']['chars'])

    def test_reasoning_counts_toward_context_limit_without_surviving_failure(self):
        config = self.config()
        assembled = self.assembled(config)
        initial = len(json.dumps(p.wire_request(config, assembled)['messages'], ensure_ascii=False))
        with patch.object(p, 'MAX_TOOL_CONTEXT_CHARS', initial + 500), \
             patch.object(p, '_send_http', return_value=response('read_my_notes', {}, 'SECRET_REASONING_' * 100)) as send:
            with self.assertRaises(p.ProviderError) as failure:
                p.decide(config, assembled)
        self.assertEqual(1, send.call_count)
        self.assertEqual('tool_context_budget', failure.exception.validation_details['category'])
        self.assertNotIn('SECRET_REASONING_', json.dumps(failure.exception.tool_trace))

    def test_thinking_archive_audit_verifies_passback_continuity_and_redaction(self):
        with patch.object(p, 'check_credentials'):
            runner = Runner([self.config(i) for i in range(1, 13)])
        def send(config, body, **kwargs):
            if not any(m['role'] == 'assistant' for m in body['messages']):
                return response('read_my_notes', {}, f'SECRET_SEAT_{config.seat}')
            action = next(t['function'] for t in body['tools'] if t['function']['name'].startswith('action_'))
            arguments = {'text': 'A synthetic night statement.'} if action['name'] == 'action_discuss' else {}
            return response(action['name'], arguments, 'SECRET_FINAL')
        with patch.object(p, '_send_http', side_effect=send):
            self.assertNotEqual('error', runner.step()['status'])
        archive = runner.export()
        self.assertNotIn('SECRET_SEAT_', json.dumps(archive))
        report = AUDIT(archive)
        self.assertEqual(4, report['accepted'])
        self.assertEqual(32, report['reasoning_tokens'])
        archive['inference'][0]['tool_trace'][1]['reasoning_passback'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(AssertionError, 'Reasoning passback'):
            AUDIT(archive)


if __name__ == '__main__':
    unittest.main()
