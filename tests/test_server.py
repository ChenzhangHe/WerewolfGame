"""Exercise local spectator HTTP boundaries without external services."""

from copy import deepcopy
import io
import json
import unittest
import os
from unittest.mock import patch

from werewolf.server import Handler, parse_setup


class FakeController:
    def __init__(self):
        self.calls = []

    def snapshot(self, mode="mystery", seat=None, at=None):
        self.calls.append(("snapshot", mode, seat, at))
        return {"status": "paused", "mode": mode, "players": [], "events": []}

    def create(self, body):
        self.calls.append(("create", deepcopy(body)))
        return {"status": "paused", "language": body.get("language", "en")}

    def control(self, action):
        self.calls.append(("control", action))
        return {"status": "paused"}

    def export(self):
        return {"private": True}


class MemorySocket:
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = io.BytesIO()

    def makefile(self, mode, buffering=None):
        return self.input

    def sendall(self, data):
        self.output.write(data)


class FakeServer:
    server_address = ("127.0.0.1", 8765)
    server_name = "localhost"
    server_port = 8765

    def __init__(self):
        self.controller = FakeController()


def request(method="GET", path="/api/state", body=None, headers=None):
    server = FakeServer()
    data = b"" if body is None else json.dumps(body).encode()
    fields = {"Host": "127.0.0.1:8765", "Content-Length": str(len(data))}
    if method == "POST":
        fields["Content-Type"] = "application/json"
    fields.update(headers or {})
    raw = (f"{method} {path} HTTP/1.0\r\n" +
           "".join(f"{key}: {value}\r\n" for key, value in fields.items()) +
           "\r\n").encode() + data
    connection = MemorySocket(raw)
    Handler(connection, ("127.0.0.1", 12345), server)
    head, content = connection.output.getvalue().split(b"\r\n\r\n", 1)
    status = int(head.split(b" ")[1])
    return status, head.decode(), content, server.controller.calls


class SetupTests(unittest.TestCase):
    def test_flash_preset_freezes_all_twelve_seats(self):
        configs, seed, language = parse_setup({"preset": "deepseek_flash", "language": "zh", "seed": 42})
        self.assertEqual((seed, language), (42, "zh"))
        self.assertEqual(len(configs), 12)
        for config in configs:
            self.assertEqual(config.provider, "deepseek")
            self.assertEqual(config.model, "deepseek-flash")
            self.assertEqual(config.thinking, "enabled")
            self.assertEqual(config.reasoning_effort, "low")
            self.assertIsNone(config.temperature)
            self.assertEqual(config.max_tokens, 8192)
            self.assertEqual(config.language, "zh")

    def test_explicit_player_thinking_and_effort_survive_setup(self):
        configs, _, _ = parse_setup({})
        from dataclasses import asdict
        players = [asdict(config) for config in configs]
        players[0].update(provider="deepseek", model="deepseek-flash", thinking="enabled",
                          reasoning_effort="high", temperature=None, max_tokens=4096)
        configs, _, _ = parse_setup({"players": players})
        self.assertEqual(configs[0].reasoning_effort, "high")
        players[0]["temperature"] = 0.7
        with self.assertRaises(ValueError):
            parse_setup({"players": players})

    def test_preset_and_explicit_players_are_not_ambiguously_combined(self):
        with self.assertRaises(ValueError):
            parse_setup({"preset": "deepseek_flash", "players": []})

    def test_default_setup_has_twelve_scripted_players(self):
        configs, seed, language = parse_setup({})
        self.assertEqual([p.seat for p in configs], list(range(1, 13)))
        self.assertTrue(all(p.provider == "demo" for p in configs))
        self.assertEqual((seed, language), (1, "en"))

    def test_chinese_is_frozen_into_every_seat(self):
        configs, _, language = parse_setup({"language": "zh"})
        self.assertEqual(language, "zh")
        self.assertTrue(all(p.language == "zh" for p in configs))

    def test_rejects_secrets_and_arbitrary_provider_endpoints(self):
        configs, _, _ = parse_setup({})
        players = [dict(seat=p.seat, name=p.name, provider=p.provider, model=p.model)
                   for p in configs]
        for field in ("api_key", "base_url", "command"):
            invalid = deepcopy(players)
            invalid[0][field] = "secret"
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse_setup({"players": invalid})

    def test_invalid_setup_does_not_get_coerced(self):
        for body in ({"seed": True}, {"seed": -1}, {"language": "xx"},
                     {"players": []}, {"unexpected": 1}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_setup(body)


class HTTPBoundaryTests(unittest.TestCase):
    def test_provider_status_returns_presence_without_secret(self):
        with patch("werewolf.server.load_local_credentials"), \
             patch.dict(os.environ, {"DEEPSEEK_API_KEY": "PRIVATE_TEST_CREDENTIAL"}):
            status, _, body, _ = request(path="/api/providers")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["deepseek"]["configured"])
        self.assertNotIn(b"PRIVATE_TEST_CREDENTIAL", body)

    def test_connection_check_is_explicit_and_does_not_touch_game(self):
        with patch("werewolf.server.load_local_credentials"), \
             patch("werewolf.server.providers.check_deepseek", return_value={"ok": True}) as check:
            status, _, body, calls = request("POST", "/api/providers/deepseek/check", {"language": "zh"})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        check.assert_called_once_with("zh")
        self.assertEqual(calls, [])

    def test_cross_origin_connection_check_cannot_spend_tokens(self):
        with patch("werewolf.server.providers.check_deepseek") as check:
            status, _, _, _ = request("POST", "/api/providers/deepseek/check", {},
                                      {"Origin": "https://untrusted.example"})
        self.assertEqual(status, 403)
        check.assert_not_called()

    def test_replay_query_reaches_read_only_snapshot(self):
        status, headers, body, calls = request(path="/api/state?mode=player&seat=7&at=3")
        self.assertEqual(status, 200)
        self.assertEqual(calls, [("snapshot", "player", 7, 3)])
        self.assertIn("Cache-Control: no-store", headers)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(json.loads(body)["mode"], "player")

    def test_dns_rebinding_host_is_denied(self):
        status, _, _, calls = request(headers={"Host": "attacker.example:8765"})
        self.assertEqual(status, 403)
        self.assertEqual(calls, [])

    def test_cross_origin_state_change_is_denied(self):
        status, _, _, calls = request("POST", "/api/play", {},
                                      {"Origin": "https://attacker.example"})
        self.assertEqual(status, 403)
        self.assertEqual(calls, [])

    def test_cross_site_request_without_origin_is_denied(self):
        status, _, _, calls = request("POST", "/api/play", {},
                                      {"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)
        self.assertEqual(calls, [])

    def test_html_form_cannot_start_inference(self):
        status, _, _, calls = request("POST", "/api/play", {},
                                      {"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        self.assertEqual(calls, [])

    def test_same_origin_chinese_setup_is_accepted(self):
        status, _, body, calls = request("POST", "/api/game", {"language": "zh"},
                                         {"Origin": "http://127.0.0.1:8765"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["language"], "zh")
        self.assertEqual(calls, [("create", {"language": "zh"})])

    def test_only_explicit_static_assets_are_served(self):
        for path in ("/../docs/rules-v1.md", "/.env", "/werewolf/server.py"):
            with self.subTest(path=path):
                self.assertEqual(request(path=path)[0], 404)

    def test_export_identifies_the_private_archive(self):
        status, headers, body, _ = request(path="/api/export")
        self.assertEqual(status, 200)
        self.assertIn("werewolf-private-archive.json", headers)
        self.assertTrue(json.loads(body)["private"])

    def test_unknown_failure_does_not_expose_exception_payload(self):
        with patch.object(FakeController, "snapshot", side_effect=Exception("Bearer secret")):
            status, _, body, _ = request()
        self.assertEqual(status, 500)
        self.assertNotIn(b"secret", body)


if __name__ == "__main__":
    unittest.main()
