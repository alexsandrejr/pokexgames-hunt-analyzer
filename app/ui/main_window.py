"""Janela principal: sidebar + páginas empilhadas + menu."""

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
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QMessageBox, QStackedWidget, QWidget

from app.services.backup_service import BackupService
from app.services.categories import Category
from app.services.entity_report import EntityKind
from app.services.hunt_service import HuntService
from app.services.price_service import PriceService
from app.services.settings_service import AppSettings, SettingsStore
from app.services.statistics_service import StatisticsService
from app.ui.bosses.bosses_widget import BossesPage
from app.ui.dashboard.dashboard_widget import DashboardPage
from app.ui.hunts.hunts_widget import HuntsPage
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
from app.utils.constants import APP_NAME, APP_VERSION

NAV_ITEMS = [
    NavItem("dashboard", "Dashboard", "dashboard"),
    NavItem("hunts", "Hunts", "hunts"),
    NavItem("bosses", "Bosses", "bosses"),
    NavItem("reports", "Relatórios", "reports"),
    NavItem("items", "Itens", "items"),
    NavItem("enemies", "Inimigos", "enemies"),
    NavItem("prices", "Preços", "prices"),
    NavItem("settings", "Configurações", "settings"),
]


class MainWindow(QMainWindow):
    def __init__(self, hunt_service: HuntService, statistics_service: StatisticsService,
                 database_path: Path, backup_service: BackupService | None = None,
                 settings_store: SettingsStore | None = None,
                 settings: AppSettings | None = None,
                 restart: Callable[[], None] | None = None,
                 price_service: PriceService | None = None) -> None:
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
        self.hunts_page = HuntsPage(hunt_service, self.importer, self.filters)
        self.bosses_page = BossesPage(hunt_service, statistics_service, self.importer,
                                      self.filters, self.open_hunt)
        self.reports_page = ReportsPage(statistics_service, self.filters)
        self.pages: dict[str, QWidget] = {
            "dashboard": self.dashboard_page,
            "hunts": self.hunts_page,
            "bosses": self.bosses_page,
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
        for item in NAV_ITEMS:
            self.stack.addWidget(self.pages[item.key])

        self.sidebar = Sidebar(NAV_ITEMS)
        self.sidebar.page_selected.connect(self.show_page_index)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        # Arrastar e soltar arquivos .json/.tsv ou pastas em qualquer ponto da janela.
        self.setAcceptDrops(True)
        self.drop_overlay = DropOverlay(central)

        for button in self.findChildren(ExportButton):
            button.exported.connect(self._announce_export)
        self._build_menu()
        self.statusBar().showMessage("Pronto", 3000)
        self.show_page("dashboard")

    def _build_menu(self) -> None:
        hunts_menu = self.menuBar().addMenu("&Hunts")
        import_action = QAction(icon("import"), "&Importar JSON/TSV…", self)
        import_action.setShortcut(QKeySequence("Ctrl+I"))
        import_action.triggered.connect(self.importer.choose_and_import)
        folder_action = QAction(icon("folder"), "Importar &pasta…", self)
        folder_action.setShortcut(QKeySequence("Ctrl+Shift+I"))
        folder_action.triggered.connect(self.importer.choose_folder_and_import)
        paste_action = QAction(icon("paste"), "&Colar JSON/TSV…", self)
        paste_action.setShortcut(QKeySequence("Ctrl+Shift+V"))
        paste_action.triggered.connect(self.importer.paste_and_import)
        refresh_action = QAction(icon("refresh"), "&Atualizar", self)
        refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        refresh_action.triggered.connect(self.refresh_current_page)
        quit_action = QAction("&Sair", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        hunts_menu.addActions([import_action, folder_action, paste_action, refresh_action])
        hunts_menu.addSeparator()
        hunts_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("A&juda")
        about_action = QAction("&Sobre", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    # ------------------------------------------------------------ navegação

    def show_page(self, key: str) -> None:
        self.show_page_index([item.key for item in NAV_ITEMS].index(key))

    def show_page_index(self, index: int) -> None:
        self.sidebar.set_current(index)
        self.stack.setCurrentIndex(index)
        self._attach_filter_panel(self.stack.currentWidget())
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
        show_hunt_details(self._hunt_service, hunt_id, self)

    def refresh_current_page(self) -> None:
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
            self.show_page("bosses")
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
