"""Páginas de lista da seção Sessões: todas as sessões e só as Hunts."""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.services.categories import Category
from app.services.hunt_service import HuntService
from app.ui.filters.filter_controller import FilterController
from app.ui.hunts.hunt_list import ALL_SESSIONS_TEXTS, HUNT_TEXTS, HuntListView, ListTexts
from app.ui.widgets.page import PAGE_MARGINS, PageHeader


class _SessionListPage(HuntListView):
    """Lista com título e o espaço do painel de filtros."""

    def __init__(self, title: str, subtitle: str, service: HuntService,
                 filters: FilterController, category: Category | None, texts: ListTexts,
                 parent: QWidget | None = None) -> None:
        super().__init__(service, filters, category, texts, parent)
        self._header = PageHeader(title, subtitle)
        # O painel de filtros compartilhado é inserido aqui pela janela principal.
        self.filter_slot = QVBoxLayout()

        layout = self.layout()
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.insertWidget(0, self._header)
        layout.insertLayout(1, self.filter_slot)


class HuntsPage(_SessionListPage):
    def __init__(self, service: HuntService, filters: FilterController,
                 parent: QWidget | None = None) -> None:
        super().__init__("Hunts", "Sessões de caça importadas", service, filters, Category.HUNT,
                         HUNT_TEXTS, parent)


class AllSessionsPage(_SessionListPage):
    def __init__(self, service: HuntService, filters: FilterController,
                 parent: QWidget | None = None) -> None:
        super().__init__("Todas as sessões", "Hunts e bosses, da mais recente para a mais antiga",
                         service, filters, None, ALL_SESSIONS_TEXTS, parent)
