"""Importação de JSON colado (texto) com gravação automática do arquivo."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.services.dto import ImportStatus
from app.services.hunt_service import HuntService
from app.services.json_files import suggested_filename, write_new_json_file
from app.services.json_importer import ParsedSession
from tests.helpers import SAMPLE_HUNT_PATH, memory_database, sample_text


class FileNamingTests(unittest.TestCase):
    def test_suggested_filename(self) -> None:
        session = ParsedSession(session_id=1080, start_datetime=datetime(2026, 9, 26, 15, 24, 20))
        self.assertEqual(suggested_filename(session), "hunt_1080_2026-09-26_15-24-20.json")

    def test_suggested_filename_without_id_or_start(self) -> None:
        now = datetime(2026, 9, 27, 8, 0, 0)
        self.assertEqual(suggested_filename(ParsedSession(), now=now),
                         "hunt_2026-09-27_08-00-00.json")

    def test_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "new"
            first = write_new_json_file(directory, "a.json", "1")
            second = write_new_json_file(directory, "a.json", "2")
            third = write_new_json_file(directory, "a.json", "3")
            self.assertEqual([p.name for p in (first, second, third)],
                             ["a.json", "a_2.json", "a_3.json"])
            self.assertEqual(first.read_text(encoding="utf-8"), "1")


class PasteImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = memory_database()
        self.service = HuntService(self.database)
        self._tmp = tempfile.TemporaryDirectory()
        self.save_dir = Path(self._tmp.name) / "imports"
        self.text = SAMPLE_HUNT_PATH.read_text(encoding="utf-8")

    def tearDown(self) -> None:
        self.database.dispose()
        self._tmp.cleanup()

    def _saved_files(self) -> list[str]:
        return sorted(p.name for p in self.save_dir.glob("*.json")) if self.save_dir.exists() else []

    def test_pasted_json_is_imported_and_saved(self) -> None:
        result = self.service.import_pasted_text("\n  " + self.text + "\n\n", self.save_dir)

        self.assertEqual(result.status, ImportStatus.IMPORTED, result.message)
        self.assertEqual(result.saved_path, self.save_dir / "hunt_1080_2026-09-26_15-24-20.json")
        saved_text = result.saved_path.read_text(encoding="utf-8")
        self.assertEqual(json.loads(saved_text), json.loads(self.text))

        hunt = self.service.get_hunt_details(result.hunt_id)
        self.assertEqual(hunt.source_file, "hunt_1080_2026-09-26_15-24-20.json")
        self.assertEqual(hunt.raw_json, saved_text)  # banco e arquivo idênticos
        self.assertEqual(len(hunt.drops), 2)

    def test_saved_file_can_be_reimported_as_duplicate(self) -> None:
        result = self.service.import_pasted_text(self.text, self.save_dir)
        again = self.service.import_file(result.saved_path)
        self.assertEqual(again.status, ImportStatus.DUPLICATE)

    def test_invalid_text_creates_no_file(self) -> None:
        for text in ("", "   ", "{ quebrado", '{"Drops": []}'):
            with self.subTest(text=text):
                result = self.service.import_pasted_text(text, self.save_dir)
                self.assertEqual(result.status, ImportStatus.ERROR)
                self.assertIsNone(result.saved_path)
        self.assertEqual(self._saved_files(), [])
        self.assertEqual(self.service.count_hunts(), 0)

    def test_duplicate_not_confirmed_creates_no_file(self) -> None:
        self.service.import_file(SAMPLE_HUNT_PATH)
        result = self.service.import_pasted_text(self.text, self.save_dir)
        self.assertEqual(result.status, ImportStatus.DUPLICATE)
        self.assertEqual(self._saved_files(), [])
        self.assertEqual(self.service.count_hunts(), 1)

    def test_forced_duplicate_gets_new_file_name(self) -> None:
        self.service.import_pasted_text(self.text, self.save_dir)
        forced = self.service.import_pasted_text(self.text, self.save_dir, allow_duplicate=True)
        self.assertEqual(forced.status, ImportStatus.IMPORTED)
        self.assertEqual(self._saved_files(), ["hunt_1080_2026-09-26_15-24-20.json",
                                               "hunt_1080_2026-09-26_15-24-20_2.json"])

    def test_different_hunts_get_different_files(self) -> None:
        self.service.import_pasted_text(self.text, self.save_dir)
        other = sample_text(**{"Session ID": 1081, "Start": "2026-09-26 17:00:00"})
        self.service.import_pasted_text(other, self.save_dir)
        self.assertEqual(self._saved_files(), ["hunt_1080_2026-09-26_15-24-20.json",
                                               "hunt_1081_2026-09-26_17-00-00.json"])


if __name__ == "__main__":
    unittest.main()
