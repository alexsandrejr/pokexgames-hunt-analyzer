"""Relatório de um item (drop/supply) ou inimigo sobre as Hunts filtradas."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.dto import FilterOptions
from app.services.entity_report import EntityHuntRow, EntityKind, EntityReport
from app.services.export_documents import entity_document
from app.services.export_service import ExportDocument
from app.services.hunt_service import HuntService
from app.services.rates import rate_per_hour
from app.services.statistics_service import StatisticsService
from app.ui.charts.charts import ChartPoint, HuntSeriesChart
from app.ui.filters.filter_controller import FilterController
from app.ui.widgets.cards import ResponsiveGrid, StatCard
from app.ui.widgets.combos import searchable_combo, set_combo_options
from app.ui.widgets.export_button import ExportButton
from app.ui.widgets.page import PAGE_MARGINS, EmptyState, PageHeader
from app.ui.widgets.record_table import Column, RecordTable
from app.utils.formatters import (
    format_datetime_short,
    format_duration,
    format_money,
    format_number,
    format_percent,
    format_text,
)

ROW_HEIGHT = 34


def _row_label(row: EntityHuntRow | None) -> str:
    if row is None:
        return ""
    return f"Hunt {format_text(row.session_id)} · {format_datetime_short(row.start_datetime)}"


def _options_for(kind: EntityKind, options: FilterOptions) -> list[str]:
    return {EntityKind.DROPS: options.drop_items, EntityKind.SUPPLIES: options.supply_items,
            EntityKind.ENEMIES: options.enemies}[kind]


def _hunt_columns(kind: EntityKind) -> list[Column[EntityHuntRow]]:
    columns: list[Column[EntityHuntRow]] = [
        Column("Data", lambda r: r.start_datetime, format_datetime_short, fit_contents=True),
        Column("Sessão", lambda r: r.session_id, format_text, numeric=True),
        Column("Duração", lambda r: r.duration_seconds, format_duration, numeric=True),
        Column("Quantidade", lambda r: r.quantity, format_number, numeric=True),
        Column("Por hora", lambda r: rate_per_hour(r.quantity, r.duration_seconds),
               format_number, numeric=True),
    ]
    if kind.has_value:
        columns.append(Column("Valor", lambda r: r.value, format_money, numeric=True))
    return columns


class EntityReportPage(QWidget):
    def __init__(self, title: str, subtitle: str, kinds: Sequence[EntityKind],
                 hunts: HuntService, statistics: StatisticsService,
                 filters: FilterController, open_hunt: Callable[[int], object],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kinds = list(kinds)
        self._hunts = hunts
        self._statistics = statistics
        self._filters = filters
        self._options = FilterOptions()
        self.report: EntityReport | None = None

        self._header = PageHeader(title, subtitle)
        self.export_button = ExportButton(self._export_document)
        self.export_button.setEnabled(False)
        self._header.add_action(self.export_button)

        self.kind_combo = QComboBox()
        for kind in self._kinds:
            self.kind_combo.addItem(kind.label + "s", kind)
        self.kind_combo.setVisible(len(self._kinds) > 1)
        self.kind_combo.currentIndexChanged.connect(self._reload_names)
        noun = "inimigo" if self._kinds == [EntityKind.ENEMIES] else "item"
        self.name_combo = searchable_combo(f"Escolha ou digite o {noun}…")
        self.name_combo.setMinimumWidth(280)
        self.name_combo.lineEdit().returnPressed.connect(self.analyze)
        self.name_combo.activated.connect(lambda _index: self.analyze())
        analyze_button = QPushButton("Analisar")
        analyze_button.setObjectName("PrimaryButton")
        analyze_button.clicked.connect(self.analyze)

        selector = QHBoxLayout()
        selector.setSpacing(8)
        selector.addWidget(self.kind_combo)
        selector.addWidget(self.name_combo, 1)
        selector.addWidget(analyze_button)

        self._cards: dict[str, StatCard] = {}
        self._chart = HuntSeriesChart("Quantidade por Hunt", format_number)
        self._chart.point_activated.connect(open_hunt)
        # Drops e supplies têm as mesmas colunas; inimigos ficam numa página própria.
        self._table = RecordTable(_hunt_columns(self._kinds[0]))
        self._table.doubleClicked.connect(
            lambda index: open_hunt(self._table.record_at(index).hunt_id))
        self._table_title = QLabel(objectName="SectionTitle")
        self._cards_grid = QVBoxLayout()

        results = QWidget()
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setSpacing(14)
        results_layout.addLayout(self._cards_grid)
        results_layout.addWidget(self._chart)
        results_layout.addWidget(self._table_title)
        results_layout.addWidget(self._table)

        self._empty = EmptyState("Nenhum item selecionado", "")
        self._stack = QStackedWidget()
        self._stack.addWidget(self._empty)
        self._stack.addWidget(results)

        # O painel de filtros compartilhado é inserido aqui pela janela principal.
        self.filter_slot = QVBoxLayout()

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.setSpacing(14)
        layout.addWidget(self._header)
        layout.addLayout(self.filter_slot)
        layout.addLayout(selector)
        layout.addWidget(self._stack)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self._show_empty(f"Escolha um {noun} acima para ver quantidade total, médias, "
                         "presença nas Hunts e o histórico.")

    @property
    def kind(self) -> EntityKind:
        return self.kind_combo.currentData()

    # ---------------------------------------------------------------- dados

    def refresh(self) -> None:
        self._options = self._hunts.filter_options()
        self._reload_names()
        if self.report is not None:
            self.analyze(self.report.name, self.report.kind)

    def _reload_names(self) -> None:
        set_combo_options(self.name_combo, _options_for(self.kind, self._options))

    def analyze(self, name: str | None = None, kind: EntityKind | None = None) -> None:
        if kind is not None and kind != self.kind:
            self.kind_combo.setCurrentIndex(self.kind_combo.findData(kind))
        name = (name if isinstance(name, str) else self.name_combo.currentText()).strip()
        if not name:
            return
        self.name_combo.setEditText(name)
        self.report = self._statistics.entity_report(self.kind, name, self._filters.current)
        self._show_report(self.report)

    # ------------------------------------------------------------- exibição

    def _show_empty(self, message: str, title: str = "Nenhum item selecionado") -> None:
        self._empty.set_text(title, message)
        self._stack.setCurrentIndex(0)
        self.export_button.setEnabled(False)

    def _show_report(self, report: EntityReport) -> None:
        if report.hunt_count == 0:
            self._show_empty("Nenhuma Hunt corresponde aos filtros atuais.", "Sem Hunts")
            return
        if report.present_count == 0:
            self._show_empty(
                f"“{report.name}” não aparece em nenhuma das {report.hunt_count} Hunts "
                "filtradas. Confira o nome ou ajuste os filtros.", "Nada encontrado")
            return

        self._build_cards(report)
        is_enemy = report.kind is EntityKind.ENEMIES
        self._chart.title.setText(f"{report.name} por Hunt")
        self._chart.set_points([
            ChartPoint(row.hunt_id,
                       row.start_datetime.strftime("%d/%m") if row.start_datetime else "—",
                       row.quantity, _row_label(row))
            for row in report.rows
        ], reference=report.average_per_hunt, subtitle=self._chart_subtitle(report))
        self._table.set_records(report.present_rows)
        self._table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        self._table.setFixedHeight(44 + ROW_HEIGHT * min(12, max(3, report.present_count)))
        self._table_title.setText(
            f"Hunts em que {'foi derrotado' if is_enemy else 'apareceu'} ({report.present_count})")
        self._stack.setCurrentIndex(1)
        self.export_button.setEnabled(True)

    @staticmethod
    def _chart_subtitle(report: EntityReport) -> str:
        """Mesma média dos cards (só Hunts em que apareceu); ausências explicitadas."""
        text = (f"Média quando aparece {format_number(report.average_per_hunt)}  ·  "
                f"Máx. {format_number(report.max_row.quantity)}")
        absent = report.hunt_count - report.present_count
        if absent:
            text += f"  ·  ausente em {absent} de {report.hunt_count} Hunts (barras vazias)"
        return text

    def _build_cards(self, report: EntityReport) -> None:
        is_enemy = report.kind is EntityKind.ENEMIES
        presence = (f"{format_number(report.present_count)} de "
                    f"{format_number(report.hunt_count)}")
        specs: list[tuple[str, str, str]] = [
            ("Total derrotado" if is_enemy else "Quantidade total",
             format_number(report.total_quantity), ""),
        ]
        if report.kind.has_value:
            specs.append(("Valor total", format_money(report.total_value),
                          f"{format_money(report.value_per_hour)} por hora"))
        specs += [
            ("Hunts", presence, f"Presença: {format_percent(report.presence_ratio)}"),
            ("Média por Hunt", format_number(report.average_per_hunt),
             "Nas Hunts em que apareceu"),
            ("Média por hora", format_number(report.per_hour), "Nas Hunts em que apareceu"),
        ]
        if report.kind.has_value:
            specs.append(("Valor médio por Hunt", format_money(report.average_value_per_hunt),
                          "Nas Hunts em que apareceu"))
        specs += [
            ("Maior quantidade", format_number(report.max_row.quantity), _row_label(report.max_row)),
            ("Menor quantidade", format_number(report.min_row.quantity), _row_label(report.min_row)),
        ]
        while self._cards_grid.count():
            widget = self._cards_grid.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        self._cards = {title: StatCard(title, value, hint) for title, value, hint in specs}
        self._cards_grid.addWidget(ResponsiveGrid(list(self._cards.values())))

    def _export_document(self) -> ExportDocument | None:
        if self.report is None:
            return None
        return entity_document(self.report, self._filters.current.describe())
