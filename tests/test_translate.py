from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import translate


class TranslationArchiveTests(unittest.TestCase):
    def test_loads_unicode_language_name_from_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "lang.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "Français.json",
                    json.dumps({"gui": {"tabs": {"main": "Principal"}}}),
                )

            with (
                patch.object(translate, "IS_PACKAGED", True),
                patch.object(translate, "LANG_PATH", root / "missing"),
                patch.object(translate, "LANG_ARCHIVE", archive_path),
            ):
                translator = translate.Translator()
                translator.set_language("Français")

            self.assertIn("Français", translator.languages)
            self.assertEqual(translator("gui", "tabs", "main"), "Principal")
            self.assertEqual(translator.current, "Français")


if __name__ == "__main__":
    unittest.main()
