"""Navegação da janela: seções, sub-navegação, botão Importar e ações da lista."""

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.services.categories import Category  # noqa: E402
from app.services.statistics_service import StatisticsService  # noqa: E402
from app.services.hunt_service import HuntService  # noqa: E402
from app.ui.main_window import NAV_ITEMS, SECTION_PAGES, MainWindow, boss_key  # noqa: E402
from app.ui.theme import apply_theme  # noqa: E402
from tests.helpers import SAMPLE_HUNT_PATH, memory_database  # noqa: E402
from tests.test_bosses import boss_text  # noqa: E402


class NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.database = memory_database()
        self.service = HuntService(self.database)
        self.hunt_id = self.service.import_file(SAMPLE_HUNT_PATH).hunt_id
        self.boss_id = self.service.import_text(boss_text(1), category=Category.TERROR).hunt_id
        self.window = MainWindow(self.service, StatisticsService(self.database), Path("m.db"))
        self.window.show()
        self.bar = self.window.section_bar

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.database.dispose()

    def test_sidebar_has_only_the_sections(self) -> None:
        self.assertEqual([item.label for item in NAV_ITEMS],
                         ["Início", "Sessões", "Análise", "DPS", "Configurações"])
        self.assertFalse(self.window.menuBar().actions())

    def test_section_bar_only_in_sections_with_subpages(self) -> None:
        self.assertTrue(self.bar.isHidden())
        self.window.show_page("sessions")
        self.assertFalse(self.bar.isHidden())
        self.assertEqual(list(self.bar.buttons), [key for key, _ in SECTION_PAGES["sessions"]])
        self.window.show_page("analysis")
        self.assertEqual(list(self.bar.buttons), [key for key, _ in SECTION_PAGES["analysis"]])
        self.window.show_page("dps")
        self.assertTrue(self.bar.isHidden())

    def test_every_page_key_marks_its_section(self) -> None:
        self.window.show_page("prices")
        self.assertIs(self.window.stack.currentWidget(), self.window.pages["prices"])
        self.assertTrue(self.window.sidebar._buttons["analysis"].isChecked())
        self.assertTrue(self.bar.buttons["prices"].isChecked())

    def test_section_reopens_last_subpage(self) -> None:
        self.window.show_page("items")
        self.window.show_page("dashboard")
        self.window.show_page("analysis")
        self.assertIs(self.window.stack.currentWidget(), self.window.pages["items"])

    def test_pill_click_opens_boss_type(self) -> None:
        self.window.show_page("sessions")
        self.bar.buttons[boss_key(Category.TERROR)].click()
        page = self.window.bosses_page
        self.assertIs(self.window.stack.currentWidget(), page)
        self.assertEqual(page.current_category, Category.TERROR)
        self.assertEqual(page._header.title.text(), "Terrors")
        self.assertTrue(page.isAncestorOf(self.window.filter_panel))

    def test_session_counts_in_pills(self) -> None:
        self.window.show_page("sessions")
        self.assertEqual(self.bar.buttons["all_sessions"].text(), "Todas (2)")
        self.assertEqual(self.bar.buttons["hunts"].text(), "Hunts (1)")
        self.assertEqual(self.bar.buttons[boss_key(Category.TERROR)].text(), "Terrors (1)")
        self.assertEqual(self.bar.buttons[boss_key(Category.RIFT)].text(), "Rifts")

    def test_all_sessions_lists_every_category(self) -> None:
        self.window.show_page("all_sessions")
        page = self.window.all_sessions_page
        self.assertEqual(page._table.visible_row_count(), 2)
        self.assertEqual(self.window._import_category(), None)
        self.assertEqual(page._export_document().tables[0].title, "Sessões")
        page.select_hunts([self.boss_id])
        page.move_selected(Category.RIFT)
        self.assertEqual(page._table.visible_row_count(), 2)
        self.assertEqual(self.service.get_summaries([self.boss_id])[0].category, "rift")

    def test_import_goes_to_the_open_boss_type(self) -> None:
        self.window.show_page(boss_key(Category.RIFT))
        self.assertEqual(self.window._import_category(), Category.RIFT)
        self.window.show_page("hunts")
        self.assertIsNone(self.window._import_category())

    def test_imported_boss_marks_its_pill(self) -> None:
        self.window.show_page("dashboard")
        self.window._on_hunts_imported([self.boss_id])
        self.assertTrue(self.bar.buttons[boss_key(Category.TERROR)].isChecked())
        self.assertIs(self.window.stack.currentWidget(), self.window.bosses_page)

    def test_import_menu_keeps_shortcuts(self) -> None:
        menu = self.window.sidebar.import_button.menu()
        shortcuts = [action.shortcut() for action in menu.actions()]
        self.assertEqual(shortcuts, [QKeySequence("Ctrl+I"), QKeySequence("Ctrl+Shift+I"),
                                     QKeySequence("Ctrl+Shift+V")])
        for action in menu.actions():
            self.assertIn(action, self.window.actions())

    def test_selection_actions_appear_only_when_usable(self) -> None:
        self.window.show_page("all_sessions")
        page = self.window.all_sessions_page
        table = page._table
        table.clearSelection()
        for button in (page._open_button, page._compare_button, page._move_button,
                       page._delete_button):
            self.assertTrue(button.isHidden())
        self.assertFalse(page.export_button.isHidden())

        table.selectRow(0)
        self.assertFalse(page._open_button.isHidden())
        self.assertTrue(page._compare_button.isHidden())
        self.assertFalse(page._delete_button.isHidden())

        table.selectAll()
        self.assertTrue(page._open_button.isHidden())
        self.assertFalse(page._compare_button.isHidden())
        self.assertEqual(page._selection_label.text(), "2 selecionada(s)")

    def test_status_bar_only_with_a_message(self) -> None:
        status = self.window.statusBar()
        self.assertTrue(status.isHidden())
        status.showMessage("Exportado")
        self.assertFalse(status.isHidden())
        status.clearMessage()
        self.assertTrue(status.isHidden())

    def test_home_hides_categories_without_sessions(self) -> None:
        self.window.show_page("dashboard")
        page = self.window.dashboard_page
        self.assertFalse(page.category_cards[Category.HUNT].isHidden())
        self.assertTrue(page.category_cards[Category.RIFT].isHidden())
        self.assertFalse(page.category_cards[Category.TERROR].isHidden())

    def test_home_without_sessions_invites_to_import(self) -> None:
        self.service.delete_hunts([self.hunt_id, self.boss_id])
        self.window.show_page("dashboard")
        page = self.window.dashboard_page
        self.assertTrue(page._cards_section.isHidden())
        self.assertTrue(page._categories_section.isHidden())
        self.assertIn("Importar", page._empty_hint.text())


if __name__ == "__main__":
    unittest.main()
