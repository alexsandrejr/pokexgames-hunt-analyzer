"""Página de Preços: preços personalizados dos itens, aplicados a todas as Hunts."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.price_service import PricedItem, PriceService, item_key
from app.ui.icons import icon
from app.ui.prices.price_dialog import PriceDialog
from app.ui.theme import COLORS
from app.ui.widgets.page import PAGE_MARGINS, EmptyState, PageHeader
from app.ui.widgets.record_table import Column, RecordTable
from app.utils.formatters import format_money, format_number

PRICE_COLUMNS: list[Column[PricedItem]] = [
    Column("Item", lambda i: i.name),
    Column("Aparece em", lambda i: i.sources),
    Column("Preço do Analyzer", lambda i: i.analyzer_price, format_money, numeric=True,
           tooltip="Preço unitário exportado pelo Analyzer na Hunt mais recente"),
    Column("Preço personalizado", lambda i: i.custom_price, format_money, numeric=True,
           color=lambda value: COLORS["accent"] if value is not None else None),
    Column("Quantidade", lambda i: i.quantity, format_number, numeric=True),
    Column("Hunts", lambda i: i.hunt_count, format_number, numeric=True),
]

EXPLANATION = (
    "O preço personalizado substitui o do Analyzer em todas as Hunts, inclusive nas "
    "próximas importações. Raw gains, Supplies, Profit e as taxas por hora são "
    "recalculados. Ao remover o preço, volta a valer o do Analyzer."
)


class PricesPage(QWidget):
    def __init__(self, service: PriceService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._items: list[PricedItem] = []

        self._header = PageHeader("Preços", "Preços personalizados dos itens")
        self._set_button = QPushButton(icon("prices"), "  Definir preço")
        self._set_button.setObjectName("PrimaryButton")
        self._set_button.setToolTip("Definir o preço do item selecionado ou de outro item")
        self._set_button.clicked.connect(self.edit_selected)
        self._clear_button = QPushButton(icon("close"), "  Remover preço")
        self._clear_button.setToolTip("Voltar ao preço do Analyzer nos itens selecionados")
        self._clear_button.clicked.connect(self.clear_selected)
        self._header.add_action(self._clear_button)
        self._header.add_action(self._set_button)

        explanation = QLabel(EXPLANATION, objectName="MutedLabel")
        explanation.setWordWrap(True)

        self._table = RecordTable(PRICE_COLUMNS)
        self._table.doubleClicked.connect(lambda _index: self.edit_selected())
        self._table.selectionModel().selectionChanged.connect(self._update_buttons)
        self._table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        self._stack = QStackedWidget()
        self._stack.addWidget(EmptyState(
            "Nenhum item ainda",
            "Importe Hunts para ver os itens aqui, ou use “Definir preço” para cadastrar "
            "o preço de um item antes de importá-lo.",
        ))
        self._stack.addWidget(self._table)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.setSpacing(16)
        layout.addWidget(self._header)
        layout.addWidget(explanation)
        layout.addLayout(self._build_toolbar())
        layout.addWidget(self._stack, 1)

        QShortcut(QKeySequence(Qt.Key.Key_Return), self._table, activated=self.edit_selected)
        QShortcut(QKeySequence.StandardKey.Delete, self._table, activated=self.clear_selected)
        self._update_buttons()

    def _build_toolbar(self) -> QHBoxLayout:
        self._search = QLineEdit()
        self._search.setPlaceholderText("Pesquisar item…")
        self._search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumWidth(220)
        self._search.setMaximumWidth(360)
        self._search.textChanged.connect(self._on_search)
        self.only_custom = QCheckBox("Somente com preço personalizado")
        self.only_custom.toggled.connect(self._show_items)
        self._count_label = QLabel(objectName="MutedLabel")

        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)
        toolbar.addWidget(self._search, 1)
        toolbar.addWidget(self.only_custom)
        toolbar.addStretch(1)
        toolbar.addWidget(self._count_label)
        return toolbar

    # ----------------------------------------------------------------- dados

    def refresh(self) -> None:
        self._items = self._service.list_items()
        self._show_items()

    def _show_items(self) -> None:
        selected = {item_key(item.name) for item in self._table.selected_records()}
        items = [item for item in self._items
                 if item.has_custom_price or not self.only_custom.isChecked()]
        self._table.set_records(items)
        self._stack.setCurrentIndex(1 if self._items else 0)
        self._select_names(selected)
        self._update_count()
        self._update_buttons()

    def _select_names(self, keys: set[str]) -> None:
        """Seleciona o primeiro item visível cujo nome (em minúsculas) está em ``keys``."""
        self._table.clearSelection()
        for row in range(self._table.proxy.rowCount()):
            index = self._table.proxy.index(row, 0)
            if item_key(self._table.record_at(index).name) in keys:
                self._table.selectRow(row)
                self._table.scrollTo(index)
                return

    def _on_search(self, text: str) -> None:
        self._table.set_search_text(text)
        self._update_count()
        self._update_buttons()

    def _update_count(self) -> None:
        custom = sum(item.has_custom_price for item in self._items)
        visible = self._table.visible_row_count()
        self._count_label.setText(f"{visible} de {len(self._items)} itens · "
                                  f"{custom} com preço personalizado")

    def _update_buttons(self) -> None:
        selected = self._table.selected_records()
        self._clear_button.setEnabled(any(item.has_custom_price for item in selected))

    # ----------------------------------------------------------------- ações

    def edit_selected(self) -> None:
        selected = self._table.selected_records()
        dialog = PriceDialog(self._items, selected[0] if len(selected) == 1 else None, self)
        if dialog.exec() != PriceDialog.DialogCode.Accepted:
            return
        self.set_price(dialog.item_name(), dialog.price())

    def set_price(self, name: str, price: float) -> int:
        hunts = self._service.set_price(name, price)
        self._after_change(f"Preço de {name} definido em {format_money(price)}; "
                           f"{hunts} Hunt(s) recalculada(s).", name)
        return hunts

    def clear_selected(self) -> None:
        items = [item for item in self._table.selected_records() if item.has_custom_price]
        if not items:
            return
        names = ", ".join(item.name for item in items)
        answer = QMessageBox.question(
            self, "Remover preço",
            f"Voltar ao preço do Analyzer em: {names}?\n\nAs Hunts serão recalculadas.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.clear_prices([item.name for item in items])

    def clear_prices(self, names: list[str]) -> int:
        hunts = sum(self._service.clear_price(name) for name in names)
        self._after_change(f"Preço do Analyzer restaurado em {len(names)} item(ns); "
                           f"{hunts} Hunt(s) recalculada(s).", names[0])
        return hunts

    def _after_change(self, message: str, name: str) -> None:
        self.refresh()
        self._select_names({item_key(name)})
        self._update_buttons()
        window = self.window()
        if hasattr(window, "statusBar"):
            window.statusBar().showMessage(message, 8000)
