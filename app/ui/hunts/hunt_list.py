"""Lista de sessões de uma categoria: busca, detalhes, comparação, mudança de categoria e exclusão.

Usada pela página Hunts e por cada aba da página Bosses.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from PySide6.QtCore import QItemSelectionModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.categories import Category
from app.services.dto import HuntSummary
from app.services.export_documents import hunts_document
from app.services.export_service import ExportDocument
from app.services.filters import EMPTY_FILTER, HuntFilter
from app.services.hunt_service import HuntService
from app.ui.filters.filter_controller import FilterController
from app.ui.hunts.comparison_dialog import ComparisonDialog
from app.ui.hunts.hunt_details import HuntDetailsDialog, show_hunt_details
from app.ui.icons import icon
from app.ui.import_controller import ImportController
from app.ui.theme import COLORS
from app.ui.widgets.export_button import ExportButton
from app.ui.widgets.page import EmptyState
from app.ui.widgets.record_table import Column, RecordTable
from app.utils.formatters import (
    format_datetime_short,
    format_duration,
    format_money,
    format_number,
    format_text,
)


def profit_color(value: float | None) -> str | None:
    if value is None or value == 0:
        return None
    return COLORS["positive"] if value > 0 else COLORS["negative"]


HUNT_COLUMNS: list[Column[HuntSummary]] = [
    Column("Data", lambda h: h.start_datetime, format_datetime_short, fit_contents=True),
    Column("Sessão", lambda h: h.session_id, format_text, numeric=True),
    Column("Player", lambda h: h.player),
    Column("Duração", lambda h: h.duration_seconds, format_duration, numeric=True),
    Column("Kills", lambda h: h.kills, format_number, numeric=True),
    Column("Kills/h", lambda h: h.kills_per_hour, format_number, numeric=True),
    Column("Profit", lambda h: h.profit, format_money, numeric=True, color=profit_color),
    Column("Profit/h", lambda h: h.profit_per_hour, format_money, numeric=True,
           color=profit_color),
    Column("Supplies", lambda h: h.supplies, format_money, numeric=True),
    Column("Supplies/h", lambda h: h.supplies_per_hour, format_money, numeric=True),
    Column("Raw Gains", lambda h: h.raw_gains, format_money, numeric=True),
]


@dataclass(frozen=True)
class ListTexts:
    """Palavras usadas na lista ("Hunt"/"Hunts" ou "sessão"/"sessões"), ambas femininas."""

    singular: str
    plural: str
    empty_title: str
    empty_message: str


IMPORT_HINT = ("Arraste arquivos .json/.tsv ou pastas para esta janela, use “Importar JSON/TSV” "
               "ou “Importar pasta”, ou cole o texto com “Colar JSON/TSV”.")

HUNT_TEXTS = ListTexts("Hunt", "Hunts", "Nenhuma Hunt importada", IMPORT_HINT)


def import_buttons(importer: ImportController) -> list[QPushButton]:
    """Botões "Colar", "Importar pasta" e "Importar" dos cabeçalhos de página."""
    paste_button = QPushButton(icon("paste"), "  Colar JSON/TSV")
    paste_button.setToolTip("Colar o texto do JSON ou TSV (Ctrl+Shift+V)")
    paste_button.clicked.connect(importer.paste_and_import)
    folder_button = QPushButton(icon("folder"), "  Importar pasta")
    folder_button.setToolTip("Importar todos os .json e .tsv de uma pasta (Ctrl+Shift+I)")
    folder_button.clicked.connect(importer.choose_folder_and_import)
    import_button = QPushButton(icon("import"), "  Importar JSON/TSV")
    import_button.setObjectName("PrimaryButton")
    import_button.setToolTip("Selecionar arquivos .json ou .tsv (Ctrl+I)")
    import_button.clicked.connect(importer.choose_and_import)
    return [paste_button, folder_button, import_button]


class HuntListView(QWidget):
    totals_changed = Signal(int)  # sessões da categoria no banco (sem filtros)

    def __init__(self, service: HuntService, filters: FilterController, category: Category,
                 texts: ListTexts, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._filters = filters
        self.category = category
        self._texts = texts
        self._total = 0  # sessões que passam no filtro
        self._total_all = 0  # sessões da categoria no banco

        self._table = RecordTable(HUNT_COLUMNS)
        self._table.doubleClicked.connect(self._open_index)
        self._table.selectionModel().selectionChanged.connect(self._update_buttons)
        self._table.sortByColumn(0, Qt.SortOrder.DescendingOrder)

        self._stack = QStackedWidget()
        self._stack.addWidget(EmptyState(texts.empty_title, texts.empty_message))
        self._stack.addWidget(self._table)
        self._stack.addWidget(EmptyState(
            f"Nenhuma {texts.singular} corresponde aos filtros",
            f"Ajuste ou limpe os filtros acima para ver mais {texts.plural}.",
        ))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addLayout(self._build_toolbar())
        layout.addWidget(self._stack, 1)

        QShortcut(QKeySequence(Qt.Key.Key_Return), self._table, activated=self.open_selected)
        QShortcut(QKeySequence.StandardKey.Delete, self._table, activated=self.delete_selected)
        self._update_buttons()

    def _build_toolbar(self) -> QHBoxLayout:
        self._search = QLineEdit()
        self._search.setPlaceholderText("Pesquisar por data, player, sessão…")
        self._search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self._search.setClearButtonEnabled(True)
        self._search.setMaximumWidth(360)
        self._search.textChanged.connect(self._on_search)

        self._open_button = QPushButton(icon("open"), "  Detalhes")
        self._open_button.clicked.connect(self.open_selected)
        self._compare_button = QPushButton(icon("compare"), "  Comparar")
        self._compare_button.setToolTip(
            f"Selecione 2 ou mais {self._texts.plural} (Ctrl+clique) para comparar")
        self._compare_button.clicked.connect(self.compare_selected)
        self._move_button = QPushButton(icon("folder"), "  Mover")
        self._move_button.setToolTip("Mover as sessões selecionadas para outra categoria "
                                     "(Hunts ou um tipo de boss)")
        move_menu = QMenu(self._move_button)
        for category in Category:
            if category is not self.category:
                move_menu.addAction(category.plural,
                                    lambda target=category: self.move_selected(target))
        self._move_button.setMenu(move_menu)
        self.export_button = ExportButton(self._export_document)
        self.export_button.setToolTip(f"Exporta as {self._texts.plural} visíveis na tabela")
        self._delete_button = QPushButton(icon("trash"), "  Excluir")
        self._delete_button.setObjectName("DangerButton")
        self._delete_button.clicked.connect(self.delete_selected)
        refresh_button = QPushButton(icon("refresh"), "  Atualizar")
        refresh_button.clicked.connect(self.refresh)
        self._count_label = QLabel(objectName="MutedLabel")

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(self._search, 1)
        toolbar.addWidget(self._count_label)
        toolbar.addStretch(1)
        toolbar.addWidget(self._open_button)
        toolbar.addWidget(self._compare_button)
        toolbar.addWidget(self._move_button)
        toolbar.addWidget(self._delete_button)
        toolbar.addWidget(self.export_button)
        toolbar.addWidget(refresh_button)
        return toolbar

    # ----------------------------------------------------------------- dados

    def scoped_filter(self) -> HuntFilter:
        """Filtro do usuário restrito à categoria da lista."""
        return self._filters.current.scoped(self.category)

    def refresh(self) -> None:
        selected = {hunt.id for hunt in self._table.selected_records()}
        hunts = self._service.list_hunts(self.scoped_filter())
        self._total = len(hunts)
        self._total_all = self._service.count_hunts(EMPTY_FILTER.scoped(self.category))
        self._table.set_records(hunts)
        self._stack.setCurrentIndex(1 if hunts else (2 if self._total_all else 0))
        self.select_hunts(selected)
        self._update_count()
        self._update_buttons()

    def select_hunts(self, hunt_ids: Iterable[int]) -> None:
        """Seleciona as sessões informadas (ex.: recém-importadas)."""
        wanted = set(hunt_ids)
        selection = self._table.selectionModel()
        selection.clearSelection()
        first: QModelIndex | None = None
        for row in range(self._table.proxy.rowCount()):
            index = self._table.proxy.index(row, 0)
            if self._table.record_at(index).id in wanted:
                selection.select(index, QItemSelectionModel.SelectionFlag.Select
                                 | QItemSelectionModel.SelectionFlag.Rows)
                first = first or index
        if first is not None:
            self._table.scrollTo(first)

    def selected_ids(self) -> list[int]:
        return [hunt.id for hunt in self._table.selected_records()]

    def _on_search(self, text: str) -> None:
        self._table.set_search_text(text)
        self._update_count()
        self._update_buttons()

    def _update_count(self) -> None:
        visible = self._table.visible_row_count()
        plural = self._texts.plural
        text = (f"{visible} de {self._total} {plural}" if visible != self._total
                else f"{self._total} {plural}")
        if self._total != self._total_all:
            text += " (filtradas)"
        self._count_label.setText(text)
        self.totals_changed.emit(self._total_all)

    def _update_buttons(self) -> None:
        count = len(self._table.selectionModel().selectedRows())
        self._open_button.setEnabled(count == 1)
        self._compare_button.setEnabled(count >= 2)
        self._move_button.setEnabled(count > 0)
        self._delete_button.setEnabled(count > 0)
        self.export_button.setEnabled(self._table.visible_row_count() > 0)

    # ----------------------------------------------------------------- ações

    def _open_index(self, index: QModelIndex) -> None:
        self.open_hunt(self._table.record_at(index).id)

    def open_selected(self) -> None:
        records = self._table.selected_records()
        if len(records) == 1:
            self.open_hunt(records[0].id)

    def open_hunt(self, hunt_id: int) -> HuntDetailsDialog | None:
        dialog = show_hunt_details(self._service, hunt_id, self.window())
        if dialog is None:
            self.refresh()
        return dialog

    def compare_selected(self) -> ComparisonDialog | None:
        ids = self.selected_ids()
        if len(ids) < 2:
            return None
        dialog = ComparisonDialog(self._service.get_summaries(ids), self.window())
        dialog.export_button.exported.connect(self._announce_export)
        dialog.show()
        return dialog

    def _export_document(self) -> ExportDocument:
        """As sessões visíveis (filtro + pesquisa), na ordem exibida na tabela."""
        ids = [hunt.id for hunt in self._table.visible_records()]
        by_id = {hunt.id: hunt for hunt in self._service.get_summaries(ids)}
        return hunts_document([by_id[i] for i in ids if i in by_id],
                              self._filters.current.describe(), title=self.category.plural)

    def _show_status(self, text: str) -> None:
        window = self.window()
        if hasattr(window, "statusBar"):
            window.statusBar().showMessage(text, 10000)

    def _announce_export(self, path: str) -> None:
        self._show_status(f"Exportado: {path}")

    def move_selected(self, category: Category) -> int:
        """Muda a categoria das sessões selecionadas; elas saem desta lista."""
        ids = self.selected_ids()
        if not ids:
            return 0
        moved = self._service.set_category(ids, category)
        self.refresh()
        self._show_status(f"{moved} sessão(ões) movida(s) para {category.plural}.")
        return moved

    def delete_selected(self) -> None:
        records = self._table.selected_records()
        if not records:
            return
        singular, plural = self._texts.singular, self._texts.plural
        noun = (f"a {singular} selecionada" if len(records) == 1
                else f"as {len(records)} {plural} selecionadas")
        answer = QMessageBox.question(
            self, f"Excluir {plural}",
            f"Deseja excluir {noun}?\n\nOs dados e o JSON original serão removidos do banco.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._service.delete_hunts(record.id for record in records)
            self.refresh()
