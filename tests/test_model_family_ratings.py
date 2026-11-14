import unittest
import json
from pathlib import Path
from scripts.rate_replays import calculate
from werewolf.replays import REPLAY_ROOT


class FamilyRatingTests(unittest.TestCase):
    def test_model_family_grouping_keeps_all_historical_outcomes(self):
        baseline=json.loads(Path('artifacts/codex-sol-terra-more-v1/preregistration.json').read_text())['baseline_replays']
        result=calculate(REPLAY_ROOT,grouping='model-family',filenames=sorted(baseline))
        self.assertEqual(39,result['valid_games'])
        self.assertEqual({'Sol','Terra'},{r['entry'] for r in result['ratings']})
        self.assertEqual(468,sum(r['seat_appearances'] for r in result['tournament_points'].values()))
        self.assertEqual({'medium':129,'low':105},result['thinking_effort_exposure']['Sol'])
        self.assertEqual({'high':105,'low':129},result['thinking_effort_exposure']['Terra'])
