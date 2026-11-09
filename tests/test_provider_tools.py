"""Native DeepSeek tool protocol tests; all network responses are synthetic."""

import copy
import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from werewolf import providers as p


def call(name, arguments, call_id="call-1"):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments)}}


def response(calls=None, *, content=None, finish="tool_calls"):
    return {"model": "synthetic-flash", "choices": [{"finish_reason": finish, "message": {
        "content": content, "tool_calls": calls or [], "reasoning_content": "PROVIDER_REASONING_MUST_NOT_SURVIVE"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}}


class ProviderToolsTests(unittest.TestCase):
    def setUp(self):
        self.config = p.deepseek_flash_config(1, "Ada")
        self.observation = {
            "seat": 1, "role": "seer", "day": 1, "phase": "day", "language": "en",
            "players": [{"seat": 1, "name": "Ada", "alive": True}],
            "history": [
                {"kind": "speech", "audience": "public", "text": "OLD_PUBLIC_ONLY_ON_READ", "seat": 2},
                *[{"kind": "speech", "audience": "public", "text": f"Recent statement {i}", "seat": 2}
                  for i in range(4)],
                {"kind": "investigation", "audience": "private", "text": "PRIVATE_RESULT_ONLY_ON_READ", "seat": 1},
            ],
        }
        self.decision = {"id": "INTERNAL_ROUTING_ID", "seat": 1, "kind": "speech", "options": [{"type": "speak"}]}

    def assembled(self):
        return p.build_request(self.config, self.observation, self.decision, "PRIVATE_NOTES_ONLY_ON_READ")

    def infer(self, responses, assembled=None):
        encoded = [io.BytesIO(json.dumps(item).encode()) for item in responses]
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "SYNTHETIC_HEADER_SECRET"}), \
             patch.object(p.http, "urlopen", side_effect=encoded) as network:
            result = p.decide(self.config, assembled or self.assembled())
        return result, network

    def test_config_defaults_preserve_legacy_json_and_new_flash_uses_tools(self):
        self.assertEqual("json", p.PlayerConfig(1, "Old seat", provider="deepseek").interaction_mode)
        self.assertEqual("tools", self.config.interaction_mode)
        self.assertEqual("json", p.deepseek_flash_config(1, "Legacy", interaction_mode="json").interaction_mode)
        for fields in ({"provider": "demo", "interaction_mode": "tools"},
                       {"provider": "openai", "interaction_mode": "tools"},
                       {"provider": "deepseek", "interaction_mode": "tools", "thinking": "enabled", "temperature": None},
                       {"provider": "deepseek", "interaction_mode": "other"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                p.PlayerConfig(1, "Ada", **fields)

    def test_initial_wire_is_compact_and_host_context_is_not_sent(self):
        assembled = self.assembled()
        self.assertIn("PRIVATE_RESULT_ONLY_ON_READ", json.dumps(assembled["tool_context"]))
        body = p.wire_request(self.config, assembled)
        encoded = json.dumps(body)
        for hidden in ("tool_context", "PRIVATE_RESULT_ONLY_ON_READ", "PRIVATE_NOTES_ONLY_ON_READ",
                       "OLD_PUBLIC_ONLY_ON_READ", "INTERNAL_ROUTING_ID"):
            self.assertNotIn(hidden, encoded)
        self.assertNotIn("response_format", body)
        self.assertEqual({"type": "disabled"}, body["thinking"])
        names = {t["function"]["name"] for t in body["tools"]}
        self.assertIn("action_speak", names)
        self.assertIn("read_my_results", names)
        self.assertNotIn("read_wolf_chat", names)
        self.assertIn("read_my_results", assembled["instructions"])
        with self.assertRaises(p.ProviderError):
            p.build_repair_request(assembled, {"type": "bad"})

    def test_reads_then_one_native_action_with_private_trace_and_no_reasoning(self):
        result, network = self.infer([
            response([call("read_my_results", {}, "read-1"), call("read_my_notes", {}, "read-2")]),
            response([call("action_speak", {"text": "I am comparing the claims.", "notes": "Remember my check."}, "action-1")]),
        ])
        self.assertEqual({"type": "speak", "text": "I am comparing the claims.", "notes": "Remember my check."}, dict(result))
        self.assertEqual(2, network.call_count)
        self.assertEqual(26, result.usage["total_tokens"])
        self.assertEqual(2, len(result.tool_trace))
        second_body = json.loads(network.call_args_list[1].args[0].data)
        tool_messages = [m for m in second_body["messages"] if m["role"] == "tool"]
        self.assertEqual(["read-1", "read-2"], [m["tool_call_id"] for m in tool_messages])
        self.assertIn("PRIVATE_RESULT_ONLY_ON_READ", tool_messages[0]["content"])
        self.assertIn("PRIVATE_NOTES_ONLY_ON_READ", tool_messages[1]["content"])
        trace = json.dumps(result.tool_trace)
        self.assertNotIn("PROVIDER_REASONING_MUST_NOT_SURVIVE", trace)
        self.assertNotIn("SYNTHETIC_HEADER_SECRET", trace)
        self.assertNotIn("reasoning_content", json.dumps(second_body))
        self.assertEqual("read_my_results", result.tool_trace[0]["tool_results"][0]["name"])
        self.assertEqual("{}", result.tool_trace[0]["tool_results"][0]["arguments"])

    def test_plain_text_is_not_treated_as_an_action_or_automatically_repaired(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "SECRET"}), \
             patch.object(p.http, "urlopen", return_value=io.BytesIO(json.dumps(
                 response(content='{"type":"speak","text":"Hello."}', finish="stop")).encode())) as network:
            with self.assertRaises(p.ProviderError) as failure:
                p.decide(self.config, self.assembled())
        self.assertEqual(1, network.call_count)
        self.assertFalse(failure.exception.repairable)
        self.assertEqual("missing_tool_call", failure.exception.validation_details["category"])
        self.assertIn('"type":"speak"', failure.exception.tool_trace[0]["assistant"]["content"])

    def test_mixed_or_multiple_terminal_calls_fail_before_execution(self):
        cases = [[call("read_my_notes", {}, "read"), call("action_speak", {"text": "Hello"}, "action")],
                 [call("action_speak", {"text": "One"}, "one"), call("action_speak", {"text": "Two"}, "two")]]
        for calls in cases:
            with self.subTest(calls=calls), patch("werewolf.harness.SeatToolHarness.call") as execute, \
                 patch.dict(os.environ, {"DEEPSEEK_API_KEY": "SECRET"}), \
                 patch.object(p.http, "urlopen", return_value=io.BytesIO(json.dumps(response(calls)).encode())):
                with self.assertRaises(p.ProviderError) as failure:
                    p.decide(self.config, self.assembled())
                self.assertEqual("mixed_or_multiple_actions", failure.exception.validation_details["category"])
                execute.assert_not_called()

    def test_unknown_reads_bad_arguments_and_bad_actions_pause_without_retry(self):
        cases = [(call("read_other_player", {"seat": 2}), "invalid_tool_read"),
                 (call("read_public_log", {"seat": 2}), "invalid_tool_read"),
                 (call("read_my_results", "NOT_JSON"), "invalid_tool_read"),
                 (call("action_speak", {"text": "Hello", "target": 2}), "invalid_tool_action")]
        for native_call, category in cases:
            with self.subTest(call=native_call), patch.dict(os.environ, {"DEEPSEEK_API_KEY": "SECRET"}), \
                 patch.object(p.http, "urlopen", return_value=io.BytesIO(json.dumps(response([native_call])).encode())) as network:
                with self.assertRaises(p.ProviderError) as failure:
                    p.decide(self.config, self.assembled())
                self.assertEqual(1, network.call_count)
                self.assertEqual(category, failure.exception.validation_details["category"])
                self.assertEqual(native_call["function"]["arguments"],
                                 failure.exception.tool_trace[0]["assistant"]["tool_calls"][0]["function"]["arguments"])

    def test_limits_bound_model_requests_reads_and_cumulative_message_size(self):
        encoded = [io.BytesIO(json.dumps(response([call("read_my_notes", {}, f"read-{i}")])).encode()) for i in range(6)]
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "SECRET"}), \
             patch.object(p.http, "urlopen", side_effect=encoded) as network:
            with self.assertRaises(p.ProviderError) as failure:
                p.decide(self.config, self.assembled())
            self.assertEqual(6, network.call_count)
            self.assertEqual("tool_model_budget", failure.exception.validation_details["category"])
        excessive = response([call("read_my_notes", {}, f"read-{i}") for i in range(13)])
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "SECRET"}), \
             patch.object(p.http, "urlopen", return_value=io.BytesIO(json.dumps(excessive).encode())) as network:
            with self.assertRaises(p.ProviderError) as failure:
                p.decide(self.config, self.assembled())
            self.assertEqual(1, network.call_count)
            self.assertEqual("tool_read_budget", failure.exception.validation_details["category"])
        with patch.object(p, "MAX_TOOL_MESSAGE_CHARS", 20), patch.object(p.http, "urlopen") as network:
            with self.assertRaises(p.ProviderError) as failure:
                p.decide(self.config, self.assembled())
            self.assertEqual("tool_message_budget", failure.exception.validation_details["category"])
            network.assert_not_called()

    def test_tool_transport_failure_has_no_retry_and_safe_diagnostics(self):
        def fail(*args, **kwargs):
            raise HTTPError("https://api.deepseek.com", 429, "SECRET_RAW_BODY", {}, io.BytesIO(b"SECRET_RAW_BODY"))
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "SECRET"}), \
             patch.object(p.http, "urlopen", side_effect=fail) as network:
            with self.assertRaises(p.ProviderError) as failure:
                p.decide(self.config, self.assembled())
        self.assertEqual(1, network.call_count)
        self.assertEqual("tool_transport_error", failure.exception.validation_details["category"])
        self.assertNotIn("SECRET", json.dumps(failure.exception.tool_trace))
        self.assertNotIn("SECRET", str(failure.exception))

    def test_malformed_native_shape_keeps_bad_argument_string_but_not_reasoning(self):
        malformed = call("action_speak", "BAD_ARGUMENTS")
        malformed["type"] = "invalid-kind"
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "SECRET"}), \
             patch.object(p.http, "urlopen", return_value=io.BytesIO(json.dumps(response([malformed])).encode())):
            with self.assertRaises(p.ProviderError) as failure:
                p.decide(self.config, self.assembled())
        self.assertEqual("invalid_tool_response", failure.exception.validation_details["category"])
        self.assertIn("BAD_ARGUMENTS", json.dumps(failure.exception.tool_trace))
        self.assertNotIn("PROVIDER_REASONING_MUST_NOT_SURVIVE", json.dumps(failure.exception.tool_trace))


if __name__ == "__main__":
    unittest.main()
