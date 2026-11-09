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
            self.assertEqual("reported-model", answer.reported_model)
            self.assertEqual({"total_tokens": 123}, answer.usage)
            self.assertNotIn("NOT STORED", answer.raw_text)

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
