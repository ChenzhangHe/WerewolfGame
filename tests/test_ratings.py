"""Synthetic outcome checks for identifiable team skill and honest shrinkage."""
from copy import deepcopy
import unittest

from werewolf.league import schedule, SOL, DEEPSEEK
from werewolf.ratings import fit_ratings, cholesky, solve


def reports_for(matches, winner):
    return [{'match_id': m['id'], 'winner': winner(m), 'all_checks_passed': True} for m in matches]


class RatingTests(unittest.TestCase):
    def test_prior_and_faction_only_results_cannot_manufacture_a_model_advantage(self):
        matches = schedule()
        empty = fit_ratings(matches, [])
        self.assertEqual(0, empty['valid_games'])
        self.assertEqual('no-valid-outcomes-prior-only', empty['status'])
        for row in empty['ratings']:
            self.assertEqual(1500, row['rating'])
            self.assertGreater(row['sd'], 190)
        fit = fit_ratings(matches, reports_for(matches, lambda m: 'good'))
        self.assertEqual(12, fit['valid_games'])
        self.assertGreater(fit['good_baseline_probability_at_map'], .5)
        self.assertTrue(all(abs(row['rating']-1500) < .01 for row in fit['ratings']))

    def test_known_stronger_entry_is_recovered_without_replicating_seat_outcomes(self):
        matches = schedule()
        def winner(m):
            wolves = sum(e == SOL and r == 'wolf' for e, r in zip(m['entries'], m['roles']))
            return 'good' if wolves < 2 or (wolves == 2 and int(m['id'][-2:]) % 2) else 'wolves'
        fit = fit_ratings(matches, reports_for(matches, winner))
        self.assertEqual(12, fit['valid_games'])
        by_entry = {row['entry']: row for row in fit['ratings']}
        self.assertGreater(by_entry[SOL]['rating'], by_entry[DEEPSEEK]['rating'])
        self.assertGreater(by_entry[SOL]['approx_95_interval'][1]-by_entry[SOL]['approx_95_interval'][0], 200)
        self.assertEqual(72, by_entry[SOL]['seat_appearances'])
        self.assertTrue(all(0 < p['good_win_probability_at_map'] < 1 for p in fit['in_sample_probabilities']))

    def test_failed_games_excluded_and_batch_refit_is_order_independent(self):
        matches = schedule()
        reports = reports_for(matches, lambda m: 'good')
        reports[0].update(all_checks_passed=False, winner=None, status='error')
        a = fit_ratings(matches, reports)
        b = fit_ratings(list(reversed(matches)), list(reversed(reports)))
        self.assertEqual(a, b)
        self.assertEqual(11, a['valid_games'])
        self.assertEqual([{'match_id': matches[0]['id'], 'status': 'error'}], a['excluded'])
        self.assertEqual(66, a['ratings'][0]['seat_appearances'])
        with self.assertRaises(ValueError):
            fit_ratings(matches, reports+[reports[1]])
        bad = deepcopy(matches)
        bad[0]['roles'][0] = 'guard'
        with self.assertRaises(ValueError):
            fit_ratings(bad, reports)

    def test_configuration_names_do_not_change_estimates(self):
        matches = schedule()
        reports = reports_for(matches, lambda m: 'good' if m['seed'] % 3 else 'wolves')
        original = fit_ratings(matches, reports)
        renamed = deepcopy(matches)
        mapping = {SOL: 'A', DEEPSEEK: 'Z'}
        for match in renamed:
            match['entries'] = [mapping[e] for e in match['entries']]
        other = fit_ratings(renamed, reports)
        by_entry = {r['entry']: r for r in other['ratings']}
        for row in original['ratings']:
            self.assertEqual(row['rating'], by_entry[mapping[row['entry']]]['rating'])
            self.assertEqual(row['sd'], by_entry[mapping[row['entry']]]['sd'])

    def test_positive_definite_solver(self):
        result = solve(cholesky([[4, 1], [1, 3]]), [1, 2])
        self.assertAlmostEqual(1/11, result[0])
        self.assertAlmostEqual(7/11, result[1])


if __name__ == '__main__':
    unittest.main()
