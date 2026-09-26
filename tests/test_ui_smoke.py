"""Teste de fumaça da interface (roda sem janela visível, plataforma offscreen)."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.services.dto import ImportStatus  # noqa: E402
from app.services.hunt_service import HuntService  # noqa: E402
from app.services.statistics_service import StatisticsService  # noqa: E402
from app.ui.hunts.paste_json_dialog import PasteJsonDialog  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.theme import apply_theme  # noqa: E402
from tests.helpers import SAMPLE_HUNT_PATH, memory_database  # noqa: E402


class MainWindowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.database = memory_database()
        self.service = HuntService(self.database)
        self.window = MainWindow(self.service, StatisticsService(self.database), Path("mem.db"))
        self.window.importer.confirm_duplicate = lambda result: False
        self.window.show()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.database.dispose()

    def test_import_flow_updates_pages(self) -> None:
        results = self.window.importer.import_paths([SAMPLE_HUNT_PATH])
        self.assertEqual(results[0].status, ImportStatus.IMPORTED)

        # Após importar, a página Hunts é exibida com a Hunt selecionada.
        page = self.window.hunts_page
        self.assertIs(self.window.stack.currentWidget(), page)
        self.assertEqual(page._table.visible_row_count(), 1)
        self.assertEqual(len(page._table.selected_records()), 1)
        model = page._table.model()
        self.assertEqual(model.index(0, 6).data(), "1.119.522")  # Profit
        self.assertEqual(model.index(0, 3).data(), "01:11:50")  # Duração

        page._search.setText("nada-disso")
        self.assertEqual(page._table.visible_row_count(), 0)
        page._search.setText("royal")
        self.assertEqual(page._table.visible_row_count(), 1)

        self.window.show_page("dashboard")
        cards = self.window.dashboard_page._cards
        self.assertEqual(cards["hunts"]._value.text(), "1")
        self.assertEqual(cards["profit"]._value.text(), "1.119.522")
        self.assertEqual(cards["duration"]._value.text(), "1h 11min")

    def test_duplicate_cancelled_keeps_single_hunt(self) -> None:
        self.window.importer.import_paths([SAMPLE_HUNT_PATH])
        results = self.window.importer.import_paths([SAMPLE_HUNT_PATH])
        self.assertEqual(results[0].status, ImportStatus.DUPLICATE)
        self.assertEqual(self.service.count_hunts(), 1)

    def test_duplicate_confirmed_imports_again(self) -> None:
        self.window.importer.import_paths([SAMPLE_HUNT_PATH])
        self.window.importer.confirm_duplicate = lambda result: True
        results = self.window.importer.import_paths([SAMPLE_HUNT_PATH])
        self.assertEqual(results[0].status, ImportStatus.IMPORTED)
        self.assertEqual(self.service.count_hunts(), 2)

    def test_details_dialog(self) -> None:
        hunt_id = self.service.import_file(SAMPLE_HUNT_PATH).hunt_id
        dialog = self.window.hunts_page.open_hunt(hunt_id)
        self.assertIsNotNone(dialog)
        tabs = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
        self.assertEqual(tabs, ["Resumo", "Enemies (3)", "Drops (2)", "Supplies (1)",
                                "Gráficos", "JSON Original"])
        drops_table = dialog.tabs.widget(2).table
        self.assertEqual(drops_table.model().index(0, 0).data(), "metal scraps")  # maior valor
        json_text = dialog.tabs.widget(5).editor.toPlainText()
        self.assertIn('"Session ID": 1080', json_text)
        dialog.close()

    def test_paste_flow_imports_and_saves_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.window.importer.paste_save_dir = Path(tmp)
            result = self.window.importer.import_pasted(SAMPLE_HUNT_PATH.read_text("utf-8"))
            self.assertEqual(result.status, ImportStatus.IMPORTED)
            self.assertTrue(result.saved_path.exists())
            self.assertEqual(result.saved_path.parent, Path(tmp))
            self.assertIs(self.window.stack.currentWidget(), self.window.hunts_page)
            self.assertEqual(len(self.window.hunts_page._table.selected_records()), 1)
            self.assertIn("JSON salvo em", self.window.statusBar().currentMessage())

    def test_paste_dialog_validation(self) -> None:
        dialog = PasteJsonDialog(Path("imports"), self.window)
        self.assertFalse(dialog.import_button.isEnabled())
        dialog.set_text("{ quebrado")
        self.assertFalse(dialog.import_button.isEnabled())
        self.assertEqual(dialog.status.text(), "JSON inválido.")
        dialog.set_text('{"Drops": []}')
        self.assertEqual(dialog.status.text(),
                         "O arquivo não possui uma sessão válida do Analyzer.")
        dialog.set_text(SAMPLE_HUNT_PATH.read_text("utf-8"))
        self.assertTrue(dialog.import_button.isEnabled())
        self.assertIn("Hunt 1080", dialog.status.text())
        self.assertIn("Royalzxd", dialog.status.text())
        dialog.deleteLater()

    def test_all_pages_render(self) -> None:
        self.service.import_file(SAMPLE_HUNT_PATH)
        for key in ("dashboard", "hunts", "reports", "items", "settings"):
            self.window.show_page(key)
            self.assertIs(self.window.stack.currentWidget(), self.window.pages[key])
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
