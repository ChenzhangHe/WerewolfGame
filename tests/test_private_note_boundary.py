"""Public text must never swallow private native-tool parameter scaffolding."""
import json
import runpy
from pathlib import Path
import unittest
from unittest.mock import patch

from werewolf import providers as p
from werewolf.runner import Runner


def reply(name, arguments):
    return {'model': 'synthetic', 'choices': [{'finish_reason': 'tool_calls', 'message': {
        'content': None, 'reasoning_content': '', 'tool_calls': [{'id': 'call', 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(arguments)}}]}}]}


class PrivateNoteBoundaryTests(unittest.TestCase):
    def test_serialization_artifacts_are_rejected_but_role_claims_are_allowed(self):
        decision = {'kind': 'speech', 'options': [{'type': 'speak'}]}
        for text in ['Public words.</text><parameter name="notes">PRIVATE_PLAN',
                     'Public words.&lt;/text&gt;&lt;parameter name="notes"&gt;PRIVATE_PLAN',
                     'Public words. "notes": "PRIVATE_PLAN"',
                     'Public words.<｜DSML｜parameter name="notes">PRIVATE_PLAN']:
            with self.subTest(text=text), self.assertRaises(p.ProviderError) as failure:
                p.validate_action({'type': 'speak', 'text': text}, decision)
            self.assertEqual('protocol_artifact_in_public_text', failure.exception.validation_details['category'])
        p.validate_action({'type': 'speak', 'text': '我是猎人，昨天的投票我认。'}, decision)

    def test_terminal_schema_separates_notes_and_host_attaches_only_private_update(self):
        config = p.deepseek_flash_config(1, 'Player 1')
        observation = {'seat': 1, 'role': 'hunter', 'language': 'en', 'players': [{'seat': 1, 'alive': True}], 'history': []}
        decision = {'kind': 'speech', 'options': [{'type': 'speak'}]}
        request = p.build_request(config, observation, decision, 'OLD_NOTES')
        h = p._seat_harness(request)
        action = next(t for t in h.tools() if t['function']['name'] == 'action_speak')
        self.assertNotIn('notes', action['function']['parameters']['properties'])
        self.assertEqual({'updated': True, 'chars': 12}, h.call('write_my_notes', {'notes': 'PRIVATE_PLAN'}))
        self.assertEqual({'type': 'speak', 'text': 'Public words.', 'notes': 'PRIVATE_PLAN'},
                         h.call('action_speak', {'text': 'Public words.'}))
        with self.assertRaises(ValueError):
            h.call('action_speak', {'text': 'Public words.', 'notes': 'WRONG_CHANNEL'})
        untouched = p._seat_harness(request)
        self.assertNotIn('notes', untouched.call('action_speak', {'text': 'Another decision.'}))
        self.assertEqual('OLD_NOTES', untouched.call('read_my_notes', {})['notes'])

    def test_note_writes_and_malformed_speech_never_commit_on_failure(self):
        with patch.object(p, 'check_credentials'):
            runner = Runner([p.deepseek_flash_config(i, f'Player {i}') for i in range(1, 13)])
        before = runner.game.export()
        def send(config, body, **kwargs):
            if not any(m['role'] == 'assistant' for m in body['messages']):
                return reply('write_my_notes', {'notes': f'PRIVATE_PLAN_SEAT_{config.seat}'})
            return reply('action_discuss', {'text': 'Public words.</text><parameter name="notes">PRIVATE_PLAN'})
        with patch.object(p, '_send_http', side_effect=send):
            self.assertEqual('error', runner.step()['status'])
        self.assertEqual(before, runner.game.export())
        self.assertTrue(all(not v for v in runner.export()['private_notes'].values()))
        self.assertNotIn('PRIVATE_PLAN', json.dumps(runner.snapshot()))
        self.assertIn('PRIVATE_PLAN', json.dumps(runner.export()['inference']))

    def test_atomic_note_and_terminal_pair_does_not_need_an_extra_model_round(self):
        config = p.deepseek_flash_config(1, 'Player 1')
        observation = {'seat': 1, 'role': 'hunter', 'language': 'en', 'players': [{'seat': 1, 'alive': True}], 'history': []}
        request = p.build_request(config, observation, {'kind': 'speech', 'options': [{'type': 'speak'}]})
        message = reply('write_my_notes', {'notes': 'PRIVATE_PLAN'})
        message['choices'][0]['message']['tool_calls'][0]['id'] = 'note'
        message['choices'][0]['message']['tool_calls'] += reply('action_speak', {'text': 'Public words.'})['choices'][0]['message']['tool_calls']
        with patch.object(p, '_send_http', return_value=message) as send:
            result = p.decide(config, request)
        self.assertEqual(1, send.call_count)
        self.assertEqual('PRIVATE_PLAN', result['notes'])
        self.assertEqual('Public words.', result['text'])
        self.assertEqual(['write_my_notes', 'action_speak'], [r['name'] for r in result.tool_trace[0]['tool_results']])

    def test_private_write_and_public_action_commit_only_to_own_notes(self):
        with patch.object(p, 'check_credentials'):
            runner = Runner([p.deepseek_flash_config(i, f'Player {i}') for i in range(1, 13)])
        actors = [d['seat'] for d in runner.game.pending()]
        def send(config, body, **kwargs):
            response = reply('write_my_notes', {'notes': f'PRIVATE_PLAN_SEAT_{config.seat}'})
            response['choices'][0]['message']['tool_calls'][0]['id'] = 'note'
            response['choices'][0]['message']['tool_calls'] += reply('action_discuss', {'text': 'A private wolf-channel game statement.'})['choices'][0]['message']['tool_calls']
            return response
        with patch.object(p, '_send_http', side_effect=send):
            self.assertNotEqual('error', runner.step()['status'])
        for seat in actors:
            self.assertEqual(f'PRIVATE_PLAN_SEAT_{seat}', runner.export()['private_notes'][seat])
        self.assertNotIn('PRIVATE_PLAN', json.dumps(runner.game.export()['events']))
        audit = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/audit_tools.py'), run_name='note_audit')['audit']
        metrics = audit(runner.export())
        self.assertEqual(4, metrics['private_note_writes'])
        self.assertEqual(0, metrics['speech_boundary_failures'])


if __name__ == '__main__':
    unittest.main()
