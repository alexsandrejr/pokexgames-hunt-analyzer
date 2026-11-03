"""Janela principal: sidebar + sub-navegação da seção + páginas empilhadas."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import (
    QAction,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.backup_service import BackupService
from app.services.categories import BOSS_CATEGORIES, Category
from app.services.dps_service import DpsService
from app.services.entity_report import EntityKind
from app.services.filters import EMPTY_FILTER
from app.services.hunt_service import HuntService
from app.services.price_service import PriceService
from app.services.settings_service import AppSettings, SettingsStore
from app.services.statistics_service import StatisticsService
from app.ui.bosses.bosses_widget import BossesPage
from app.ui.dashboard.dashboard_widget import DashboardPage
from app.ui.dps.dps_widget import DpsPage
from app.ui.hunts.hunts_widget import AllSessionsPage, HuntsPage
from app.ui.filters.filter_controller import FilterController
from app.ui.filters.filter_panel import FilterPanel
from app.ui.hunts.hunt_details import show_hunt_details
from app.ui.icons import icon
from app.ui.import_controller import ImportController, dropped_paths
from app.ui.prices.prices_widget import PricesPage
from app.ui.reports.reports_widget import ReportsPage
from app.ui.settings.settings_widget import SettingsPage
from app.ui.sidebar import NavItem, Sidebar
from app.ui.items.entity_report_page import EntityReportPage
from app.ui.widgets.drop_overlay import DropOverlay
from app.ui.widgets.export_button import ExportButton
from app.ui.widgets.section_bar import SectionBar
from app.utils.constants import APP_NAME, APP_VERSION

NAV_ITEMS = [
    NavItem("dashboard", "Início", "dashboard"),
    NavItem("sessions", "Sessões", "hunts"),
    NavItem("analysis", "Análise", "reports"),
    NavItem("dps", "DPS", "dps"),
    NavItem("settings", "Configurações", "settings", at_bottom=True),
]

BOSS_KEY_PREFIX = "boss:"


def boss_key(category: Category) -> str:
    return f"{BOSS_KEY_PREFIX}{category.value}"


# Sub-navegação das seções com mais de uma página: (chave, rótulo), na ordem exibida.
SECTION_PAGES: dict[str, tuple[tuple[str, str], ...]] = {
    "sessions": (
        ("all_sessions", "Todas"),
        ("hunts", "Hunts"),
        *((boss_key(category), category.plural) for category in BOSS_CATEGORIES),
    ),
    "analysis": (
        ("reports", "Relatórios"),
        ("items", "Itens"),
        ("enemies", "Inimigos"),
        ("prices", "Preços"),
    ),
}


class MainWindow(QMainWindow):
    def __init__(self, hunt_service: HuntService, statistics_service: StatisticsService,
                 database_path: Path, backup_service: BackupService | None = None,
                 settings_store: SettingsStore | None = None,
                 settings: AppSettings | None = None,
                 restart: Callable[[], None] | None = None,
                 price_service: PriceService | None = None,
                 dps_service: DpsService | None = None) -> None:
        super().__init__()
        self._restart = restart
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icon("app"))
        self.resize(1320, 820)
        self.setMinimumSize(980, 620)

        self.importer = ImportController(hunt_service, self)
        self.importer.hunts_imported.connect(self._on_hunts_imported)
        self.importer.status_message.connect(lambda text: self.statusBar().showMessage(text, 8000))
        self.importer.category_provider = self._import_category

        self._hunt_service = hunt_service
        self.filters = FilterController(self)
        self.filters.changed.connect(self.refresh_current_page)
        self.filter_panel = FilterPanel(self.filters)

        self.dashboard_page = DashboardPage(hunt_service, statistics_service, self.filters,
                                            self.open_hunt)
        self.all_sessions_page = AllSessionsPage(hunt_service, self.filters)
        self.hunts_page = HuntsPage(hunt_service, self.filters)
        self.bosses_page = BossesPage(hunt_service, statistics_service, self.filters,
                                      self.open_hunt)
        self.reports_page = ReportsPage(statistics_service, self.filters)
        self.pages: dict[str, QWidget] = {
            "dashboard": self.dashboard_page,
            "all_sessions": self.all_sessions_page,
            "hunts": self.hunts_page,
            "bosses": self.bosses_page,
            "dps": DpsPage(dps_service or DpsService(hunt_service.database)),
            "reports": self.reports_page,
            "items": EntityReportPage(
                "Itens", "Drops e supplies ao longo das Hunts filtradas",
                [EntityKind.DROPS, EntityKind.SUPPLIES], hunt_service, statistics_service,
                self.filters, self.open_hunt),
            "enemies": EntityReportPage(
                "Inimigos", "Pokémon derrotados ao longo das Hunts filtradas",
                [EntityKind.ENEMIES], hunt_service, statistics_service,
                self.filters, self.open_hunt),
            "prices": PricesPage(price_service or PriceService(hunt_service.database)),
            "settings": SettingsPage(hunt_service, database_path, backup_service,
                                     settings_store, settings),
        }
        self.settings_page: SettingsPage = self.pages["settings"]
        self.settings_page.data_replaced.connect(self._on_data_replaced)
        self.settings_page.restart_requested.connect(self._request_restart)

        self.stack = QStackedWidget()
        for page in self.pages.values():
            self.stack.addWidget(page)

        self.sidebar = Sidebar(NAV_ITEMS, self._build_import_menu())
        self.sidebar.section_selected.connect(self.show_page)
        self.sidebar.about_requested.connect(self._show_about)
        self.section_bar = SectionBar()
        self.section_bar.selected.connect(self.show_page)
        self._section: str | None = None
        # Ao voltar a uma seção, abre a última sub-página usada nela.
        self._last_in_section = {section: pages[0][0] for section, pages in SECTION_PAGES.items()}

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        content.addWidget(self.section_bar)
        content.addWidget(self.stack, 1)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addLayout(content, 1)
        self.setCentralWidget(central)

        # Arrastar e soltar arquivos .json/.tsv ou pastas em qualquer ponto da janela.
        self.setAcceptDrops(True)
        self.drop_overlay = DropOverlay(central)

        for button in self.findChildren(ExportButton):
            button.exported.connect(self._announce_export)
        self._add_window_shortcuts()
        # A barra de status só aparece enquanto há uma mensagem para mostrar.
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().messageChanged.connect(
            lambda text: self.statusBar().setVisible(bool(text)))
        self.statusBar().hide()
        self.show_page("dashboard")

    def _build_import_menu(self) -> QMenu:
        """Menu do botão Importar; as ações ficam na janela para os atalhos valerem sempre."""
        menu = QMenu(self)
        import_action = QAction(icon("import"), "Arquivos JSON/TSV…", self)
        import_action.setShortcut(QKeySequence("Ctrl+I"))
        import_action.triggered.connect(self.importer.choose_and_import)
        folder_action = QAction(icon("folder"), "Pasta inteira…", self)
        folder_action.setShortcut(QKeySequence("Ctrl+Shift+I"))
        folder_action.triggered.connect(self.importer.choose_folder_and_import)
        paste_action = QAction(icon("paste"), "Colar texto…", self)
        paste_action.setShortcut(QKeySequence("Ctrl+Shift+V"))
        paste_action.triggered.connect(self.importer.paste_and_import)
        menu.addActions([import_action, folder_action, paste_action])
        self.addActions([import_action, folder_action, paste_action])
        return menu

    def _add_window_shortcuts(self) -> None:
        refresh_action = QAction(self)
        refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        refresh_action.triggered.connect(self.refresh_current_page)
        quit_action = QAction(self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        self.addActions([refresh_action, quit_action])

    # ------------------------------------------------------------ navegação

    def show_page(self, key: str) -> None:
        """Abre uma seção (última sub-página usada), uma página ou um tipo de boss."""
        key = self._last_in_section.get(key, key)
        if key == "bosses":
            key = boss_key(self.bosses_page.current_category)
        if key.startswith(BOSS_KEY_PREFIX):
            self.bosses_page.select_category(
                Category.from_value(key.removeprefix(BOSS_KEY_PREFIX)))
            page = self.bosses_page
        else:
            page = self.pages[key]

        section = next((name for name, pages in SECTION_PAGES.items()
                        if any(sub_key == key for sub_key, _label in pages)), key)
        if section != self._section:
            self._section = section
            self.section_bar.set_items(SECTION_PAGES.get(section, ()))
            self.section_bar.setVisible(section in SECTION_PAGES)
        if section in SECTION_PAGES:
            self._last_in_section[section] = key
        self.sidebar.set_current(section)
        self.section_bar.set_current(key)
        self.stack.setCurrentWidget(page)
        self._attach_filter_panel(page)
        self.refresh_current_page()

    def _attach_filter_panel(self, page: QWidget) -> None:
        """Move o painel de filtros (instância única) para a página exibida."""
        slot = getattr(page, "filter_slot", None)
        if slot is None:
            self.filter_panel.hide()
            return
        slot.addWidget(self.filter_panel)
        self.filter_panel.set_options(self._hunt_service.filter_options())
        self.filter_panel.show()

    def _announce_export(self, path: str) -> None:
        self.statusBar().showMessage(f"Exportado: {path}", 10000)

    def open_hunt(self, hunt_id: int) -> None:
        dialog = show_hunt_details(self._hunt_service, hunt_id, self)
        if dialog is not None:
            dialog.hunt_changed.connect(lambda _id: self.refresh_current_page())

    def _update_session_counts(self) -> None:
        """Quantas sessões há em cada categoria, nos rótulos da sub-navegação de Sessões."""
        if self._section != "sessions":
            return
        counts = {"all_sessions": EMPTY_FILTER,
                  "hunts": EMPTY_FILTER.scoped(Category.HUNT),
                  **{boss_key(category): EMPTY_FILTER.scoped(category)
                     for category in BOSS_CATEGORIES}}
        for key, label in SECTION_PAGES["sessions"]:
            count = self._hunt_service.count_hunts(counts[key])
            self.section_bar.set_label(key, f"{label} ({count})" if count else label)

    def refresh_current_page(self) -> None:
        self._update_session_counts()
        page = self.stack.currentWidget()
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def _import_category(self) -> Category | None:
        """Categoria das importações: a aba de Bosses aberta; fora dela, automática."""
        if self.stack.currentWidget() is self.bosses_page:
            return self.bosses_page.current_category
        return None

    def _on_hunts_imported(self, hunt_ids: list[int]) -> None:
        """Mostra as sessões importadas na página (e aba) da categoria em que entraram."""
        summaries = self._hunt_service.get_summaries(hunt_ids)
        counts = Counter(Category.from_value(summary.category) for summary in summaries)
        target = counts.most_common(1)[0][0] if counts else Category.HUNT
        ids = [s.id for s in summaries if Category.from_value(s.category) is target]
        if target.is_boss:
            self.show_page(boss_key(target))
            self.bosses_page.show_category(target, ids)
            selected = self.bosses_page.views[target].sessions.selected_ids()
        else:
            self.show_page("hunts")
            self.hunts_page.select_hunts(ids)
            selected = self.hunts_page.selected_ids()
        if len(counts) > 1:
            parts = ", ".join(f"{count} em {category.plural}"
                              for category, count in counts.most_common())
            self.statusBar().showMessage(f"Sessões importadas: {parts}.", 10000)
        hidden = len(ids) - len(selected)
        if hidden > 0:
            self.statusBar().showMessage(
                f"{hidden} sessão(ões) importada(s) não aparecem por causa dos filtros ativos.",
                8000)

    def _on_data_replaced(self) -> None:
        """Após restaurar um backup: limpa filtros e recarrega listas e contagens."""
        self.filters.clear()
        self.filter_panel.set_options(self._hunt_service.filter_options())
        self.refresh_current_page()

    def _request_restart(self) -> None:
        if self._restart is not None:
            self._restart()
        else:
            QMessageBox.information(self, APP_NAME,
                                    "Feche e abra o aplicativo para aplicar as alterações.")

    # ------------------------------------------------------ arrastar e soltar

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if dropped_paths(event.mimeData()):
            event.acceptProposedAction()
            self.drop_overlay.show_over_parent()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self.drop_overlay.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self.drop_overlay.hide()
        paths = dropped_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        # Importa depois de concluir o arrastar (o Explorer fica esperando até o fim do evento).
        QTimer.singleShot(0, lambda: self.importer.import_paths(paths))

    def _show_about(self) -> None:
        QMessageBox.about(
            self, f"Sobre o {APP_NAME}",
            f"<b>{APP_NAME}</b> {APP_VERSION}<br><br>"
            "Histórico, análise e relatórios das Hunts exportadas pelo Analyzer do PokeXGames.",
        )
