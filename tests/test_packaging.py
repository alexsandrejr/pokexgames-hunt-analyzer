"""Caminhos por modo de execução (desenvolvimento, executável, portátil) e log de erros."""

import logging
import sys
import tempfile
import unittest
from pathlib import Path

import app.logging_setup as logging_setup
from app.config import APP_DIR_NAME, resolve_paths
from app.logging_setup import install_exception_hook, logger, setup_logging


class ResolvePathsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.exe = self.root / "app" / "PokeXGames Hunt Analyzer.exe"
        self.exe.parent.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_development_uses_project_folders(self) -> None:
        paths = resolve_paths(False, None, Path("python.exe"), None, project_root=self.root)
        self.assertEqual(paths.data_dir, self.root / "data")
        self.assertEqual(paths.resources_dir, self.root / "resources")
        self.assertEqual(paths.imports_dir, self.root / "imports")
        self.assertFalse(paths.portable)

    def test_executable_uses_local_app_data_and_bundle(self) -> None:
        bundle = self.exe.parent / "_internal"
        paths = resolve_paths(True, bundle, self.exe, str(self.root / "Local"))
        self.assertEqual(paths.data_dir, self.root / "Local" / APP_DIR_NAME)
        self.assertEqual(paths.imports_dir, self.root / "Local" / APP_DIR_NAME / "imports")
        self.assertEqual(paths.resources_dir, bundle / "resources")
        self.assertFalse(paths.portable)

    def test_executable_without_localappdata(self) -> None:
        paths = resolve_paths(True, None, self.exe, None)
        self.assertEqual(paths.data_dir, Path.home() / "AppData" / "Local" / APP_DIR_NAME)
        self.assertEqual(paths.resources_dir, self.exe.parent / "resources")

    def test_portable_mode_when_data_folder_is_next_to_exe(self) -> None:
        (self.exe.parent / "data").mkdir()
        paths = resolve_paths(True, None, self.exe, str(self.root / "Local"))
        self.assertTrue(paths.portable)
        self.assertEqual(paths.data_dir, self.exe.parent / "data")


class LoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_hook = sys.excepthook
        self._old_handlers = list(logger.handlers)
        # O diálogo de erro é modal; no teste, só registramos que ele seria exibido.
        self.dialogs: list[str] = []
        self._old_dialog = logging_setup._show_error_dialog
        logging_setup._show_error_dialog = lambda exc, log: self.dialogs.append(str(exc))

    def tearDown(self) -> None:
        for handler in logger.handlers:
            handler.close()
        logger.handlers = self._old_handlers
        sys.excepthook = self._old_hook
        logging_setup._show_error_dialog = self._old_dialog
        self._tmp.cleanup()

    def test_unhandled_errors_are_written_to_log(self) -> None:
        log_file = setup_logging(Path(self._tmp.name) / "logs")
        self.assertIsNotNone(log_file)
        install_exception_hook(log_file)
        try:
            raise ValueError("falha de teste")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        for handler in logger.handlers:
            handler.flush()
        text = log_file.read_text(encoding="utf-8")
        self.assertIn("Erro não tratado", text)
        self.assertIn("ValueError: falha de teste", text)
        self.assertEqual(self.dialogs, ["falha de teste"])  # o usuário seria avisado

    def test_unwritable_log_folder_does_not_break_startup(self) -> None:
        blocker = Path(self._tmp.name) / "arquivo"
        blocker.write_text("x")
        self.assertIsNone(setup_logging(blocker / "logs"))
        logging.getLogger("pxg").info("ainda funciona")


if __name__ == "__main__":
    unittest.main()
