"""Filtros de Hunts executados contra o SQLite real (em memória)."""

import copy
import json
import unittest
from datetime import date

from app.services.filters import (
    DatePreset,
    EnemyCondition,
    HuntFilter,
    ItemCondition,
    ItemSource,
    Metric,
    MetricCondition,
    Operator,
    preset_range,
)
from app.services.hunt_service import HuntService
from app.utils.validators import parse_user_duration, parse_user_number
from tests.helpers import load_sample, memory_database


def make_hunt(session_id: int, start: str, player: str = "Royalzxd", *,
              duration: int = 3600, kills: int = 300, profit: int = 1_000_000,
              drops: dict[str, int] | None = None, enemies: dict[str, int] | None = None,
              supplies: dict[str, int] | None = None) -> str:
    data = copy.deepcopy(load_sample())
    data["Session"].update({
        "Session ID": session_id, "Start": start, "Duration seconds": duration,
        "Kills": kills, "Kills per hour": kills * 3600 / duration,
        "Profit": profit, "Profit per hour": profit * 3600 / duration,
    })

    def entries(key: str, values: dict[str, int] | None, name_key: str) -> None:
        if values is None:
            for entry in data[key]:
                entry["Player"] = player
            return
        data[key] = [{name_key: name, "Count": count, "Player": player,
                      "Unit price": 100, "Total price": 100 * count}
                     for name, count in values.items()]

    entries("Drops", drops, "Item")
    entries("Enemies Defeated", enemies, "Enemy")
    entries("Supplies", supplies or {}, "Item")
    return json.dumps(data)


class HuntFilterQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.database = memory_database()
        cls.service = HuntService(cls.database)
        hunts = [
            # id, início, player, duração, kills, profit, drops, inimigos
            make_hunt(1, "2026-09-01 10:00:00", duration=3600, kills=250, profit=800_000,
                      drops={"nightmare ore": 40, "nightmare gem": 1200},
                      enemies={"Mecha Charizard": 30}),
            make_hunt(2, "2026-09-10 23:59:59", duration=7200, kills=640, profit=2_000_000,
                      drops={"nightmare ore": 80}, enemies={"Mecha Charizard": 50,
                                                            "Mecha Blastoise": 12}),
            make_hunt(3, "2026-09-11 00:00:00", player="OutroPlayer", duration=1800,
                      kills=160, profit=-50_000, drops={"metal scraps": 5},
                      enemies={"Mecha Venusaur": 20}, supplies={"Healing Elixir": 4}),
            make_hunt(4, "2026-09-26 15:24:20", duration=4310, kills=368, profit=1_119_522,
                      drops={"nightmare gem": 900, "Nightmare Ore": 60},
                      enemies={"Mecha Charizard": 40}),
        ]
        for text in hunts:
            assert cls.service.import_text(text).hunt_id is not None
        cls.ids = {hunt.session_id: hunt.id for hunt in cls.service.list_hunts()}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.database.dispose()

    def session_ids(self, hunt_filter: HuntFilter) -> list[int]:
        return sorted(h.session_id for h in self.service.list_hunts(hunt_filter))

    def test_empty_filter_returns_all(self) -> None:
        self.assertEqual(self.session_ids(HuntFilter()), [1, 2, 3, 4])
        self.assertTrue(HuntFilter().is_empty)

    def test_date_range_is_inclusive_by_day(self) -> None:
        f = HuntFilter(date_from=date(2026, 9, 10), date_to=date(2026, 9, 10))
        self.assertEqual(self.session_ids(f), [2])  # 23:59:59 do dia 10 entra; 00:00 do 11 não
        self.assertEqual(self.session_ids(HuntFilter(date_from=date(2026, 9, 11))), [3, 4])
        self.assertEqual(self.session_ids(HuntFilter(date_to=date(2026, 9, 10))), [1, 2])

    def test_player_contains_case_insensitive(self) -> None:
        self.assertEqual(self.session_ids(HuntFilter(player="royal")), [1, 2, 4])
        self.assertEqual(self.session_ids(HuntFilter(player="OUTRO")), [3])
        self.assertEqual(self.session_ids(HuntFilter(player="100%")), [])

    def test_metric_operators(self) -> None:
        def ids(metric: Metric, operator: Operator, value: float) -> list[int]:
            return self.session_ids(HuntFilter(metrics=(MetricCondition(metric, operator, value),)))

        self.assertEqual(ids(Metric.PROFIT, Operator.GT, 1_000_000), [2, 4])
        self.assertEqual(ids(Metric.PROFIT, Operator.GE, 800_000), [1, 2, 4])
        self.assertEqual(ids(Metric.PROFIT, Operator.LT, 0), [3])
        self.assertEqual(ids(Metric.KILLS, Operator.EQ, 368), [4])
        self.assertEqual(ids(Metric.KILLS, Operator.LE, 250), [1, 3])
        # Hunt 3: 160 kills em 30 min = 320/h.
        self.assertEqual(ids(Metric.KILLS_PER_HOUR, Operator.GT, 300), [2, 3, 4])
        self.assertEqual(ids(Metric.DURATION, Operator.GE, 3600), [1, 2, 4])
        # Taxas decimais: "=" compara o valor arredondado (1119522×3600/4310 ≈ 935099,58).
        self.assertEqual(ids(Metric.PROFIT_PER_HOUR, Operator.EQ, 935_100), [4])

    def test_item_presence_and_quantity(self) -> None:
        def ids(*conditions: ItemCondition) -> list[int]:
            return self.session_ids(HuntFilter(items=conditions))

        self.assertEqual(ids(ItemCondition("Nightmare ore")), [1, 2, 4])  # sem diferenciar caixa
        self.assertEqual(ids(ItemCondition("nightmare ore", Operator.GT, 50)), [2, 4])
        # Hunts sem o item contam como 0 em comparações de quantidade.
        self.assertEqual(ids(ItemCondition("nightmare ore", Operator.LT, 50)), [1, 3])
        self.assertEqual(ids(ItemCondition("nightmare ore", Operator.GT, 50),
                             ItemCondition("nightmare gem", Operator.GT, 800)), [4])
        self.assertEqual(ids(ItemCondition("Healing Elixir")), [])  # só em supplies
        self.assertEqual(ids(ItemCondition("Healing Elixir", source=ItemSource.SUPPLIES)), [3])

    def test_enemy_presence_and_quantity(self) -> None:
        def ids(*conditions: EnemyCondition) -> list[int]:
            return self.session_ids(HuntFilter(enemies=conditions))

        self.assertEqual(ids(EnemyCondition("mecha charizard")), [1, 2, 4])
        self.assertEqual(ids(EnemyCondition("Mecha Charizard", Operator.GE, 40)), [2, 4])
        self.assertEqual(ids(EnemyCondition("Mecha Charizard"),
                             EnemyCondition("Mecha Blastoise")), [2])

    def test_all_criteria_combined(self) -> None:
        f = HuntFilter(
            date_from=date(2026, 9, 1), date_to=date(2026, 9, 26), player="Royalzxd",
            items=(ItemCondition("nightmare ore", Operator.GT, 50),),
            metrics=(MetricCondition(Metric.PROFIT_PER_HOUR, Operator.GT, 800_000),
                     MetricCondition(Metric.KILLS_PER_HOUR, Operator.GT, 250)),
        )
        self.assertEqual(self.session_ids(f), [2, 4])
        # Remover o critério de item não traz a Hunt 3 (player e profit/h a excluem).
        self.assertEqual(self.session_ids(HuntFilter(
            player="Royalzxd", metrics=f.metrics)), [2, 4])
        self.assertEqual(self.service.count_hunts(f), 2)

    def test_describe(self) -> None:
        f = HuntFilter(
            date_from=date(2026, 9, 1), date_to=date(2026, 9, 26), player="Royalzxd",
            enemies=(EnemyCondition("Mecha Charizard"),),
            items=(ItemCondition("nightmare ore", Operator.GT, 50),),
            metrics=(MetricCondition(Metric.KILLS_PER_HOUR, Operator.GT, 250),
                     MetricCondition(Metric.DURATION, Operator.GE, 3600)),
        )
        self.assertEqual(f.describe(), [
            "Data: 01/09/2026 a 26/09/2026", "Player: Royalzxd", "Inimigo: Mecha Charizard",
            "Drop: nightmare ore > 50", "Kills/h > 250", "Duração >= 01:00:00",
        ])
        self.assertFalse(f.is_empty)

    def test_filter_options(self) -> None:
        options = self.service.filter_options()
        self.assertEqual(options.players, ["OutroPlayer", "Royalzxd"])
        self.assertIn("Mecha Blastoise", options.enemies)
        self.assertIn("nightmare gem", options.drop_items)
        self.assertEqual(options.supply_items, ["Healing Elixir"])


class DatePresetTests(unittest.TestCase):
    def test_presets(self) -> None:
        today = date(2026, 9, 26)
        self.assertEqual(preset_range(DatePreset.ALL, today), (None, None))
        self.assertEqual(preset_range(DatePreset.TODAY, today), (today, today))
        self.assertEqual(preset_range(DatePreset.LAST_7_DAYS, today), (date(2026, 9, 20), today))
        self.assertEqual(preset_range(DatePreset.LAST_30_DAYS, today), (date(2026, 8, 28), today))
        self.assertEqual(preset_range(DatePreset.THIS_MONTH, today), (date(2026, 9, 1), today))
        self.assertEqual(preset_range(DatePreset.LAST_MONTH, today),
                         (date(2026, 8, 1), date(2026, 8, 31)))
        self.assertEqual(preset_range(DatePreset.LAST_MONTH, date(2026, 3, 15)),
                         (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(preset_range(DatePreset.LAST_MONTH, date(2026, 1, 5)),
                         (date(2025, 12, 1), date(2025, 12, 31)))


class UserInputParsingTests(unittest.TestCase):
    def test_numbers(self) -> None:
        cases = {
            "800000": 800_000, "1.000.000": 1_000_000, "12,5": 12.5, "1.5": 1.5,
            "800k": 800_000, "800K": 800_000, "1,2kk": 1_200_000, "1.5kk": 1_500_000,
            "2kkk": 2_000_000_000, " 250 ": 250, "-500": -500, "-1.000": -1000,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertAlmostEqual(parse_user_number(text), expected)
        for text in ("", "  ", "abc", "1,2,3", "k", None):
            with self.subTest(text=text):
                self.assertIsNone(parse_user_number(text))

    def test_durations(self) -> None:
        cases = {"1:30": 5400, "01:11:50": 4310, "90": 5400, "1h30": 5400, "1h 30min": 5400,
                 "2h": 7200, "45min": 2700, "45m": 2700, "0:45": 2700}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_user_duration(text), expected)
        for text in ("", "abc", "1:75", "1h90", None):
            with self.subTest(text=text):
                self.assertIsNone(parse_user_duration(text))


if __name__ == "__main__":
    unittest.main()
