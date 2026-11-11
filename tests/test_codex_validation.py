"""Reconstruct Codex validation records and reject cross-seat/future tampering."""
from copy import deepcopy
from dataclasses import asdict
import unittest

from werewolf.codex_harness import CodexGameHarness, CodexPlayer
from scripts.verify_codex import audit_trial, synthetic_source
from test_codex_harness import FakeRPC, observation, PASS


class CodexValidationTests(unittest.TestCase):
    def game(self):
        game = CodexGameHarness('audit-game', rpc_factory=FakeRPC)
        self.addCleanup(game.close)
        return game

    def player(self):
        return CodexPlayer(1, 'Player 1', language='en')

    def trial(self):
        game = self.game()
        config = self.player()
        player = game.bind(config)
        game.rpc.plans[player.thread_id] = [
            [('write_my_notes', {'notes': 'MY_PLAN'}), ('action_pass', {})],
            [('read_my_notes', {}), ('action_pass', {})]]
        records = []
        obs, notes = observation(), ''
        for index in range(2):
            result = player.decide(obs, PASS, notes)
            records.append({'seat': 1, 'source_batch': index, 'observation': deepcopy(obs),
                            'decision': deepcopy(PASS), 'notes_before': notes,
                            'tool_trace': result.tool_trace, 'action': dict(result)})
            notes = result.get('notes', notes)
            obs['history'].append({'kind': 'speech', 'audience': 'public', 'text': f'Public {index}'})
        return {'protocol': 'codex-seat-thread-v1', 'source_archive_replay_verified': False,
                'players': [{'config': asdict(config), 'binding': player.binding, 'decisions': records,
                             'deliveries': deepcopy(player.deliveries), 'idle_feed_started_turns': 0}]}

    def test_audit_reconstructs_own_notes_catalog_and_thread_continuity(self):
        report = audit_trial(self.trial())
        self.assertTrue(report['all_checks_passed'])
        self.assertEqual(2, report['accepted_actions'])
        self.assertEqual(1, report['players_with_successful_thread_reuse'])
        self.assertEqual(10, report['usage']['reasoningOutputTokens'])

    def test_audit_detects_tampered_input_tool_result_delivery_and_binding(self):
        mutations = [
            lambda t: t['players'][0]['decisions'][0]['tool_trace'][0]['input']['briefing'].update(role='wolf'),
            lambda t: t['players'][0]['decisions'][1]['tool_trace'][0]['calls'][0].update(result={'notes': 'OTHER_SEAT'}),
            lambda t: t['players'][0]['deliveries'][0]['events'].append({'kind': 'speech', 'text': 'FUTURE'}),
            lambda t: t['players'][0]['decisions'][1]['tool_trace'][0].update(binding='other-thread'),
            lambda t: t['players'][0]['decisions'][1]['tool_trace'][0].update(turn_index=0),
            lambda t: t['players'][0]['decisions'][0]['tool_trace'][0].update(reasoning_content='SHOULD_NOT_BE_HERE'),
        ]
        for mutate in mutations:
            trial = self.trial()
            mutate(trial)
            with self.assertRaises(AssertionError):
                audit_trial(trial)

    def test_failed_turn_inputs_are_still_audited(self):
        trial = self.trial()
        record = trial['players'][0]['decisions'][-1]
        record.update(error='Simulated timeout', category='codex_turn_timeout')
        record['tool_trace'][0]['error'] = 'Simulated timeout'
        self.assertFalse(audit_trial(trial)['all_checks_passed'])
        record['tool_trace'][0]['input']['briefing']['role'] = 'wolf'
        with self.assertRaisesRegex(AssertionError, 'Actual turn input'):
            audit_trial(trial)

    def test_synthetic_source_covers_twelve_seats_and_all_six_roles(self):
        source = synthetic_source(3, range(1, 13))
        contexts = [r['request']['tool_context'] for r in source['inference']]
        self.assertEqual(36, len(contexts))
        self.assertEqual(set(range(1, 13)), {c['observation']['seat'] for c in contexts})
        self.assertEqual({'wolf', 'villager', 'witch', 'seer', 'hunter', 'idiot'},
                         {c['observation']['role'] for c in contexts})
        for context in contexts:
            obs = context['observation']
            self.assertFalse(any('role' in p and p['seat'] != obs['seat'] for p in obs['players']))
            if obs['role'] != 'wolf':
                self.assertNotIn('wolf_teammates', obs)
