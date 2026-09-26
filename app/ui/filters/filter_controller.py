"""Estado global do filtro, compartilhado por Dashboard, Hunts e Relatórios."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.services.filters import EMPTY_FILTER, HuntFilter


class FilterController(QObject):
    changed = Signal(object)  # HuntFilter

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._current = EMPTY_FILTER

    @property
    def current(self) -> HuntFilter:
        return self._current

    def set_filter(self, hunt_filter: HuntFilter) -> None:
        if hunt_filter != self._current:
            self._current = hunt_filter
            self.changed.emit(hunt_filter)

    def clear(self) -> None:
        self.set_filter(EMPTY_FILTER)
