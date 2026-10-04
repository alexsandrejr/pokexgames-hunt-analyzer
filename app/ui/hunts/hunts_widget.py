"""Página Hunts: a lista de sessões da categoria Hunt, com os botões de importação."""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.services.categories import Category
from app.services.hunt_service import HuntService
from app.ui.filters.filter_controller import FilterController
from app.ui.hunts.hunt_list import HUNT_TEXTS, HuntListView, import_buttons
from app.ui.import_controller import ImportController
from app.ui.widgets.page import PAGE_MARGINS, PageHeader

SUBTITLE = "Histórico de sessões importadas"


class HuntsPage(HuntListView):
    def __init__(self, service: HuntService, importer: ImportController,
                 filters: FilterController, parent: QWidget | None = None) -> None:
        super().__init__(service, filters, Category.HUNT, HUNT_TEXTS, parent)
        self._importer = importer

        self._header = PageHeader("Hunts", SUBTITLE)
        for button in import_buttons(importer):
            self._header.add_action(button)
        self.totals_changed.connect(
            lambda total: self._header.set_subtitle(f"{SUBTITLE} · {total} no total"))
        # O painel de filtros compartilhado é inserido aqui pela janela principal.
        self.filter_slot = QVBoxLayout()

        layout = self.layout()
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.insertWidget(0, self._header)
        layout.insertLayout(1, self.filter_slot)
