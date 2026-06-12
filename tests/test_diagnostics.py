from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import diagnostics


class DiagnosticLoggingTests(unittest.TestCase):
    def test_verbose_logging_writes_to_rotating_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "logs", "kick-drops-miner.log")
            with patch.object(diagnostics, "VERBOSE_LOG_PATH", path):
                result = diagnostics.configure_verbose_logging(
                    True,
                    logging_level=logging.ERROR,
                    api_level=logging.NOTSET,
                    websocket_level=logging.NOTSET,
                )
                logging.getLogger("KickDrops.websocket").debug("websocket diagnostic")
                diagnostics.configure_verbose_logging(
                    False,
                    logging_level=logging.ERROR,
                    api_level=logging.NOTSET,
                    websocket_level=logging.NOTSET,
                )

            self.assertEqual(result, path)
            self.assertTrue(path.exists())
            self.assertIn("websocket diagnostic", path.read_text(encoding="utf8"))


if __name__ == "__main__":
    unittest.main()
