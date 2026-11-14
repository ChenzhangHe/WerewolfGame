from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from werewolf.codex_quartet import ENTRIES, schedule, configs_for
from werewolf.codex_harness import CodexGameHarness
from werewolf.ratings import fit_ratings
from scripts.play_codex import play
from scripts.play_codex_league import verify_trial
from scripts.play_codex_quartet import create_plan, verify_plan, run_season
from test_codex_league import SevenRPC


class QuartetTests(unittest.TestCase):
    def test_six_games_have_equal_roles_positions_and_three_seats_per_category(self):
        for seed in range(10):
            matches = schedule(seed)
            self.assertEqual(matches, schedule(seed))
            for m in matches:
                self.assertEqual(Counter({e: 3 for e in ENTRIES}), Counter(m['entries']))
            for e in ENTRIES:
                roles = Counter(r for m in matches for entry, r in zip(m['entries'], m['roles']) if e == entry)
                self.assertEqual(6, roles['wolf'])
                self.assertEqual(6, roles['villager'])
                self.assertEqual([1, 1, 2, 2], sorted(roles[r] for r in ('seer', 'witch', 'hunter', 'idiot')))
                positions = Counter(s for m in matches for s, entry in enumerate(m['entries'], 1) if e == entry)
                self.assertEqual(18, sum(positions.values()))
            self.assertEqual({('gpt-6.1-sol', 'medium'), ('gpt-6.1-sol', 'low'), ('gpt-6.1-terra', 'high'), ('gpt-6.1-terra', 'low')},
                             {(c.model, c.effort) for m in matches for c in configs_for(m)})

    def test_uniform_faction_results_do_not_invent_entry_advantage(self):
        matches = schedule()
        for winner in ('good', 'wolves'):
            reports = [{'match_id': m['id'], 'all_checks_passed': True, 'winner': winner} for m in matches]
            ratings = fit_ratings(matches, reports)
            self.assertEqual(6, ratings['valid_games'])
            self.assertTrue(all(abs(r['rating']-1500) < .01 for r in ratings['ratings']))

    def test_full_quartet_game_replays_and_catches_private_view_tampering(self):
        match = schedule()[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = play(match['seed'], roles=match['roles'], configs=configs_for(match), output_dir=root,
                          artifact_stem=match['id'], progress=False,
                          harness_factory=lambda scope: CodexGameHarness(scope, rpc_factory=SevenRPC))
            self.assertTrue(report['all_checks_passed'])
            trial = json.loads((root/f"{match['id']}.private.json").read_text())
            plan = {'configs': {match['id']: [asdict(c) for c in configs_for(match)]}}
            self.assertTrue(verify_trial(trial, match, plan)['referee_replay_verified'])
            record = next(r for p in trial['players'] for r in p['decisions'])
            record['notes_before'] = 'Another player private note'
            with self.assertRaisesRegex(AssertionError, 'notes'):
                verify_trial(trial, match, plan)

    def test_six_way_execution_starts_all_six_before_any_result_returns(self):
        barrier = threading.Barrier(6)
        started = []; lock = threading.Lock()
        with tempfile.TemporaryDirectory() as directory, \
             patch('scripts.play_codex_quartet.check_canaries', return_value={'tested': True}), \
             patch('scripts.play_codex_quartet.parallel_baseline', return_value={'baseline': 'audited'}):
            root = Path(directory)
            plan = create_plan(root/'plan.private.json', 23000, parallel_games=6)
            self.assertEqual(0, plan['initial_gate_games'])
            self.assertEqual(6, plan['parallel_games_after_gate'])
            verify_plan(plan, execution=True)
            changed = deepcopy(plan); changed['parallel_games_after_gate'] = 2
            with self.assertRaisesRegex(AssertionError, 'Execution settings'):
                verify_plan(changed)
            def finish(match, *args):
                with lock: started.append(match['id'])
                barrier.wait(timeout=5)
                return {'match_id': match['id'], 'status': 'finished', 'winner': 'good', 'all_checks_passed': True}
            with patch('scripts.play_codex_quartet.run_one', side_effect=finish), patch('scripts.play_codex_quartet.emit'):
                self.assertEqual(0, run_season(plan, root))
            self.assertEqual(6, len(set(started)))
            self.assertEqual(6, json.loads((root/'ratings.json').read_text())['valid_games'])

    def test_plan_freezes_settings_and_failed_gate_prevents_further_launches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('scripts.play_codex_quartet.check_canaries', return_value={'tested': True}):
                plan = create_plan(root/'plan.private.json', 18000)
                verify_plan(plan, execution=True)
                changed = deepcopy(plan); changed['entries']['sol-medium']['effort'] = 'high'
                with self.assertRaisesRegex(AssertionError, 'Entries'):
                    verify_plan(changed)
                failure = {'match_id': plan['matches'][0]['id'], 'status': 'error', 'all_checks_passed': False}
                with patch('scripts.play_codex_quartet.run_one', return_value=failure) as runner, patch('scripts.play_codex_quartet.emit'):
                    self.assertEqual(1, run_season(plan, root))
                    self.assertEqual(1, runner.call_count)
                ratings = json.loads((root/'ratings.json').read_text())
                self.assertEqual(0, ratings['valid_games'])


if __name__ == '__main__':
    unittest.main()
