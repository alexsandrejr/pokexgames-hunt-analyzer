"""Blocos comuns de página: cabeçalho e estado vazio."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

PAGE_MARGINS = (28, 24, 28, 24)


class PageHeader(QWidget):
    """Título + subtítulo à esquerda e área de ações à direita."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(QLabel(title, objectName="PageTitle"))
        self.subtitle = QLabel(subtitle, objectName="PageSubtitle")
        self.subtitle.setVisible(bool(subtitle))
        texts.addWidget(self.subtitle)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(texts, 1)
        layout.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))


class EmptyState(QWidget):
    """Mensagem centralizada para listas vazias ou recursos futuros."""

    def __init__(self, title: str, message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        self._heading = QLabel(title, objectName="EmptyTitle")
        self._heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._body = QLabel(message, objectName="MutedLabel")
        self._body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._body.setWordWrap(True)
        layout.addWidget(self._heading)
        layout.addWidget(self._body)
        layout.addStretch(1)

    def set_text(self, title: str, message: str) -> None:
        self._heading.setText(title)
        self._body.setText(message)
