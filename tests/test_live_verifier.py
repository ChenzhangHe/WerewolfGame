import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.verify_live import download_archive


class Response(io.BytesIO):
    def __init__(self, payload, extra_length=0):
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload) + extra_length)}


class ArchiveDownloadTests(unittest.TestCase):
    def test_partial_transfer_retries_only_download_then_atomically_saves(self):
        payload = json.dumps({"game": {"winner": None}, "inference": []}).encode()
        with TemporaryDirectory() as directory:
            output = Path(directory) / "saved.private.json"
            output.write_text("previous archive", encoding="utf-8")
            with patch("scripts.verify_live.urlopen", side_effect=[Response(payload, 1), Response(payload)]) as network:
                archive = download_archive("http://127.0.0.1:8765", output)
            self.assertEqual(json.loads(output.read_text()), archive)
            self.assertEqual(network.call_count, 2)
            self.assertTrue(all(call.args[0].endswith("/api/export") for call in network.call_args_list))

    def test_permanent_transfer_failure_preserves_previous_archive(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "saved.private.json"
            output.write_text("previous archive", encoding="utf-8")
            with patch("scripts.verify_live.urlopen", side_effect=[Response(b"{}", 1), Response(b"{}", 1)]):
                with self.assertRaises(OSError):
                    download_archive("http://127.0.0.1:8765", output)
            self.assertEqual(output.read_text(), "previous archive")


if __name__ == "__main__":
    unittest.main()
