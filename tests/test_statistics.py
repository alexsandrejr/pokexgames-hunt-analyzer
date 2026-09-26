import unittest

from app.services.filters import HuntFilter, Metric, MetricCondition, Operator
from app.services.hunt_service import HuntService
from app.services.statistics_service import RateUnit, StatisticsService, rate_per_hour
from tests.helpers import memory_database, sample_text


class RatePerHourTests(unittest.TestCase):
    def test_rate(self) -> None:
        self.assertAlmostEqual(rate_per_hour(1119522, 4310), 935099.58, places=2)
        self.assertEqual(rate_per_hour(100, 1800), 200)

    def test_no_duration(self) -> None:
        self.assertIsNone(rate_per_hour(100, 0))
        self.assertIsNone(rate_per_hour(100, None))
        self.assertIsNone(rate_per_hour(None, 3600))


class OverviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = memory_database()
        self.hunts = HuntService(self.database)
        self.stats = StatisticsService(self.database)

    def tearDown(self) -> None:
        self.database.dispose()

    def test_empty_database(self) -> None:
        overview = self.stats.overview()
        self.assertEqual(overview.hunt_count, 0)
        self.assertEqual(overview.total_profit, 0)
        self.assertIsNone(overview.average_profit_per_hour)
        self.assertIsNone(overview.profit_per_total_hour)

    def test_totals_and_both_kinds_of_average(self) -> None:
        # Hunt A: 1h, profit 1.000.000 → 1.000.000/h
        # Hunt B: 3h, profit 1.500.000 →   500.000/h
        self.hunts.import_text(sample_text(**{
            "Session ID": 1, "Start": "2026-09-01 10:00:00", "Duration seconds": 3600,
            "Profit": 1_000_000, "Profit per hour": 1_000_000,
            "Kills": 300, "Kills per hour": 300, "Supplies": 100_000, "Raw gains": 1_100_000,
        }))
        self.hunts.import_text(sample_text(**{
            "Session ID": 2, "Start": "2026-09-02 10:00:00", "Duration seconds": 10800,
            "Profit": 1_500_000, "Profit per hour": 500_000,
            "Kills": 600, "Kills per hour": 200, "Supplies": 300_000, "Raw gains": 1_800_000,
        }))

        overview = self.stats.overview()
        self.assertEqual(overview.hunt_count, 2)
        self.assertEqual(overview.total_duration_seconds, 14400)
        self.assertEqual(overview.total_profit, 2_500_000)
        self.assertEqual(overview.total_kills, 900)
        self.assertEqual(overview.total_supplies, 400_000)
        self.assertEqual(overview.total_raw_gains, 2_900_000)

        # Média simples dos Profit/h individuais ≠ Profit total ÷ tempo total.
        self.assertAlmostEqual(overview.average_profit_per_hour, 750_000)
        self.assertAlmostEqual(overview.profit_per_total_hour, 625_000)
        self.assertAlmostEqual(overview.average_kills_per_hour, 250)
        self.assertAlmostEqual(overview.kills_per_total_hour, 225)
        self.assertEqual(overview.first_start.day, 1)
        self.assertEqual(overview.last_start.day, 2)
        self.assertEqual(overview.average_duration_seconds, 7200)

    def test_overview_respects_filter(self) -> None:
        self._two_hunts()
        only_long = HuntFilter(metrics=(MetricCondition(Metric.DURATION, Operator.GT, 3600),))
        overview = self.stats.overview(only_long)
        self.assertEqual(overview.hunt_count, 1)
        self.assertEqual(overview.total_profit, 1_500_000)
        nothing = HuntFilter(player="ninguém")
        self.assertEqual(self.stats.overview(nothing).hunt_count, 0)
        self.assertIsNone(self.stats.overview(nothing).average_duration_seconds)

    def test_metric_breakdown(self) -> None:
        self._two_hunts()
        metrics = {m.key: m for m in self.stats.metric_breakdown()}
        profit = metrics["profit"]
        self.assertEqual(profit.total, 2_500_000)
        self.assertEqual(profit.average, 1_250_000)
        self.assertEqual((profit.minimum, profit.maximum), (1_000_000, 1_500_000))
        self.assertAlmostEqual(profit.average_rate, 750_000)  # média dos Profit/h
        self.assertAlmostEqual(profit.rate_over_total_time, 625_000)  # total ÷ 4h
        duration = metrics["duration"]
        self.assertEqual((duration.total, duration.minimum, duration.maximum), (14400, 3600, 10800))
        self.assertIsNone(duration.rate_over_total_time)
        dealt = metrics["damage_dealt"]
        self.assertEqual(dealt.rate_unit, RateUnit.SECOND)
        self.assertAlmostEqual(dealt.rate_over_total_time, 2 * 119470652 / 14400)
        self.assertEqual([m.key for m in self.stats.metric_breakdown()][:3],
                         ["duration", "kills", "profit"])

    def test_metric_breakdown_empty(self) -> None:
        metrics = self.stats.metric_breakdown(HuntFilter(player="ninguém"))
        self.assertTrue(all(m.total is None and m.rate_over_total_time is None for m in metrics))

    def test_top_entries(self) -> None:
        self._two_hunts()
        drops = self.stats.top_drops()
        self.assertEqual([d.name for d in drops], ["metal scraps", "nightmare gem"])  # por valor
        self.assertEqual(drops[0].quantity, 2 * 194)
        self.assertEqual(drops[0].value, 2 * 388000)
        self.assertEqual(drops[0].hunt_count, 2)
        self.assertEqual(drops[0].average_per_hunt, 194)

        enemies = self.stats.top_enemies(limit=2)
        self.assertEqual([e.name for e in enemies], ["Mecha Charizard", "Mecha Abomasnow"])
        self.assertIsNone(enemies[0].value)
        self.assertEqual(self.stats.top_supplies()[0].name, "Healing Elixir")

        first_only = HuntFilter(metrics=(MetricCondition(Metric.DURATION, Operator.EQ, 3600),))
        self.assertEqual(self.stats.top_drops(first_only)[0].quantity, 194)
        self.assertEqual(self.stats.top_drops(HuntFilter(player="ninguém")), [])

    def _two_hunts(self) -> None:
        self.hunts.import_text(sample_text(**{
            "Session ID": 1, "Start": "2026-09-01 10:00:00", "Duration seconds": 3600,
            "Profit": 1_000_000, "Profit per hour": 1_000_000,
        }))
        self.hunts.import_text(sample_text(**{
            "Session ID": 2, "Start": "2026-09-02 10:00:00", "Duration seconds": 10800,
            "Profit": 1_500_000, "Profit per hour": 500_000,
        }))


if __name__ == "__main__":
    unittest.main()
