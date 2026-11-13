from collections import Counter
import unittest
from scripts.queue_quartet import next_schedule, prior_ready
from scripts.extend_codex_quartet import continuation_schedule
from werewolf.codex_quartet import ENTRIES, schedule


class QueueTests(unittest.TestCase):
    def test_four_rotations_balance_every_role_over_twenty_four_games(self):
        matches=schedule()+continuation_schedule()+next_schedule()
        self.assertEqual(24,len({m['id'] for m in matches}))
        for entry in ENTRIES:
            counts=Counter(r for m in matches for e,r in zip(m['entries'],m['roles']) if e==entry)
            self.assertEqual(Counter(wolf=24,villager=24,seer=6,witch=6,hunter=6,idiot=6),counts)
        self.assertEqual(6,len(next_schedule()))
        for m in next_schedule():self.assertEqual(Counter({e:3 for e in ENTRIES}),Counter(m['entries']))

    def test_queue_only_unlocks_after_complete_successful_previous_run(self):
        self.assertFalse(prior_ready({'phase':'running_games','completed_games':11}))
        with self.assertRaises(ValueError):prior_ready({'phase':'stopped_on_failure'})
        with self.assertRaises(AssertionError):prior_ready({'phase':'finished','completed_games':11,'returned_games':12,'runner_exit_code':0,'rating_exit_code':0})
        with self.assertRaises(AssertionError):prior_ready({'phase':'finished','completed_games':12,'returned_games':12,'runner_exit_code':0,'rating_exit_code':1})
        self.assertTrue(prior_ready({'phase':'finished','completed_games':12,'returned_games':12,'runner_exit_code':0,'rating_exit_code':0}))


if __name__=='__main__':unittest.main()
