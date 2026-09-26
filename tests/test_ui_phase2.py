"""Interface da Fase 2: painel de filtros, Dashboard com gráficos, Relatórios."""

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.services.filters import HuntFilter, Metric, MetricCondition, Operator  # noqa: E402
from app.services.hunt_service import HuntService  # noqa: E402
from app.services.statistics_service import StatisticsService  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.theme import apply_theme  # noqa: E402
from tests.helpers import memory_database  # noqa: E402
from tests.test_filters import make_hunt  # noqa: E402


class Phase2UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.database = memory_database()
        self.service = HuntService(self.database)
        for text in (
            make_hunt(1, "2026-09-01 10:00:00", kills=250, profit=800_000,
                      drops={"nightmare ore": 40}),
            make_hunt(2, "2026-09-10 10:00:00", duration=7200, kills=640, profit=2_000_000,
                      drops={"nightmare ore": 80}),
            make_hunt(3, "2026-09-11 10:00:00", player="OutroPlayer", duration=1800,
                      kills=160, profit=-50_000),
        ):
            self.service.import_text(text)
        self.window = MainWindow(self.service, StatisticsService(self.database), Path("m.db"))
        self.window.show()
        self.panel = self.window.filter_panel

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.database.dispose()

    def hunts_table_count(self) -> int:
        self.window.show_page("hunts")
        return self.window.hunts_page._table.visible_row_count()

    def test_panel_moves_to_the_visible_page(self) -> None:
        for key, has_panel in (("dashboard", True), ("hunts", True), ("reports", True),
                               ("items", True), ("enemies", True), ("settings", False)):
            self.window.show_page(key)
            page = self.window.pages[key]
            self.assertEqual(self.panel.isVisibleTo(self.window), has_panel, key)
            if has_panel:
                self.assertTrue(page.isAncestorOf(self.panel), key)

    def test_filter_options_loaded(self) -> None:
        self.window.show_page("hunts")
        players = [self.panel._player.itemText(i) for i in range(self.panel._player.count())]
        self.assertEqual(players, ["OutroPlayer", "Royalzxd"])

    def test_player_filter_through_widgets(self) -> None:
        self.assertEqual(self.hunts_table_count(), 3)
        self.panel._player.setEditText("royal")
        self.assertTrue(self.panel.apply())
        self.assertEqual(self.window.filters.current.player, "royal")
        self.assertEqual(self.hunts_table_count(), 2)
        self.assertIn("(filtradas)", self.window.hunts_page._count_label.text())
        self.assertEqual(self.panel._badge.text(), "1")

        self.panel.clear()
        self.assertTrue(self.window.filters.current.is_empty)
        self.assertEqual(self.hunts_table_count(), 3)

    def test_metric_and_item_filters_through_widgets(self) -> None:
        operator, value = self.panel._metric_inputs[Metric.KILLS_PER_HOUR]
        operator.setCurrentIndex(operator.findData(Operator.GT))
        value.setText("300")
        self.panel.apply()
        # Hunt 1: 250/h; Hunt 2: 640 kills em 2h = 320/h; Hunt 3: 160 em 30min = 320/h.
        self.assertEqual(self.hunts_table_count(), 2)

        value.setText("")
        self.panel._item.name.setEditText("Nightmare Ore")
        self.panel._item.quantity.setText("50")
        self.panel.apply()
        self.assertEqual(self.hunts_table_count(), 1)
        self.assertEqual(self.window.hunts_page._table.source_model.record(0).session_id, 2)

    def test_metric_values_accept_game_notation(self) -> None:
        operator, value = self.panel._metric_inputs[Metric.PROFIT]
        value.setText("1kk")
        self.panel.apply()
        self.assertEqual(self.window.filters.current.metrics,
                         (MetricCondition(Metric.PROFIT, Operator.GE, 1_000_000),))
        duration_op, duration = self.panel._metric_inputs[Metric.DURATION]
        value.setText("")
        duration.setText("1:30")
        self.panel.apply()
        self.assertEqual(self.window.filters.current.metrics[0].value, 5400)

    def test_invalid_value_is_rejected(self) -> None:
        _operator, value = self.panel._metric_inputs[Metric.PROFIT]
        value.setText("muito")
        self.assertFalse(self.panel.apply())
        self.assertTrue(self.window.filters.current.is_empty)
        self.assertIn("Profit", self.panel._error.text())
        self.assertTrue(value.property("invalid"))

    def test_quantity_without_item_is_rejected(self) -> None:
        self.panel._enemy.quantity.setText("10")
        self.assertFalse(self.panel.apply())
        self.assertIn("inimigo", self.panel._error.text())

    def test_dashboard_charts_follow_filter(self) -> None:
        self.window.show_page("dashboard")
        page = self.window.dashboard_page
        self.assertTrue(page._charts_section.isVisibleTo(self.window))
        self.assertEqual(len(page.charts), 8)
        profit_chart = next(chart for spec, chart in page.charts if spec.attribute == "profit")
        self.assertEqual([p.value for p in profit_chart._points], [800_000, 2_000_000, -50_000])
        self.assertEqual(profit_chart._points[0].label, "01/09")

        # Com uma só Hunt, os gráficos somem e o aviso aparece.
        self.window.filters.set_filter(HuntFilter(player="Outro"))
        self.assertFalse(page._charts_section.isVisibleTo(self.window))
        self.assertEqual(page._cards["hunts"]._value.text(), "1")
        self.assertIn("2 Hunts", page._empty_hint.text())

    def test_chart_click_opens_hunt(self) -> None:
        opened: list[int] = []
        self.window.open_hunt = opened.append  # não abre diálogo no teste
        self.window.show_page("dashboard")
        _spec, chart = self.window.dashboard_page.charts[0]
        chart.point_activated.emit(chart._points[1].key)
        self.assertEqual(opened, [chart._points[1].key])

    def test_reports_page(self) -> None:
        self.window.show_page("reports")
        page = self.window.reports_page
        metrics = page._metrics.model()
        self.assertEqual(metrics.rowCount(), 8)
        self.assertEqual(metrics.index(0, 0).data(), "Duração")
        profit_row = next(r for r in range(8) if metrics.index(r, 0).data() == "Profit")
        self.assertEqual(metrics.index(profit_row, 1).data(), "2.750.000")
        self.assertTrue(metrics.index(profit_row, 5).data().endswith("/h"))
        drops = page._drops.model()
        values = [drops.index(r, 2).data() for r in range(drops.rowCount())]
        self.assertEqual(drops.index(0, 0).data(), "metal scraps")  # maior valor total
        self.assertEqual(values, sorted(values, key=lambda v: int(v.replace(".", "")),
                                        reverse=True))
        ore_row = next(r for r in range(drops.rowCount())
                       if drops.index(r, 0).data() == "nightmare ore")
        self.assertEqual(drops.index(ore_row, 1).data(), "120")

        self.window.filters.set_filter(HuntFilter(player="Outro"))
        self.assertEqual(page._cards["hunts"]._value.text(), "1")
        self.assertEqual(page._drops.model().rowCount(), 2)  # drops do JSON de exemplo

    def test_details_charts_tab(self) -> None:
        hunt_id = self.service.list_hunts()[0].id
        dialog = self.window.hunts_page.open_hunt(hunt_id)
        charts_tab = dialog.tabs.widget(4)
        self.assertEqual(dialog.tabs.tabText(4), "Gráficos")
        self.assertGreaterEqual(len(charts_tab.charts), 2)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
