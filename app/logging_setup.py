"""Log em arquivo e tratamento de erros não previstos.

No executável não há console: sem isto, um erro inesperado fecharia o
aplicativo sem nenhuma pista. Aqui o erro vai para ``logs/app.log`` e o
usuário vê uma mensagem com o caminho do arquivo para enviar a quem o ajuda.
"""

from __future__ import annotations

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

LOG_FILE_NAME = "app.log"
MAX_LOG_BYTES = 1_000_000
LOG_BACKUPS = 3

logger = logging.getLogger("pxg")


def setup_logging(logs_dir: Path) -> Path | None:
    """Configura o log rotativo; retorna o arquivo (ou ``None`` se não for gravável)."""
    logger.setLevel(logging.INFO)
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        path = logs_dir / LOG_FILE_NAME
        handler = RotatingFileHandler(path, maxBytes=MAX_LOG_BYTES, backupCount=LOG_BACKUPS,
                                      encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.handlers = [handler]
    return path


def install_exception_hook(log_file: Path | None) -> None:
    """Registra erros não tratados e avisa o usuário, sem fechar o aplicativo."""

    def hook(exc_type: type[BaseException], exc: BaseException,
             tb: TracebackType | None) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logger.error("Erro não tratado:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        _show_error_dialog(exc, log_file)

    sys.excepthook = hook


def _show_error_dialog(exc: BaseException, log_file: Path | None) -> None:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:  # pragma: no cover
        return
    if QApplication.instance() is None:
        return
    where = f"\n\nDetalhes gravados em:\n{log_file}" if log_file else ""
    box = QMessageBox(QMessageBox.Icon.Critical, "Erro inesperado",
                      f"Ocorreu um erro inesperado: {exc}{where}\n\n"
                      "O aplicativo continua aberto, mas a última ação pode não ter sido "
                      "concluída.")
    box.setDetailedText("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    box.exec()
