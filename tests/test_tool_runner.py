"""The tool transport preserves the runner's commit and archive boundaries."""
import copy
import json
import unittest
from unittest.mock import patch

from werewolf import providers as p
from werewolf.runner import Runner


class ToolRunnerTests(unittest.TestCase):
    def runner(self, **kwargs):
        configs = [p.deepseek_flash_config(s, f"Player {s}") for s in range(1, 13)]
        with patch.object(p, "check_credentials"):
            return Runner(configs, **kwargs)

    @staticmethod
    def answer(config, request):
        action = copy.deepcopy(request["tool_context"]["decision"]["options"][0])
        if action["type"] in {"speak", "discuss"}:
            action["text"] = "A game statement."
        result = p.DecisionResult(action)
        result.tool_trace = [{"wire_request": p.wire_request(config, request),
                              "assistant": {"content": None, "tool_calls": []},
                              "tool_results": [{"result": "PRIVATE_TRACE_SENTINEL"}]}]
        return result

    def test_successful_tool_trace_is_private_and_restore_is_model_free(self):
        runner = self.runner()
        with patch.object(p, "decide", side_effect=self.answer):
            self.assertNotEqual("error", runner.step()["status"])
        archive = runner.export()
        self.assertTrue(all(r["accepted"] and r["tool_trace"] for r in archive["inference"]))
        for mode, seat in (("mystery", None), ("player", 1)):
            self.assertNotIn("PRIVATE_TRACE_SENTINEL", json.dumps(runner.snapshot(mode, seat)))
        with patch.object(p, "decide", side_effect=AssertionError("No inference during restore")):
            restored = Runner.from_archive(archive)
        self.assertEqual(archive["game"]["events"], restored.export()["game"]["events"])
        self.assertTrue(all(c.interaction_mode == "tools" for c in restored.configs))

    def test_tool_failure_never_repairs_or_partially_commits(self):
        runner = self.runner(allow_format_repair=True)
        before = runner.game.export()
        count = len(runner.game.pending())
        def reject(config, request):
            exc = p.ProviderError("Invalid tool arguments.")
            exc.rejected_result = p.DecisionResult({"type": "invalid"})
            exc.tool_trace = [{"error": "PRIVATE_TRACE_SENTINEL"}]
            raise exc
        with patch.object(p, "decide", side_effect=reject) as inference:
            self.assertEqual("error", runner.step()["status"])
        self.assertEqual(count, inference.call_count)
        self.assertEqual(before, runner.game.export())
        self.assertTrue(all(r["tool_trace"] and not r["repair"] for r in runner.export()["inference"]))
        self.assertNotIn("PRIVATE_TRACE_SENTINEL", json.dumps(runner.snapshot()))

    def test_restore_checks_full_host_context_not_only_compact_briefing(self):
        runner = self.runner()
        first = runner.game.pending()[0]["seat"]
        def infer(config, request):
            if config.seat == first:
                raise p.ProviderError("Test failure.")
            return self.answer(config, request)
        with patch.object(p, "decide", side_effect=infer):
            runner.step()
        archive = runner.export()
        archive["pending_batch"][0]["request"]["tool_context"]["observation"]["history"].append(
            {"kind": "speech", "audience": "public", "text": "Injected archive context"})
        with self.assertRaises(ValueError):
            Runner.from_archive(archive)

    def test_restore_keeps_original_tool_protocol_after_application_upgrade(self):
        runner = self.runner()
        archive = runner.export()
        archive['tool_prompt_version'] = 'player-tools-v2'
        restored = Runner.from_archive(archive)
        with patch.object(p, 'TOOLS_PROMPT_VERSION', 'player-tools-v3'), \
             patch.object(p, 'decide', side_effect=self.answer):
            restored.step()
        record = restored.export()['inference'][0]
        self.assertEqual('player-tools-v2', record['request']['prompt_version'])
        log_tool = next(t for t in record['wire_request']['tools']
                        if t['function']['name'] == 'read_public_log')
        self.assertIn('limit', log_tool['function']['parameters']['properties'])
        self.assertEqual('player-tools-v2', restored.export()['tool_prompt_version'])
