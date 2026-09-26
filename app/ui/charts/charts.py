"""Gráficos pyqtgraph no estilo do app.

Regras visuais (guia de dataviz): uma série por gráfico (o título a nomeia, sem
legenda), barras finas (<= 24px) com ponta arredondada de 4px e base reta,
espaço entre barras, grade em linha fina e contínua, textos em tons neutros
(nunca na cor da série) e tooltip ao passar o mouse com o valor em destaque.
"""

from __future__ import annotations

import html
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QLabel, QToolTip, QVBoxLayout, QWidget

from app.ui.theme import COLORS
from app.utils.formatters import format_compact

pg.setConfigOptions(antialias=True)



class _ChartColors:
    """Cores dos gráficos, lidas do tema ativo no momento do uso."""

    _KEYS = {"series": "chart_series", "series_hover": "chart_series_hover",
             "grid": "chart_grid", "baseline": "chart_baseline",
             "reference": "chart_reference", "surface": "surface", "axis_text": "muted"}

    def __getitem__(self, key: str) -> str:
        return COLORS[self._KEYS[key]]


CHART = _ChartColors()
MAX_BAR_PX = 24.0
BAR_FILL_RATIO = 0.72  # parte da faixa ocupada pela barra; o resto é o espaço
END_RADIUS_PX = 4.0
LINE_MODE_THRESHOLD = 60  # acima disso, linha em vez de barras
MAX_X_LABELS = 8

ValueFormatter = Callable[[float | None], str]


@dataclass(frozen=True)
class ChartPoint:
    key: Any  # id da Hunt ou nome do item (emitido ao clicar)
    label: str  # rótulo curto do eixo (ex.: "26/09")
    value: float | None
    title: str  # linha secundária do tooltip


def _axis_font() -> QFont:
    font = QFont("Segoe UI")
    font.setPointSizeF(8)
    return font


class CompactValueAxis(pg.AxisItem):
    """Eixo de valores com números compactos (1,2 M) ou formatador próprio."""

    def __init__(self, orientation: str, formatter: ValueFormatter | None = None) -> None:
        super().__init__(orientation)
        self._formatter = formatter or format_compact

    def tickStrings(self, values, scale, spacing):  # noqa: N802 - API do pyqtgraph
        return [self._formatter(value) for value in values]


class DurationAxis(pg.AxisItem):
    """Eixo em segundos com marcas redondas (30 min ou 1 h): ``30min``, ``1h``, ``1h30``."""

    def tickSpacing(self, minVal, maxVal, size):  # noqa: N802,N803 - API do pyqtgraph
        span = maxVal - minVal
        major = 3600 if span > 4 * 3600 else 1800
        while span / major > 6:
            major *= 2
        return [(major, 0)]

    def tickStrings(self, values, scale, spacing):  # noqa: N802
        return [format_duration_tick(value) for value in values]


def format_duration_tick(seconds: float) -> str:
    total_minutes = int(round(seconds / 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h{minutes:02d}"
    if not total_minutes:
        return "0"
    return f"{hours}h" if hours else f"{minutes}min"


def _style_axis(axis: pg.AxisItem, show_line: bool) -> None:
    # Eixos (e suas linhas de grade) ficam atrás das barras.
    axis.setZValue(-1000)
    axis.setPen(pg.mkPen(CHART["baseline"] if show_line else CHART["surface"], width=1))
    axis.setTextPen(pg.mkPen(CHART["axis_text"]))
    axis.setStyle(tickFont=_axis_font(), tickLength=0, tickTextOffset=6)


class RoundedBars(pg.GraphicsObject):
    """Barras desenhadas em pixels: espessura limitada e ponta arredondada."""

    def __init__(self, values: Sequence[float | None], horizontal: bool = False) -> None:
        super().__init__()
        self._values = [v if v is not None and math.isfinite(v) else None for v in values]
        self._horizontal = horizontal
        self._hover = -1
        finite = [v for v in self._values if v is not None] or [0.0]
        self._low, self._high = min(0.0, min(finite)), max(0.0, max(finite))

    def set_hover(self, index: int) -> None:
        if index != self._hover:
            self._hover = index
            self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802
        count = len(self._values)
        span = (self._high - self._low) or 1.0
        if self._horizontal:
            return QRectF(self._low, -0.5, span, count)
        return QRectF(-0.5, self._low, count, span)

    def paint(self, painter: QPainter, *_args) -> None:
        transform = painter.transform()
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        slot = abs(transform.m22() if self._horizontal else transform.m11())
        thickness = max(1.5, min(MAX_BAR_PX, slot * BAR_FILL_RATIO))
        for index, value in enumerate(self._values):
            if not value:
                continue
            if self._horizontal:
                base = transform.map(QPointF(0, index))
                tip = transform.map(QPointF(value, index))
                rect = QRectF(min(base.x(), tip.x()), base.y() - thickness / 2,
                              abs(tip.x() - base.x()), thickness)
            else:
                base = transform.map(QPointF(index, 0))
                tip = transform.map(QPointF(index, value))
                rect = QRectF(base.x() - thickness / 2, min(base.y(), tip.y()),
                              thickness, abs(tip.y() - base.y()))
            color = CHART["series_hover"] if index == self._hover else CHART["series"]
            painter.fillPath(_rounded_end(rect, tip, self._horizontal), QColor(color))
        painter.restore()


def _rounded_end(rect: QRectF, tip: QPointF, horizontal: bool) -> QPainterPath:
    """Retângulo com apenas a ponta de dados arredondada (base reta)."""
    length = rect.width() if horizontal else rect.height()
    radius = min(END_RADIUS_PX, length, (rect.height() if horizontal else rect.width()) / 2)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    square = QRectF(rect)
    if horizontal:
        tip_on_right = tip.x() >= rect.center().x()
        square.setWidth(rect.width() - radius)
        if not tip_on_right:
            square.moveLeft(rect.left() + radius)
    else:
        tip_on_top = tip.y() <= rect.center().y()
        square.setHeight(rect.height() - radius)
        if tip_on_top:
            square.moveTop(rect.top() + radius)
    square_path = QPainterPath()
    square_path.addRect(square)
    return path.united(square_path)


class _PlotWidget(pg.PlotWidget):
    left = Signal()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.left.emit()


class _ChartCard(QFrame):
    """Card com título, subtítulo e um gráfico pyqtgraph."""

    point_activated = Signal(object)

    def __init__(self, title: str, value_formatter: ValueFormatter, plot_height: int,
                 value_axis: pg.AxisItem | None, horizontal: bool,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._format_value = value_formatter
        self._horizontal = horizontal
        self._points: list[ChartPoint] = []
        self._hover = -1
        self._bars: RoundedBars | None = None

        self.title = QLabel(title, objectName="ChartTitle")
        self.subtitle = QLabel(objectName="CardHint")

        value_axis = value_axis or CompactValueAxis("bottom" if horizontal else "left")
        axis_items = {"bottom": value_axis} if horizontal else {"left": value_axis}
        self.plot = _PlotWidget(background=CHART["surface"], axisItems=axis_items)
        self.plot.setFixedHeight(plot_height)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.setAntialiasing(True)
        item = self.plot.getPlotItem()
        item.getViewBox().setDefaultPadding(0.0)
        if horizontal:
            item.getViewBox().invertY(True)
        _style_axis(item.getAxis("left"), show_line=horizontal)
        _style_axis(item.getAxis("bottom"), show_line=not horizontal)
        item.showGrid(x=horizontal, y=not horizontal, alpha=0.35)
        (item.getAxis("bottom") if horizontal else item.getAxis("left")).setGrid(70)

        self._hover_line = pg.InfiniteLine(angle=90, pen=pg.mkPen(CHART["reference"], width=1))
        self._hover_dot = pg.ScatterPlotItem(size=10, brush=pg.mkBrush(CHART["series"]),
                                             pen=pg.mkPen(CHART["surface"], width=2))
        self.plot.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.plot.scene().sigMouseClicked.connect(self._on_mouse_clicked)
        self.plot.left.connect(self._clear_hover)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(2)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addSpacing(6)
        layout.addWidget(self.plot, 1)

    # ------------------------------------------------------------- hover

    def _index_at(self, scene_pos: QPointF) -> int:
        view_box = self.plot.getPlotItem().getViewBox()
        if not view_box.sceneBoundingRect().contains(scene_pos) or not self._points:
            return -1
        point = view_box.mapSceneToView(scene_pos)
        position = point.y() if self._horizontal else point.x()
        index = int(round(position))
        return index if 0 <= index < len(self._points) else -1

    def _on_mouse_moved(self, scene_pos: QPointF) -> None:
        index = self._index_at(scene_pos)
        if index < 0:
            self._clear_hover()
            return
        self._set_hover(index)
        point = self._points[index]
        QToolTip.showText(
            QCursor.pos(),
            f"<b style='font-size:11pt'>{html.escape(self._format_value(point.value))}</b>"
            f"<br><span style='color:{COLORS['muted']}'>{html.escape(point.title)}</span>",
            self.plot,
        )
        self.plot.setCursor(Qt.CursorShape.PointingHandCursor)

    def _on_mouse_clicked(self, event) -> None:
        index = self._index_at(event.scenePos())
        if index >= 0 and event.button() == Qt.MouseButton.LeftButton:
            self.point_activated.emit(self._points[index].key)

    def _set_hover(self, index: int) -> None:
        self._hover = index
        if self._bars is not None:
            self._bars.set_hover(index)
        else:
            value = self._points[index].value
            self._hover_line.setPos(index)
            self._hover_line.show()
            self._hover_dot.setData([index], [value if value is not None else 0])
            self._hover_dot.show()

    def _clear_hover(self) -> None:
        self._hover = -1
        if self._bars is not None:
            self._bars.set_hover(-1)
        self._hover_line.hide()
        self._hover_dot.hide()
        QToolTip.hideText()
        self.plot.unsetCursor()


class HuntSeriesChart(_ChartCard):
    """Uma métrica por Hunt, em ordem cronológica (colunas; linha se houver muitas)."""

    def __init__(self, title: str, value_formatter: ValueFormatter,
                 duration_axis: bool = False, parent: QWidget | None = None) -> None:
        axis = DurationAxis("left") if duration_axis else CompactValueAxis("left")
        super().__init__(title, value_formatter, 230, axis, False, parent)

    def set_points(self, points: Sequence[ChartPoint], reference: float | None = None,
                   subtitle: str | None = None) -> None:
        """Desenha os pontos; ``reference``/``subtitle`` substituem a média padrão."""
        self._points = list(points)
        item = self.plot.getPlotItem()
        item.clear()
        self._bars = None
        values = [p.value for p in self._points]
        finite = [v for v in values if v is not None]
        if not finite:
            self.subtitle.setText("Sem dados para as Hunts filtradas")
            return

        average = reference if reference is not None else sum(finite) / len(finite)
        self.subtitle.setText(subtitle or (
            f"Média {self._format_value(average)}  ·  "
            f"Mín. {self._format_value(min(finite))}  ·  Máx. {self._format_value(max(finite))}"))

        xs = list(range(len(values)))
        if len(values) > LINE_MODE_THRESHOLD:
            ys = [v if v is not None else float("nan") for v in values]
            item.addItem(pg.PlotDataItem(xs, ys, pen=pg.mkPen(CHART["series"], width=2),
                                         connect="finite"))
            item.addItem(self._hover_line, ignoreBounds=True)
            item.addItem(self._hover_dot)
        else:
            self._bars = RoundedBars(values)
            item.addItem(self._bars)
        self._hover_line.hide()
        self._hover_dot.hide()

        # Linha de referência discreta na média (identificada no subtítulo).
        item.addItem(pg.InfiniteLine(pos=average, angle=0,
                                     pen=pg.mkPen(CHART["reference"], width=1)),
                     ignoreBounds=True)

        low, high = min(0.0, min(finite)), max(0.0, max(finite))
        span = (high - low) or 1.0
        item.setXRange(-0.6, len(values) - 0.4, padding=0)
        item.setYRange(low - (span * 0.06 if low < 0 else 0), high + span * 0.08, padding=0)
        step = max(1, math.ceil(len(values) / MAX_X_LABELS))
        ticks = [(i, self._points[i].label) for i in range(0, len(values), step)]
        item.getAxis("bottom").setTicks([ticks, []])


class RankedBarChart(_ChartCard):
    """Barras horizontais ordenadas (ex.: inimigos, drops por valor), com valor na ponta."""

    ROW_HEIGHT = 28

    def __init__(self, title: str, value_formatter: ValueFormatter,
                 parent: QWidget | None = None) -> None:
        super().__init__(title, value_formatter, 120, None, True, parent)
        self.plot.getPlotItem().getAxis("left").setWidth(150)

    def set_points(self, points: Sequence[ChartPoint]) -> None:
        self._points = list(points)
        item = self.plot.getPlotItem()
        item.clear()
        values = [p.value or 0 for p in self._points]
        self._bars = RoundedBars(values, horizontal=True)
        item.addItem(self._bars)
        high = max(values, default=0) or 1.0
        for index, value in enumerate(values):
            label = pg.TextItem(self._format_value(value), color=COLORS["muted"], anchor=(0, 0.5))
            label.setFont(_axis_font())
            label.setPos(value, index)
            item.addItem(label, ignoreBounds=True)
        # Espaço à direita para o rótulo de valor na ponta da barra.
        item.setXRange(0, high * 1.22, padding=0)
        item.setYRange(-0.6, max(len(values), 1) - 0.4, padding=0)
        item.getAxis("left").setTicks([[(i, _shorten(p.label, 22))
                                        for i, p in enumerate(self._points)], []])
        self.plot.setFixedHeight(max(90, len(values) * self.ROW_HEIGHT + 36))


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
