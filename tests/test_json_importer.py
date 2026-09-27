import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.services.json_importer import (
    FileReadError,
    InvalidAnalyzerSessionError,
    InvalidJsonError,
    compute_content_hash,
    parse_analyzer_json,
    read_analyzer_file,
)
from tests.helpers import SAMPLE_HUNT_PATH, load_sample, sample_text


class ValidJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = SAMPLE_HUNT_PATH.read_text(encoding="utf-8")
        self.parsed = parse_analyzer_json(self.text, source_file="sample_hunt.json")

    def test_session_fields(self) -> None:
        session = self.parsed.session
        self.assertEqual(session.session_id, 1080)
        self.assertEqual(session.start_datetime, datetime(2026, 9, 26, 15, 24, 20))
        self.assertEqual(session.duration_seconds, 4310)
        self.assertEqual(session.status, "Active")
        self.assertEqual(session.session_type, "player")
        self.assertEqual(session.kills, 368)
        self.assertEqual(session.kills_per_hour, 307)
        self.assertEqual(session.profit, 1119522)
        self.assertEqual(session.profit_per_hour, 935099)
        self.assertEqual(session.supplies, 116450)
        self.assertEqual(session.raw_gains, 1235972)
        self.assertEqual(session.damage_dealt, 119470652)
        self.assertEqual(session.damage_taken, 1460258)
        self.assertEqual(session.paused_seconds, 0)
        self.assertIsNone(session.time_to_next_level)
        self.assertIsNone(session.time_to_next_level_seconds)

    def test_player_is_inferred_from_lists(self) -> None:
        self.assertEqual(self.parsed.session.player, "Royalzxd")

    def test_lists(self) -> None:
        self.assertEqual([e.enemy for e in self.parsed.enemies],
                         ["Mecha Abomasnow", "Mecha Blastoise", "Mecha Charizard"])
        self.assertEqual(self.parsed.enemies[2].count, 40)
        self.assertIs(self.parsed.enemies[0].rare, False)

        gem = self.parsed.drops[0]
        self.assertEqual((gem.item, gem.count, gem.unit_price, gem.total_price),
                         ("nightmare gem", 1217, 216, 262872))
        self.assertIsNone(gem.ignored)

        self.assertEqual(len(self.parsed.supplies), 1)
        self.assertEqual(self.parsed.supplies[0].total_price, 30000)

    def test_raw_json_preserved_exactly(self) -> None:
        self.assertEqual(self.parsed.raw_json, self.text)
        self.assertEqual(self.parsed.warnings, [])

    def test_unknown_fields_are_kept_in_raw_json(self) -> None:
        data = load_sample()
        data["NewField"] = 123
        data["Session"]["Brand new metric"] = 9
        text = json.dumps(data)
        parsed = parse_analyzer_json(text)
        self.assertEqual(json.loads(parsed.raw_json)["NewField"], 123)
        self.assertEqual(parsed.session.session_id, 1080)

    def test_content_hash_ignores_formatting(self) -> None:
        data = load_sample()
        compact = json.dumps(data, separators=(",", ":"))
        self.assertEqual(parse_analyzer_json(compact).content_hash, self.parsed.content_hash)
        self.assertEqual(compute_content_hash(data), self.parsed.content_hash)


class InvalidJsonTests(unittest.TestCase):
    def test_malformed_json(self) -> None:
        with self.assertRaises(InvalidJsonError) as ctx:
            parse_analyzer_json('{"Session": {')
        self.assertEqual(ctx.exception.message, "JSON inválido.")

    def test_empty_text(self) -> None:
        with self.assertRaises(InvalidJsonError):
            parse_analyzer_json("")

    def test_root_is_not_object(self) -> None:
        with self.assertRaises(InvalidAnalyzerSessionError) as ctx:
            parse_analyzer_json("[1, 2, 3]")
        self.assertEqual(ctx.exception.message,
                         "O arquivo não possui uma sessão válida do Analyzer.")

    def test_missing_session(self) -> None:
        data = load_sample()
        del data["Session"]
        with self.assertRaises(InvalidAnalyzerSessionError):
            parse_analyzer_json(json.dumps(data))

    def test_session_not_an_object(self) -> None:
        for value in (None, [], "x", {}):
            with self.subTest(value=value), self.assertRaises(InvalidAnalyzerSessionError):
                parse_analyzer_json(json.dumps({"Session": value}))

    def test_session_without_identifying_fields(self) -> None:
        with self.assertRaises(InvalidAnalyzerSessionError):
            parse_analyzer_json(json.dumps({"Session": {"Kills": 10}}))


class IncompleteJsonTests(unittest.TestCase):
    def test_minimal_session_only(self) -> None:
        parsed = parse_analyzer_json(json.dumps({"Session": {"Session ID": 5}}))
        self.assertEqual(parsed.session.session_id, 5)
        self.assertIsNone(parsed.session.player)
        self.assertIsNone(parsed.session.start_datetime)
        self.assertEqual((parsed.enemies, parsed.drops, parsed.supplies), ([], [], []))

    def test_null_values_are_safe(self) -> None:
        text = sample_text(**{"Kills": None, "Profit": None, "Start": None,
                              "Profit per hour": None, "Kills per hour": None})
        parsed = parse_analyzer_json(text)
        self.assertIsNone(parsed.session.kills)
        self.assertIsNone(parsed.session.profit)
        self.assertIsNone(parsed.session.profit_per_hour)
        self.assertIsNone(parsed.session.start_datetime)

    def test_duration_from_text_when_seconds_missing(self) -> None:
        parsed = parse_analyzer_json(sample_text(**{"Duration seconds": None}))
        self.assertEqual(parsed.session.duration_seconds, 4310)

    def test_missing_rates_are_derived(self) -> None:
        parsed = parse_analyzer_json(sample_text(**{"Profit per hour": None,
                                                     "Damage dealt per second": None}))
        self.assertAlmostEqual(parsed.session.profit_per_hour, 1119522 * 3600 / 4310)
        self.assertAlmostEqual(parsed.session.damage_dealt_per_second, 119470652 / 4310)

    def test_numeric_strings_are_converted(self) -> None:
        parsed = parse_analyzer_json(sample_text(**{"Session ID": "1080", "Kills": "368"}))
        self.assertEqual(parsed.session.session_id, 1080)
        self.assertEqual(parsed.session.kills, 368)

    def test_bad_list_types_and_entries_generate_warnings(self) -> None:
        data = load_sample()
        data["Drops"] = {"not": "a list"}
        data["Enemies Defeated"].append("garbage")
        data["Enemies Defeated"].append({"Count": 3})  # sem nome
        data["Supplies"].append({"Item": "Potion", "Count": 4, "Unit price": 50})
        parsed = parse_analyzer_json(json.dumps(data))

        self.assertEqual(parsed.drops, [])
        self.assertEqual(len(parsed.enemies), 3)
        self.assertEqual(parsed.supplies[-1].total_price, 200)  # derivado de count × preço
        self.assertEqual(len(parsed.warnings), 2)

    def test_null_lists(self) -> None:
        data = load_sample()
        data["Drops"] = None
        parsed = parse_analyzer_json(json.dumps(data))
        self.assertEqual(parsed.drops, [])
        self.assertEqual(parsed.warnings, [])

    def test_multiple_players(self) -> None:
        data = load_sample()
        data["Drops"][1]["Player"] = "Partner"
        parsed = parse_analyzer_json(json.dumps(data))
        self.assertEqual(parsed.session.player, "Royalzxd, Partner")


class ReadFileTests(unittest.TestCase):
    def test_reads_file_with_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bom.json"
            path.write_text(SAMPLE_HUNT_PATH.read_text(encoding="utf-8"), encoding="utf-8-sig")
            parsed = parse_analyzer_json(read_analyzer_file(path))
            self.assertEqual(parsed.session.session_id, 1080)

    def test_missing_file(self) -> None:
        with self.assertRaises(FileReadError):
            read_analyzer_file(Path(tempfile.gettempdir()) / "does-not-exist-pxg.json")

    def test_binary_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "binary.json"
            path.write_bytes(b"\xff\xfe\x00\x81\x82")
            with self.assertRaises(InvalidJsonError):
                read_analyzer_file(path)


if __name__ == "__main__":
    unittest.main()
