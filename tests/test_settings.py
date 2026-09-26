import csv
import json
import tempfile
import unittest
from pathlib import Path

from app.services.export_documents import hunts_document
from app.services.export_service import ExportFormat, export_document
from app.services.settings_service import AppSettings, SettingsStore
from app.utils import formatters as f
from app.utils.validators import parse_user_number


class SettingsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "data" / "settings.json"
        self.store = SettingsStore(self.path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_missing_file_gives_defaults(self) -> None:
        self.assertEqual(self.store.load(), AppSettings())

    def test_round_trip(self) -> None:
        settings = AppSettings(theme="light", number_format="en-US",
                               database_path="D:/pxg/hunts.db", auto_backup=False,
                               backups_to_keep=25)
        self.store.save(settings)
        self.assertEqual(self.store.load(), settings)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_corrupted_or_invalid_values_fall_back_to_defaults(self) -> None:
        self.path.parent.mkdir(parents=True)
        for content in ("{ quebrado", "[1, 2]", "null"):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                self.assertEqual(self.store.load(), AppSettings())

        self.path.write_text(json.dumps({
            "theme": "neon", "number_format": "xx", "database_path": "   ",
            "auto_backup": "sim", "backups_to_keep": 0, "campo_futuro": 1,
        }), encoding="utf-8")
        self.assertEqual(self.store.load(), AppSettings())

        self.path.write_text(json.dumps({"backups_to_keep": True}), encoding="utf-8")
        self.assertEqual(self.store.load().backups_to_keep, 10)


class NumberFormatTests(unittest.TestCase):
    def tearDown(self) -> None:
        f.set_number_format("pt-BR")

    def test_en_us_formatting(self) -> None:
        f.set_number_format("en-US")
        self.assertEqual(f.format_number(1119522), "1,119,522")
        self.assertEqual(f.format_number(12.5, decimals=1), "12.5")
        self.assertEqual(f.format_compact(119470652), "119.5 M")
        self.assertEqual(f.format_percent(0.75), "75.0%")
        self.assertEqual(f.number_format().example, "1,234,567.89")

    def test_unknown_format_falls_back_to_pt_br(self) -> None:
        self.assertEqual(f.set_number_format("xx").name, "pt-BR")
        self.assertEqual(f.format_number(1119522), "1.119.522")

    def test_parsing_follows_active_format(self) -> None:
        self.assertEqual(parse_user_number("1.200"), 1200)  # pt-BR: ponto = milhar
        self.assertEqual(parse_user_number("1,200"), 1.2)
        f.set_number_format("en-US")
        self.assertEqual(parse_user_number("1,200"), 1200)  # en-US: vírgula = milhar
        self.assertEqual(parse_user_number("1.200"), 1.2)
        self.assertEqual(parse_user_number("1,000,000"), 1_000_000)
        self.assertEqual(parse_user_number("1.5kk"), 1_500_000)
        self.assertEqual(parse_user_number("800k"), 800_000)

    def test_csv_follows_active_format(self) -> None:
        from app.services.dto import HuntSummary
        hunt = HuntSummary(id=1, session_id=1080, player="Royalzxd", start_datetime=None,
                           duration_seconds=4310, status=None, kills=368,
                           kills_per_hour=307.4, profit=1119522, profit_per_hour=935099.58,
                           supplies=None, supplies_per_hour=None, raw_gains=None,
                           raw_gains_per_hour=None)
        with tempfile.TemporaryDirectory() as tmp:
            pt = export_document(hunts_document([hunt]), Path(tmp) / "pt.csv", ExportFormat.CSV)
            f.set_number_format("en-US")
            en = export_document(hunts_document([hunt]), Path(tmp) / "en.csv", ExportFormat.CSV)
            with pt.open(encoding="utf-8-sig", newline="") as file:
                pt_rows = list(csv.reader(file, delimiter=";"))
            with en.open(encoding="utf-8-sig", newline="") as file:
                en_rows = list(csv.reader(file, delimiter=","))
        column = pt_rows[0].index("Profit/h")
        self.assertEqual(pt_rows[1][column], "935099,58")
        self.assertEqual(en_rows[1][column], "935099.58")
        self.assertEqual(len(en_rows[0]), len(pt_rows[0]))


if __name__ == "__main__":
    unittest.main()
