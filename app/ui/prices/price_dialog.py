"""Diálogo para definir o preço personalizado de um item."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.price_service import PricedItem, item_key
from app.ui.icons import icon
from app.ui.theme import COLORS
from app.ui.widgets.combos import searchable_combo, set_combo_options
from app.utils.formatters import format_money
from app.utils.validators import parse_user_number


class PriceDialog(QDialog):
    """Nome do item (lista dos conhecidos ou digitado) e o novo preço unitário."""

    def __init__(self, items: Sequence[PricedItem], selected: PricedItem | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preço do item")
        self.setWindowIcon(icon("prices"))
        self.setMinimumWidth(460)
        self._items = {item_key(item.name): item for item in items}

        self.name_combo = searchable_combo("Escolha ou digite o item…")
        set_combo_options(self.name_combo, [item.name for item in items])
        self.name_combo.editTextChanged.connect(self.validate)
        self.price_edit = QLineEdit()
        self.price_edit.setPlaceholderText("Ex.: 1500, 800k, 1,2kk")
        self.price_edit.textChanged.connect(self.validate)
        self.info = QLabel(objectName="MutedLabel")
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.PlainText)

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("Item", self.name_combo)
        form.addRow("Preço unitário", self.price_edit)

        cancel_button = QPushButton("Cancelar")
        cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton(icon("check"), "  Salvar")
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.info)
        layout.addLayout(buttons)

        if selected is not None:
            self.name_combo.setEditText(selected.name)
            price = selected.custom_price if selected.has_custom_price else selected.analyzer_price
            if price is not None:
                # Sem separador de milhar, para ser lido igual em pt-BR e en-US.
                self.price_edit.setText(str(int(price)) if price.is_integer() else str(price))
            self.price_edit.setFocus()
            self.price_edit.selectAll()
        self.validate()

    def item_name(self) -> str:
        return self.name_combo.currentText().strip()

    def price(self) -> float | None:
        value = parse_user_number(self.price_edit.text())
        return value if value is not None and value >= 0 else None

    def validate(self) -> bool:
        name, price = self.item_name(), self.price()
        known = self._items.get(item_key(name)) if name else None
        if known is None:
            text = ("Item ainda não visto nas Hunts: o preço valerá quando ele aparecer."
                    if name else "")
        else:
            text = (f"Preço do Analyzer: {format_money(known.analyzer_price)} · "
                    f"aparece em {known.hunt_count} Hunt(s) como {known.sources.lower()}.")
        if self.price_edit.text().strip() and price is None:
            self.info.setStyleSheet(f"color: {COLORS['negative']};")
            text = "Preço inválido: use um número maior ou igual a zero."
        else:
            self.info.setStyleSheet("")
        self.info.setText(text)
        valid = bool(name) and price is not None
        self.save_button.setEnabled(valid)
        return valid
