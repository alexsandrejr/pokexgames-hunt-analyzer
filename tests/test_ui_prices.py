"""Página de Preços (plataforma offscreen)."""

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.services.hunt_service import HuntService  # noqa: E402
from app.services.statistics_service import StatisticsService  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.prices.price_dialog import PriceDialog  # noqa: E402
from app.ui.theme import apply_theme  # noqa: E402
from tests.helpers import FIXTURES_DIR, memory_database  # noqa: E402

SAMPLE_TSV_PATH = FIXTURES_DIR / "sample_hunt.tsv"


class PricesPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.database = memory_database()
        self.service = HuntService(self.database)
        self.hunt_id = self.service.import_file(SAMPLE_TSV_PATH).hunt_id
        self.window = MainWindow(self.service, StatisticsService(self.database), Path("mem.db"))
        self.window.show()
        self.window.show_page("prices")
        self.page = self.window.pages["prices"]

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.database.dispose()

    def test_lists_items_and_recalculates_hunts(self) -> None:
        self.assertIs(self.window.stack.currentWidget(), self.page)
        self.assertEqual(self.page._table.visible_row_count(), 34)  # 16 drops + 18 supplies

        self.page.set_price("Healing Elixir", 10000)
        self.assertEqual(self.service.get_hunt_details(self.hunt_id).profit, 2371504 - 60000)
        [selected] = self.page._table.selected_records()
        self.assertEqual((selected.name, selected.custom_price), ("Healing Elixir", 10000))
        self.assertTrue(self.page._clear_button.isEnabled())

        self.page.only_custom.setChecked(True)
        self.assertEqual(self.page._table.visible_row_count(), 1)

        self.window.show_page("hunts")
        profit = self.window.hunts_page._table.model().index(0, 6).data()
        self.assertEqual(profit, "2.311.504")

        self.window.show_page("prices")
        self.page.clear_prices(["Healing Elixir"])
        self.assertEqual(self.service.get_hunt_details(self.hunt_id).profit, 2371504)
        self.assertEqual(self.page._table.visible_row_count(), 0)  # "somente personalizados"

    def test_dialog_parses_game_notation(self) -> None:
        items = self.page._service.list_items()
        spike = next(item for item in items if item.name == "turtle spike")
        dialog = PriceDialog(items, spike)
        self.assertEqual(dialog.item_name(), "turtle spike")
        self.assertEqual(dialog.price(), 8000)  # preenchido com o preço atual
        self.assertIn("Preço do Analyzer", dialog.info.text())

        dialog.price_edit.setText("1,2kk")
        self.assertEqual(dialog.price(), 1_200_000)
        self.assertTrue(dialog.save_button.isEnabled())

        dialog.price_edit.setText("-5")
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.price_edit.setText("10")
        dialog.name_combo.setEditText("Item Novo")
        self.assertTrue(dialog.save_button.isEnabled())
        self.assertIn("ainda não visto", dialog.info.text())
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
