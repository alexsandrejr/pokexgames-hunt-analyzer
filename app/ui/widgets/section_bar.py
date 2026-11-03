"""Sub-navegação de uma seção: botões arredondados, um deles sempre marcado."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from app.ui.widgets.page import PAGE_MARGINS


class SectionBar(QWidget):
    selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SectionBar")
        self.buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(PAGE_MARGINS[0] - 2, 16, PAGE_MARGINS[2], 0)
        self._layout.setSpacing(4)
        self._layout.addStretch(1)

    def set_items(self, items: Sequence[tuple[str, str]]) -> None:
        """Troca os botões pelos ``(chave, rótulo)`` informados."""
        for button in self.buttons.values():
            self._group.removeButton(button)
            self._layout.removeWidget(button)
            button.setParent(None)  # sai da tela já, sem esperar o deleteLater
            button.deleteLater()
        self.buttons = {}
        for position, (key, label) in enumerate(items):
            button = QPushButton(label, objectName="SectionPill")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, target=key: self.selected.emit(target))
            self._group.addButton(button)
            self._layout.insertWidget(position, button)
            self.buttons[key] = button

    def set_current(self, key: str) -> None:
        button = self.buttons.get(key)
        if button is not None:
            button.setChecked(True)

    def set_label(self, key: str, label: str) -> None:
        button = self.buttons.get(key)
        if button is not None:
            button.setText(label)
