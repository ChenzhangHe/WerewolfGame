from pathlib import Path
import json
import unittest
from scripts.rate_replays import calculate
from werewolf.replays import REPLAY_ROOT


class PortableRatingTests(unittest.TestCase):
    def test_git_replays_reproduce_original_ratings_and_game_totals(self):
        result=calculate(REPLAY_ROOT)
        expected=json.loads(Path('artifacts/codex-quartet-v1/ratings.json').read_text())
        self.assertEqual(6,result['valid_games'])
        self.assertEqual([(r['entry'],r['rating']) for r in expected['ratings']],[(r['entry'],r['rating']) for r in result['ratings']])
        self.assertEqual(72,sum(r['seat_appearances'] for r in result['tournament_points'].values()))

