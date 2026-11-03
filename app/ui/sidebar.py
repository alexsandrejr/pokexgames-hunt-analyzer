"""Barra lateral: marca, botão Importar e navegação entre as seções."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.icons import icon, white_icon
from app.utils.constants import APP_VERSION

SIDEBAR_WIDTH = 210


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon_name: str
    at_bottom: bool = False  # fica no rodapé, separado das seções de trabalho


class Sidebar(QFrame):
    section_selected = Signal(str)
    about_requested = Signal()

    def __init__(self, items: Sequence[NavItem], import_menu: QMenu,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(SIDEBAR_WIDTH)

        self.import_button = QPushButton(white_icon("import"), "  Importar",
                                         objectName="PrimaryButton")
        self.import_button.setIconSize(QSize(16, 16))
        self.import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_button.setToolTip("Importar arquivos, uma pasta ou texto colado do Analyzer.\n"
                                      "Você também pode arrastar arquivos para a janela.")
        self.import_button.setMenu(import_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 20, 14, 12)
        layout.setSpacing(4)
        layout.addWidget(self._build_brand())
        layout.addSpacing(16)
        layout.addWidget(self.import_button)
        layout.addSpacing(16)

        self._buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for item in items:
            if not item.at_bottom:
                layout.addWidget(self._nav_button(item))
        layout.addStretch(1)
        for item in items:
            if item.at_bottom:
                layout.addWidget(self._nav_button(item))

        version = QPushButton(f"Versão {APP_VERSION}", objectName="SidebarFooter")
        version.setCursor(Qt.CursorShape.PointingHandCursor)
        version.setToolTip("Sobre o aplicativo")
        version.clicked.connect(self.about_requested)
        layout.addWidget(version)

    def _nav_button(self, item: NavItem) -> QPushButton:
        button = QPushButton(icon(item.icon_name), f"  {item.label}", objectName="NavButton")
        button.setCheckable(True)
        button.setIconSize(QSize(18, 18))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, key=item.key: self.section_selected.emit(key))
        self._group.addButton(button)
        self._buttons[item.key] = button
        return button

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

    def set_current(self, key: str) -> None:
        button = self._buttons.get(key)
        if button is not None:
            button.setChecked(True)
