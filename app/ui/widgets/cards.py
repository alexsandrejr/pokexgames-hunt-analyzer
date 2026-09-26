"""Cards de estatística e grade responsiva."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QTimer
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


class StatCard(QFrame):
    """Card com título, valor principal e uma dica opcional."""

    def __init__(self, title: str, value: str = "—", hint: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        # Vertical "Minimum": cards da mesma linha crescem até a altura da linha.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self._title = QLabel(title, objectName="CardTitle")
        self._value = QLabel(value, objectName="CardValue")
        self._hint = QLabel(hint, objectName="CardHint")
        self._hint.setWordWrap(True)
        self._hint.setVisible(bool(hint))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(4)
        layout.addWidget(self._title)
        layout.addWidget(self._value)
        layout.addWidget(self._hint)
        layout.addStretch(1)

    def set_value(self, value: str, hint: str | None = None) -> None:
        self._value.setText(value)
        if hint is not None:
            self._hint.setText(hint)
            self._hint.setVisible(bool(hint))


class ResponsiveGrid(QWidget):
    """Distribui widgets em colunas conforme a largura disponível."""

    def __init__(self, widgets: Sequence[QWidget], min_item_width: int = 220,
                 max_columns: int = 4, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._widgets = list(widgets)
        self._min_item_width = min_item_width
        self._max_columns = max_columns
        self._columns = 0
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(14)
        self._relayout(max_columns)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        spacing = self._layout.horizontalSpacing()
        fit = (event.size().width() + spacing) // (self._min_item_width + spacing)
        self._relayout(max(1, min(self._max_columns, fit, len(self._widgets))))

    def _relayout(self, columns: int) -> None:
        if columns == self._columns:
            return
        self._columns = columns
        for widget in self._widgets:
            self._layout.removeWidget(widget)
        for position, widget in enumerate(self._widgets):
            self._layout.addWidget(widget, position // columns, position % columns)
        for column in range(self._max_columns):
            self._layout.setColumnStretch(column, 1 if column < columns else 0)
        # O número de linhas mudou: os layouts acima precisam recalcular a altura.
        # Isso acontece durante um resizeEvent (no meio de um cálculo de layout), quando
        # o aviso imediato se perde; por isso ele é reenviado ao fim do cálculo atual.
        self.updateGeometry()
        QTimer.singleShot(0, self._invalidate_ancestors)

    def _invalidate_ancestors(self) -> None:
        widget: QWidget | None = self
        while widget is not None:
            if widget.layout() is not None:
                widget.layout().invalidate()
            widget = widget.parentWidget()
