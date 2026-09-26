"""Barra lateral de navegação."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.icons import icon
from app.utils.constants import APP_VERSION

SIDEBAR_WIDTH = 220


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon_name: str


class Sidebar(QFrame):
    page_selected = Signal(int)

    def __init__(self, items: Sequence[NavItem], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(SIDEBAR_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 20, 14, 16)
        layout.setSpacing(4)
        layout.addWidget(self._build_brand())
        layout.addSpacing(18)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, item in enumerate(items):
            button = QPushButton(icon(item.icon_name), f"  {item.label}")
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setIconSize(QSize(18, 18))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(button, index)
            layout.addWidget(button)
        self._group.idClicked.connect(self.page_selected)

        layout.addStretch(1)
        layout.addWidget(QLabel(f"Versão {APP_VERSION}", objectName="SidebarFooter"))

    def _build_brand(self) -> QWidget:
        logo = QLabel()
        logo.setPixmap(icon("app").pixmap(32, 32))
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(QLabel("PokeXGames", objectName="SidebarTitle"))
        texts.addWidget(QLabel("Hunt Analyzer", objectName="SidebarSubtitle"))

        brand = QWidget()
        row = QHBoxLayout(brand)
        row.setContentsMargins(6, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(logo)
        row.addLayout(texts, 1)
        return brand

    def set_current(self, index: int) -> None:
        button = self._group.button(index)
        if button is not None:
            button.setChecked(True)
