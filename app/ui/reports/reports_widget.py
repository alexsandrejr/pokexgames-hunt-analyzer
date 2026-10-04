"""Página Relatórios: estatísticas agregadas das Hunts filtradas."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QTabWidget, QVBoxLayout, QWidget

from app.services.dto import RankedEntry
from app.services.export_documents import report_document
from app.services.export_service import ExportDocument
from app.services.filters import HuntFilter
from app.services.statistics_service import (
    MetricStats,
    StatisticsService,
)
from app.ui.filters.filter_controller import FilterController
from app.ui.widgets.cards import ResponsiveGrid, StatCard
from app.ui.widgets.category_scope import CategoryScopeCombo
from app.ui.widgets.export_button import ExportButton
from app.ui.widgets.page import PAGE_MARGINS, PageHeader
from app.ui.widgets.record_table import Column, RecordTable
from app.utils.formatters import (
    PLACEHOLDER,
    ValueKind,
    format_date,
    format_duration,
    format_duration_long,
    format_money,
    format_number,
    format_value,
)

RANKING_LIMIT = 25
ROW_HEIGHT = 34
HEADER_HEIGHT = 40

def format_metric(metric: MetricStats, value: float | None) -> str:
    return format_value(metric.kind, value)


def format_metric_total(metric: MetricStats) -> str:
    if metric.kind is ValueKind.DURATION:
        return format_duration_long(metric.total)
    return format_metric(metric, metric.total)


def format_rate(metric: MetricStats, value: float | None) -> str:
    if value is None or metric.rate_unit is None:
        return PLACEHOLDER
    return f"{format_metric(metric, value)} {metric.rate_unit.value}"


METRIC_COLUMNS: list[Column[MetricStats]] = [
    Column("Métrica", lambda m: m.label),
    Column("Total", lambda m: m, format_metric_total, numeric=True),
    Column("Média por Hunt", lambda m: m, lambda m: format_metric(m, m.average), numeric=True),
    Column("Mínimo", lambda m: m, lambda m: format_metric(m, m.minimum), numeric=True),
    Column("Máximo", lambda m: m, lambda m: format_metric(m, m.maximum), numeric=True),
    Column("Média das taxas", lambda m: m, lambda m: format_rate(m, m.average_rate),
           numeric=True, tooltip="Média simples das taxas (/h ou /s) de cada Hunt"),
    Column("Total ÷ tempo total", lambda m: m,
           lambda m: format_rate(m, m.rate_over_total_time), numeric=True,
           tooltip="Total dividido pelo tempo total (ponderado pela duração)"),
]

ITEM_RANK_COLUMNS: list[Column[RankedEntry]] = [
    Column("Item", lambda e: e.name),
    Column("Quantidade", lambda e: e.quantity, format_number, numeric=True),
    Column("Valor total", lambda e: e.value, format_money, numeric=True),
    Column("Hunts", lambda e: e.hunt_count, format_number, numeric=True),
    Column("Média por Hunt", lambda e: e.average_per_hunt, format_number, numeric=True),
]

ENEMY_RANK_COLUMNS: list[Column[RankedEntry]] = [
    Column("Inimigo", lambda e: e.name),
    Column("Derrotados", lambda e: e.quantity, format_number, numeric=True),
    Column("Hunts", lambda e: e.hunt_count, format_number, numeric=True),
    Column("Média por Hunt", lambda e: e.average_per_hunt, format_number, numeric=True),
]


def _fixed_height_table(columns: list[Column], rows: int,
                        sort_column: int | None = None) -> RecordTable:
    table = RecordTable(columns)
    table.setFixedHeight(HEADER_HEIGHT + ROW_HEIGHT * rows + 4)
    if sort_column is None:
        table.set_sortable(False)
    else:
        table.sortByColumn(sort_column, Qt.SortOrder.DescendingOrder)
    return table


class ReportsPage(QWidget):
    def __init__(self, statistics: StatisticsService, filters: FilterController,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._statistics = statistics
        self._filters = filters

        self._header = PageHeader("Relatórios", "Estatísticas agregadas das Hunts filtradas")
        self.scope = CategoryScopeCombo()
        self.scope.currentIndexChanged.connect(self.refresh)
        self.export_button = ExportButton(self._export_document)
        self._header.add_action(self.scope)
        self._header.add_action(self.export_button)
        self._cards = {
            "hunts": StatCard("Hunts analisadas"),
            "duration": StatCard("Tempo total"),
            "profit": StatCard("Profit total"),
            "profit_h": StatCard("Profit/h"),
        }

        self._metrics = _fixed_height_table(METRIC_COLUMNS, 8)
        note = QLabel(
            "“Média das taxas” é a média simples dos valores por hora (ou por segundo) de "
            "cada Hunt: todas pesam igual. “Total ÷ tempo total” divide a soma pelo tempo "
            "somado, então Hunts mais longas pesam mais.",
            objectName="CardHint",
        )
        note.setWordWrap(True)

        # Rankings: por valor total (itens) ou quantidade derrotada (inimigos).
        self._drops = _fixed_height_table(ITEM_RANK_COLUMNS, 10, sort_column=2)
        self._supplies = _fixed_height_table(ITEM_RANK_COLUMNS, 10, sort_column=2)
        self._enemies = _fixed_height_table(ENEMY_RANK_COLUMNS, 10, sort_column=1)
        self._rank_tabs = QTabWidget()
        self._rank_tabs.addTab(self._wrap(self._drops), "Drops")
        self._rank_tabs.addTab(self._wrap(self._supplies), "Supplies")
        self._rank_tabs.addTab(self._wrap(self._enemies), "Inimigos")

        # O painel de filtros compartilhado é inserido aqui pela janela principal.
        self.filter_slot = QVBoxLayout()

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.setSpacing(14)
        layout.addWidget(self._header)
        layout.addLayout(self.filter_slot)
        layout.addWidget(ResponsiveGrid(list(self._cards.values())))
        layout.addSpacing(6)
        layout.addWidget(QLabel("Métricas", objectName="SectionTitle"))
        layout.addWidget(self._metrics)
        layout.addWidget(note)
        layout.addSpacing(6)
        layout.addWidget(QLabel(f"Mais frequentes (top {RANKING_LIMIT})",
                                objectName="SectionTitle"))
        layout.addWidget(self._rank_tabs)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    @staticmethod
    def _wrap(table: RecordTable) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(table)
        return widget

    def _filter(self) -> HuntFilter:
        return self._filters.current.scoped(*self.scope.categories())

    def _export_document(self) -> ExportDocument:
        hunt_filter = self._filter()
        return report_document(
            self._statistics.overview(hunt_filter),
            self._statistics.metric_breakdown(hunt_filter),
            self._statistics.top_drops(hunt_filter, RANKING_LIMIT),
            self._statistics.top_supplies(hunt_filter, RANKING_LIMIT),
            self._statistics.top_enemies(hunt_filter, RANKING_LIMIT),
            [self.scope.describe(), *hunt_filter.describe()],
        )

    def refresh(self) -> None:
        hunt_filter = self._filter()
        overview = self._statistics.overview(hunt_filter)
        scope = "das Hunts filtradas" if not hunt_filter.is_empty else "de todas as Hunts"
        period = (f" · {format_date(overview.first_start)} a {format_date(overview.last_start)}"
                  if overview.first_start else "")
        self._header.set_subtitle(f"Estatísticas agregadas {scope}{period}")

        self._cards["hunts"].set_value(format_number(overview.hunt_count))
        self._cards["duration"].set_value(
            format_duration_long(overview.total_duration_seconds),
            f"Média por Hunt: {format_duration(overview.average_duration_seconds)}")
        self._cards["profit"].set_value(
            format_money(overview.total_profit),
            f"Média por Hunt: {format_money(overview.average_profit)}")
        self._cards["profit_h"].set_value(
            format_money(overview.profit_per_total_hour),
            f"Média das Hunts: {format_money(overview.average_profit_per_hour)}")

        self._metrics.set_records(self._statistics.metric_breakdown(hunt_filter))
        self._drops.set_records(self._statistics.top_drops(hunt_filter, RANKING_LIMIT))
        self._supplies.set_records(self._statistics.top_supplies(hunt_filter, RANKING_LIMIT))
        self._enemies.set_records(self._statistics.top_enemies(hunt_filter, RANKING_LIMIT))

