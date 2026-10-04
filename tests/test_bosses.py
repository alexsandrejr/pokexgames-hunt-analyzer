"""Categorias de sessão (Hunts e bosses): importação, filtros, estatísticas e página Bosses."""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database.database import Database  # noqa: E402
from app.services.categories import (  # noqa: E402
    BOSS_CATEGORIES,
    Category,
    category_dir,
    category_from_folder,
)
from app.services.filters import EMPTY_FILTER, HuntFilter  # noqa: E402
from app.services.hunt_service import IMPORTED_MESSAGE, HuntService  # noqa: E402
from app.services.statistics_service import StatisticsService, damage_by_element  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.theme import apply_theme  # noqa: E402
from tests.helpers import FIXTURES_DIR, SAMPLE_HUNT_PATH, memory_database  # noqa: E402

SAMPLE_BOSS_PATH = FIXTURES_DIR / "sample_boss.json"


def boss_text(session_id: int = 651, start: str = "2026-10-04 13:04:54", **session) -> str:
    data = copy.deepcopy(json.loads(SAMPLE_BOSS_PATH.read_text(encoding="utf-8")))
    data["Session"].update({"Session ID": session_id, "Start": start, **session})
    return json.dumps(data)


class CategoryTests(unittest.TestCase):
    def test_labels_and_folders(self) -> None:
        self.assertEqual([c.plural for c in BOSS_CATEGORIES],
                         ["Rifts", "Energia Vermelha", "Energia Azul", "Terrors"])
        self.assertEqual(Category.from_value("terror"), Category.TERROR)
        self.assertEqual(Category.from_value("desconhecida"), Category.HUNT)
        self.assertEqual(category_dir(Path("imp"), Category.HUNT), Path("imp"))
        self.assertEqual(category_dir(Path("imp"), Category.BOSS_RED),
                         Path("imp") / "energia_vermelha")

    def test_category_from_folder(self) -> None:
        self.assertEqual(category_from_folder("x/imports/Terrors/a.json"), Category.TERROR)
        self.assertEqual(category_from_folder("x/imports/energia_azul/a.json"),
                         Category.BOSS_BLUE)
        self.assertIsNone(category_from_folder("x/imports/a.json"))
        self.assertIsNone(category_from_folder("Texto colado"))

    def test_scope_is_not_a_user_filter(self) -> None:
        scoped = EMPTY_FILTER.scoped(Category.TERROR)
        self.assertEqual(scoped.categories, (Category.TERROR,))
        self.assertTrue(scoped.is_empty)
        self.assertEqual(scoped.describe(), [])
        self.assertEqual(HuntFilter(player="x").scoped().categories, ())


class BossImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = memory_database()
        self.service = HuntService(self.database)
        self.statistics = StatisticsService(self.database)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self.database.dispose()
        self._tmp.cleanup()

    def category_of(self, hunt_id: int) -> Category:
        return Category.from_value(self.service.get_hunt_details(hunt_id).category)

    def test_hunt_is_the_default(self) -> None:
        result = self.service.import_file(SAMPLE_HUNT_PATH)
        self.assertEqual(result.category, Category.HUNT)
        self.assertEqual(result.message, IMPORTED_MESSAGE)
        self.assertEqual(self.category_of(result.hunt_id), Category.HUNT)

    def test_requested_category(self) -> None:
        result = self.service.import_file(SAMPLE_BOSS_PATH, category=Category.TERROR)
        self.assertEqual(result.category, Category.TERROR)
        self.assertEqual(result.message, "Sessão importada em Terrors.")
        self.assertEqual(self.category_of(result.hunt_id), Category.TERROR)

    def test_folder_wins_over_requested_category(self) -> None:
        folder = self.root / "rifts"
        folder.mkdir()
        path = folder / "boss.json"
        path.write_text(boss_text(), encoding="utf-8")
        result = self.service.import_file(path, category=Category.TERROR)
        self.assertEqual(result.category, Category.RIFT)

    def test_known_boss_enemies_are_detected(self) -> None:
        self.service.import_text(boss_text(1), category=Category.BOSS_RED)
        result = self.service.import_text(boss_text(2, "2026-10-05 10:00:00"))
        self.assertEqual(result.category, Category.BOSS_RED)

    def test_enemy_also_seen_in_hunts_is_not_detected(self) -> None:
        self.service.import_text(boss_text(1), category=Category.TERROR)
        self.service.import_text(boss_text(2, "2026-10-05 10:00:00"), category=Category.HUNT)
        result = self.service.import_text(boss_text(3, "2026-10-06 10:00:00"))
        self.assertEqual(result.category, Category.HUNT)

    def test_pasted_boss_is_saved_in_category_folder(self) -> None:
        result = self.service.import_pasted_text(boss_text(), self.root,
                                                 category=Category.BOSS_BLUE)
        self.assertEqual(result.saved_path.parent, self.root / "energia_azul")
        # O arquivo salvo volta para a mesma categoria, mesmo importado fora da aba.
        other = HuntService(memory_database())
        self.assertEqual(other.import_file(result.saved_path).category, Category.BOSS_BLUE)

    def test_pasted_hunt_stays_in_imports_root(self) -> None:
        result = self.service.import_pasted_text(SAMPLE_HUNT_PATH.read_text(encoding="utf-8"),
                                                 self.root)
        self.assertEqual(result.saved_path.parent, self.root)

    def test_scoped_queries_and_set_category(self) -> None:
        hunt = self.service.import_file(SAMPLE_HUNT_PATH).hunt_id
        boss = self.service.import_file(SAMPLE_BOSS_PATH, category=Category.TERROR).hunt_id
        hunts_only = EMPTY_FILTER.scoped(Category.HUNT)
        self.assertEqual([h.id for h in self.service.list_hunts(hunts_only)], [hunt])
        self.assertEqual(self.service.count_hunts(EMPTY_FILTER.scoped(Category.TERROR)), 1)
        self.assertEqual(self.service.count_hunts(), 2)

        self.assertEqual(self.service.set_category([boss], Category.RIFT), 1)
        self.assertEqual(self.service.count_hunts(EMPTY_FILTER.scoped(Category.TERROR)), 0)
        [summary] = self.service.list_hunts(EMPTY_FILTER.scoped(Category.RIFT))
        self.assertEqual((summary.id, summary.category), (boss, "rift"))

    def test_boss_statistics(self) -> None:
        self.service.import_text(boss_text(1), category=Category.TERROR)
        self.service.import_text(boss_text(2, "2026-10-05 10:00:00", Kills=3, Profit=300_000),
                                 category=Category.TERROR)
        self.service.import_file(SAMPLE_HUNT_PATH)
        terrors = EMPTY_FILTER.scoped(Category.TERROR)

        stats = self.statistics.overview(terrors)
        self.assertEqual((stats.hunt_count, stats.total_kills), (2, 4))
        self.assertEqual(stats.profit_per_kill, (147_900 + 300_000) / 4)
        self.assertEqual(stats.duration_per_kill, 454 * 2 / 4)

        elements = self.statistics.damage_by_element(terrors)
        self.assertEqual([(e.element, e.dealt, e.taken) for e in elements],
                         [("Dragon", 2 * 1_883_827, 0), ("Neutral", 0, 2 * 188_003)])
        self.assertEqual(elements[0].dealt_share, 1.0)
        self.assertEqual(elements[1].taken_share, 1.0)

    def test_damage_by_element_ignores_missing_sections(self) -> None:
        documents = ['{"Session": {}}', "não é json", json.dumps({"Damage": [
            {"Element": "Fire", "Damage dealt": 30, "Damage taken": 10},
            {"Element": "Water", "Damage dealt": 70},
            "inválido",
        ]})]
        rows = damage_by_element(documents)
        self.assertEqual([(r.element, r.dealt, r.taken) for r in rows],
                         [("Water", 70, 0), ("Fire", 30, 10)])
        self.assertAlmostEqual(rows[0].dealt_share, 0.7)
        self.assertEqual(damage_by_element([]), [])


class CategoryMigrationTests(unittest.TestCase):
    def test_version3_database_gets_category_column(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "hunts.db"
            old = Database.from_path(path)
            old.create_schema()
            HuntService(old).import_file(SAMPLE_HUNT_PATH)
            with old.engine.begin() as connection:
                connection.execute(text("DROP INDEX ix_hunt_sessions_category"))
                connection.execute(text("ALTER TABLE hunt_sessions DROP COLUMN category"))
                connection.execute(text("PRAGMA user_version = 3"))
            old.dispose()

            database = Database.from_path(path)
            self.assertEqual([m.version for m in database.create_schema()], [4])
            service = HuntService(database)
            [summary] = service.list_hunts()
            self.assertEqual(summary.category, "hunt")
            boss = service.import_file(SAMPLE_BOSS_PATH, category=Category.RIFT)
            self.assertEqual(service.count_hunts(EMPTY_FILTER.scoped(Category.RIFT)), 1)
            self.assertIsNotNone(boss.hunt_id)
            database.dispose()


class BossesUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.database = memory_database()
        self.service = HuntService(self.database)
        self.service.import_file(SAMPLE_HUNT_PATH)
        self.service.import_text(boss_text(1), category=Category.TERROR)
        self.service.import_text(boss_text(2, "2026-10-05 10:00:00"), category=Category.TERROR)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.window = MainWindow(self.service, StatisticsService(self.database), Path("m.db"))
        self.window.importer.paste_save_dir = self.root
        self.window.show()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.database.dispose()
        self._tmp.cleanup()

    def test_hunts_page_and_dashboard_ignore_bosses(self) -> None:
        self.window.show_page("hunts")
        self.assertEqual(self.window.hunts_page._table.visible_row_count(), 1)
        self.window.show_page("dashboard")
        self.assertEqual(self.window.dashboard_page._cards["hunts"]._value.text(), "1")

    def test_bosses_page_tabs_and_summary(self) -> None:
        self.window.show_page("bosses")
        page = self.window.bosses_page
        self.assertEqual([page.tabs.tabText(i) for i in range(page.tabs.count())],
                         ["Rifts", "Energia Vermelha", "Energia Azul", "Terrors (2)"])
        self.assertTrue(page.isAncestorOf(self.window.filter_panel))

        page.tabs.setCurrentIndex(3)
        summary = page.current_view.summary
        self.assertEqual(summary.cards["sessions"]._value.text(), "2")
        self.assertEqual(summary.cards["kills"]._value.text(), "2")
        self.assertEqual(summary.enemies.visible_records()[0].name, "Iron-Masked Marauder")
        self.assertEqual(summary.elements.visible_row_count(), 2)
        self.assertTrue(summary._charts_section.isVisibleTo(self.window))

        page.tabs.setCurrentIndex(0)  # Rifts: vazio
        self.assertFalse(page.current_view.summary._tables_section.isVisibleTo(self.window))

    def test_import_with_boss_tab_open(self) -> None:
        self.window.show_page("bosses")
        self.window.bosses_page.tabs.setCurrentIndex(1)  # Energia Vermelha
        result = self.window.importer.import_pasted(boss_text(9, "2026-10-09 10:00:00"))
        self.assertEqual(result.category, Category.BOSS_RED)
        self.assertEqual(result.saved_path.parent, self.root / "energia_vermelha")
        view = self.window.bosses_page.views[Category.BOSS_RED]
        self.assertIs(self.window.bosses_page.current_view, view)
        self.assertEqual(view.sessions.selected_ids(), [result.hunt_id])

    def test_import_outside_bosses_goes_to_hunts(self) -> None:
        self.window.show_page("hunts")
        hunt = json.loads(SAMPLE_HUNT_PATH.read_text(encoding="utf-8"))
        hunt["Session"]["Session ID"] = 777
        result = self.window.importer.import_pasted(json.dumps(hunt))
        self.assertEqual(result.category, Category.HUNT)
        self.assertIs(self.window.stack.currentWidget(), self.window.hunts_page)
        self.assertEqual(self.window.hunts_page.selected_ids(), [result.hunt_id])

    def test_known_boss_imported_from_hunts_opens_its_tab(self) -> None:
        self.window.show_page("hunts")
        result = self.window.importer.import_pasted(boss_text(10, "2026-10-10 10:00:00"))
        self.assertEqual(result.category, Category.TERROR)
        self.assertIs(self.window.stack.currentWidget(), self.window.bosses_page)
        self.assertEqual(self.window.bosses_page.current_category, Category.TERROR)

    def test_move_hunt_to_boss_category(self) -> None:
        self.window.show_page("hunts")
        page = self.window.hunts_page
        page.select_hunts(h.id for h in page._table.visible_records())
        self.assertTrue(page._move_button.isEnabled())
        self.assertEqual(page.move_selected(Category.RIFT), 1)
        self.assertEqual(page._table.visible_row_count(), 0)
        self.assertIn("movida(s) para Rifts", self.window.statusBar().currentMessage())
        self.assertEqual(self.service.count_hunts(EMPTY_FILTER.scoped(Category.RIFT)), 1)

    def test_reports_scope(self) -> None:
        self.window.show_page("reports")
        page = self.window.reports_page
        self.assertEqual(page._cards["hunts"]._value.text(), "1")
        page.scope.set_categories((Category.TERROR,))
        self.assertEqual(page._cards["hunts"]._value.text(), "2")
        page.scope.set_categories(())
        self.assertEqual(page._cards["hunts"]._value.text(), "3")
        self.assertIn("Categoria: Hunts e bosses", page._export_document().subtitle)

    def test_boss_details_title(self) -> None:
        boss_id = self.service.list_hunts(EMPTY_FILTER.scoped(Category.TERROR))[0].id
        dialog = self.window.hunts_page.open_hunt(boss_id)
        self.assertEqual(dialog.windowTitle(), "Terror 2")
        dialog.close()


if __name__ == "__main__":
    unittest.main()
