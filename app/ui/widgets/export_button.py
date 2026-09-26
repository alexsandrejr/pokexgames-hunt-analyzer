"""Botão "Exportar" com menu de formatos (CSV, Excel, PDF, JSON)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox, QPushButton, QWidget

from app.services.export_service import (
    ExportDocument,
    ExportError,
    ExportFormat,
    export_document,
    suggested_filename,
)
from app.ui.icons import icon

DocumentProvider = Callable[[], ExportDocument | None]


def _default_directory() -> Path:
    documents = Path.home() / "Documents"
    return documents if documents.is_dir() else Path.home()


class ExportButton(QPushButton):
    exported = Signal(str)  # caminho do arquivo gerado

    # Última pasta usada, compartilhada entre os botões da aplicação.
    last_directory: Path | None = None

    def __init__(self, provider: DocumentProvider, parent: QWidget | None = None) -> None:
        super().__init__(icon("export"), "  Exportar", parent)
        self._provider = provider
        menu = QMenu(self)
        for fmt in ExportFormat:
            action = menu.addAction(f"{fmt.label} (.{fmt.extension})")
            action.triggered.connect(lambda _checked=False, f=fmt: self.choose_and_export(f))
        self.setMenu(menu)

    def choose_and_export(self, fmt: ExportFormat) -> Path | None:
        document = self._provider()
        if document is None:
            return None
        directory = ExportButton.last_directory or _default_directory()
        path, _ = QFileDialog.getSaveFileName(
            self.window(), f"Exportar {fmt.label}",
            str(directory / suggested_filename(document.title, fmt)), fmt.file_filter)
        return self.export_to(document, Path(path), fmt) if path else None

    def export_to(self, document: ExportDocument, path: Path, fmt: ExportFormat) -> Path | None:
        try:
            saved = export_document(document, path, fmt)
        except ExportError as exc:
            QMessageBox.warning(self.window(), "Falha na exportação", str(exc))
            return None
        ExportButton.last_directory = saved.parent
        self.exported.emit(str(saved))
        return saved
