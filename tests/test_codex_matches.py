"""Referee commits, dead-seat delivery, and full-match replay without network."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.play_codex import play, audit_match
from werewolf.codex_harness import CodexGameHarness
from test_codex_harness import FakeRPC


class AutoRPC(FakeRPC):
    def __init__(self, cwd):
        super().__init__(cwd)
        self.generation_starts = Counter()

    def rpc(self, method, params, **kwargs):
        if method == 'turn/start':
            prompt = json.loads(params['input'][0]['text'])
            briefing = prompt['briefing']
            tools = {t['function']['name']: t['function'] for t in prompt['tool_catalog']
                     if t['function']['name'].startswith('action_')}
            name = next((n for n in ('action_pass', 'action_stay', 'action_withdraw') if n in tools), next(iter(tools)))
            args = {}
            for key, schema in tools[name]['parameters']['properties'].items():
                if key == 'text':
                    args[key] = 'A fictional offline test statement.'
                elif 'enum' in schema:
                    choices = schema['enum']
                    if key == 'target':
                        choices = [v for v in choices if v is not None and v not in briefing.get('wolf_teammates', [])] or choices
                    args[key] = choices[0]
            self.plans[params['threadId']] = [[(name, args)]]
            self.generation_starts[params['threadId']] += 1
        return super().rpc(method, params, **kwargs)


def factory(scope):
    return CodexGameHarness(scope, rpc_factory=AutoRPC)


class CodexMatchTests(unittest.TestCase):
    def test_existing_private_evidence_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'codex-match-1.private.json'
            target.write_text('existing evidence')
            def never_start(scope):
                raise AssertionError('Must not start Codex before checking existing artifacts.')
            with self.assertRaisesRegex(ValueError, 'already exist'):
                play(1, output_dir=Path(directory), harness_factory=never_start, progress=False)
            self.assertEqual('existing evidence', target.read_text())

    def test_full_match_commits_and_audits_without_delivering_to_dead_players(self):
        with tempfile.TemporaryDirectory() as directory:
            report = play(1, output_dir=Path(directory), harness_factory=factory, progress=False)
            self.assertTrue(report['all_checks_passed'])
            self.assertTrue(report['referee_replay_verified'])
            self.assertEqual('finished', report['status'])
            self.assertEqual(report['accepted_actions'], report['committed_actions'])
            trial = json.loads((Path(directory)/'codex-match-1.private.json').read_text())
            player = next(p for p in trial['players'] if len(p['decisions']) >= 2)
            tampered = deepcopy(trial)
            record = next(p for p in tampered['players'] if p['config']['seat'] == player['config']['seat'])['decisions'][0]
            record['observation']['players'][0]['role'] = 'seer'
            with self.assertRaises(AssertionError):
                audit_match(tampered)

    def test_batch_limit_is_not_reported_as_a_completed_game(self):
        with tempfile.TemporaryDirectory() as directory:
            report = play(2, output_dir=Path(directory), harness_factory=factory, progress=False, max_batches=1)
            self.assertEqual('batch_limit', report['status'])
            self.assertIsNone(report['winner'])
            self.assertFalse(report['all_checks_passed'])


if __name__ == '__main__':
    unittest.main()
