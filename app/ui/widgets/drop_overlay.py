"""Camada exibida sobre a janela enquanto arquivos são arrastados para ela."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from app.ui.theme import COLORS


class DropOverlay(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        # Não intercepta o mouse: os eventos de arrastar continuam indo para a janela.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def show_over_parent(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        backdrop = QColor(COLORS["bg"])
        backdrop.setAlpha(215)
        painter.fillRect(self.rect(), backdrop)

        frame = QRectF(self.rect()).adjusted(24, 24, -24, -24)
        pen = QPen(QColor(COLORS["accent"]), 2, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(frame, 16, 16)

        title_font = painter.font()
        title_font.setPointSizeF(16)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(COLORS["text"]))
        center = frame.center()
        painter.drawText(QRectF(frame.left(), center.y() - 40, frame.width(), 34),
                         Qt.AlignmentFlag.AlignCenter, "Solte para importar")
        body_font = painter.font()
        body_font.setPointSizeF(10)
        body_font.setBold(False)
        painter.setFont(body_font)
        painter.setPen(QColor(COLORS["muted"]))
        painter.drawText(QRectF(frame.left(), center.y() + 2, frame.width(), 24),
                         Qt.AlignmentFlag.AlignCenter,
                         "Arquivos .json do Analyzer ou pastas inteiras")
