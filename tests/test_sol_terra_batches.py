from collections import Counter
import unittest
from scripts.run_sol_terra_batches import batches,batch_succeeded


class BatchCampaignTests(unittest.TestCase):
    def test_twelve_fresh_games_keep_two_fixed_settings_and_exact_roles(self):
        cohorts=batches(27000,2);matches=[m for c in cohorts for m in c['matches']]
        self.assertEqual(12,len({m['id'] for m in matches}))
        self.assertEqual([27000,28000],[c['seed'] for c in cohorts])
        for entry in ('Sol','Terra'):
            roles=Counter(r for m in matches for e,r in zip(m['entries'],m['roles']) if e==entry)
            self.assertEqual(Counter(wolf=24,villager=24,seer=6,witch=6,hunter=6,idiot=6),roles)
        for c in cohorts:
            for m in c['matches']:
                for entry,config in zip(m['entries'],c['configs'][m['id']]):
                    expected=('gpt-6.1-sol','medium') if entry=='Sol' else ('gpt-6.1-terra','low')
                    self.assertEqual(expected,(config['model'],config['effort']))

    def test_failure_or_killed_worker_never_unlocks_the_next_cohort(self):
        reports=[{'all_checks_passed':True} for _ in range(6)]
        self.assertTrue(batch_succeeded(0,reports))
        self.assertFalse(batch_succeeded(-9,reports))
        self.assertFalse(batch_succeeded(1,reports))
        self.assertFalse(batch_succeeded(0,reports[:5]))
        reports[0]={'all_checks_passed':False}
        self.assertFalse(batch_succeeded(0,reports))


if __name__=='__main__':unittest.main()
