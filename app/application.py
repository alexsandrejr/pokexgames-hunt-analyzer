"""Montagem da aplicação: configurações, banco, backups, tema e janela principal."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QProcess, QTimer, QTranslator
from PySide6.QtWidgets import QApplication, QMessageBox

from app.config import (
    IS_FROZEN,
    LOGS_DIR,
    PATHS,
    SETTINGS_PATH,
    backups_dir_for,
    get_database_path,
)
from app.database.database import Database
from app.database.migrations import SchemaTooNewError
from app.logging_setup import install_exception_hook, logger, setup_logging
from app.services.backup_service import BackupError, BackupKind, BackupService
from app.services.hunt_service import HuntService
from app.services.settings_service import AppSettings, SettingsStore
from app.services.statistics_service import StatisticsService
from app.ui.icons import icon
from app.ui.main_window import NAV_ITEMS, MainWindow
from app.ui.theme import apply_theme, use_palette
from app.utils.constants import APP_NAME, APP_VERSION, ORGANIZATION_NAME
from app.utils.formatters import set_number_format

WINDOWS_APP_ID = "pokexgames.hunt-analyzer"
SMOKE_TEST_ARG = "--smoke-test"  # abre, visita todas as telas e fecha (verificação do .exe)


def _set_windows_app_id() -> None:
    """Faz o Windows usar o ícone da aplicação na barra de tarefas."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    except (AttributeError, OSError):
        pass


def install_qt_translation(app: QApplication) -> bool:
    """Traduz os textos padrão do Qt (Sim/Não, Cancelar, diálogos de arquivo) para pt-BR."""
    translator = QTranslator(app)
    directory = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if not translator.load(QLocale(QLocale.Language.Portuguese, QLocale.Country.Brazil),
                           "qtbase", "_", directory):
        logger.warning("Tradução pt-BR do Qt não encontrada em %s", directory)
        return False
    return app.installTranslator(translator)


def restart_application() -> None:
    """Abre uma nova instância com os mesmos argumentos e encerra a atual."""
    # No executável, sys.argv[0] já é o próprio .exe; em desenvolvimento, é o main.py.
    arguments = sys.argv[1:] if IS_FROZEN else sys.argv
    QProcess.startDetached(sys.executable, arguments)
    QApplication.quit()


def open_database(path: Path, backups: BackupService | None = None) -> Database:
    """Abre o banco e o atualiza, com backup antes de migrar um banco existente."""
    database = Database.from_path(path)
    had_data = path.exists() and path.stat().st_size > 0
    if had_data and database.pending_migrations():
        backup_service = backups or BackupService(database, backups_dir_for(path))
        try:
            backup_service.create_backup(BackupKind.BEFORE_MIGRATION)
        except BackupError as exc:  # não impede a abertura; a migração só cria índices/colunas
            logger.warning("Backup antes da atualização não realizado: %s", exc)
    database.create_schema()
    return database


def run_automatic_backup(backups: BackupService, settings: AppSettings) -> None:
    if not settings.auto_backup:
        return
    try:
        backups.automatic_backup_if_due(settings.backups_to_keep)
    except BackupError as exc:
        logger.warning("Backup automático não realizado: %s", exc)  # nunca impede o uso


def _schedule_smoke_test(window: MainWindow) -> None:
    """Visita todas as telas e encerra: código 0 se nada falhou, 1 caso contrário."""

    def visit() -> None:
        try:
            for item in NAV_ITEMS:
                window.show_page(item.key)
        except Exception:  # noqa: BLE001
            logger.exception("Smoke test falhou")
            QApplication.exit(1)
            return
        logger.info("Smoke test concluído")
        QApplication.exit(0)

    QTimer.singleShot(500, visit)


def run(argv: Sequence[str] | None = None) -> int:
    _set_windows_app_id()
    arguments = list(argv) if argv is not None else sys.argv
    log_file = setup_logging(LOGS_DIR)
    install_exception_hook(log_file)
    logger.info("Iniciando %s %s (executável: %s, dados: %s%s)", APP_NAME, APP_VERSION,
                IS_FROZEN, PATHS.data_dir, ", portátil" if PATHS.portable else "")

    app = QApplication(arguments)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORGANIZATION_NAME)
    install_qt_translation(app)

    store = SettingsStore(SETTINGS_PATH)
    settings = store.load()
    set_number_format(settings.number_format)
    use_palette(settings.theme)  # antes de criar qualquer widget
    app.setWindowIcon(icon("app"))
    apply_theme(app)

    database_path = get_database_path(settings.database_path)
    try:
        database = open_database(database_path)
    except SchemaTooNewError as exc:
        logger.error("%s", exc)
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001 - qualquer falha aqui impede o uso do app
        logger.exception("Falha ao abrir o banco %s", database_path)
        QMessageBox.critical(None, APP_NAME, "Não foi possível abrir o banco de dados:\n"
                             f"{database_path}\n\n{exc}")
        return 1
    logger.info("Banco: %s (versão %s)", database_path, database.schema_version())

    backups = BackupService(database, backups_dir_for(database_path))
    run_automatic_backup(backups, settings)

    window = MainWindow(HuntService(database), StatisticsService(database), database_path,
                        backups, store, settings, restart=restart_application)
    window.show()
    if SMOKE_TEST_ARG in arguments:
        _schedule_smoke_test(window)
    exit_code = app.exec()
    logger.info("Encerrado com código %s", exit_code)
    database.dispose()
    return exit_code
