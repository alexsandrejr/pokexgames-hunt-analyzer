"""Abas de listas da tela de detalhes: Enemies, Drops, Supplies e JSON Original."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.database.models import Drop, EnemyDefeated, Supply
from app.ui.charts.charts import ChartPoint, RankedBarChart
from app.ui.icons import icon
from app.ui.theme import COLORS, monospace_font
from app.ui.widgets.page import EmptyState
from app.ui.widgets.record_table import Column, RecordTable
from app.utils.formatters import format_bool, format_money, format_number, pretty_json

TAB_MARGINS = (16, 16, 16, 16)

ENEMY_COLUMNS: list[Column[EnemyDefeated]] = [
    Column("Enemy", lambda e: e.enemy),
    Column("Count", lambda e: e.count, format_number, numeric=True),
    Column("Player", lambda e: e.player),
    Column("Rare", lambda e: e.rare, format_bool, centered=True),
    Column("Ignored", lambda e: e.ignored, format_bool, centered=True),
]

ItemEntry = Drop | Supply
ITEM_COLUMNS: list[Column[ItemEntry]] = [
    Column("Item", lambda i: i.item),
    Column("Count", lambda i: i.count, format_number, numeric=True),
    Column("Unit price", lambda i: i.unit_price, format_money, numeric=True),
    Column("Total price", lambda i: i.total_price, format_money, numeric=True),
    Column("Analyzer price", lambda i: i.original_unit_price, format_money, numeric=True,
           tooltip="Preço unitário exportado pelo Analyzer (antes dos preços personalizados)"),
    Column("Player", lambda i: i.player),
    Column("Ignored", lambda i: i.ignored, format_bool, centered=True),
]


def _summary_label(text: str) -> QLabel:
    label = QLabel(text, objectName="MutedLabel")
    label.setTextFormat(Qt.TextFormat.RichText)
    return label


def _strong(value: str) -> str:
    return f"<b style='color:{COLORS['text']}'>{value}</b>"


class _TableTab(QWidget):
    def __init__(self, summary: str, columns: Sequence[Column], records: Sequence,
                 sort_column: int, empty_message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*TAB_MARGINS)
        layout.setSpacing(12)
        layout.addWidget(_summary_label(summary))
        if records:
            self.table = RecordTable(columns)
            self.table.set_records(records)
            self.table.sortByColumn(sort_column, Qt.SortOrder.DescendingOrder)
            layout.addWidget(self.table, 1)
        else:
            layout.addWidget(EmptyState("Sem registros", empty_message), 1)


class EnemiesTab(_TableTab):
    def __init__(self, enemies: Sequence[EnemyDefeated], parent: QWidget | None = None) -> None:
        total = sum(enemy.count for enemy in enemies)
        summary = (f"Inimigos derrotados: {_strong(format_number(total))} "
                   f"&nbsp;·&nbsp; Tipos: {_strong(format_number(len(enemies)))}")
        super().__init__(summary, ENEMY_COLUMNS, enemies, 1,
                         "Nenhum inimigo registrado nesta Hunt.", parent)


class DropsTab(_TableTab):
    def __init__(self, drops: Sequence[Drop], parent: QWidget | None = None) -> None:
        value = sum(drop.total_price or 0 for drop in drops)
        quantity = sum(drop.count for drop in drops)
        summary = (f"Valor total dos drops: {_strong(format_money(value))} "
                   f"&nbsp;·&nbsp; Quantidade de itens: {_strong(format_number(quantity))} "
                   f"&nbsp;·&nbsp; Tipos: {_strong(format_number(len(drops)))}")
        super().__init__(summary, ITEM_COLUMNS, drops, 3,
                         "Nenhum drop registrado nesta Hunt.", parent)


class SuppliesTab(_TableTab):
    def __init__(self, supplies: Sequence[Supply], parent: QWidget | None = None) -> None:
        cost = sum(supply.total_price or 0 for supply in supplies)
        quantity = sum(supply.count for supply in supplies)
        summary = (f"Custo total dos supplies: {_strong(format_money(cost))} "
                   f"&nbsp;·&nbsp; Quantidade: {_strong(format_number(quantity))}")
        super().__init__(summary, ITEM_COLUMNS, supplies, 3,
                         "Nenhum supply registrado nesta Hunt.", parent)


CHART_TOP_N = 15


def _ranked_points(entries: Sequence, name: Callable[[Any], str],
                   value: Callable[[Any], float | None]) -> list[ChartPoint]:
    ranked = sorted(entries, key=lambda e: value(e) or 0, reverse=True)[:CHART_TOP_N]
    return [ChartPoint(key=name(e), label=name(e), value=value(e), title=name(e))
            for e in ranked]


class ChartsTab(QScrollArea):
    """Inimigos derrotados e drops por valor da Hunt, em barras ordenadas."""

    def __init__(self, enemies: Sequence[EnemyDefeated], drops: Sequence[Drop],
                 supplies: Sequence[Supply], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.charts: list[RankedBarChart] = []

        specs = [
            (f"Inimigos derrotados (top {CHART_TOP_N})", enemies,
             lambda e: e.enemy, lambda e: e.count, format_number),
            (f"Drops por valor total (top {CHART_TOP_N})", drops,
             lambda d: d.item, lambda d: d.total_price, format_money),
            ("Supplies por custo total", supplies,
             lambda s: s.item, lambda s: s.total_price, format_money),
        ]
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(*TAB_MARGINS)
        layout.setSpacing(14)
        for title, entries, name, value, formatter in specs:
            if len(entries) < 2:  # uma barra só não é um gráfico: o número está na tabela
                continue
            chart = RankedBarChart(title, formatter)
            chart.set_points(_ranked_points(entries, name, value))
            self.charts.append(chart)
            layout.addWidget(chart)
        if not self.charts:
            layout.addWidget(EmptyState("Sem gráficos",
                                        "Esta Hunt tem poucos inimigos e itens para comparar."))
        layout.addStretch(1)
        self.setWidget(content)


class JsonTab(QWidget):
    """JSON original formatado, somente leitura, com botão de cópia."""

    def __init__(self, raw_json: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._raw_json = raw_json

        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setFont(monospace_font(10))
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setPlainText(pretty_json(raw_json))

        copy_button = QPushButton(icon("copy"), "  Copiar JSON")
        copy_button.clicked.connect(self._copy)
        self._feedback = QLabel(objectName="MutedLabel")

        bar = QHBoxLayout()
        bar.addWidget(_summary_label("JSON exatamente como foi importado (formatado para leitura)."))
        bar.addStretch(1)
        bar.addWidget(self._feedback)
        bar.addWidget(copy_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*TAB_MARGINS)
        layout.setSpacing(12)
        layout.addLayout(bar)
        layout.addWidget(self.editor, 1)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.editor.toPlainText())
        self._feedback.setText("Copiado!")
