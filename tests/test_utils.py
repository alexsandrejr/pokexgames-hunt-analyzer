import unittest
from datetime import datetime

from app.utils import formatters as f
from app.utils.validators import (
    parse_datetime,
    parse_duration,
    to_bool,
    to_float,
    to_int,
    to_str,
)


class FormatterTests(unittest.TestCase):
    def test_number(self) -> None:
        self.assertEqual(f.format_number(1119522), "1.119.522")
        self.assertEqual(f.format_number(935099.4), "935.099")
        self.assertEqual(f.format_number(12.5, decimals=1), "12,5")
        self.assertEqual(f.format_number(-1500), "-1.500")
        self.assertEqual(f.format_number(-0.2), "0")
        self.assertEqual(f.format_number(0), "0")
        self.assertEqual(f.format_number(None), f.PLACEHOLDER)
        self.assertEqual(f.format_number(float("nan")), f.PLACEHOLDER)

    def test_money(self) -> None:
        self.assertEqual(f.format_money(1119522), "1.119.522")

    def test_compact(self) -> None:
        self.assertEqual(f.format_compact(119470652), "119,5 M")
        self.assertEqual(f.format_compact(1_460_258), "1,5 M")
        self.assertEqual(f.format_compact(2_500_000_000), "2,5 B")
        self.assertEqual(f.format_compact(950), "950")

    def test_duration(self) -> None:
        self.assertEqual(f.format_duration(4310), "01:11:50")
        self.assertEqual(f.format_duration(0), "00:00:00")
        self.assertEqual(f.format_duration(90061), "25:01:01")
        self.assertEqual(f.format_duration(None), f.PLACEHOLDER)
        self.assertEqual(f.format_duration(-5), f.PLACEHOLDER)

    def test_duration_long(self) -> None:
        self.assertEqual(f.format_duration_long(42 * 3600 + 18 * 60 + 30), "42h 18min")
        self.assertEqual(f.format_duration_long(540), "9min")
        self.assertEqual(f.format_duration_long(1500 * 3600), "1.500h 00min")

    def test_dates(self) -> None:
        moment = datetime(2026, 9, 26, 15, 24, 20)
        self.assertEqual(f.format_date(moment), "26/09/2026")
        self.assertEqual(f.format_datetime(moment), "26/09/2026 15:24:20")
        self.assertEqual(f.format_date(None), f.PLACEHOLDER)

    def test_bool(self) -> None:
        self.assertEqual(f.format_bool(True), "Sim")
        self.assertEqual(f.format_bool(False), "Não")
        self.assertEqual(f.format_bool(None), f.PLACEHOLDER)


class ValidatorTests(unittest.TestCase):
    def test_to_int(self) -> None:
        self.assertEqual(to_int(5), 5)
        self.assertEqual(to_int(5.6), 6)
        self.assertEqual(to_int("42"), 42)
        self.assertEqual(to_int(" 7.0 "), 7)
        self.assertIsNone(to_int("abc"))
        self.assertIsNone(to_int(None))
        self.assertIsNone(to_int(True))
        self.assertIsNone(to_int([1]))
        self.assertEqual(to_int(None, default=0), 0)

    def test_to_float(self) -> None:
        self.assertEqual(to_float("1.5"), 1.5)
        self.assertIsNone(to_float("inf"))
        self.assertIsNone(to_float({}))

    def test_to_bool(self) -> None:
        self.assertIs(to_bool(False), False)
        self.assertIs(to_bool("true"), True)
        self.assertIs(to_bool(0), False)
        self.assertIsNone(to_bool(None))
        self.assertIsNone(to_bool("maybe"))

    def test_to_str(self) -> None:
        self.assertEqual(to_str("  x "), "x")
        self.assertIsNone(to_str("   "))
        self.assertEqual(to_str(10), "10")
        self.assertIsNone(to_str({"a": 1}))

    def test_parse_datetime(self) -> None:
        self.assertEqual(parse_datetime("2026-09-26 15:24:20"), datetime(2026, 9, 26, 15, 24, 20))
        self.assertEqual(parse_datetime("26/09/2026 15:24:20"), datetime(2026, 9, 26, 15, 24, 20))
        self.assertIsNone(parse_datetime("ontem"))
        self.assertIsNone(parse_datetime(None))

    def test_parse_duration(self) -> None:
        self.assertEqual(parse_duration("01:11:50"), 4310)
        self.assertEqual(parse_duration("11:50"), 710)
        self.assertEqual(parse_duration("25:00:00"), 90000)
        self.assertIsNone(parse_duration("01:61:00"))
        self.assertIsNone(parse_duration("1h"))
        self.assertIsNone(parse_duration(None))


if __name__ == "__main__":
    unittest.main()
