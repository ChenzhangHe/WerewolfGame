import unittest
from scripts.rate_replays import calculate
from werewolf.replays import REPLAY_ROOT


class FamilyRatingTests(unittest.TestCase):
    def test_model_family_grouping_keeps_all_historical_outcomes(self):
        result=calculate(REPLAY_ROOT,grouping='model-family')
        self.assertEqual(35,result['valid_games'])
        self.assertEqual({'Sol','Terra'},{r['entry'] for r in result['ratings']})
        self.assertEqual(420,sum(r['seat_appearances'] for r in result['tournament_points'].values()))
        self.assertEqual({'medium':105,'low':105},result['thinking_effort_exposure']['Sol'])
        self.assertEqual({'high':105,'low':105},result['thinking_effort_exposure']['Terra'])
