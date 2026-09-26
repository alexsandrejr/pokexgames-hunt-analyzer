import unittest

from app.services.advanced_search import parse_advanced_query
from app.services.dto import FilterOptions
from app.services.filters import (
    EnemyCondition,
    HuntFilter,
    ItemCondition,
    ItemSource,
    Metric,
    MetricCondition,
    Operator,
)
from app.services.hunt_service import HuntService
from tests.helpers import memory_database
from tests.test_filters import make_hunt

OPTIONS = FilterOptions(
    players=["Royalzxd"],
    enemies=["Mecha Charizard", "Mecha Blastoise"],
    drop_items=["nightmare ore", "nightmare gem", "metal scraps"],
    supply_items=["Healing Elixir"],
)


class ParserTests(unittest.TestCase):
    def parse(self, text: str):
        return parse_advanced_query(text, OPTIONS)

    def test_spec_example(self) -> None:
        query = self.parse("Nightmare ore > 50 E Nightmare gem > 1000")
        self.assertTrue(query.ok, query.errors)
        self.assertEqual(query.items, [
            ItemCondition("nightmare ore", Operator.GT, 50),
            ItemCondition("nightmare gem", Operator.GT, 1000),
        ])

    def test_presence_and_resolution_order(self) -> None:
        query = self.parse("Mecha Charizard; healing elixir; metal scraps")
        self.assertEqual(query.enemies, [EnemyCondition("Mecha Charizard")])
        self.assertEqual(query.items, [
            ItemCondition("Healing Elixir", source=ItemSource.SUPPLIES),
            ItemCondition("metal scraps"),
        ])

    def test_metrics_with_game_notation(self) -> None:
        query = self.parse("profit/h >= 800k and kills/h > 300 & duração >= 1h30; profit < 1,2kk")
        self.assertTrue(query.ok, query.errors)
        self.assertEqual(query.metrics, [
            MetricCondition(Metric.PROFIT_PER_HOUR, Operator.GE, 800_000),
            MetricCondition(Metric.KILLS_PER_HOUR, Operator.GT, 300),
            MetricCondition(Metric.DURATION, Operator.GE, 5400),
            MetricCondition(Metric.PROFIT, Operator.LT, 1_200_000),
        ])

    def test_unicode_operators_and_spacing(self) -> None:
        query = self.parse("  nightmare   ore≥10 ;  mecha blastoise ≤ 5 ")
        self.assertEqual(query.items, [ItemCondition("nightmare ore", Operator.GE, 10)])
        self.assertEqual(query.enemies, [EnemyCondition("Mecha Blastoise", Operator.LE, 5)])

    def test_prefixes_force_type(self) -> None:
        query = self.parse("supply: Potion > 2; inimigo: Mecha Mew; drop: rare candy")
        self.assertTrue(query.ok, query.errors)
        self.assertEqual(query.items, [
            ItemCondition("Potion", Operator.GT, 2, source=ItemSource.SUPPLIES),
            ItemCondition("rare candy"),
        ])
        self.assertEqual(query.enemies, [EnemyCondition("Mecha Mew")])

    def test_prefix_does_not_turn_metric_name_into_metric(self) -> None:
        query = self.parse("drop: kills")
        self.assertEqual(query.items, [ItemCondition("kills")])
        self.assertEqual(query.metrics, [])

    def test_errors(self) -> None:
        cases = {
            "unobtainium > 3": "não foi encontrado",
            "kills/h": "Informe operador",
            "profit > muito": "Valor inválido",
            "nightmare ore > x": "Quantidade inválida",
            "nightmare ore >": "Falta o valor",
        }
        for text, message in cases.items():
            with self.subTest(text=text):
                query = self.parse(text)
                self.assertFalse(query.ok)
                self.assertIn(message, query.errors[0])

    def test_empty(self) -> None:
        for text in ("", "  ", " ; ; "):
            query = self.parse(text)
            self.assertTrue(query.ok)
            self.assertEqual((query.items, query.enemies, query.metrics), ([], [], []))

    def test_merge_keeps_existing_criteria(self) -> None:
        base = HuntFilter(player="Royal", items=(ItemCondition("metal scraps"),))
        merged = self.parse("nightmare ore > 50").merged_into(base)
        self.assertEqual(merged.player, "Royal")
        self.assertEqual(len(merged.items), 2)


class AdvancedSearchEndToEndTests(unittest.TestCase):
    def test_query_against_database(self) -> None:
        database = memory_database()
        service = HuntService(database)
        for text in (
            make_hunt(1, "2026-09-01 10:00:00", drops={"nightmare ore": 40, "nightmare gem": 1200}),
            make_hunt(2, "2026-09-02 10:00:00", drops={"nightmare ore": 80, "nightmare gem": 900}),
            make_hunt(3, "2026-09-03 10:00:00", drops={"nightmare ore": 60, "nightmare gem": 1500}),
        ):
            service.import_text(text)
        query = parse_advanced_query("Nightmare ore > 50 e Nightmare gem > 1000",
                                     service.filter_options())
        hunts = service.list_hunts(query.merged_into(HuntFilter()))
        self.assertEqual([h.session_id for h in hunts], [3])
        database.dispose()


if __name__ == "__main__":
    unittest.main()
