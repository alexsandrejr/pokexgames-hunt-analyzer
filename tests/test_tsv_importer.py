import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.services.dto import ImportStatus
from app.services.hunt_service import HuntService
from app.services.json_files import collect_analyzer_files
from app.services.json_importer import (
    InvalidJsonError,
    InvalidTsvError,
    parse_analyzer_text,
)
from app.services.tsv_importer import looks_like_tsv, tsv_to_document
from tests.helpers import FIXTURES_DIR, SAMPLE_HUNT_PATH, memory_database

SAMPLE_TSV_PATH = FIXTURES_DIR / "sample_hunt.tsv"


class TsvDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = SAMPLE_TSV_PATH.read_text(encoding="utf-8")
        self.document = tsv_to_document(self.text)

    def test_sections_are_translated(self) -> None:
        self.assertEqual(list(self.document),
                         ["Session", "Experience", "Drops", "Supplies",
                          "Enemies Defeated", "Damage"])

    def test_session_fields_are_translated_and_typed(self) -> None:
        session = self.document["Session"]
        self.assertEqual(session["Session ID"], 198)
        self.assertEqual(session["Start"], "2026-09-20 09:11:03")
        self.assertEqual(session["Duration"], "01:59:16")
        self.assertEqual(session["Profit per hour"], 1193042)
        self.assertEqual(session["Status"], "Pausado")

    def test_rows_use_json_keys(self) -> None:
        self.assertEqual(self.document["Drops"][0], {
            "Player": "Avg Sandrinhas", "Item": "pot of lava", "Count": 368,
            "Unit price": 18, "Total price": 6624, "Ignored": None,
        })
        self.assertEqual(self.document["Enemies Defeated"][0], {
            "Player": "Avg Sandrinhas", "Enemy": "Nightmare Shiny Torkoal", "Count": 2,
            "Rare": True, "Ignored": False,
        })
        self.assertEqual(self.document["Damage"][0]["Element"], "Melee")

    def test_english_labels_pass_through(self) -> None:
        text = ("Session\nField\tValue\nSession ID\t5\nDuration seconds\t60\n\n"
                "Drops\nPlayer\tItem\tCount\tUnit price\tTotal price\tIgnored\n"
                "Ash\tgem\t2\t10\t20\tfalse\n")
        document = tsv_to_document(text)
        self.assertEqual(document["Session"], {"Session ID": 5, "Duration seconds": 60})
        self.assertEqual(document["Drops"][0]["Ignored"], False)

    def test_detection(self) -> None:
        self.assertTrue(looks_like_tsv(self.text))
        self.assertFalse(looks_like_tsv(SAMPLE_HUNT_PATH.read_text(encoding="utf-8")))
        self.assertFalse(looks_like_tsv('{"a":\t1}'))


class TsvParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = SAMPLE_TSV_PATH.read_text(encoding="utf-8")
        self.parsed = parse_analyzer_text(self.text, source_file="sample_hunt.tsv")

    def test_session(self) -> None:
        session = self.parsed.session
        self.assertEqual(session.session_id, 198)
        self.assertEqual(session.player, "Avg Sandrinhas")
        self.assertEqual(session.start_datetime, datetime(2026, 9, 20, 9, 11, 3))
        self.assertEqual(session.duration_seconds, 7156)
        self.assertEqual(session.experience, 7992903)
        self.assertEqual(session.profit, 2371504)
        self.assertEqual(session.kills, 610)
        self.assertEqual(session.rare_kills, 2)
        self.assertEqual(session.damage_dealt_per_second, 31236)
        self.assertEqual(session.time_to_next_level, "03:10:33")
        self.assertEqual(session.time_to_next_level_seconds, 11433)

    def test_lists(self) -> None:
        self.assertEqual(len(self.parsed.drops), 16)
        self.assertEqual(len(self.parsed.supplies), 18)
        self.assertEqual([e.enemy for e in self.parsed.enemies],
                         ["Nightmare Shiny Torkoal", "Nightmare Turtonator"])
        self.assertEqual([e.rare for e in self.parsed.enemies], [True, False])
        spike = next(d for d in self.parsed.drops if d.item == "turtle spike")
        self.assertEqual((spike.count, spike.unit_price, spike.total_price), (183, 8000, 1464000))
        self.assertIsNone(spike.ignored)
        self.assertEqual(self.parsed.warnings, [])

    def test_raw_json_keeps_every_section(self) -> None:
        data = json.loads(self.parsed.raw_json)
        self.assertEqual(data, tsv_to_document(self.text))
        self.assertEqual(len(data["Damage"]), 16)

    def test_hash_ignores_line_endings(self) -> None:
        crlf = parse_analyzer_text(self.text.replace("\n", "\r\n"))
        self.assertEqual(crlf.content_hash, self.parsed.content_hash)

    def test_text_without_sections(self) -> None:
        with self.assertRaises(InvalidTsvError) as ctx:
            parse_analyzer_text("a\tb\tc")
        self.assertEqual(ctx.exception.message, "TSV inválido.")

    def test_plain_text_is_still_reported_as_json(self) -> None:
        with self.assertRaises(InvalidJsonError):
            parse_analyzer_text("isto não é nada")


class TsvImportServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = memory_database()
        self.service = HuntService(self.database)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self.database.dispose()
        self._tmp.cleanup()

    def test_import_file_and_detect_duplicate(self) -> None:
        result = self.service.import_file(SAMPLE_TSV_PATH)
        self.assertEqual(result.status, ImportStatus.IMPORTED, result.message)
        hunt = self.service.get_hunt_details(result.hunt_id)
        self.assertEqual(hunt.source_file, "sample_hunt.tsv")
        self.assertEqual(hunt.session_id, 198)
        self.assertEqual(len(hunt.drops), 16)

        again = self.service.import_file(SAMPLE_TSV_PATH)
        self.assertEqual(again.status, ImportStatus.DUPLICATE)

    def test_pasted_tsv_is_saved_as_json(self) -> None:
        text = SAMPLE_TSV_PATH.read_text(encoding="utf-8")
        result = self.service.import_pasted_text(text, self.root / "imports")
        self.assertEqual(result.status, ImportStatus.IMPORTED, result.message)
        self.assertEqual(result.saved_path.name, "hunt_198_2026-09-20_09-11-03.json")
        saved = json.loads(result.saved_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["Session"]["Session ID"], 198)

    def test_folder_collects_json_and_tsv(self) -> None:
        folder = self.root / "exports"
        folder.mkdir()
        for name in ("a.json", "b.TSV", "notas.txt"):
            (folder / name).write_text("x", encoding="utf-8")
        names = [path.name for path in collect_analyzer_files([folder])]
        self.assertEqual(names, ["a.json", "b.TSV"])


if __name__ == "__main__":
    unittest.main()
