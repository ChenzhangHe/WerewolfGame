from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from werewolf.credentials import load_local_credentials


class CredentialsTests(unittest.TestCase):
    def load(self, content, environ=None):
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(content, encoding="utf-8")
            values = {} if environ is None else environ
            loaded = load_local_credentials(path, values)
            return loaded, values

    def test_literal_key_loading_never_returns_values(self):
        loaded, values = self.load('# local only\nDEEPSEEK_API_KEY="local-test-key" # comment\n')
        self.assertEqual(loaded, ["DEEPSEEK_API_KEY"])
        self.assertEqual(values, {"DEEPSEEK_API_KEY": "local-test-key"})

    def test_process_environment_takes_precedence(self):
        loaded, values = self.load("DEEPSEEK_API_KEY=file-key", {"DEEPSEEK_API_KEY": "process-key"})
        self.assertEqual(loaded, [])
        self.assertEqual(values["DEEPSEEK_API_KEY"], "process-key")

    def test_unknown_environment_settings_are_not_loaded(self):
        loaded, values = self.load("PATH=/not-used\nPYTHONPATH=/not-used\nDEEPSEEK_API_KEY=test")
        self.assertEqual(set(values), {"DEEPSEEK_API_KEY"})

    def test_no_variable_expansion_or_shell_evaluation(self):
        _, values = self.load("export DEEPSEEK_API_KEY='$UNEXPANDED'\n")
        self.assertEqual(values["DEEPSEEK_API_KEY"], "$UNEXPANDED")

    def test_invalid_file_does_not_partially_load_or_disclose_values(self):
        for suffix in ("NOT_A_VALID_ENTRY", 'DEEPSEEK_API_KEY="secret-unclosed',
                       "DEEPSEEK_API_KEY=secret with spaces"):
            values = {}
            with self.subTest(suffix=suffix), TemporaryDirectory() as directory:
                path = Path(directory) / ".env"
                path.write_text("DEEPSEEK_API_KEY=secret-first\n" + suffix, encoding="utf-8")
                with self.assertRaises(ValueError) as failure:
                    load_local_credentials(path, values)
                self.assertNotIn("secret", str(failure.exception))
                self.assertEqual(values, {})

    def test_missing_file_is_optional(self):
        with TemporaryDirectory() as directory:
            self.assertEqual(load_local_credentials(Path(directory) / ".env", {}), [])


if __name__ == "__main__":
    unittest.main()
