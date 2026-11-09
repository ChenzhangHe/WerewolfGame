import copy
import json
import unittest
from unittest.mock import patch

from werewolf.providers import PlayerConfig, ProviderError, build_request
from werewolf.runner import Runner


def configs():
    return [PlayerConfig(seat, f"Player {seat}") for seat in range(1, 13)]


class RunnerTests(unittest.TestCase):
    def test_batch_failure_preserves_successes_without_partial_commit(self):
        runner = Runner(configs())
        pending = runner.game.pending()
        self.assertGreater(len(pending), 1)
        before = runner.game.export()
        first = pending[0]["seat"]
        failing = pending[1]["seat"]
        calls = []
        real_decide = __import__("werewolf.providers", fromlist=["decide"]).decide
        def decide(config, request):
            calls.append(config.seat)
            if config.seat == failing:
                raise ProviderError("Test provider unavailable.")
            return real_decide(config, request)
        with patch("werewolf.runner.providers.decide", side_effect=decide):
            snapshot = runner.step()
        self.assertEqual("error", snapshot["status"])
        self.assertEqual(before, runner.game.export())
        self.assertEqual(0, runner.max_step)
        with patch("werewolf.runner.providers.decide", wraps=real_decide) as retry:
            runner.step()
            self.assertNotIn(first, [call.args[0].seat for call in retry.call_args_list])
        self.assertEqual(1, runner.max_step)
        records = runner.export()["inference"]
        self.assertEqual(len(pending), sum(r["accepted"] for r in records))
        self.assertEqual(1, sum("error" in r for r in records))

    def test_private_notes_stay_with_their_seat(self):
        runner = Runner(configs())
        pending = runner.game.pending()
        seat = pending[0]["seat"]
        runner._notes[seat] = "PRIVATE_SENTINEL"
        other = next(s for s in range(1, 13) if s != seat)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(runner.snapshot("player", other)))
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(runner.snapshot("mystery")))
        for decision in pending:
            request = build_request(runner.configs[decision["seat"] - 1], runner.game.observe(decision["seat"]),
                                    decision, runner._notes[decision["seat"]])
            self.assertEqual(decision["seat"] == seat, "PRIVATE_SENTINEL" in json.dumps(request))

    def test_replay_is_detached_and_spectating_does_not_affect_requests(self):
        runner = Runner(configs())
        old = runner.replay(0)
        pending = runner.game.pending()
        before = [build_request(runner.configs[d["seat"] - 1], runner.game.observe(d["seat"]), d) for d in pending]
        runner.snapshot("omniscient")
        for seat in range(1, 13):
            runner.snapshot("player", seat)
        after = [build_request(runner.configs[d["seat"] - 1], runner.game.observe(d["seat"]), d) for d in pending]
        self.assertEqual(before, after)
        runner.step()
        replay = runner.replay(0)
        for key in ("day", "phase", "players", "events"):
            self.assertEqual(old[key], replay[key])
        replay["players"][0]["name"] = "mutated"
        self.assertNotEqual("mutated", runner.replay(0)["players"][0]["name"])

    def test_game_language_frozen_into_every_config_and_prompt(self):
        runner = Runner(configs(), language="zh")
        self.assertTrue(all(c.language == "zh" for c in runner.configs))
        self.assertEqual("zh", runner.snapshot()["language"])
        for d in runner.game.pending():
            request = build_request(runner.configs[d["seat"] - 1], runner.game.observe(d["seat"]), d)
            self.assertEqual("zh", request["language"])

    def test_no_postgame_roles_leak_backward(self):
        runner = Runner(configs())
        initial = runner.replay(0)
        for _ in range(1000):
            if runner.step()["status"] in {"finished", "error"}:
                break
        self.assertEqual("finished", runner.status, runner.error)
        self.assertIn(runner.snapshot()["winner"], {"good", "wolves"})
        self.assertTrue(all("role" in p for p in runner.snapshot()["players"]))
        self.assertTrue(all("role" not in p for p in runner.replay(0)["players"]))
        self.assertEqual(initial["events"], runner.replay(0)["events"])

    def test_raw_exceptions_do_not_leak_credentials(self):
        runner = Runner(configs())
        with patch("werewolf.runner.providers.decide", side_effect=RuntimeError("Bearer SECRET")):
            result = runner.step()
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn("SECRET", json.dumps(runner.export()))


if __name__ == "__main__":
    unittest.main()
