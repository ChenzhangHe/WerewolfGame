from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from werewolf.codex_league import ENTRIES, schedule, validate_schedule, configs_for
from werewolf.codex_harness import CodexGameHarness
from werewolf.ratings import fit_ratings
from scripts.play_codex import play
from scripts.play_codex_league import create_plan, verify_plan, verify_trial, run_season, collect_existing
from test_codex_matches import AutoRPC


class SevenRPC(AutoRPC):
    def __init__(self, cwd):
        super().__init__(cwd)
        self.models = {model: {'supportedReasoningEfforts': [{'reasoningEffort': e} for e in ('high', 'medium', 'low')]}
                       for model, _ in ENTRIES.values()}


class CodexLeagueTests(unittest.TestCase):
    def test_initial_pair_has_exact_roles_positions_and_requested_models(self):
        matches = schedule()
        for entry in ('sol-medium', 'terra-low'):
            roles = Counter(r for m in matches for e, r in zip(m['entries'], m['roles']) if e == entry)
            self.assertEqual(Counter(wolf=12, villager=12, seer=3, witch=3, hunter=3, idiot=3), roles)
            positions = Counter(s for m in matches for s, e in enumerate(m['entries'], 1) if e == entry)
            self.assertEqual(Counter({s: 3 for s in range(1, 13)}), positions)
        self.assertEqual({('gpt-6.1-sol', 'medium'), ('gpt-6.1-terra', 'low')},
                         {(c.model, c.effort) for m in matches for c in configs_for(m)})

    def test_six_game_rotation_limits_role_and_position_imbalance(self):
        for seed in range(10):
            matches = schedule(seed, profile="seven")
            validate_schedule(matches)
            self.assertEqual(6, len(matches))
            counts = Counter(e for m in matches for e in m['entries'])
            self.assertEqual([10, 10, 10, 10, 10, 11, 11], sorted(counts.values()))
            for e in ENTRIES:
                roles = Counter(r for m in matches for entry, r in zip(m['entries'], m['roles']) if entry == e)
                self.assertIn(roles['wolf'], (3, 4))
                self.assertIn(roles['villager'], (3, 4))
            self.assertEqual(matches, schedule(seed, profile="seven"))

    def test_fourteen_game_rotation_balances_roles_and_personalities(self):
        matches = schedule(games=14, profile="seven")
        for e in ENTRIES:
            roles = Counter(r for m in matches for entry, r in zip(m['entries'], m['roles']) if entry == e)
            self.assertEqual(Counter(wolf=8, villager=8, seer=2, witch=2, hunter=2, idiot=2), roles)
        reports = [{'match_id': m['id'], 'all_checks_passed': True, 'winner': 'good'} for m in matches]
        self.assertTrue(all(abs(r['rating']-1500) < .01 for r in fit_ratings(matches, reports)['ratings']))

    def test_full_seven_configuration_game_replays_and_detects_config_tampering(self):
        match = schedule(profile="seven")[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = play(match['seed'], roles=match['roles'], configs=configs_for(match),
                          output_dir=root, artifact_stem=match['id'], progress=False,
                          harness_factory=lambda scope: CodexGameHarness(scope, rpc_factory=SevenRPC))
            self.assertTrue(report['all_checks_passed'])
            trial = json.loads((root/f"{match['id']}.private.json").read_text())
            plan = {'configs': {match['id']: [asdict(c) for c in configs_for(match)]}}
            self.assertTrue(verify_trial(trial, match, plan)['referee_replay_verified'])
            trial['players'][0]['config']['effort'] = 'max'
            with self.assertRaisesRegex(AssertionError, 'configurations'):
                verify_trial(trial, match, plan)

    def make_plan(self, root):
        with patch('scripts.play_codex_league.check_canaries', return_value={'checked': True}):
            return create_plan(root/'plan.private.json', 15000)

    def test_plan_freezes_models_schedule_and_code(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = self.make_plan(Path(directory))
            verify_plan(plan, execution=True)
            changed = deepcopy(plan)
            changed['configs'][changed['matches'][0]['id']][0]['effort'] = 'max'
            with self.assertRaisesRegex(AssertionError, 'settings'):
                verify_plan(changed)
            changed = deepcopy(plan); changed['source_fingerprint'] = 'changed'
            verify_plan(changed)
            with self.assertRaisesRegex(AssertionError, 'Code changed'):
                verify_plan(changed, execution=True)

    def test_gate_failure_stops_without_launching_remaining_games(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.make_plan(root)
            failure = {'match_id': plan['matches'][0]['id'], 'status': 'error', 'all_checks_passed': False}
            with patch('scripts.play_codex_league.check_canaries', return_value=plan['canary_digests']), \
                 patch('scripts.play_codex_league.run_one', return_value=failure) as runner, \
                 patch('scripts.play_codex_league.emit'):
                self.assertEqual(1, run_season(plan, root))
                self.assertEqual(1, runner.call_count)
            self.assertEqual(5, len(json.loads((root/'results.json').read_text())['scheduler']['unattempted']))

    def test_uncertain_attempt_is_retained_and_never_restarted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.make_plan(root)
            match = plan['matches'][0]
            (root/f"{match['id']}.claim.private.json").write_text('{}')
            reports, remaining = collect_existing(plan, root)
            self.assertEqual('interrupted', reports[0]['status'])
            self.assertEqual(5, len(remaining))


if __name__ == '__main__':
    unittest.main()
