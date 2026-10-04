"""Página Bosses: uma aba por tipo de boss (Rifts, Energia Vermelha, Energia Azul, Terrors).

Cada aba tem um "Resumo" (cards, gráficos, bosses, drops e dano por elemento) e as
"Sessões" (a mesma lista da página Hunts, restrita à categoria). Importar com uma
aba aberta grava as sessões naquela categoria (ver ``MainWindow._import_category``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QTabWidget, QVBoxLayout, QWidget

from app.services.categories import BOSS_CATEGORIES, Category
from app.services.dto import RankedEntry
from app.services.filters import EMPTY_FILTER
from app.services.hunt_service import HuntService
from app.services.rates import rate_per_second
from app.services.statistics_service import ElementDamage, OverviewStats, StatisticsService
from app.ui.charts.charts import HuntSeriesChart
from app.ui.dashboard.dashboard_widget import ChartSpec, chart_points, chronological
from app.ui.filters.filter_controller import FilterController
from app.ui.hunts.hunt_list import IMPORT_HINT, HuntListView, ListTexts, import_buttons
from app.ui.import_controller import ImportController
from app.ui.widgets.cards import ResponsiveGrid, StatCard
from app.ui.widgets.page import PAGE_MARGINS, PageHeader
from app.ui.widgets.record_table import Column, RecordTable
from app.utils.formatters import (
    format_date,
    format_duration,
    format_duration_long,
    format_money,
    format_number,
    format_percent,
)

RANKING_LIMIT = 25
ROW_HEIGHT = 34
HEADER_HEIGHT = 40
MIN_SESSIONS_FOR_CHARTS = 2

BOSS_CHARTS: tuple[ChartSpec, ...] = (
    ChartSpec("Profit por sessão", "profit", format_money),
    ChartSpec("Profit/h por sessão", "profit_per_hour", format_money),
    ChartSpec("Duração das sessões", "duration_seconds", format_duration, duration_axis=True),
    ChartSpec("Damage dealt por segundo", "damage_dealt_per_second", format_number),
)

ENEMY_COLUMNS: list[Column[RankedEntry]] = [
    Column("Boss / inimigo", lambda e: e.name),
    Column("Derrotados", lambda e: e.quantity, format_number, numeric=True),
    Column("Sessões", lambda e: e.hunt_count, format_number, numeric=True),
    Column("Média por sessão", lambda e: e.average_per_hunt, format_number, numeric=True),
]

DROP_COLUMNS: list[Column[RankedEntry]] = [
    Column("Item", lambda e: e.name),
    Column("Quantidade", lambda e: e.quantity, format_number, numeric=True),
    Column("Valor total", lambda e: e.value, format_money, numeric=True),
    Column("Sessões", lambda e: e.hunt_count, format_number, numeric=True),
]

ELEMENT_COLUMNS: list[Column[ElementDamage]] = [
    Column("Elemento", lambda e: e.element),
    Column("Causado", lambda e: e.dealt, format_number, numeric=True),
    Column("% causado", lambda e: e.dealt_share, format_percent, numeric=True),
    Column("Recebido", lambda e: e.taken, format_number, numeric=True),
    Column("% recebido", lambda e: e.taken_share, format_percent, numeric=True),
]


def session_texts(category: Category) -> ListTexts:
    return ListTexts("sessão", "sessões", f"Nenhuma sessão de {category.plural}",
                     f"Importe com esta aba aberta, ou selecione uma sessão em Hunts e use "
                     f"“Mover” → {category.plural}. {IMPORT_HINT}")


def _ranking_table(columns: list[Column], sort_column: int) -> RecordTable:
    table = RecordTable(columns)
    # Largura mínima explícita: senão a dica de tamanho das colunas alarga a página
    # inteira e a grade responsiva nunca cai para menos colunas.
    table.setMinimumWidth(260)
    table.sortByColumn(sort_column, Qt.SortOrder.DescendingOrder)
    return table


def _fit_rows(table: RecordTable, rows: int) -> None:
    table.setFixedHeight(HEADER_HEIGHT + ROW_HEIGHT * min(8, max(3, rows)) + 4)


def _titled(title: str, widget: QWidget) -> QWidget:
    section = QWidget()
    layout = QVBoxLayout(section)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.addWidget(QLabel(title, objectName="SectionTitle"))
    layout.addWidget(widget)
    layout.addStretch(1)  # tabelas de alturas diferentes alinhadas pelo topo
    return section


class BossSummaryView(QScrollArea):
    """Cards, gráficos e tabelas de uma categoria de boss, sobre as sessões filtradas."""

    def __init__(self, category: Category, hunts: HuntService, statistics: StatisticsService,
                 filters: FilterController, open_hunt: Callable[[int], object],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.category = category
        self._hunts = hunts
        self._statistics = statistics
        self._filters = filters

        self.cards = {
            "sessions": StatCard("Sessões"),
            "kills": StatCard("Kills"),
            "duration": StatCard("Tempo total"),
            "profit": StatCard("Profit"),
            "profit_h": StatCard("Profit/h"),
            "supplies": StatCard("Supplies"),
            "experience": StatCard("Experience"),
            "damage": StatCard("Damage dealt/s"),
        }
        self._empty_hint = QLabel(objectName="MutedLabel")
        self._empty_hint.setWordWrap(True)

        self.charts: list[tuple[ChartSpec, HuntSeriesChart]] = []
        for spec in BOSS_CHARTS:
            chart = HuntSeriesChart(spec.title, spec.formatter, spec.duration_axis)
            chart.point_activated.connect(open_hunt)
            self.charts.append((spec, chart))
        self._charts_section = _titled(
            "Evolução por sessão",
            ResponsiveGrid([chart for _spec, chart in self.charts], min_item_width=440,
                           max_columns=2))

        self.enemies = _ranking_table(ENEMY_COLUMNS, 1)
        self.drops = _ranking_table(DROP_COLUMNS, 2)
        self.elements = _ranking_table(ELEMENT_COLUMNS, 1)
        self._tables_section = ResponsiveGrid([
            _titled("Bosses derrotados", self.enemies),
            _titled(f"Drops mais valiosos (top {RANKING_LIMIT})", self.drops),
            _titled("Dano por elemento", self.elements),
        ], min_item_width=380, max_columns=3)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(18)
        layout.addWidget(ResponsiveGrid(list(self.cards.values())))
        layout.addWidget(self._empty_hint)
        layout.addWidget(self._tables_section)
        layout.addWidget(self._charts_section)
        layout.addStretch(1)
        self.setWidgetResizable(True)
        self.setWidget(content)

    def refresh(self) -> None:
        hunt_filter = self._filters.current.scoped(self.category)
        stats = self._statistics.overview(hunt_filter)
        self._show_cards(stats)

        has_sessions = stats.hunt_count > 0
        self._tables_section.setVisible(has_sessions)
        if has_sessions:
            for table, rows in (
                (self.enemies, self._statistics.top_enemies(hunt_filter, RANKING_LIMIT)),
                (self.drops, self._statistics.top_drops(hunt_filter, RANKING_LIMIT)),
                (self.elements, self._statistics.damage_by_element(hunt_filter)),
            ):
                table.set_records(rows)
                _fit_rows(table, len(rows))

        enough = stats.hunt_count >= MIN_SESSIONS_FOR_CHARTS
        self._charts_section.setVisible(enough)
        if enough:
            sessions = chronological(self._hunts.list_hunts(hunt_filter))
            for spec, chart in self.charts:
                chart.set_points(chart_points(sessions, spec.attribute, "Sessão"))

        if not has_sessions:
            self._empty_hint.setText(
                "Nenhuma sessão corresponde aos filtros." if not self._filters.current.is_empty
                else f"Nenhuma sessão de {self.category.plural} ainda. Importe com esta aba "
                     f"aberta, ou mova uma sessão da página Hunts com “Mover”.")
        elif not enough:
            self._empty_hint.setText("Os gráficos aparecem a partir de 2 sessões.")
        self._empty_hint.setVisible(not enough)

    def _show_cards(self, stats: OverviewStats) -> None:
        c = self.cards
        c["sessions"].set_value(format_number(stats.hunt_count),
                                f"Última: {format_date(stats.last_start)}")
        c["kills"].set_value(format_number(stats.total_kills),
                             f"Média por sessão: {format_number(stats.average_kills)}")
        c["duration"].set_value(format_duration_long(stats.total_duration_seconds),
                                f"Por kill: {format_duration(stats.duration_per_kill)}")
        c["profit"].set_value(format_money(stats.total_profit),
                              f"Por kill: {format_money(stats.profit_per_kill)}")
        c["profit_h"].set_value(format_money(stats.profit_per_total_hour),
                                f"Média das sessões: {format_money(stats.average_profit_per_hour)}")
        c["supplies"].set_value(format_money(stats.total_supplies),
                                f"Por kill: {format_money(stats.supplies_per_kill)}")
        c["experience"].set_value(format_number(stats.total_experience),
                                  f"Por kill: {format_number(stats.experience_per_kill)}")
        taken = rate_per_second(stats.total_damage_taken, stats.total_duration_seconds)
        c["damage"].set_value(format_number(stats.average_damage_dealt_per_second),
                              f"Damage taken/s: {format_number(taken)}")


class BossCategoryView(QWidget):
    """Aba de uma categoria: "Resumo" e "Sessões".

    O conteúdo (gráficos, tabelas) só é montado na primeira vez que a aba é exibida,
    para não atrasar a abertura da janela com quatro abas que talvez nem sejam usadas.
    """

    def __init__(self, category: Category, hunts: HuntService, statistics: StatisticsService,
                 filters: FilterController, open_hunt: Callable[[int], object],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.category = category
        self._services = (hunts, statistics, filters, open_hunt)
        self._summary: BossSummaryView | None = None
        self._sessions: HuntListView | None = None
        self.tabs = QTabWidget()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 12, 0, 0)

    def _ensure_built(self) -> None:
        if self._summary is not None:
            return
        hunts, statistics, filters, open_hunt = self._services
        self._summary = BossSummaryView(self.category, hunts, statistics, filters, open_hunt)
        self._sessions = HuntListView(hunts, filters, self.category,
                                      session_texts(self.category))
        sessions_page = QWidget()
        sessions_layout = QVBoxLayout(sessions_page)
        sessions_layout.setContentsMargins(16, 16, 16, 16)
        sessions_layout.addWidget(self._sessions)

        self.tabs.addTab(self._summary, "Resumo")
        self.tabs.addTab(sessions_page, "Sessões")
        self.tabs.currentChanged.connect(lambda _index: self.refresh())
        self._layout.addWidget(self.tabs)
        self.tabs.show()  # sem isso, a aba montada agora só aparece no próximo ciclo de eventos

    @property
    def summary(self) -> BossSummaryView:
        self._ensure_built()
        return self._summary

    @property
    def sessions(self) -> HuntListView:
        self._ensure_built()
        return self._sessions

    def refresh(self) -> None:
        self._ensure_built()
        if self.tabs.currentIndex() == 0:
            self.summary.refresh()
        else:
            self.sessions.refresh()

    def show_sessions(self, hunt_ids: Iterable[int] = ()) -> None:
        """Abre "Sessões" com as sessões informadas selecionadas (ex.: recém-importadas)."""
        self._ensure_built()
        self.tabs.setCurrentIndex(1)
        self.sessions.refresh()
        self.sessions.select_hunts(hunt_ids)


class BossesPage(QWidget):
    def __init__(self, hunts: HuntService, statistics: StatisticsService,
                 importer: ImportController, filters: FilterController,
                 open_hunt: Callable[[int], object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hunts = hunts

        self._header = PageHeader(
            "Bosses", "Importar com uma aba aberta grava as sessões naquele tipo de boss")
        for button in import_buttons(importer):
            self._header.add_action(button)

        self.views = {category: BossCategoryView(category, hunts, statistics, filters, open_hunt)
                      for category in BOSS_CATEGORIES}
        self.tabs = QTabWidget(objectName="CategoryTabs")
        for category, view in self.views.items():
            self.tabs.addTab(view, category.plural)
        self.tabs.currentChanged.connect(lambda _index: self.refresh())

        # O painel de filtros compartilhado é inserido aqui pela janela principal.
        self.filter_slot = QVBoxLayout()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.setSpacing(16)
        layout.addWidget(self._header)
        layout.addLayout(self.filter_slot)
        layout.addWidget(self.tabs, 1)

    @property
    def current_view(self) -> BossCategoryView:
        return self.tabs.currentWidget()

    @property
    def current_category(self) -> Category:
        return self.current_view.category

    def refresh(self) -> None:
        for index, category in enumerate(self.views):
            count = self._hunts.count_hunts(EMPTY_FILTER.scoped(category))
            self.tabs.setTabText(index, f"{category.plural} ({count})" if count
                                 else category.plural)
        self.current_view.refresh()

    def show_category(self, category: Category, hunt_ids: Iterable[int] = ()) -> None:
        """Abre a aba da categoria em "Sessões", selecionando as sessões informadas."""
        view = self.views[category]
        self.tabs.blockSignals(True)
        self.tabs.setCurrentWidget(view)
        self.tabs.blockSignals(False)
        view.show_sessions(hunt_ids)
