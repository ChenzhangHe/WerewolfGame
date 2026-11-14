from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from werewolf.codex_league import schedule, configs_for
from scripts.play_codex_league import create_plan, verify_plan, run_season


class SolTerraTests(unittest.TestCase):
    def test_only_two_rating_entries_with_fixed_requested_efforts(self):
        matches=schedule(26000,profile='sol-terra')
        self.assertEqual({'Sol','Terra'},{e for m in matches for e in m['entries']})
        for entry in ('Sol','Terra'):
            roles=Counter(r for m in matches for e,r in zip(m['entries'],m['roles']) if e==entry)
            self.assertEqual(Counter(wolf=12,villager=12,seer=3,witch=3,hunter=3,idiot=3),roles)
        for m in matches:
            self.assertEqual(Counter(Sol=6,Terra=6),Counter(m['entries']))
            for e,c in zip(m['entries'],configs_for(m)):
                self.assertEqual(('gpt-6.1-sol','medium') if e=='Sol' else ('gpt-6.1-terra','low'),(c.model,c.effort))

    def test_all_six_start_and_ratings_have_exactly_two_entries(self):
        barrier=threading.Barrier(6)
        with tempfile.TemporaryDirectory() as directory, \
             patch('scripts.play_codex_league.check_canaries',return_value={'canary':'verified'}), \
             patch('scripts.play_codex_league.validated_pair_baseline',return_value={'baseline':'audited'}):
            root=Path(directory)
            plan=create_plan(root/'plan.private.json',26000,profile='sol-terra',parallel_games=6)
            verify_plan(plan,execution=True)
            bad=deepcopy(plan);bad['entries']['Terra']['effort']='medium'
            with self.assertRaisesRegex(AssertionError,'Entries'):verify_plan(bad)
            def finish(m,*args):
                barrier.wait(timeout=5)
                return {'match_id':m['id'],'status':'finished','winner':'good','all_checks_passed':True}
            old=schedule(25000,profile='sol-terra')[0];old['pair']='history:1'
            previous={'match_id':old['id'],'winner':'wolves','all_checks_passed':True}
            with patch('scripts.play_codex_league.run_one',side_effect=finish) as runner,patch('scripts.play_codex_league.emit'), \
                 patch('scripts.play_codex_league.historical_inputs',return_value=([old],[previous],{})):
                self.assertEqual(0,run_season(plan,root));self.assertEqual(6,runner.call_count)
            ratings=json.loads((root/'ratings.json').read_text())
            self.assertEqual({'Sol','Terra'},{r['entry'] for r in ratings['ratings']})
            self.assertEqual(7,ratings['valid_games'])
            self.assertEqual('model-family',ratings['entry_grouping'])


if __name__=='__main__':unittest.main()
