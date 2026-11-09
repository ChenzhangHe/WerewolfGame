"""Long thinking waits and retry status must not look like model action errors."""
from dataclasses import replace
import io
import json
import os
import unittest
from unittest.mock import patch

from werewolf import providers as p
from werewolf.server import Controller


class TransportWaitTests(unittest.TestCase):
    def test_thinking_wait_budget_and_safe_timeout_diagnostics(self):
        config = replace(p.deepseek_flash_config(1, 'Player'), thinking='enabled',
                         reasoning_effort='high', temperature=None, max_tokens=32768)
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'KEY_MUST_NOT_APPEAR'}), \
             patch.object(p.http, 'urlopen', side_effect=TimeoutError('SECRET_CAUSE_MUST_NOT_APPEAR')) as network:
            with self.assertRaises(p.ProviderError) as failure:
                p._send_http(config, {'model': 'synthetic'}, attempts=1)
        self.assertEqual(300, network.call_args.kwargs['timeout'])
        self.assertEqual({'failure_type': 'TimeoutError', 'timeout_seconds': 300, 'attempts': 1},
                         failure.exception.validation_details['transport'])
        self.assertNotIn('SECRET_CAUSE', str(failure.exception))
        self.assertNotIn('KEY_MUST', json.dumps(failure.exception.validation_details))

    def test_fast_mode_wait_is_unchanged(self):
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'SYNTHETIC'}), \
             patch.object(p.http, 'urlopen', return_value=io.BytesIO(b'{}')) as network:
            p._send_http(p.deepseek_flash_config(1, 'Player'), {'model': 'synthetic'}, attempts=1)
        self.assertEqual(90, network.call_args.kwargs['timeout'])

    def test_inflight_retry_hides_stale_error_without_erasing_failure_view(self):
        controller = Controller()
        try:
            with controller.condition:
                controller.views['mystery'].update(status='error', error='Prior recorded failure')
                controller.busy = True
                live = controller.snapshot()
                self.assertEqual('running', live['status'])
                self.assertIsNone(live['error'])
                controller.busy = False
                self.assertEqual('Prior recorded failure', controller.snapshot()['error'])
        finally:
            controller.close()
            controller.worker.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
