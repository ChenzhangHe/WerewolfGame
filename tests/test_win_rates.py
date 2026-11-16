import unittest
from werewolf.win_rates import win_rates


class PositionRateTests(unittest.TestCase):
    def setUp(self):
        roles=['wolf']*4+['villager']*4+['seer','witch','hunter','idiot']
        self.matches=[{'id':'a','roles':roles,'entries':['Sol']*6+['Terra']*6},
                      {'id':'b','roles':roles,'entries':['Terra']*6+['Sol']*6}]
        self.reports=[{'match_id':'a','winner':'good','all_checks_passed':True},
                      {'match_id':'b','winner':'wolves','all_checks_passed':True}]

    def test_manual_seat_role_and_overall_counts(self):
        s=win_rates(self.matches,self.reports)
        self.assertEqual(2,s['valid_games'])
        self.assertEqual((2,12),tuple(s['overall']['Sol'][k] for k in ('wins','appearances')))
        self.assertEqual((10,12),tuple(s['overall']['Terra'][k] for k in ('wins','appearances')))
        self.assertEqual(0,s['by_seat']['1']['Sol']['wins'])
        self.assertEqual(1,s['by_seat']['1']['Terra']['wins'])
        self.assertEqual(0,s['by_role']['seer']['Sol']['wins'])
        self.assertEqual(1,s['by_role']['seer']['Terra']['wins'])
        for model in ('Sol','Terra'):
            self.assertEqual(12,sum(r[model]['appearances'] for r in s['by_seat'].values()))
            self.assertEqual(12,sum(r[model]['appearances'] for r in s['by_role'].values()))
            self.assertEqual(12,sum(r[model]['appearances'] for seat in s['by_seat_and_role'].values() for r in seat.values()))

    def test_failed_game_is_excluded_and_unobserved_cell_is_null(self):
        self.reports[1]['all_checks_passed']=False
        s=win_rates(self.matches,self.reports)
        self.assertEqual(1,s['valid_games'])
        self.assertEqual(0,s['by_seat']['1']['Terra']['appearances'])
        self.assertIsNone(s['by_seat']['1']['Terra']['win_rate'])
        self.assertEqual(0.0,s['by_seat']['1']['Sol']['win_rate'])

    def test_duplicate_and_unknown_results_are_rejected(self):
        with self.assertRaises(ValueError):win_rates(self.matches,self.reports+[self.reports[0]])
        with self.assertRaises(ValueError):win_rates(self.matches,[{'match_id':'missing'}])
        with self.assertRaises(ValueError):win_rates(self.matches,[{'match_id':'a','winner':None,'all_checks_passed':True}])


if __name__=='__main__':unittest.main()
