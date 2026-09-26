"""Carregamento dos ícones SVG de ``resources/icons``, na cor do tema ativo."""

from __future__ import annotations

from functools import cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from app.config import ICONS_DIR
from app.ui.theme import COLORS, active_theme

# Cor com que os SVGs são desenhados; é trocada pela cor de ícone do tema.
SVG_ICON_COLOR = "#aeb6c4"
_SIZES = (16, 20, 24, 32, 48)


def icon(name: str) -> QIcon:
    """Retorna o ícone ``<name>.svg``; ícone vazio se o arquivo não existir."""
    return _themed_icon(name, active_theme())


@cache
def _themed_icon(name: str, _theme: str) -> QIcon:
    path = ICONS_DIR / f"{name}.svg"
    if not path.exists():
        return QIcon()
    svg = path.read_text(encoding="utf-8").replace(SVG_ICON_COLOR, COLORS["icon"])
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    result = QIcon()
    for size in _SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        result.addPixmap(pixmap)
    return result
