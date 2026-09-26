"""Comparação de Hunts lado a lado (métricas nas linhas, Hunts nas colunas)."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.dto import HuntSummary
from app.services.export_documents import comparison_document, comparison_table
from app.ui.icons import icon
from app.ui.widgets.export_button import ExportButton
from app.utils.formatters import format_datetime_short, format_text

_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


class ComparisonDialog(QDialog):
    """Apenas apresenta os valores lado a lado: sem ranking nem destaque de "melhor"."""

    def __init__(self, hunts: Sequence[HuntSummary], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hunts = list(hunts)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowIcon(icon("app"))
        self.setWindowTitle(f"Comparação de {len(self.hunts)} Hunts")
        self.resize(min(1300, 260 + 170 * len(self.hunts)), 660)

        self.table = self._build_table()
        self.export_button = ExportButton(lambda: comparison_document(self.hunts))

        header = QHBoxLayout()
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(QLabel("Comparação de Hunts", objectName="PageTitle"))
        texts.addWidget(QLabel(f"{len(self.hunts)} Hunts em ordem cronológica",
                               objectName="PageSubtitle"))
        header.addLayout(texts, 1)
        header.addWidget(self.export_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        layout.addLayout(header)
        layout.addWidget(self.table, 1)

    def _build_table(self) -> QTableWidget:
        data = comparison_table(self.hunts)
        display = data.display_rows()
        table = QTableWidget(len(display), len(self.hunts) + 1)
        table.setHorizontalHeaderLabels(
            ["Métrica"] + [f"Hunt {format_text(h.session_id)}\n"
                           f"{format_datetime_short(h.start_datetime)}" for h in self.hunts])
        for r, row in enumerate(display):
            for c, text in enumerate(row):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if c:
                    item.setTextAlignment(_RIGHT)
                table.setItem(r, c, item)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(32)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setMinimumSectionSize(130)
        header.setDefaultAlignment(_RIGHT)
        table.horizontalHeaderItem(0).setTextAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return table
