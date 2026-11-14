from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from werewolf.replays import ReplayRunner, load_replay, library, REPLAY_ROOT
from werewolf.server import Controller


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = json.loads((REPLAY_ROOT/'codex-quartet-18000-01.json').read_text())
        cls.runner = ReplayRunner(cls.archive)

    def test_all_games_are_in_catalog_without_roles_or_winners(self):
        catalog = library()
        self.assertEqual(24, len(catalog))
        for row in catalog:
            self.assertEqual({'id','title','language','steps'},set(row))

    def test_early_perspectives_do_not_use_final_roles(self):
        runner = self.runner
        view = runner.replay(0)
        self.assertIsNone(view['winner'])
        self.assertTrue(all(not p.get('role') for p in view['players']))
        own = runner.replay(0,'player',1)
        self.assertEqual(self.archive['roles'][0],own['players'][0]['role'])
        self.assertTrue(all(not p.get('role') for p in own['players'][1:]))
        self.assertEqual('wolves',runner.snapshot()['winner'])
        view['players'][0]['role']='wolf'
        self.assertFalse(runner.replay(0)['players'][0].get('role'))

    def test_private_fields_and_illegal_or_incomplete_actions_are_rejected(self):
        for bad in ('private_notes','tool_trace','api_key'):
            source = deepcopy(self.archive);source[bad]='SECRET'
            with self.assertRaises(ValueError):ReplayRunner(source)
        source=deepcopy(self.archive);source['batches'][0][0]['action']['notes']='SECRET'
        with self.assertRaises(ValueError):ReplayRunner(source)
        source=deepcopy(self.archive);source['batches'][0][0]['action']={'type':'poison','target':99}
        with self.assertRaises(ValueError):ReplayRunner(source)
        source=deepcopy(self.archive);source['batches']=source['batches'][:1]
        with self.assertRaises(ValueError):ReplayRunner(source)
        source=deepcopy(self.archive);source['batches'][0][1]=source['batches'][0][0]
        with self.assertRaises(ValueError):ReplayRunner(source)

    def test_no_path_or_arbitrary_archive_can_be_loaded(self):
        for name in ('../.env','/etc/passwd','a.private.json','',None):
            with self.assertRaises(ValueError):load_replay(name)

    def test_controller_load_is_readonly_and_never_calls_provider(self):
        controller=Controller()
        try:
            with patch('werewolf.providers.decide',side_effect=AssertionError('No inference allowed')):
                first=controller.load_saved({'archive':self.archive},imported=True)
                self.assertTrue(first['read_only']);self.assertEqual(0,first['step']);self.assertIsNone(first['winner'])
                self.assertEqual(111,controller.snapshot()['max_step'])
                self.assertEqual(0,controller.snapshot()['step'])
                self.assertIsNone(controller.snapshot()['winner'])
                for action in ('step','play'):
                    with self.assertRaisesRegex(ValueError,'read-only'):controller.control(action)
                self.assertEqual(self.archive,controller.export())
                controller.busy=True
                with self.assertRaises(RuntimeError):controller.load_saved({'archive':self.archive},imported=True)
                controller.busy=False
        finally:controller.close()



if __name__=='__main__':unittest.main()
