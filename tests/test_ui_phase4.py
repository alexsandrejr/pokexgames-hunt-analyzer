"""Fase 4: importação em lote e arrastar e soltar, configurações, backup/restauração, temas."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.application import open_database, run_automatic_backup  # noqa: E402
from app.config import backups_dir_for  # noqa: E402
from app.database.database import Database  # noqa: E402
from app.database.migrations import LATEST_VERSION  # noqa: E402
from app.database.models import Base  # noqa: E402
from app.services.backup_service import BackupKind, BackupService  # noqa: E402
from app.services.dto import ImportStatus  # noqa: E402
from app.services.hunt_service import HuntService  # noqa: E402
from app.services.settings_service import AppSettings, SettingsStore  # noqa: E402
from app.services.statistics_service import StatisticsService  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.utils import formatters  # noqa: E402
from tests.helpers import SAMPLE_HUNT_PATH, sample_text  # noqa: E402


class Phase4UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        theme.apply_theme(cls.app)

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "data" / "hunts.db"
        self.database = open_database(self.db_path)
        self.hunts = HuntService(self.database)
        self.backups = BackupService(self.database, backups_dir_for(self.db_path))
        self.store = SettingsStore(self.root / "data" / "settings.json")
        self.restarts: list[bool] = []
        self.window = MainWindow(self.hunts, StatisticsService(self.database), self.db_path,
                                 self.backups, self.store, AppSettings(),
                                 restart=lambda: self.restarts.append(True))
        self.reports: list[tuple[str, list[str]]] = []
        importer = self.window.importer
        importer.show_batch_report = lambda summary, details: self.reports.append(
            (summary, details))
        importer.confirm_duplicate = self._fail_if_asked
        self.window.show()

    def tearDown(self) -> None:
        formatters.set_number_format("pt-BR")
        self.window.close()
        self.window.deleteLater()
        self.database.dispose()
        self._tmp.cleanup()

    def _fail_if_asked(self, _result) -> bool:
        raise AssertionError("A importação em lote não deve perguntar sobre duplicatas.")

    def _make_folder(self) -> Path:
        folder = self.root / "exports"
        (folder / "sub").mkdir(parents=True)
        shutil.copy(SAMPLE_HUNT_PATH, folder / "a.json")
        shutil.copy(SAMPLE_HUNT_PATH, folder / "sub" / "a_copia.JSON")  # duplicata
        (folder / "b.json").write_text(sample_text(**{"Session ID": 2,
                                                      "Start": "2026-09-27 10:00:00"}))
        (folder / "quebrado.json").write_text("{ nada")
        (folder / "notas.txt").write_text("ignorar")
        return folder

    # ------------------------------------------------------------ importação

    def test_folder_import_skips_duplicates_and_reports(self) -> None:
        results = self.window.importer.import_paths([self._make_folder()])
        statuses = sorted(r.status.value for r in results)
        self.assertEqual(statuses, ["duplicate", "error", "imported", "imported"])
        self.assertEqual(self.hunts.count_hunts(), 2)
        [(summary, details)] = self.reports
        self.assertEqual(summary, "Importação concluída: 2 importada(s), "
                                  "1 duplicada(s) ignorada(s), 1 com erro.")
        self.assertTrue(any("quebrado.json: JSON inválido." in line for line in details))
        self.assertTrue(any("já importada" in line for line in details))
        self.assertIs(self.window.stack.currentWidget(), self.window.hunts_page)

    def test_folder_without_json(self) -> None:
        empty = self.root / "vazia"
        empty.mkdir()
        self.assertEqual(self.window.importer.import_paths([empty]), [])
        self.assertEqual(self.reports, [("Nenhum arquivo .json ou .tsv foi encontrado.", [])])

    def test_drag_and_drop(self) -> None:
        folder = self._make_folder()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(folder / "a.json")),
                      QUrl.fromLocalFile(str(folder / "b.json")),
                      QUrl.fromLocalFile(str(folder / "notas.txt")),
                      QUrl("https://example.com/x.json")])
        enter = QDragEnterEvent(QPoint(50, 50), Qt.DropAction.CopyAction, mime,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.window.dragEnterEvent(enter)
        self.assertTrue(enter.isAccepted())
        self.assertTrue(self.window.drop_overlay.isVisible())

        drop = QDropEvent(QPoint(50, 50), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.window.dropEvent(drop)
        self.assertFalse(self.window.drop_overlay.isVisible())
        for _ in range(3):
            self.app.processEvents()  # a importação roda logo após o drop
        self.assertEqual(self.hunts.count_hunts(), 2)

    def test_drag_of_unsupported_files_is_refused(self) -> None:
        (self.root / "x.txt").write_text("x")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.root / "x.txt"))])
        enter = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.window.dragEnterEvent(enter)
        self.assertFalse(enter.isAccepted())
        self.assertFalse(self.window.drop_overlay.isVisible())

    def test_single_duplicate_still_asks(self) -> None:
        self.hunts.import_file(SAMPLE_HUNT_PATH)
        asked: list[bool] = []
        self.window.importer.confirm_duplicate = lambda result: asked.append(True) or False
        [result] = self.window.importer.import_paths([SAMPLE_HUNT_PATH])
        self.assertEqual(result.status, ImportStatus.DUPLICATE)
        self.assertEqual(asked, [True])

    # --------------------------------------------------------------- configurações

    def test_backup_and_restore_from_settings(self) -> None:
        self.hunts.import_file(SAMPLE_HUNT_PATH)
        self.window.show_page("settings")
        page = self.window.settings_page
        backup = page.backup_now()
        self.assertTrue(backup.exists())
        self.assertEqual(page.backups_table.source_model.rowCount(), 1)

        self.hunts.import_text(sample_text(**{"Session ID": 9, "Start": "2026-09-28 10:00:00"}))
        self.window.filters.set_filter(self.window.filters.current.__class__(player="Royal"))
        page.confirm_restore = lambda path, count: True
        safety = page.restore_from(backup)
        self.assertIsNotNone(safety)
        self.assertEqual(self.hunts.count_hunts(), 1)
        self.assertTrue(self.window.filters.current.is_empty)  # filtros limpos
        kinds = [b.kind for b in self.backups.list_backups()]
        self.assertIn(BackupKind.BEFORE_RESTORE, kinds)
        self.assertIn("Backup restaurado", self.window.statusBar().currentMessage())

    def test_restore_cancelled_changes_nothing(self) -> None:
        self.hunts.import_file(SAMPLE_HUNT_PATH)
        page = self.window.settings_page
        backup = page.backup_now()
        self.hunts.import_text(sample_text(**{"Session ID": 9, "Start": "2026-09-28 10:00:00"}))
        page.confirm_restore = lambda path, count: False
        self.assertIsNone(page.restore_from(backup))
        self.assertEqual(self.hunts.count_hunts(), 2)

    def test_number_format_applies_immediately_and_is_saved(self) -> None:
        self.hunts.import_file(SAMPLE_HUNT_PATH)
        page = self.window.settings_page
        page.number_combo.setCurrentIndex(page.number_combo.findData("en-US"))
        self.assertEqual(self.store.load().number_format, "en-US")
        self.window.show_page("hunts")
        profit = self.window.hunts_page._table.model().index(0, 6).data()
        self.assertEqual(profit, "1,119,522")

    def test_theme_and_database_changes_ask_for_restart(self) -> None:
        page = self.window.settings_page
        page.theme_combo.setCurrentIndex(page.theme_combo.findData("light"))
        self.assertEqual(self.store.load().theme, "light")
        self.assertTrue(page._restart_notice.isVisibleTo(page))

        other = self.root / "outro" / "novo.db"
        page.set_database_path(other)
        self.assertEqual(self.store.load().database_path, str(other.resolve()))
        self.assertIn("será criado", page._restart_label.text())
        self.assertTrue(page.default_db_button.isEnabled())
        page.set_database_path(None)
        self.assertIsNone(self.store.load().database_path)

        page.restart_requested.emit()
        self.assertEqual(self.restarts, [True])

    def test_invalid_database_file_is_rejected(self) -> None:
        bad = self.root / "texto.db"
        bad.write_text("não é banco")
        warnings: list[str] = []
        import app.ui.settings.settings_widget as module
        original = module.QMessageBox.warning
        module.QMessageBox.warning = lambda *args: warnings.append(args[2])
        try:
            self.window.settings_page.set_database_path(bad)
        finally:
            module.QMessageBox.warning = original
        self.assertEqual(len(warnings), 1)
        self.assertIsNone(self.store.load().database_path)

    def test_backup_options_are_saved(self) -> None:
        page = self.window.settings_page
        page.auto_backup_check.setChecked(False)
        page.keep_spin.setValue(4)
        saved = self.store.load()
        self.assertEqual((saved.auto_backup, saved.backups_to_keep), (False, 4))


class StartupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        # Limpezas rodam na ordem inversa: o banco é fechado antes de apagar a pasta.
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "hunts.db"

    def test_old_database_gets_backup_before_migration(self) -> None:
        old = Database.from_path(self.path)
        Base.metadata.create_all(old.engine)
        HuntService(old).import_file(SAMPLE_HUNT_PATH)
        old.dispose()

        database = open_database(self.path)
        self.addCleanup(database.dispose)
        self.assertEqual(database.schema_version(), LATEST_VERSION)
        backups = BackupService(database, backups_dir_for(self.path)).list_backups()
        self.assertEqual([b.kind for b in backups], [BackupKind.BEFORE_MIGRATION])

    def test_new_database_has_no_migration_backup(self) -> None:
        database = open_database(self.path)
        self.addCleanup(database.dispose)
        self.assertEqual(BackupService(database, backups_dir_for(self.path)).list_backups(), [])

    def test_automatic_backup_follows_settings(self) -> None:
        database = open_database(self.path)
        self.addCleanup(database.dispose)
        HuntService(database).import_file(SAMPLE_HUNT_PATH)
        backups = BackupService(database, backups_dir_for(self.path))
        run_automatic_backup(backups, AppSettings(auto_backup=False))
        self.assertEqual(backups.list_backups(), [])
        run_automatic_backup(backups, AppSettings(auto_backup=True))
        self.assertEqual([b.kind for b in backups.list_backups()], [BackupKind.AUTOMATIC])


class TranslationTests(unittest.TestCase):
    def test_qt_standard_texts_in_portuguese(self) -> None:
        from PySide6.QtCore import QCoreApplication

        from app.application import install_qt_translation
        app = QApplication.instance() or QApplication([])
        self.assertTrue(install_qt_translation(app))
        # Texto usado nos botões padrão das caixas de mensagem.
        self.assertEqual(QCoreApplication.translate("QPlatformTheme", "&Yes"), "&Sim")


class ThemeTests(unittest.TestCase):
    def tearDown(self) -> None:
        theme.use_palette("dark")

    def test_palettes_have_same_keys(self) -> None:
        self.assertEqual(set(theme.PALETTES["dark"]), set(theme.PALETTES["light"]))

    def test_use_palette_updates_shared_colors(self) -> None:
        from app.ui.charts.charts import CHART
        from app.ui.theme import COLORS
        self.assertEqual(theme.use_palette("light"), "light")
        self.assertEqual(COLORS["surface"], "#ffffff")
        self.assertEqual(CHART["series"], "#2a78d6")  # gráficos leem o tema ativo
        self.assertEqual(theme.use_palette("inexistente"), "dark")
        self.assertEqual(CHART["series"], "#3987e5")


if __name__ == "__main__":
    unittest.main()
