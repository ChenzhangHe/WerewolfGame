"""Validate frozen per-seat tool interaction setup without network calls."""

from dataclasses import FrozenInstanceError, asdict
import unittest

from werewolf.server import parse_setup


class ToolSetupTests(unittest.TestCase):
    def players(self):
        return [asdict(config) for config in parse_setup({})[0]]

    def test_legacy_explicit_configs_default_to_json(self):
        players = self.players()
        for player in players:
            player.pop("interaction_mode", None)
        configs, _, _ = parse_setup({"players": players})
        self.assertTrue(all(config.interaction_mode == "json" for config in configs))

    def test_flash_preset_uses_frozen_tools_without_thinking(self):
        configs, _, language = parse_setup({"preset": "deepseek_flash", "language": "zh"})
        self.assertEqual(language, "zh")
        for config in configs:
            self.assertEqual(config.interaction_mode, "tools")
            self.assertEqual(config.provider, "deepseek")
            self.assertEqual(config.thinking, "disabled")
        with self.assertRaises(FrozenInstanceError):
            configs[0].interaction_mode = "json"

    def test_mixed_interaction_modes_are_preserved(self):
        for thinking in (None, "disabled"):
            with self.subTest(thinking=thinking):
                players = self.players()
                players[0].update(provider="deepseek", model="deepseek-flash",
                                  interaction_mode="tools", thinking=thinking)
                configs, _, _ = parse_setup({"players": players})
                self.assertEqual(configs[0].interaction_mode, "tools")
                self.assertTrue(all(config.interaction_mode == "json" for config in configs[1:]))

    def test_tools_reject_other_providers_and_enabled_thinking(self):
        for provider, thinking in (("demo", None), ("openai", None),
                                   ("openai_subscription", None), ("deepseek", "enabled")):
            with self.subTest(provider=provider, thinking=thinking):
                players = self.players()
                players[0].update(provider=provider, model="model", thinking=thinking,
                                  temperature=None, max_tokens=None, interaction_mode="tools")
                with self.assertRaisesRegex(ValueError, "Tool interaction"):
                    parse_setup({"players": players})

    def test_invalid_modes_are_not_coerced(self):
        for value in (None, True, 1, "tool", "", [], {}):
            with self.subTest(value=value):
                players = self.players()
                players[0]["interaction_mode"] = value
                with self.assertRaisesRegex(ValueError, "Interaction mode"):
                    parse_setup({"players": players})


if __name__ == "__main__":
    unittest.main()
