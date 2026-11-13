from collections import Counter
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.extend_codex_quartet import continuation_schedule, create_plan, verify_plan, run_season
from werewolf.codex_quartet import ENTRIES, schedule
from werewolf.ratings import fit_ratings


class ExtensionTests(unittest.TestCase):
    def test_twelve_new_games_keep_roles_balanced_and_layout_ids_distinct(self):
        new = continuation_schedule()
        self.assertEqual(12, len(new))
        old = schedule()
        for m in old:
            m['pair'] = f"18000:{m['pair']}"
        matches = old+new
        self.assertEqual(18, len({m['id'] for m in matches}))
        self.assertEqual(9, len({m['pair'] for m in matches}))
        for entry in ENTRIES:
            counts = Counter(r for m in matches for e, r in zip(m['entries'], m['roles']) if e == entry)
            self.assertEqual(18, counts['wolf']); self.assertEqual(18, counts['villager'])
            self.assertEqual([4, 4, 5, 5], sorted(counts[r] for r in ('seer', 'witch', 'hunter', 'idiot')))
        reports = [{'match_id': m['id'], 'all_checks_passed': True, 'winner': 'good'} for m in matches]
        fit = fit_ratings(matches, reports)
        self.assertEqual(18, fit['valid_games'])
        self.assertTrue(all(abs(r['rating']-1500) < .01 for r in fit['ratings']))

    def test_first_failure_stops_additional_games_and_preserves_baseline(self):
        old = schedule()
        for m in old:
            m['pair'] = f"18000:{m['pair']}"
        reports = [{'match_id': m['id'], 'all_checks_passed': True, 'winner': 'good'} for m in old]
        evidence = old, reports, {'baseline': 'frozen'}
        with tempfile.TemporaryDirectory() as directory, \
             patch('scripts.extend_codex_quartet.baseline_evidence', return_value=evidence), \
             patch('scripts.extend_codex_quartet.check_canaries', return_value={'canary': 'frozen'}):
            root = Path(directory)
            plan = create_plan(root/'plan.private.json'); verify_plan(plan, execution=True)
            failure = {'match_id': plan['matches'][0]['id'], 'status': 'error', 'all_checks_passed': False}
            with patch('scripts.extend_codex_quartet.run_one', return_value=failure) as run, patch('scripts.extend_codex_quartet.emit'):
                self.assertEqual(1, run_season(plan, root)); self.assertEqual(1, run.call_count)
            import json
            cumulative = json.loads((root/'cumulative-ratings.json').read_text())
            self.assertEqual(6, cumulative['valid_games'])
            self.assertEqual(18, cumulative['scheduled_games'])


if __name__ == '__main__':
    unittest.main()
