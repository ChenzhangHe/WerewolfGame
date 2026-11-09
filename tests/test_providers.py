import copy
from dataclasses import FrozenInstanceError
import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from werewolf import providers as p


class ProvidersTests(unittest.TestCase):
    def test_nonspeech_task_has_its_own_json_shape_and_no_speech_example(self):
        decision = {"id": "hidden", "seat": 1, "kind": "wolf_attack",
                    "options": [{"type": "attack", "target": None}, {"type": "attack", "target": 6}]}
        request = p.build_request(self.config, self.observation, decision)
        instructions = request["instructions"]
        self.assertIn("CURRENT TASK: wolf_attack", instructions)
        self.assertIn('"type": "attack", "target": null', instructions)
        self.assertIn("NOT a speech task", instructions)
        self.assertIn("Never use json_object or json as the action type", instructions)
        self.assertNotIn('"type":"speak","text"', instructions)

    def test_rejected_result_is_captured_without_transport_or_reasoning(self):
        rejected = p.DecisionResult({"type": "speak", "text": "Wrong phase."},
                                    model="test-model", usage={"total_tokens": 20},
                                    raw_text='{"type":"speak","text":"Wrong phase."}')
        decision = {"kind": "wolf_attack", "options": [{"type": "attack", "target": None}]}
        assembled = p.build_request(self.config, self.observation, decision)
        with patch.object(p, "_demo", return_value=rejected):
            with self.assertRaises(p.ProviderError) as failure:
                p.decide(self.config, assembled)
        self.assertEqual(dict(failure.exception.rejected_result), dict(rejected))
        corrected = p.build_repair_request(assembled, failure.exception.rejected_result)
        self.assertEqual(corrected["input"]["observation"], assembled["input"]["observation"])
        self.assertEqual(corrected["input"]["decision"], assembled["input"]["decision"])
        self.assertEqual(corrected["input"]["rejected_action"], dict(rejected))
        self.assertNotIn("rejected_action", assembled["input"])
        self.assertNotIn("id", corrected["input"]["decision"])

    def test_malformed_and_truncated_content_keep_only_safe_diagnostics(self):
        config = p.deepseek_flash_config(1, "Test")
        for content, finish_reason, repairable in (("not JSON", "stop", True),
                ("[]", "stop", True), ("   ", "stop", True), ('{"type":', "length", False)):
            wire = {"model": "deepseek-flash", "choices": [{"finish_reason": finish_reason,
                    "message": {"content": content, "reasoning_content": "PRIVATE_PROVIDER_REASONING"}}],
                    "usage": {"total_tokens": 100}}
            with self.subTest(content=content), patch.dict(os.environ, {"DEEPSEEK_API_KEY": "TEST_TOKEN"}), \
                 patch.object(p.http, "urlopen", return_value=io.BytesIO(json.dumps(wire).encode())):
                with self.assertRaises(p.ProviderError) as failure:
                    p.decide(config, self.request(config))
                exc = failure.exception
                self.assertEqual(exc.rejected_text, content)
                self.assertEqual(exc.repairable, repairable)
                self.assertEqual(exc.usage, {"total_tokens": 100})
                self.assertNotIn("PRIVATE_PROVIDER_REASONING", json.dumps(exc.__dict__))
                repair = p.build_repair_request(self.request(config), content)
                self.assertEqual(repair["input"]["rejected_output"], content)
                self.assertEqual(repair["input"]["observation"], self.observation)

    def setUp(self):
        self.config = p.PlayerConfig(1, "Ada")
        self.observation = {"seat": 1, "role": "villager", "day": 1, "language": "en", "history": []}
        self.decision = {"id": "PRIVATE_GLOBAL_COUNTER_987", "seat": 1,
                         "kind": "speech", "options": [{"type": "speak"}]}

    def request(self, config=None):
        return p.build_request(config or self.config, self.observation, self.decision)

    def test_global_decision_identifiers_do_not_reach_model(self):
        request = self.request()
        self.assertNotIn(self.decision["id"], json.dumps(request))
        changed = {**self.decision, "id": "another-hidden-counter"}
        self.assertEqual(request, p.build_request(self.config, self.observation, changed))

    def test_config_frozen_and_request_detached(self):
        with self.assertRaises(FrozenInstanceError):
            self.config.model = "replacement"
        request = self.request()
        request["input"]["observation"]["history"].append("changed")
        self.assertEqual([], self.observation["history"])

    def test_private_notes_and_language_are_explicit(self):
        self.observation["language"] = "zh"
        request = p.build_request(self.config, self.observation, self.decision, "只属于一号")
        self.assertEqual("zh", request["language"])
        self.assertIn("简体中文", request["instructions"])
        self.assertEqual("只属于一号", request["input"]["private_notes"])
        result = p.decide(self.config, request)
        self.assertIn("我是1号", result["text"])

    def test_finite_option_validation_and_text_limits(self):
        vote = {"options": [{"type": "vote", "target": 1}]}
        for invalid in [{"type": "vote", "target": True}, {"type": "vote", "target": 2},
                        {"type": "vote", "target": 1, "hidden": "extra"}]:
            with self.assertRaises(p.ProviderError):
                p.validate_action(invalid, vote)
        with self.assertRaises(p.ProviderError):
            p.validate_action({"type": "speak", "text": "x" * 1201}, self.decision)

    def test_subscription_body_omits_unsupported_settings_and_sessions(self):
        config = p.PlayerConfig(1, "Ada", provider="openai_subscription", model="account-model",
                                temperature=None, max_tokens=None)
        body = p.wire_request(config, self.request(config))
        self.assertTrue(body["stream"])
        self.assertFalse(body["store"])
        for name in ("temperature", "max_output_tokens", "previous_response_id", "conversation", "tools"):
            self.assertNotIn(name, body)
        with self.assertRaises(ValueError):
            p.PlayerConfig(1, "Ada", provider="openai_subscription", model="account-model")

    def test_missing_credential_fails_without_network(self):
        config = p.PlayerConfig(1, "Ada", provider="deepseek", model="chosen-model")
        with patch.dict(os.environ, {}, clear=True), patch.object(p.http, "urlopen") as network:
            with self.assertRaisesRegex(p.ProviderError, "DEEPSEEK_API_KEY"):
                p.decide(config, self.request(config))
            network.assert_not_called()

    def test_deepseek_wire_and_metadata(self):
        config = p.PlayerConfig(1, "Ada", provider="deepseek", model="chosen-model")
        wire = {"model": "reported-model", "choices": [{"finish_reason": "stop", "message": {
            "content": '{"type":"speak","text":"Hello village."}', "reasoning_content": "NOT STORED"}}],
                "usage": {"total_tokens": 123}}
        response = io.BytesIO(json.dumps(wire).encode())
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "SECRET_SENT_ONLY_IN_HEADER"}), \
             patch.object(p.http, "urlopen", return_value=response) as network:
            request = self.request(config)
            answer = p.decide(config, request)
            sent = network.call_args.args[0]
            self.assertEqual("Bearer SECRET_SENT_ONLY_IN_HEADER", sent.headers["Authorization"])
            self.assertNotIn("SECRET_SENT_ONLY_IN_HEADER", sent.data.decode())
            self.assertNotIn("tools", json.loads(sent.data))
            self.assertEqual({"type": "disabled"}, json.loads(sent.data)["thinking"])
            self.assertNotIn("reasoning_effort", json.loads(sent.data))
            self.assertEqual("reported-model", answer.reported_model)
            self.assertEqual({"total_tokens": 123}, answer.usage)
            self.assertNotIn("NOT STORED", answer.raw_text)

    def test_flash_preset_pins_model_and_supported_thinking_settings(self):
        config = p.deepseek_flash_config(3, "Flash player", language="zh")
        self.assertEqual("deepseek-flash", config.model)
        self.assertEqual("enabled", config.thinking)
        self.assertEqual("low", config.reasoning_effort)
        self.assertIsNone(config.temperature)
        self.assertEqual(4096, config.max_tokens)
        self.assertEqual("zh", config.language)
        body = p.wire_request(config, self.request(config))
        self.assertEqual({"type": "enabled"}, body["thinking"])
        self.assertEqual("low", body["reasoning_effort"])
        self.assertEqual(4096, body["max_tokens"])
        self.assertNotIn("temperature", body)
        self.assertNotIn("tools", body)
        with self.assertRaises(FrozenInstanceError):
            config.thinking = "disabled"

    def test_thinking_validation_prevents_ignored_or_irrelevant_settings(self):
        cases = [
            {"provider": "deepseek", "thinking": "enabled"},  # default non-null temperature
            {"provider": "deepseek", "thinking": "disabled", "reasoning_effort": "low"},
            {"provider": "deepseek", "reasoning_effort": "low"},
            {"provider": "deepseek", "thinking": "sometimes"},
            {"provider": "deepseek", "thinking": "enabled", "temperature": None, "reasoning_effort": "ultra"},
            {"provider": "demo", "thinking": "disabled"},
            {"provider": "openai", "reasoning_effort": "low"},
        ]
        for fields in cases:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                p.PlayerConfig(1, "Ada", **fields)
        # Explicit enabling without an effort chooses a pinned low effort rather
        # than leaving the provider's default high effort implicit.
        config = p.PlayerConfig(1, "Ada", provider="deepseek", thinking="enabled", temperature=None)
        self.assertEqual("low", p.wire_request(config, self.request(config))["reasoning_effort"])

    def test_connection_check_uses_synthetic_state_and_reports_only_safe_fields(self):
        wire = {"model": "DeepSeek-V4.1-Flash-1017", "choices": [{"finish_reason": "stop", "message": {
            "content": '{"type":"speak","text":"连接正常。"}', "reasoning_content": "DO NOT RETURN"}}],
            "usage": {"total_tokens": 30}}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "SECRET"}), \
             patch.object(p.http, "urlopen", return_value=io.BytesIO(json.dumps(wire).encode())) as network:
            result = p.check_deepseek("zh")
        self.assertTrue(result["ok"])
        self.assertEqual("deepseek-flash", result["model"])
        self.assertEqual("DeepSeek-V4.1-Flash-1017", result["reported_model"])
        self.assertEqual("连接正常。", result["text"])
        self.assertEqual({"ok", "provider", "model", "reported_model", "usage", "text"}, set(result))
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn("DO NOT RETURN", json.dumps(result))
        body = json.loads(network.call_args.args[0].data)
        synthetic = json.loads(body["messages"][1]["content"])
        self.assertEqual([], synthetic["observation"]["players"])
        self.assertEqual([], synthetic["observation"]["history"])
        self.assertNotIn("id", synthetic["decision"])
        self.assertIn("简体中文", body["messages"][0]["content"])

    def test_deepseek_blank_truncated_and_malformed_actions_fail_closed(self):
        config = p.deepseek_flash_config(1, "Ada")
        cases = [("stop", "   ", "blank"), ("length", '{"type":"speak"', "token limit"),
                 ("stop", "not JSON", "complete JSON action"), ("stop", "[]", "complete JSON action")]
        for finish_reason, content, message in cases:
            wire = {"choices": [{"finish_reason": finish_reason, "message": {"content": content}}]}
            with self.subTest(content=content), patch.dict(os.environ, {"DEEPSEEK_API_KEY": "SECRET"}), \
                 patch.object(p.http, "urlopen", return_value=io.BytesIO(json.dumps(wire).encode())):
                with self.assertRaisesRegex(p.ProviderError, message):
                    p.decide(config, self.request(config))

    def test_deepseek_actionable_errors_do_not_echo_secrets(self):
        config = p.deepseek_flash_config(1, "Ada")
        for status, expected in [(401, "authentication"), (402, "balance"), (429, "usage limit")]:
            def fail(*args, **kwargs):
                raise HTTPError("https://api.deepseek.com", status, "SECRET RAW BODY", {}, io.BytesIO(b"SECRET"))
            with self.subTest(status=status), patch.dict(os.environ, {"DEEPSEEK_API_KEY": "SECRET"}), \
                 patch.object(p.http, "urlopen", side_effect=fail) as network, patch.object(p.time, "sleep"):
                with self.assertRaisesRegex(p.ProviderError, expected) as failure:
                    p.decide(config, self.request(config))
                self.assertNotIn("SECRET", str(failure.exception))
                self.assertEqual(2 if status == 429 else 1, network.call_count)

    def test_http_errors_are_bounded_and_do_not_expose_body(self):
        config = p.PlayerConfig(1, "Ada", provider="deepseek", model="chosen-model")
        def fail(*args, **kwargs):
            raise HTTPError("https://api.deepseek.com", 429, "SECRET RAW BODY", {}, io.BytesIO(b"SECRET"))
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "SECRET"}), \
             patch.object(p.http, "urlopen", side_effect=fail) as network, patch.object(p.time, "sleep"):
            with self.assertRaises(p.ProviderError) as failure:
                p.decide(config, self.request(config))
            self.assertNotIn("SECRET", str(failure.exception))
            self.assertEqual(2, network.call_count)

    def test_subscription_requires_completed_stream(self):
        config = p.PlayerConfig(1, "Ada", provider="openai_subscription", model="chosen-model",
                                temperature=None, max_tokens=None)
        completed = {"type": "response.completed", "response": {"status": "completed", "model": "reported-model",
                     "output": [{"type": "message", "content": [{"type": "output_text", "text":
                         '{"type":"speak","text":"Hello."}'}]}]}}
        events = b'data: {"type":"response.output_text.delta","delta":"partial"}\n\n'
        events += b"data: " + json.dumps(completed).encode() + b"\n\n"
        with patch.dict(os.environ, {"OPENAI_CHATGPT_ACCESS_TOKEN": "SECRET"}), \
             patch.object(p.http, "urlopen", return_value=io.BytesIO(events)):
            self.assertEqual("Hello.", p.decide(config, self.request(config))["text"])
        with patch.dict(os.environ, {"OPENAI_CHATGPT_ACCESS_TOKEN": "SECRET"}), \
             patch.object(p.http, "urlopen", return_value=io.BytesIO(events.split(b"data: ")[1])):
            with self.assertRaises(p.ProviderError):
                p.decide(config, self.request(config))


if __name__ == "__main__":
    unittest.main()
