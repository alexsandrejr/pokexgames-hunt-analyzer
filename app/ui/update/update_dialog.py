"""Janela "Nova versão disponível": mostra as novidades, baixa e prepara a instalação."""

from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.logging_setup import logger
from app.services.update_service import (
    ReleaseInfo,
    UpdateCancelled,
    UpdateError,
    UpdateService,
    ensure_writable,
)
from app.ui.icons import icon
from app.utils.constants import APP_VERSION
from app.utils.formatters import format_number

MEGABYTE = 1024 * 1024
BAR_RESOLUTION = 1000


class _DownloadSignals(QObject):
    """Sinais emitidos pela thread do download e entregues na thread da interface."""

    progress = Signal(int, int)
    ready = Signal(object)
    failed = Signal(str)
    cancelled = Signal()


class UpdateDialog(QDialog):
    """Depois de ``accept``, ``new_root`` é a pasta extraída com a versão nova."""

    def __init__(self, release: ReleaseInfo, service: UpdateService, install_dir: Path | None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._release = release
        self._service = service
        self._install_dir = install_dir
        self._cancel = Event()
        self._downloading = False
        self.new_root: Path | None = None
        self.setWindowTitle("Nova versão disponível")
        self.setWindowIcon(icon("refresh"))
        self.resize(620, 480)

        title = QLabel(f"Versão {release.version} disponível", objectName="SectionTitle")
        current = QLabel(f"Você está na versão {APP_VERSION}.", objectName="MutedLabel")
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        if release.notes.strip():
            self.notes.setMarkdown(release.notes)
        else:
            self.notes.setPlainText("Esta versão não traz uma lista de novidades.")

        self.can_install = install_dir is not None and release.installable
        self.hint = QLabel(objectName="MutedLabel")
        self.hint.setWordWrap(True)
        self.hint.setText(self._hint_text(install_dir, release))
        self.progress = QProgressBar()
        self.progress.setRange(0, BAR_RESOLUTION)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.status_label = QLabel(objectName="MutedLabel")
        self.status_label.hide()
        self.error_label = QLabel(objectName="ErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.hide()

        self.later_button = QPushButton("Agora não")
        self.later_button.setAutoDefault(False)
        self.later_button.clicked.connect(self.reject)
        self.page_button = QPushButton("Abrir no GitHub")
        self.page_button.setAutoDefault(False)
        self.page_button.clicked.connect(self.open_page)
        self.update_button = QPushButton(icon("refresh"), "  Atualizar agora",
                                         objectName="PrimaryButton")
        self.update_button.setAutoDefault(False)
        self.update_button.clicked.connect(self.start_update)
        self.update_button.setVisible(self.can_install)
        buttons = QHBoxLayout()
        buttons.addWidget(self.page_button)
        buttons.addStretch(1)
        buttons.addWidget(self.later_button)
        buttons.addWidget(self.update_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(current)
        layout.addWidget(self.notes, 1)
        layout.addWidget(self.hint)
        layout.addWidget(self.progress)
        layout.addWidget(self.status_label)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

        self._signals = _DownloadSignals(self)
        self._signals.progress.connect(self._on_progress)
        self._signals.ready.connect(self._on_ready)
        self._signals.failed.connect(self._on_failed)
        self._signals.cancelled.connect(super().reject)

    @staticmethod
    def _hint_text(install_dir: Path | None, release: ReleaseInfo) -> str:
        if install_dir is None:
            return "A instalação automática só funciona no programa em .exe."
        if not release.installable:
            return "Este release não tem o pacote esperado. Baixe a versão pela página do GitHub."
        return ("O app baixa a versão nova, fecha e abre de novo já atualizado. Seus dados "
                "continuam no mesmo lugar, e o banco ganha um backup antes de qualquer mudança "
                "de versão.")

    def open_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self._release.page_url))

    # ---------------------------------------------------------------- download

    def start_update(self) -> None:
        if self._downloading or self._install_dir is None:
            return
        self.error_label.hide()
        try:
            ensure_writable(self._install_dir)
        except UpdateError as exc:
            self._show_error(str(exc))
            return
        self._downloading = True
        self._cancel.clear()
        self.update_button.setEnabled(False)
        self.later_button.setText("Cancelar")
        self.progress.setValue(0)
        self.progress.show()
        self.status_label.setText("Baixando…")
        self.status_label.show()
        Thread(target=self._download, name="update-download", daemon=True).start()

    def _download(self) -> None:
        """Roda em outra thread; só se comunica com a interface por sinais."""
        try:
            archive = self._service.download(self._release, self._signals.progress.emit,
                                             self._cancel)
            self._emit_extracting()
            root = self._service.extract(archive, self._release.version)
        except UpdateCancelled:
            self._signals.cancelled.emit()
        except UpdateError as exc:
            logger.warning("Atualização não concluída: %s", exc)
            self._signals.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - a thread não pode morrer calada
            logger.exception("Falha inesperada ao baixar a atualização")
            self._signals.failed.emit(f"Falha inesperada na atualização: {exc}")
        else:
            self._signals.ready.emit(root)

    def _emit_extracting(self) -> None:
        self._signals.progress.emit(self._release.asset_size, self._release.asset_size)

    def _on_progress(self, received: int, total: int) -> None:
        self.progress.setValue(round(received / total * BAR_RESOLUTION) if total else 0)
        if received >= total:
            self.status_label.setText("Preparando a instalação…")
        else:
            self.status_label.setText(f"Baixando… {format_number(received // MEGABYTE)} de "
                                      f"{format_number(total // MEGABYTE)} MB")

    def _on_ready(self, root: Path) -> None:
        self._downloading = False
        self.new_root = root
        super().accept()

    def _on_failed(self, message: str) -> None:
        self._downloading = False
        self.progress.hide()
        self.status_label.hide()
        self.update_button.setEnabled(True)
        self.later_button.setText("Agora não")
        self.later_button.setEnabled(True)
        self._show_error(message)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def reject(self) -> None:
        if self._downloading:
            # O diálogo fecha quando a thread confirmar, para não apagar arquivos em uso.
            self._cancel.set()
            self.later_button.setEnabled(False)
            self.status_label.setText("Cancelando…")
            return
        super().reject()
