"""Relatórios por item/inimigo e resumos usados na comparação."""

import unittest
from datetime import date

from app.services.entity_report import EntityKind
from app.services.filters import HuntFilter
from app.services.hunt_service import HuntService
from app.services.statistics_service import StatisticsService
from tests.helpers import memory_database
from tests.test_filters import make_hunt


class EntityReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.database = memory_database()
        cls.hunts = HuntService(cls.database)
        cls.stats = StatisticsService(cls.database)
        for text in (
            # 1h, 40 ore; 2h, 80 ore; 30min, sem ore; 1h, 60 ore (nome com outra caixa)
            make_hunt(1, "2026-09-01 10:00:00", duration=3600,
                      drops={"nightmare ore": 40}, enemies={"Mecha Charizard": 30},
                      supplies={"Healing Elixir": 3}),
            make_hunt(2, "2026-09-10 10:00:00", duration=7200,
                      drops={"nightmare ore": 80, "nightmare gem": 5},
                      enemies={"Mecha Charizard": 50}),
            make_hunt(3, "2026-09-11 10:00:00", duration=1800, drops={"metal scraps": 5},
                      enemies={"Mecha Venusaur": 20}),
            make_hunt(4, "2026-09-26 10:00:00", duration=3600,
                      drops={"Nightmare Ore": 60}, enemies={"Mecha Charizard": 40}),
        ):
            cls.hunts.import_text(text)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.database.dispose()

    def test_drop_report(self) -> None:
        report = self.stats.entity_report(EntityKind.DROPS, "nightmare ore")
        self.assertEqual([r.session_id for r in report.rows], [1, 2, 3, 4])  # cronológico
        self.assertEqual([r.quantity for r in report.rows], [40, 80, 0, 60])
        self.assertEqual(report.hunt_count, 4)
        self.assertEqual(report.present_count, 3)
        self.assertAlmostEqual(report.presence_ratio, 0.75)
        self.assertEqual(report.total_quantity, 180)
        self.assertEqual(report.total_value, 180 * 100)  # make_hunt usa preço 100
        self.assertEqual(report.average_per_hunt, 60)  # nas Hunts em que apareceu
        self.assertEqual(report.average_value_per_hunt, 6000)
        self.assertEqual(report.present_duration_seconds, 4 * 3600)
        self.assertEqual(report.per_hour, 45)  # 180 em 4h
        self.assertEqual(report.max_row.session_id, 2)
        self.assertEqual(report.min_row.session_id, 1)
        self.assertIsNone(report.rows[2].value)

    def test_enemy_report(self) -> None:
        report = self.stats.entity_report(EntityKind.ENEMIES, " Mecha Charizard ")
        self.assertEqual(report.name, "Mecha Charizard")
        self.assertEqual(report.total_quantity, 120)
        self.assertEqual(report.present_count, 3)
        self.assertIsNone(report.total_value)
        self.assertIsNone(report.average_value_per_hunt)
        self.assertEqual(report.average_per_hunt, 40)
        self.assertEqual((report.min_row.quantity, report.max_row.quantity), (30, 50))

    def test_supply_report(self) -> None:
        report = self.stats.entity_report(EntityKind.SUPPLIES, "Healing Elixir")
        self.assertEqual(report.present_count, 1)
        self.assertEqual(report.total_value, 300)

    def test_report_respects_filter(self) -> None:
        f = HuntFilter(date_from=date(2026, 9, 10))
        report = self.stats.entity_report(EntityKind.DROPS, "nightmare ore", f)
        self.assertEqual([r.quantity for r in report.rows], [80, 0, 60])
        self.assertEqual(report.total_quantity, 140)

    def test_unknown_name_and_empty_filter(self) -> None:
        unknown = self.stats.entity_report(EntityKind.DROPS, "não existe")
        self.assertEqual(unknown.hunt_count, 4)
        self.assertEqual(unknown.present_count, 0)
        self.assertIsNone(unknown.average_per_hunt)
        self.assertIsNone(unknown.per_hour)
        self.assertIsNone(unknown.max_row)
        nothing = self.stats.entity_report(EntityKind.DROPS, "nightmare ore",
                                           HuntFilter(player="ninguém"))
        self.assertEqual(nothing.rows, ())
        self.assertIsNone(nothing.presence_ratio)

    def test_summaries_for_comparison(self) -> None:
        ids = [h.id for h in self.hunts.list_hunts()]  # mais recentes primeiro
        summaries = self.hunts.get_summaries(ids[:3])
        self.assertEqual([s.session_id for s in summaries], [2, 3, 4])  # cronológico
        self.assertIsNotNone(summaries[0].damage_dealt)
        self.assertEqual(self.hunts.get_summaries([]), [])


if __name__ == "__main__":
    unittest.main()
