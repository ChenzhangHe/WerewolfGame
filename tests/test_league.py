"""Balanced scheduling and mixed-provider replay/input boundaries, without network."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from werewolf import providers as p
from werewolf.league import schedule, configs_for, scoreboard, SOL, DEEPSEEK
from scripts.play_codex import play, audit_match
from scripts.play_league import MixedHarness, audit_players, create_plan, verify_plan, scheduled_games
from test_codex_matches import factory
from test_thinking_tools import response


def send(config, body, **kwargs):
    tools = {t['function']['name']: t['function'] for t in body['tools'] if t['function']['name'].startswith('action_')}
    name = next((n for n in ('action_pass', 'action_stay', 'action_withdraw') if n in tools), next(iter(tools)))
    args = {}
    for key, schema in tools[name]['parameters']['properties'].items():
        if key == 'text':
            args[key] = 'Offline test statement.'
        elif key == 'confirm':
            args[key] = True
        elif 'enum' in schema:
            choices = [v for v in schema['enum'] if v is not None] or schema['enum']
            args[key] = choices[0]
    return response(name, args, 'Private synthetic reasoning, never archived.')


class LeagueTests(unittest.TestCase):
    def test_season_stops_new_games_after_failure_but_collects_inflight_result(self):
        import threading
        release_inflight = threading.Event()
        calls = []
        def run(match):
            calls.append(match)
            if match == 0:
                return {'match_id': '0', 'all_checks_passed': False}
            release_inflight.wait(timeout=1)
            return {'match_id': str(match), 'all_checks_passed': True}
        scheduled = scheduled_games(list(range(12)), run, parallel_games=2)
        first = next(scheduled)
        self.assertTrue(first[1])
        release_inflight.set()
        results = [first]+list(scheduled)
        self.assertEqual({0, 1}, set(calls))
        self.assertEqual(2, len(results))
        self.assertTrue(results[-1][1])

    def test_current_plan_pins_transport_and_changed_code_is_execution_only_block(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = create_plan(Path(directory)/'plan.private.json', 13000)
            verify_plan(plan, execution=True)
            self.assertEqual(2, plan['workers_per_game'])
            self.assertEqual(600, plan['codex_turn_timeout_seconds'])
            plan['source_fingerprint'] = 'older-implementation'
            verify_plan(plan)  # Historical evidence can still be replayed offline.
            with self.assertRaisesRegex(AssertionError, 'Code changed'):
                verify_plan(plan, execution=True)

    def test_v2_full_mixed_game_uses_strict_protocol_and_replays(self):
        match = schedule(13000, version=2)[0]
        def mixed(scope):
            return MixedHarness(scope, codex_factory=factory, prompt_version='player-tools-v13')
        with tempfile.TemporaryDirectory() as directory, patch.object(p, '_send_http', side_effect=send):
            result = play(match['seed'], configs=configs_for(match), roles=match['roles'],
                protocol='mixed-league-v2', harness_factory=mixed, audit_players=audit_players,
                output_dir=Path(directory), artifact_stem='v2-test', progress=False)
            self.assertTrue(result['all_checks_passed'])
            self.assertEqual('mixed-league-v2', result['protocol'])

    def test_v3_game_uses_native_validation_protocol_and_replays(self):
        match = schedule(14000, version=3)[0]
        def mixed(scope):
            return MixedHarness(scope, codex_factory=factory)
        with tempfile.TemporaryDirectory() as directory, patch.object(p, '_send_http', side_effect=send):
            result = play(match['seed'], configs=configs_for(match), roles=match['roles'],
                protocol='mixed-league-v3', harness_factory=mixed, audit_players=audit_players,
                output_dir=Path(directory), artifact_stem='v3-test', progress=False)
            self.assertTrue(result['all_checks_passed'])
            self.assertEqual('mixed-league-v3', result['protocol'])

    def test_schedule_balances_every_role_and_varies_faction_composition(self):
        matches = schedule()
        self.assertEqual(matches, schedule())
        self.assertEqual(12, len(matches))
        for entry in (SOL, DEEPSEEK):
            counts = Counter(role for m in matches for e, role in zip(m['entries'], m['roles']) if e == entry)
            self.assertEqual(dict(wolf=24, villager=24, seer=6, witch=6, hunter=6, idiot=6), counts)
        self.assertEqual(set(range(5)), {sum(e == SOL and r == 'wolf' for e, r in zip(m['entries'], m['roles'])) for m in matches})
        for i in range(0, 12, 2):
            self.assertEqual(matches[i]['roles'], matches[i+1]['roles'])
            self.assertTrue(all(a != b for a, b in zip(matches[i]['entries'], matches[i+1]['entries'])))

    def test_balanced_score_is_not_biased_by_more_good_seats_or_failed_games(self):
        matches = schedule()
        reports = [{'match_id': m['id'], 'winner': 'good', 'all_checks_passed': True} for m in matches]
        result = scoreboard(matches, reports)
        self.assertEqual(12, result['valid_games'])
        for row in result['table']:
            self.assertEqual(.5, row['balanced_win_rate'])
            self.assertEqual(0, row['balanced_points_per_seat'])
            self.assertEqual(72, row['appearances'])
        reports[0]['all_checks_passed'] = False
        self.assertEqual(11, scoreboard(matches, reports)['valid_games'])

    def test_mixed_game_replay_and_native_wire_audits_reject_cross_seat_data(self):
        match = schedule()[0]
        def mixed(scope):
            return MixedHarness(scope, codex_factory=factory, prompt_version='player-tools-v12')
        with tempfile.TemporaryDirectory() as directory, patch.object(p, '_send_http', side_effect=send):
            result = play(match['seed'], configs=configs_for(match), roles=match['roles'],
                          protocol='mixed-league-v1', harness_factory=mixed, audit_players=audit_players,
                          output_dir=Path(directory), artifact_stem='mixed-test', progress=False)
            self.assertTrue(result['all_checks_passed'])
            self.assertEqual(6, result['codex']['unique_thread_bindings'])
            trial = json.loads((Path(directory)/'mixed-test.private.json').read_text())
            player = next(v for v in trial['players'] if v['transport'].startswith('deepseek'))
            self.assertEqual([], player['deliveries'])
            altered = deepcopy(trial)
            record = next(v for v in altered['players'] if v['config']['seat'] == player['config']['seat'])['decisions'][0]
            record['tool_trace'][0]['wire_request']['messages'].append({'role': 'user', 'content': 'foreign private fact'})
            with self.assertRaisesRegex(AssertionError, '[Ww]ire'):
                audit_match(altered, audit_players=audit_players)
            altered = deepcopy(trial)
            next(v for v in altered['players'] if v['config']['seat'] == player['config']['seat'])['decisions'][0]['notes_before'] = 'another seat notes'
            with self.assertRaisesRegex(AssertionError, 'notes'):
                audit_match(altered, audit_players=audit_players)
            self.assertNotIn('Private synthetic reasoning', json.dumps(trial))


if __name__ == '__main__':
    unittest.main()
