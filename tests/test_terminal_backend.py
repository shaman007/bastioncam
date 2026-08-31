import unittest
from unittest.mock import patch
import subprocess

from bastioncam import terminal_backend


class TerminalBackendMetadataTest(unittest.TestCase):
    def test_current_plugin_flag(self):
        self.assertTrue(terminal_backend.is_plugin({"id": 1, "is_plugin": True}))
        self.assertFalse(terminal_backend.is_plugin({"id": 2, "is_plugin": False}))

    def test_legacy_plugin_type(self):
        self.assertTrue(terminal_backend.is_plugin({"pane_type": "plugin"}))
        self.assertFalse(terminal_backend.is_plugin({"pane_type": "terminal"}))

    @patch("bastioncam.terminal_backend.run")
    @patch("bastioncam.terminal_backend.redact_text", side_effect=lambda value: value)
    def test_dump_includes_full_scrollback(self, _redact, run):
        run.return_value = subprocess.CompletedProcess([], 0, "prompt\noutput\n", "")
        self.assertEqual(terminal_backend.dump("work", "terminal_7"), "prompt\noutput")
        run.assert_called_once_with("--session", "work", "action", "dump-screen",
                                    "--full", "--pane-id", "terminal_7")


if __name__ == "__main__":
    unittest.main()
