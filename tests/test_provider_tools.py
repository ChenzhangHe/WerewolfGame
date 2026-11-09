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

    def assembled(self, version=None):
        if version is not None:
            return p._build_tools_request(self.config, self.observation, self.decision,
                                          "PRIVATE_NOTES_ONLY_ON_READ", "en", version=version)
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

    def test_v5_adds_upfront_facts_without_changing_v4_briefing_or_legal_choices(self):
        observation = copy.deepcopy(self.observation)
        observation["role"] = "wolf"
        observation["wolf_teammates"] = [1, 3, 7, 12]
        decision = {"kind": "explosion", "options": [{"type": "pass"}, {"type": "explode"}]}
        def assembled(version):
            return p._build_tools_request(self.config, observation, decision, "", "en", version=version)
        old = assembled("player-tools-v4")
        old_body = p.wire_request(self.config, old)
        new = assembled("player-tools-v5")
        new_body = p.wire_request(self.config, new)
        self.assertNotIn("win_conditions", old["input"])
        self.assertNotIn("death_consequences", old["input"])
        self.assertIn("win_conditions", new["input"])
        self.assertIn("death_consequences", new["input"])
        # The delta is public rules, not another seat's knowledge or changed state.
        new_without_facts = {k: v for k, v in new["input"].items()
                             if k not in {"win_conditions", "death_consequences"}}
        self.assertEqual(old["input"], new_without_facts)
        old_tools = {t["function"]["name"]: t["function"] for t in old_body["tools"]}
        new_tools = {t["function"]["name"]: t["function"] for t in new_body["tools"]}
        self.assertEqual(set(old_tools), set(new_tools))
        self.assertIn("action_pass", new_tools)
        self.assertIn("action_explode", new_tools)
        for name in old_tools:
            self.assertEqual(old_tools[name]["parameters"], new_tools[name]["parameters"])
            if name not in {"action_pass", "action_explode"}:
                self.assertEqual(old_tools[name], new_tools[name])
        self.assertNotEqual(old_tools["action_explode"]["description"], new_tools["action_explode"]["description"])
        self.assertNotEqual(old_tools["action_pass"]["description"], new_tools["action_pass"]["description"])
        self.assertEqual(old["instructions"], new["instructions"])
        # Constructing v5 cannot mutate the legacy request/harness profile.
        self.assertEqual(old_body, p.wire_request(self.config, assembled("player-tools-v4")))
        self.assertEqual(p.tool_protocol_limits("player-tools-v4"), p.tool_protocol_limits("player-tools-v5"))

    def test_serialized_v4_request_keeps_its_profile_when_default_advances(self):
        original = self.assembled("player-tools-v4")
        stored = json.loads(json.dumps(original))
        body = p.wire_request(self.config, original)
        self.assertEqual("player-tools-v8", p.TOOLS_PROMPT_VERSION)
        self.assertEqual("player-tools-v4", stored["prompt_version"])
        self.assertEqual(body, p.wire_request(self.config, stored))
        self.assertNotIn("win_conditions", json.loads(body["messages"][1]["content"]))
        self.assertIn("win_conditions", self.assembled()["input"])

    def test_v5_bilingual_facts_do_not_remove_last_wolfs_legal_explosion(self):
        for language in ("en", "zh"):
            observation = {**copy.deepcopy(self.observation), "language": language,
                           "role": "wolf", "wolf_teammates": [1]}
            decision = {"kind": "explosion", "options": [{"type": "pass"}, {"type": "explode"}]}
            request = p._build_tools_request(self.config, observation, decision, "", language,
                                              version="player-tools-v5")
            for key in ("win_conditions", "death_consequences"):
                self.assertIsInstance(request["input"][key], str)
                self.assertTrue(request["input"][key])
            self.assertIn("狼人" if language == "zh" else "wolves", request["input"]["win_conditions"].lower())
            # Rules are made explicit; the host neither chooses for the model
            # nor prohibits a legal (even losing) sacrifice.
            self.assertEqual({"type": "explode"}, p._seat_harness(request).call("action_explode", {}))

    def test_v6_handles_long_chinese_log_across_all_six_requests(self):
        observation = copy.deepcopy(self.observation)
        observation["language"] = "zh"
        observation["history"] = [
            {"kind": "speech", "audience": "public", "seat": 2,
             "text": f"公开发言{i}：" + "请根据公开票型判断。" * 100}
            for i in range(50)
        ]
        def assembled(version):
            return p._build_tools_request(self.config, observation, self.decision, "", "zh", version=version)
        replies = [response([call("read_public_log", {"offset": i * 10}, f"read-{i}")])
                   for i in range(5)]
        replies.append(response([call("action_speak", {"text": "我会根据公开记录投票。"})]))
        result, network = self.infer(replies, assembled("player-tools-v6"))
        self.assertEqual(6, network.call_count)
        sizes = [len(json.dumps(t["wire_request"]["messages"], ensure_ascii=False))
                 for t in result.tool_trace]
        self.assertGreater(max(sizes), 24_000)
        self.assertGreater(sum(sizes), 144_000)
        self.assertEqual("speak", result["type"])
        self.assertEqual({"action_speak"}, {t["function"]["name"]
                         for t in result.tool_trace[-1]["wire_request"]["tools"]})
        self.assertEqual(p.wire_request(self.config, assembled("player-tools-v5")),
                         p.wire_request(self.config, assembled("player-tools-v6")))
        with self.assertRaises(p.ProviderError) as failure:
            self.infer(replies, assembled("player-tools-v5"))
        self.assertEqual("tool_context_budget", failure.exception.validation_details["category"])
        for version in ("player-tools-v4", "player-tools-v5"):
            limits = p.tool_protocol_limits(version)
            self.assertEqual(24_000, limits["context_chars"])
            self.assertEqual(144_000, limits["message_chars"])

    def test_v8_puts_output_limits_upfront_without_changing_legal_actions(self):
        for language in ("en", "zh"):
            observation = {**copy.deepcopy(self.observation), "language": language}
            def assembled(version):
                return p._build_tools_request(self.config, observation, self.decision, "", language, version=version)
            old, new = assembled("player-tools-v7"), assembled("player-tools-v8")
            self.assertNotIn("output_limits", old["input"])
            self.assertEqual(1200, new["input"]["output_limits"]["speech_max_chars"])
            self.assertEqual(old["input"], {k:v for k,v in new["input"].items() if k != "output_limits"})
            self.assertIn("OUTPUT LENGTH:", new["instructions"])
            self.assertIn("not a token or word limit", new["instructions"])
            old_tools, new_tools = p.wire_request(self.config, old)["tools"], p.wire_request(self.config, new)["tools"]
            self.assertEqual([t["function"]["name"] for t in old_tools], [t["function"]["name"] for t in new_tools])
            text = next(t for t in new_tools if t["function"]["name"] == "action_speak")["function"]["parameters"]["properties"]["text"]
            self.assertEqual(1200, text["maxLength"])
            self.assertIn("400–700", text["description"])

    def test_tool_speech_length_boundaries_preserve_text_and_diagnose_rejection(self):
        for length in (1200, 1201, 1259):
            text = "中\n " + "文" * (length - 3)
            reply = response([call("action_speak", {"text": text})])
            if length == 1200:
                result, _ = self.infer([reply])
                self.assertEqual(text, result["text"])
                continue
            with self.subTest(length=length), self.assertRaises(p.ProviderError) as failure:
                self.infer([reply])
            details = failure.exception.validation_details
            self.assertEqual("invalid_tool_action", details["category"])
            self.assertEqual({"category": "invalid_speech_text", "field": "text", "actual_chars": length, "max_chars": 1200},
                             details["action_validation"])
            self.assertEqual(reply["choices"][0]["message"]["tool_calls"], failure.exception.tool_trace[0]["assistant"]["tool_calls"])
            self.assertEqual([], failure.exception.tool_trace[0]["tool_results"])

    def test_initial_wire_is_compact_and_host_context_is_not_sent(self):
        assembled = self.assembled()
        self.assertIn("PRIVATE_RESULT_ONLY_ON_READ", json.dumps(assembled["tool_context"]))
        body = p.wire_request(self.config, assembled)
        encoded = json.dumps(body)
        for hidden in ("tool_context", "PRIVATE_RESULT_ONLY_ON_READ", "PRIVATE_NOTES_ONLY_ON_READ",
                       "OLD_PUBLIC_ONLY_ON_READ", "INTERNAL_ROUTING_ID"):
            self.assertNotIn(hidden, encoded)
        self.assertNotIn("response_format", body)
        self.assertEqual("required", body["tool_choice"])
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
                p.decide(self.config, self.assembled("player-tools-v3"))
            self.assertEqual(6, network.call_count)
            self.assertEqual("tool_model_budget", failure.exception.validation_details["category"])
        excessive = response([call("read_my_notes", {}, f"read-{i}") for i in range(13)])
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "SECRET"}), \
             patch.object(p.http, "urlopen", return_value=io.BytesIO(json.dumps(excessive).encode())) as network:
            with self.assertRaises(p.ProviderError) as failure:
                p.decide(self.config, self.assembled("player-tools-v6"))
            self.assertEqual(1, network.call_count)
            self.assertEqual("tool_read_budget", failure.exception.validation_details["category"])
        with patch.object(p, "MAX_TOOL_MESSAGE_CHARS", 20), patch.object(p.http, "urlopen") as network:
            with self.assertRaises(p.ProviderError) as failure:
                p.decide(self.config, self.assembled("player-tools-v6"))
            self.assertEqual("tool_message_budget", failure.exception.validation_details["category"])
            network.assert_not_called()

    def test_v4_sixth_request_offers_only_actions_and_model_can_finish(self):
        responses = [response([call("read_my_notes", {}, f"read-{i}")]) for i in range(5)]
        responses.append(response([call("action_speak", {"text": "I am ready to vote."}, "finish")]))
        result, network = self.infer(responses, self.assembled("player-tools-v6"))
        self.assertEqual("speak", result["type"])
        self.assertEqual(6, network.call_count)
        for sent in network.call_args_list[:5]:
            names = {tool["function"]["name"] for tool in json.loads(sent.args[0].data)["tools"]}
            self.assertIn("read_my_notes", names)
        final = json.loads(network.call_args_list[-1].args[0].data)
        self.assertEqual({"action_speak"}, {tool["function"]["name"] for tool in final["tools"]})
        self.assertEqual("required", final["tool_choice"])
        self.assertEqual(final, result.tool_trace[-1]["wire_request"])
        self.assertIn("repeated reads cannot produce new events", self.assembled("player-tools-v6")["instructions"])

    def test_v4_rejects_revoked_read_on_final_step_without_executing_it(self):
        responses = [io.BytesIO(json.dumps(response([call("read_my_notes", {}, f"read-{i}")])).encode())
                     for i in range(6)]
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "SECRET"}), \
             patch.object(p.http, "urlopen", side_effect=responses) as network:
            with self.assertRaises(p.ProviderError) as failure:
                p.decide(self.config, self.assembled("player-tools-v6"))
        self.assertEqual(6, network.call_count)
        self.assertEqual("invalid_tool_read", failure.exception.validation_details["category"])
        self.assertEqual([], failure.exception.tool_trace[-1]["tool_results"])
        self.assertEqual({"action_speak"}, {tool["function"]["name"]
                         for tool in failure.exception.tool_trace[-1]["wire_request"]["tools"]})

    def test_v7_can_read_past_sixth_request_then_act(self):
        replies = [response([call("read_my_notes", {}, f"read-{i}")]) for i in range(6)]
        replies.append(response([call("action_speak", {"text": "I have enough information."})]))
        result, network = self.infer(replies)
        self.assertEqual(7, network.call_count)
        sixth = result.tool_trace[5]["wire_request"]
        self.assertIn("read_my_notes", {t["function"]["name"] for t in sixth["tools"]})
        self.assertNotIn("ACTION PHASE:", sixth["messages"][0]["content"])
        self.assertEqual("speak", result["type"])

    def test_v7_final_request_has_explicit_host_action_phase(self):
        replies = [response([call("read_my_notes", {}, f"read-{i}")]) for i in range(11)]
        replies.append(response([call("action_speak", {"text": "My decision."})]))
        result, network = self.infer(replies)
        self.assertEqual(12, network.call_count)
        final = result.tool_trace[-1]["wire_request"]
        self.assertEqual({"action_speak"}, {t["function"]["name"] for t in final["tools"]})
        self.assertIn("ACTION PHASE:", final["messages"][0]["content"])
        self.assertIn("action_speak", final["messages"][0]["content"])
        self.assertIn("twelfth and final", self.assembled()["instructions"])
        self.assertNotIn("sixth and final", self.assembled()["instructions"])

    def test_v7_exhausted_read_calls_switch_to_action_phase_early(self):
        replies = [response([call("read_my_notes", {}, f"read-{i}-{j}") for j in range(3)])
                   for i in range(4)]
        replies.append(response([call("action_speak", {"text": "My decision."})]))
        result, network = self.infer(replies)
        self.assertEqual(5, network.call_count)
        final = result.tool_trace[-1]["wire_request"]
        self.assertEqual({"action_speak"}, {t["function"]["name"] for t in final["tools"]})
        self.assertIn("ACTION PHASE:", final["messages"][0]["content"])

    def test_v7_hallucinated_read_in_action_phase_is_still_rejected(self):
        replies = [response([call("read_my_notes", {}, f"read-{i}")]) for i in range(12)]
        with self.assertRaises(p.ProviderError) as failure:
            self.infer(replies)
        self.assertEqual("invalid_tool_read", failure.exception.validation_details["category"])
        self.assertEqual([], failure.exception.tool_trace[-1]["tool_results"])

    def test_v6_context_cap_stops_before_http_but_legacy_has_no_request_cap(self):
        with patch.object(p, "MAX_TOOL_CONTEXT_CHARS", 20), patch.object(p.http, "urlopen") as network:
            with self.assertRaises(p.ProviderError) as failure:
                p.decide(self.config, self.assembled())
            self.assertEqual("tool_context_budget", failure.exception.validation_details["category"])
            network.assert_not_called()
        with patch.object(p, "MAX_TOOL_CONTEXT_CHARS", 20):
            result, network = self.infer([response([call("action_speak", {"text": "Legacy action."})])],
                                         assembled=self.assembled("player-tools-v3"))
        self.assertEqual("speak", result["type"])
        self.assertEqual(1, network.call_count)

    def test_legacy_cumulative_limit_is_preserved_while_v4_can_reach_final_action(self):
        observation = copy.deepcopy(self.observation)
        for event in observation["history"]:
            if event["audience"] == "public":
                event["text"] = "Public statement. " + "x" * 1000
        def assembled(version):
            return p._build_tools_request(self.config, observation, self.decision, "n" * 2000, "en", version=version)
        replies = [response([call("read_my_notes", {}, f"read-{i}")]) for i in range(5)]
        replies.append(response([call("action_speak", {"text": "Final decision."}, "finish")]))
        encoded = [io.BytesIO(json.dumps(item).encode()) for item in replies]
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "SECRET"}), \
             patch.object(p.http, "urlopen", side_effect=encoded) as network:
            with self.assertRaises(p.ProviderError) as failure:
                p.decide(self.config, assembled("player-tools-v3"))
        self.assertEqual("tool_message_budget", failure.exception.validation_details["category"])
        self.assertLess(network.call_count, 6)
        result, network = self.infer(replies, assembled=assembled("player-tools-v4"))
        self.assertEqual("speak", result["type"])
        self.assertEqual(6, network.call_count)

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
