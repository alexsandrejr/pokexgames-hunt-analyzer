"""Página Dashboard: cards e gráficos das Hunts filtradas.

Só a categoria Hunt entra aqui; os bosses têm o seu resumo na página Bosses.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from app.services.categories import Category
from app.services.dto import HuntSummary
from app.services.hunt_service import HuntService
from app.services.statistics_service import OverviewStats, StatisticsService
from app.ui.charts.charts import ChartPoint, HuntSeriesChart
from app.ui.filters.filter_controller import FilterController
from app.ui.widgets.cards import ResponsiveGrid, StatCard
from app.ui.widgets.page import PAGE_MARGINS, PageHeader
from app.utils.formatters import (
    format_date,
    format_datetime_short,
    format_duration,
    format_duration_long,
    format_money,
    format_number,
    format_text,
)

MIN_HUNTS_FOR_CHARTS = 2


@dataclass(frozen=True)
class ChartSpec:
    title: str
    attribute: str  # campo de HuntSummary
    formatter: Callable[[float | None], str]
    duration_axis: bool = False


DASHBOARD_CHARTS: tuple[ChartSpec, ...] = (
    ChartSpec("Profit/h por Hunt", "profit_per_hour", format_money),
    ChartSpec("Kills/h por Hunt", "kills_per_hour", format_number),
    ChartSpec("Profit por Hunt", "profit", format_money),
    ChartSpec("Supplies/h por Hunt", "supplies_per_hour", format_money),
    ChartSpec("Damage dealt por segundo", "damage_dealt_per_second", format_number),
    ChartSpec("Damage taken por segundo", "damage_taken_per_second", format_number),
    ChartSpec("Kills por Hunt", "kills", format_number),
    ChartSpec("Duração das Hunts", "duration_seconds", format_duration, duration_axis=True),
)


def chronological(hunts: Sequence[HuntSummary]) -> list[HuntSummary]:
    """Hunts da mais antiga para a mais recente (sem data vão para o fim)."""
    return sorted(hunts, key=lambda h: (h.start_datetime or datetime.max, h.id))


def chart_points(hunts: Sequence[HuntSummary], attribute: str,
                 noun: str = "Hunt") -> list[ChartPoint]:
    return [
        ChartPoint(
            key=hunt.id,
            label=hunt.start_datetime.strftime("%d/%m") if hunt.start_datetime else "—",
            value=getattr(hunt, attribute),
            title=f"{noun} {format_text(hunt.session_id)} · {format_datetime_short(hunt.start_datetime)}",
        )
        for hunt in hunts
    ]


class DashboardPage(QWidget):
    def __init__(self, hunts: HuntService, statistics: StatisticsService,
                 filters: FilterController, open_hunt: Callable[[int], object],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hunts = hunts
        self._statistics = statistics
        self._filters = filters

        self._header = PageHeader("Dashboard", "Visão geral das Hunts importadas")
        self._cards = {
            "hunts": StatCard("Hunts analisadas"),
            "duration": StatCard("Tempo total"),
            "kills": StatCard("Kills"),
            "profit": StatCard("Profit"),
            "profit_h": StatCard("Profit/h médio"),
            "kills_h": StatCard("Kills/h médio"),
            "supplies": StatCard("Supplies"),
            "raw_gains": StatCard("Raw Gains"),
        }
        self._empty_hint = QLabel(objectName="MutedLabel")
        self._empty_hint.setWordWrap(True)

        self.charts: list[tuple[ChartSpec, HuntSeriesChart]] = []
        for spec in DASHBOARD_CHARTS:
            chart = HuntSeriesChart(spec.title, spec.formatter, spec.duration_axis)
            chart.point_activated.connect(open_hunt)
            self.charts.append((spec, chart))
        self._charts_section = QWidget()
        charts_layout = QVBoxLayout(self._charts_section)
        charts_layout.setContentsMargins(0, 8, 0, 0)
        charts_layout.setSpacing(12)
        charts_title = QLabel("Evolução por Hunt", objectName="SectionTitle")
        charts_hint = QLabel("Hunts em ordem cronológica. A linha horizontal marca a média. "
                             "Clique em uma barra para abrir a Hunt.", objectName="CardHint")
        charts_layout.addWidget(charts_title)
        charts_layout.addWidget(charts_hint)
        charts_layout.addWidget(ResponsiveGrid([chart for _spec, chart in self.charts],
                                               min_item_width=440, max_columns=2))

        # O painel de filtros compartilhado é inserido aqui pela janela principal.
        self.filter_slot = QVBoxLayout()

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.setSpacing(18)
        layout.addWidget(self._header)
        layout.addLayout(self.filter_slot)
        layout.addWidget(ResponsiveGrid(list(self._cards.values())))
        layout.addWidget(self._empty_hint)
        layout.addWidget(self._charts_section)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def refresh(self) -> None:
        hunt_filter = self._filters.current.scoped(Category.HUNT)
        stats = self._statistics.overview(hunt_filter)
        self._show_cards(stats, filtered=not hunt_filter.is_empty)

        enough = stats.hunt_count >= MIN_HUNTS_FOR_CHARTS
        self._charts_section.setVisible(enough)
        if enough:
            hunts = chronological(self._hunts.list_hunts(hunt_filter))
            for spec, chart in self.charts:
                chart.set_points(chart_points(hunts, spec.attribute))

        if stats.hunt_count == 0:
            self._empty_hint.setText(
                "Nenhuma Hunt corresponde aos filtros." if not hunt_filter.is_empty
                else "Nenhuma Hunt importada ainda. Use Hunts → Importar JSON/TSV para começar.")
        elif not enough:
            self._empty_hint.setText("Os gráficos aparecem a partir de 2 Hunts.")
        self._empty_hint.setVisible(not enough)

    def _show_cards(self, stats: OverviewStats, filtered: bool) -> None:
        scope = "Hunts filtradas" if filtered else "todas as Hunts importadas"
        period = (f" · {format_date(stats.first_start)} a {format_date(stats.last_start)}"
                  if stats.first_start else "")
        self._header.set_subtitle(f"Visão geral de {scope}{period}")

        c = self._cards
        c["hunts"].set_value(format_number(stats.hunt_count),
                             f"Última: {format_date(stats.last_start)}")
        c["duration"].set_value(format_duration_long(stats.total_duration_seconds),
                                f"Média por Hunt: {format_duration(stats.average_duration_seconds)}")
        c["kills"].set_value(format_number(stats.total_kills),
                             f"Média por Hunt: {format_number(stats.average_kills)}")
        c["profit"].set_value(format_money(stats.total_profit),
                              f"Média por Hunt: {format_money(stats.average_profit)}")
        c["profit_h"].set_value(format_money(stats.average_profit_per_hour),
                                f"Total ÷ tempo total: {format_money(stats.profit_per_total_hour)}")
        c["kills_h"].set_value(format_number(stats.average_kills_per_hour),
                               f"Total ÷ tempo total: {format_number(stats.kills_per_total_hour)}")
        c["supplies"].set_value(format_money(stats.total_supplies),
                                f"Por hora: {format_money(stats.supplies_per_total_hour)}")
        c["raw_gains"].set_value(format_money(stats.total_raw_gains),
                                 f"Por hora: {format_money(stats.raw_gains_per_total_hour)}")
