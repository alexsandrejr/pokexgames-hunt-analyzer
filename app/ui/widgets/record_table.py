"""Tabela genérica e ordenável baseada em definições de colunas.

Cada coluna define como obter o valor bruto (usado na ordenação) e como
formatá-lo para exibição. Assim a mesma infraestrutura atende a lista de
Hunts, inimigos, drops, supplies e futuros relatórios.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QWidget

from app.utils.formatters import format_text

T = TypeVar("T")

SORT_ROLE = Qt.ItemDataRole.UserRole
RECORD_ROLE = Qt.ItemDataRole.UserRole + 1

_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
_CENTER = Qt.AlignmentFlag.AlignCenter

AnyIndex = QModelIndex | QPersistentModelIndex


@dataclass(frozen=True)
class Column(Generic[T]):
    title: str
    value: Callable[[T], Any]
    formatter: Callable[[Any], str] = format_text
    numeric: bool = False
    centered: bool = False
    fit_contents: bool = False  # largura pelo conteúdo em vez de dividir o espaço
    color: Callable[[Any], str | None] | None = None
    tooltip: str | None = None


class RecordTableModel(QAbstractTableModel, Generic[T]):
    def __init__(self, columns: Sequence[Column[T]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._records: list[T] = []

    def set_records(self, records: Sequence[T]) -> None:
        self.beginResetModel()
        self._records = list(records)
        self.endResetModel()

    def record(self, row: int) -> T:
        return self._records[row]

    def rowCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._columns)

    def data(self, index: AnyIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        record = self._records[index.row()]
        column = self._columns[index.column()]
        if role == RECORD_ROLE:
            return record

        value = column.value(record)
        if role == Qt.ItemDataRole.DisplayRole:
            return column.formatter(value)
        if role == SORT_ROLE:
            return _sort_key(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column.centered:
                return _CENTER
            return _RIGHT if column.numeric else _LEFT
        if role == Qt.ItemDataRole.ForegroundRole and column.color:
            color = column.color(value)
            return QColor(color) if color else None
        return None

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation != Qt.Orientation.Horizontal:
            return None
        column = self._columns[section]
        if role == Qt.ItemDataRole.DisplayRole:
            return column.title
        if role == Qt.ItemDataRole.ToolTipRole:
            return column.tooltip
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column.centered:
                return _CENTER
            return _RIGHT if column.numeric else _LEFT
        return None


def _sort_key(value: Any) -> Any:
    # None vira QVariant inválido, que o Qt ordena de forma consistente (após os
    # demais valores na ordem crescente). Datas viram timestamps.
    if value is None:
        return None
    if hasattr(value, "timestamp"):
        return value.timestamp()
    if isinstance(value, str):
        return value.casefold()
    return value


class RecordTable(QTableView):
    """``QTableView`` pré-configurada: ordenação, busca textual e colunas elásticas."""

    def __init__(self, columns: Sequence[Column[T]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.source_model: RecordTableModel[T] = RecordTableModel(columns, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.source_model)
        self.proxy.setSortRole(SORT_ROLE)
        self.proxy.setFilterKeyColumn(-1)  # busca em todas as colunas
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setModel(self.proxy)

        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(34)

        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(90)
        header.setHighlightSections(False)
        header.setDefaultAlignment(_LEFT)
        for position, column in enumerate(columns):
            if column.fit_contents:
                header.setSectionResizeMode(position, QHeaderView.ResizeMode.ResizeToContents)

    def set_records(self, records: Sequence[T]) -> None:
        self.source_model.set_records(records)

    def set_sortable(self, sortable: bool) -> None:
        """Sem ordenação, as linhas ficam na ordem em que foram fornecidas."""
        self.setSortingEnabled(sortable)
        if not sortable:
            self.proxy.sort(-1)
            self.horizontalHeader().setSortIndicatorShown(False)

    def set_search_text(self, text: str) -> None:
        self.proxy.setFilterFixedString(text.strip())

    def visible_row_count(self) -> int:
        return self.proxy.rowCount()

    def visible_records(self) -> list[T]:
        """Registros que passam na pesquisa, na ordem exibida."""
        return [self.record_at(self.proxy.index(row, 0)) for row in range(self.proxy.rowCount())]

    def selected_records(self) -> list[T]:
        rows = {self.proxy.mapToSource(index).row() for index in self.selectionModel().selectedRows()}
        return [self.source_model.record(row) for row in sorted(rows)]

    def record_at(self, proxy_index: QModelIndex) -> T:
        return self.source_model.record(self.proxy.mapToSource(proxy_index).row())
