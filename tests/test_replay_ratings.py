from pathlib import Path
import json
import unittest
import tempfile
import shutil
from scripts.rate_replays import calculate
from werewolf.replays import REPLAY_ROOT


class PortableRatingTests(unittest.TestCase):
    def test_all_replays_reproduce_twenty_four_game_ratings(self):
        result=calculate(REPLAY_ROOT)
        expected=json.loads(Path('artifacts/codex-quartet-21000/cumulative-ratings.json').read_text())
        self.assertEqual(24,result['valid_games'])
        self.assertEqual([(r['entry'],r['rating']) for r in expected['ratings']],[(r['entry'],r['rating']) for r in result['ratings']])
        self.assertEqual(288,sum(r['seat_appearances'] for r in result['tournament_points'].values()))


    def test_first_six_games_still_reproduce_original_pilot(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for source in REPLAY_ROOT.glob('codex-quartet-18000-??.json'):
                shutil.copyfile(source,root/source.name)
            result=calculate(root)
        expected=json.loads(Path('artifacts/codex-quartet-v1/ratings.json').read_text())
        self.assertEqual(6,result['valid_games'])
        self.assertEqual([(r['entry'],r['rating']) for r in expected['ratings']],[(r['entry'],r['rating']) for r in result['ratings']])
