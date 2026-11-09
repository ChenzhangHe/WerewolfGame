"""End-to-end milestone checks using clearly scripted, credential-free players."""

from dataclasses import FrozenInstanceError
import re
import unittest

from werewolf.runner import Runner
from werewolf.server import Controller, parse_setup
from werewolf.engine import Game, ROLES
from werewolf.providers import PlayerConfig, build_request, wire_request


class CompleteGameTests(unittest.TestCase):
    def test_server_restores_game_paused_without_inference(self):
        from unittest.mock import patch
        configs, seed, language = parse_setup({})
        original = Runner(configs, seed=seed, language=language)
        original.step()
        archive = original.export()
        with patch("werewolf.providers.decide", side_effect=AssertionError("Unexpected model call")):
            restored = Runner.from_archive(archive)
            controller = Controller(restored_runner=restored)
            try:
                snapshot = controller.snapshot()
                self.assertEqual(snapshot["status"], "paused")
                self.assertEqual(snapshot["step"], original.max_step)
                self.assertEqual(snapshot["events"], original.snapshot()["events"])
                self.assertEqual(snapshot["configs"], original.snapshot()["configs"])
                self.assertFalse(snapshot["busy"])
            finally:
                controller.close()
                controller.worker.join(timeout=2)

    def test_hidden_role_swap_produces_identical_actual_player_requests(self):
        assignments = list(ROLES)
        swapped = assignments.copy()
        swapped[8], swapped[9] = swapped[9], swapped[8]
        worlds = [Game(roles=roles) for roles in (assignments, swapped)]
        for game in worlds:
            # Advance each world's different private night decisions to the same
            # public election. Never publish or inspect those actions as seat 5.
            for _ in range(10):
                decisions = game.pending()
                if decisions[0]["kind"] == "nominate":
                    break
                actions = {}
                for decision in decisions:
                    action = dict(decision["options"][0])
                    if action["type"] in {"speak", "discuss"}:
                        action["text"] = "Coordinate tonight."
                    actions[decision["id"]] = action
                game.submit(actions)
        config = PlayerConfig(seat=5, name="Observer", provider="deepseek", model="test-model")
        requests = []
        for game in worlds:
            decision = next(d for d in game.pending() if d["seat"] == 5)
            self.assertEqual(decision["kind"], "nominate")
            requests.append(build_request(config, game.observe(5), decision))
        self.assertEqual(requests[0], requests[1])
        self.assertEqual(wire_request(config, requests[0]), wire_request(config, requests[1]))

    def play(self, language):
        configs, seed, _ = parse_setup({"language": language})
        runner = Runner(configs, seed=seed, language=language)
        for _ in range(600):
            if runner.snapshot().get("winner"):
                break
            runner.step()
            self.assertNotEqual(runner.status, "error", runner.error)
        self.assertIn(runner.snapshot().get("winner"), {"good", "wolves"})
        return runner

    def test_complete_bilingual_games_preserve_information_boundaries(self):
        for language in ("en", "zh"):
            with self.subTest(language=language):
                runner = self.play(language)
                archive = runner.export()
                self.assertEqual(len(archive["configs"]), 12)
                self.assertTrue(all(c["language"] == language for c in archive["configs"]))
                speech = []
                for record in archive["inference"]:
                    payload = record["request"]["input"]
                    observation = payload["observation"]
                    seat = record["seat"]
                    self.assertEqual(observation["seat"], seat)
                    self.assertEqual(observation["language"], language)
                    self.assertNotIn("seed", observation)
                    self.assertNotIn("id", payload["decision"])
                    for player in observation["players"]:
                        if player["seat"] != seat and not player.get("revealed_role"):
                            self.assertNotIn("role", player)
                    for event in observation["history"]:
                        if event["kind"] in {"wolf_discussion", "wolf_attack"}:
                            self.assertEqual(observation["role"], "wolf")
                        if event["kind"] == "investigation":
                            self.assertEqual(observation["role"], "seer")
                        if event["kind"] in {"witch_target", "witch_action"}:
                            self.assertEqual(observation["role"], "witch")
                    if record.get("response", {}).get("type") in {"speak", "discuss"}:
                        speech.append(record["response"]["text"])
                self.assertTrue(speech)
                if language == "zh":
                    self.assertTrue(all(re.search(r"[\u4e00-\u9fff]", s) for s in speech))
                else:
                    self.assertTrue(all(not re.search(r"[\u4e00-\u9fff]", s) for s in speech))
                # Endgame may reveal roles, but replay must preserve historical ignorance.
                first = runner.replay(0)
                self.assertTrue(all("role" not in p for p in first["players"]))
                self.assertIsNone(first["winner"])
                own = runner.replay(0, "player", 1)
                self.assertEqual(sum("role" in p for p in own["players"]), 1)
                before = runner.snapshot()
                runner.replay(0, "omniscient")
                self.assertEqual(before, runner.snapshot())
                with self.assertRaises(FrozenInstanceError):
                    runner.configs[0].model = "another-model"

    def test_controller_step_commits_once_and_preserves_replay(self):
        controller = Controller()
        try:
            self.assertEqual(controller.snapshot()["step"], 0)
            controller.control("step")
            with controller.condition:
                completed = controller.condition.wait_for(
                    lambda: not controller.busy and not controller.step_requested, timeout=5)
            self.assertTrue(completed)
            state = controller.snapshot()
            self.assertEqual(state["step"], 1)
            self.assertEqual(state["status"], "paused")
            historical = controller.snapshot(at=0)
            self.assertEqual(historical["step"], 0)
            self.assertEqual(controller.snapshot()["step"], 1)
            self.assertTrue(all("role" not in p for p in historical["players"]))
        finally:
            controller.close()
            controller.worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
