"""Instalação feita pelo ``.exe`` novo (``--apply-update <pasta> <pid>``), antes de abrir o banco."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from threading import Thread

from PySide6.QtCore import QEventLoop, QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from app.config import IS_FROZEN, SETTINGS_PATH
from app.logging_setup import logger
from app.services.settings_service import SettingsStore
from app.services.update_service import (
    APPLY_UPDATE_ARG,
    EXE_NAME,
    UpdateError,
    apply_update,
    relaunch,
    wait_for_exit,
)
from app.ui.icons import icon
from app.ui.theme import apply_theme, use_palette
from app.utils.constants import APP_NAME

SMOKE_TEST_ARG = "--smoke-test"


class _Signals(QObject):
    finished = Signal(str)  # vazio: deu certo


def _install(source: Path, target: Path, pid: int) -> None:
    if not wait_for_exit(pid):
        raise UpdateError("O programa antigo não fechou a tempo. Feche-o e tente de novo.")
    apply_update(source, target)


def run_install(arguments: Sequence[str]) -> int:
    """Troca os arquivos e abre o programa; em caso de falha, abre a versão antiga."""
    position = list(arguments).index(APPLY_UPDATE_ARG)
    try:
        target = Path(arguments[position + 1])
        pid = int(arguments[position + 2])
    except (IndexError, ValueError):
        logger.error("Argumentos inválidos para a atualização: %s", arguments)
        return 2
    source = Path(sys.executable).parent
    # Fora do .exe, ``source`` seria a pasta do Python: nada pode ser copiado dela.
    if not IS_FROZEN or Path(sys.executable).name != EXE_NAME:
        logger.error("A atualização só pode ser instalada pelo executável")
        return 2

    logger.info("Instalando a atualização de %s em %s", source, target)
    app = QApplication(list(arguments))
    app.setApplicationName(APP_NAME)
    use_palette(SettingsStore(SETTINGS_PATH).load().theme)
    app.setWindowIcon(icon("app"))
    apply_theme(app)
    window = QProgressDialog("Instalando a atualização…", "", 0, 0)
    window.setWindowTitle(APP_NAME)
    window.setCancelButton(None)
    window.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
    window.setMinimumDuration(0)
    window.show()

    errors: list[str] = []
    loop = QEventLoop()
    signals = _Signals()

    def work() -> None:
        try:
            _install(source, target, pid)
            signals.finished.emit("")
        except Exception as exc:  # noqa: BLE001 - qualquer falha precisa chegar à pessoa
            logger.exception("Falha ao instalar a atualização")
            signals.finished.emit(str(exc) or type(exc).__name__)

    def done(message: str) -> None:
        if message:
            errors.append(message)
        loop.quit()

    signals.finished.connect(done)
    Thread(target=work, name="update-install", daemon=True).start()
    loop.exec()
    window.close()

    smoke_test = SMOKE_TEST_ARG in arguments  # usado pelo build_exe.py
    if errors and not smoke_test:
        QMessageBox.critical(None, APP_NAME, f"A atualização não foi instalada.\n\n{errors[0]}")
    if not smoke_test and (target / EXE_NAME).is_file():
        try:
            relaunch(target, source)
        except OSError as exc:
            logger.exception("Falha ao reabrir o programa")
            QMessageBox.critical(None, APP_NAME, "O programa não pôde ser aberto de novo. "
                                 f"Abra-o pela pasta {target}.\n\n{exc}")
            return 1
    logger.info("Atualização %s", "falhou" if errors else "instalada")
    return 1 if errors else 0
