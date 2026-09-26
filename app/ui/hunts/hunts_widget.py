"""Página Hunts: listagem, busca, abertura de detalhes e exclusão."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QItemSelectionModel, QModelIndex, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.dto import HuntSummary
from app.services.export_documents import hunts_document
from app.services.export_service import ExportDocument
from app.services.hunt_service import HuntService
from app.ui.hunts.comparison_dialog import ComparisonDialog
from app.ui.hunts.hunt_details import HuntDetailsDialog, show_hunt_details
from app.ui.filters.filter_controller import FilterController
from app.ui.icons import icon
from app.ui.import_controller import ImportController
from app.ui.theme import COLORS
from app.ui.widgets.export_button import ExportButton
from app.ui.widgets.page import PAGE_MARGINS, EmptyState, PageHeader
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


class HuntsPage(QWidget):
    def __init__(self, service: HuntService, importer: ImportController,
                 filters: FilterController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._importer = importer
        self._filters = filters
        self._total = 0  # Hunts que passam no filtro
        self._total_all = 0  # Hunts no banco

        self._header = PageHeader("Hunts", "Histórico de sessões importadas")
        paste_button = QPushButton(icon("paste"), "  Colar JSON")
        paste_button.setToolTip("Colar o texto do JSON (Ctrl+Shift+V)")
        paste_button.clicked.connect(self._importer.paste_and_import)
        folder_button = QPushButton(icon("folder"), "  Importar pasta")
        folder_button.setToolTip("Importar todos os .json de uma pasta (Ctrl+Shift+I)")
        folder_button.clicked.connect(self._importer.choose_folder_and_import)
        import_button = QPushButton(icon("import"), "  Importar JSON")
        import_button.setObjectName("PrimaryButton")
        import_button.setToolTip("Selecionar arquivos .json (Ctrl+I)")
        import_button.clicked.connect(self._importer.choose_and_import)
        self._header.add_action(paste_button)
        self._header.add_action(folder_button)
        self._header.add_action(import_button)

        self._table = RecordTable(HUNT_COLUMNS)
        self._table.doubleClicked.connect(self._open_index)
        self._table.selectionModel().selectionChanged.connect(self._update_buttons)
        self._table.sortByColumn(0, Qt.SortOrder.DescendingOrder)

        self._stack = QStackedWidget()
        self._stack.addWidget(EmptyState(
            "Nenhuma Hunt importada",
            "Arraste arquivos .json ou pastas para esta janela, use “Importar JSON” ou "
            "“Importar pasta”, ou cole o texto com “Colar JSON”.",
        ))
        self._stack.addWidget(self._table)
        self._stack.addWidget(EmptyState(
            "Nenhuma Hunt corresponde aos filtros",
            "Ajuste ou limpe os filtros acima para ver mais Hunts.",
        ))
        # O painel de filtros compartilhado é inserido aqui pela janela principal.
        self.filter_slot = QVBoxLayout()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.setSpacing(16)
        layout.addWidget(self._header)
        layout.addLayout(self.filter_slot)
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
        self._compare_button.setToolTip("Selecione 2 ou mais Hunts (Ctrl+clique) para comparar")
        self._compare_button.clicked.connect(self.compare_selected)
        self.export_button = ExportButton(self._export_document)
        self.export_button.setToolTip("Exporta as Hunts visíveis na tabela")
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
        toolbar.addWidget(self._delete_button)
        toolbar.addWidget(self.export_button)
        toolbar.addWidget(refresh_button)
        return toolbar

    # ----------------------------------------------------------------- dados

    def refresh(self) -> None:
        selected = {hunt.id for hunt in self._table.selected_records()}
        hunts = self._service.list_hunts(self._filters.current)
        self._total = len(hunts)
        self._total_all = self._service.count_hunts()
        self._table.set_records(hunts)
        self._stack.setCurrentIndex(1 if hunts else (2 if self._total_all else 0))
        self.select_hunts(selected)
        self._update_count()
        self._update_buttons()

    def select_hunts(self, hunt_ids: Iterable[int]) -> None:
        """Seleciona as Hunts informadas (ex.: recém-importadas)."""
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
        text = (f"{visible} de {self._total} Hunts" if visible != self._total
                else f"{self._total} Hunts")
        if self._total != self._total_all:
            text += " (filtradas)"
        self._count_label.setText(text)
        self._header.set_subtitle(f"Histórico de sessões importadas · {self._total_all} no total")

    def _update_buttons(self) -> None:
        count = len(self._table.selectionModel().selectedRows())
        self._open_button.setEnabled(count == 1)
        self._compare_button.setEnabled(count >= 2)
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
        """As Hunts visíveis (filtro + pesquisa), na ordem exibida na tabela."""
        ids = [hunt.id for hunt in self._table.visible_records()]
        by_id = {hunt.id: hunt for hunt in self._service.get_summaries(ids)}
        return hunts_document([by_id[i] for i in ids if i in by_id],
                              self._filters.current.describe())

    def _announce_export(self, path: str) -> None:
        window = self.window()
        if hasattr(window, "statusBar"):
            window.statusBar().showMessage(f"Exportado: {path}", 10000)

    def delete_selected(self) -> None:
        records = self._table.selected_records()
        if not records:
            return
        noun = "a Hunt selecionada" if len(records) == 1 else f"as {len(records)} Hunts selecionadas"
        answer = QMessageBox.question(
            self, "Excluir Hunts",
            f"Deseja excluir {noun}?\n\nOs dados e o JSON original serão removidos do banco.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._service.delete_hunts(record.id for record in records)
            self.refresh()
