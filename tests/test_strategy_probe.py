"""The optional paid strategy probe keeps mode comparisons and seat scope clear."""
import copy
import json
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from werewolf import providers as p

PROBE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts' / 'compare_strategy.py'),
                      run_name='strategy_probe_tests')


class StrategyProbeTests(unittest.TestCase):
    def setUp(self):
        self.config = p.deepseek_flash_config(8, 'Yue')
        self.record = {'seat': 8, 'batch_index': 5, 'request': {'tool_context': {
            'observation': {'seat': 8, 'role': 'wolf', 'language': 'zh', 'history': [],
                            'players': [{'seat': 8, 'alive': True}], 'wolf_teammates': [4, 7, 8, 10]},
            'decision': {'kind': 'explosion', 'options': [{'type': 'pass'}, {'type': 'explode'}]},
            'private_notes': 'ONLY_THIS_SEATS_NOTES'}}}

    def test_matched_modes_have_identical_messages_and_output_cap(self):
        before = copy.deepcopy(self.record)
        off = PROBE['prepare'](self.config, self.record, 'off')[2]
        high = PROBE['prepare'](self.config, self.record, 'high')[2]
        self.assertEqual(off['messages'], high['messages'])
        self.assertEqual(32768, off['max_tokens'])
        self.assertEqual(off['max_tokens'], high['max_tokens'])
        self.assertEqual({'type': 'enabled'}, high['thinking'])
        self.assertEqual('high', high['reasoning_effort'])
        self.assertNotIn('temperature', off)
        self.assertNotIn('temperature', high)
        self.assertNotIn('tools', high)
        self.assertEqual(before, self.record)

    def test_native_modes_use_same_messages_tools_choice_and_output_cap(self):
        off = PROBE['prepare'](self.config, self.record, 'off', 'tools')[2]
        high = PROBE['prepare'](self.config, self.record, 'high', 'tools')[2]
        self.assertEqual(off['messages'], high['messages'])
        self.assertEqual(off['tools'], high['tools'])
        self.assertEqual('auto', off['tool_choice'])
        self.assertEqual(off['tool_choice'], high['tool_choice'])
        self.assertEqual(off['max_tokens'], high['max_tokens'])
        self.assertNotIn('response_format', high)

    def test_reasoning_never_survives_into_probe_results_and_no_retry(self):
        response = {'model': 'synthetic', 'choices': [{'finish_reason': 'stop', 'message': {
            'content': '{"type":"pass"}', 'reasoning_content': 'PRIVATE_REASONING_SENTINEL'}}],
            'usage': {'completion_tokens': 5}}
        with patch.object(p, '_send_http', return_value=response) as send:
            result = PROBE['run_one'](('last_wolf', self.record, self.config, 'high', 0))
        self.assertEqual({'type': 'pass'}, result['action'])
        self.assertNotIn('PRIVATE_REASONING_SENTINEL', json.dumps(result))
        self.assertEqual(1, send.call_count)
        self.assertEqual({'attempts': 1}, send.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
