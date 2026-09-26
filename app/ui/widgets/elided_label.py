"""Rótulo de uma linha que corta o texto com "…" quando não cabe."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setText(text)  # mantém sizeHint e acessibilidade coerentes
        self.update()

    def full_text(self) -> str:
        return self._full_text

    def minimumSizeHint(self) -> QSize:
        return QSize(20, super().minimumSizeHint().height())

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        rect = self.contentsRect()
        elided = self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, rect.width())
        self.style().drawItemText(
            painter, rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.palette(), self.isEnabled(), elided, self.foregroundRole())
