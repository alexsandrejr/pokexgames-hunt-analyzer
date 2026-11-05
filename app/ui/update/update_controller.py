"""Verifica se há versão nova sem travar a janela e conduz a atualização."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from threading import Thread

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from app.logging_setup import logger
from app.services.update_service import (
    ReleaseInfo,
    UpdateError,
    UpdateService,
    can_install_itself,
    start_installer,
)
from app.ui.update.update_dialog import UpdateDialog
from app.utils.constants import APP_VERSION

MODAL_RETRY_MS = 5000


class UpdateController(QObject):
    status_changed = Signal(str)
    checking_changed = Signal(bool)
    _checked = Signal(object, bool)
    _check_failed = Signal(str, bool)

    def __init__(self, window: QWidget, service: UpdateService, *, frozen: bool = False,
                 executable: Path | None = None,
                 install: Callable[[Path, Path, int], None] = start_installer,
                 quit_app: Callable[[], None] = QApplication.quit,
                 show_dialog: Callable[[UpdateDialog], int] | None = None) -> None:
        super().__init__(window)
        self._window = window
        self._service = service
        executable = executable or Path(sys.executable)
        self._install_dir = executable.parent if can_install_itself(frozen, executable) else None
        self._install = install
        self._quit_app = quit_app
        self._show_dialog = show_dialog or UpdateDialog.exec
        self._checking = False
        self._checked.connect(self._on_checked)
        self._check_failed.connect(self._on_check_failed)

    def check(self, *, silent: bool = False) -> None:
        """Verifica em outra thread. Em ``silent``, só aparece algo se houver versão nova."""
        if self._checking:
            return
        self._checking = True
        self.checking_changed.emit(True)
        if not silent:
            self.status_changed.emit("Verificando…")
        Thread(target=self._run_check, args=(silent,), name="update-check", daemon=True).start()

    def _run_check(self, silent: bool) -> None:
        """Roda em outra thread; só se comunica com a interface por sinais."""
        try:
            self._checked.emit(self._service.check(), silent)
        except UpdateError as exc:
            logger.info("Verificação de atualização não concluída: %s", exc)
            self._check_failed.emit(str(exc), silent)
        except Exception as exc:  # noqa: BLE001 - a thread não pode morrer calada
            logger.exception("Falha inesperada ao verificar atualizações")
            self._check_failed.emit(f"Falha inesperada na verificação: {exc}", silent)

    def _on_check_failed(self, message: str, silent: bool) -> None:
        self._finish_check()
        # Sem internet ao abrir o app não é um problema a mostrar.
        if not silent:
            self.status_changed.emit(message)

    def _on_checked(self, release: ReleaseInfo | None, silent: bool) -> None:
        self._finish_check()
        if release is None:
            if not silent:
                self.status_changed.emit(f"Você já está na versão mais recente ({APP_VERSION}).")
            return
        self.status_changed.emit(f"Versão {release.version} disponível.")
        self._offer(release)

    def _finish_check(self) -> None:
        self._checking = False
        self.checking_changed.emit(False)

    def _offer(self, release: ReleaseInfo) -> None:
        # Não interrompe quem está com outra janela aberta, como o cadastro de um pokémon.
        if QApplication.activeModalWidget() is not None:
            QTimer.singleShot(MODAL_RETRY_MS, self, lambda: self._offer(release))
            return
        dialog = UpdateDialog(release, self._service, self._install_dir, self._window)
        if self._show_dialog(dialog) != UpdateDialog.DialogCode.Accepted:
            return
        self.install(dialog.new_root)

    def install(self, new_root: Path) -> None:
        """Abre o instalador da versão nova e fecha o app para ele trocar os arquivos."""
        try:
            self._install(new_root, self._install_dir, QApplication.applicationPid())
        except UpdateError as exc:
            logger.error("%s", exc)
            QMessageBox.warning(self._window, "Atualização", str(exc))
            return
        logger.info("Instalador da atualização aberto; encerrando")
        self._quit_app()
