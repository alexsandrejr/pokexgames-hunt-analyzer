"""Diálogo para colar o texto do Analyzer (JSON ou TSV) em vez de escolher um arquivo."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.json_importer import AnalyzerImportError, parse_analyzer_text
from app.services.tsv_importer import looks_like_tsv
from app.ui.icons import icon
from app.ui.theme import COLORS, monospace_font
from app.utils.formatters import format_datetime, format_duration, format_money, format_text

VALIDATION_DELAY_MS = 250


class PasteJsonDialog(QDialog):
    def __init__(self, save_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Colar JSON/TSV do Analyzer")
        self.setWindowIcon(icon("app"))
        self.resize(760, 560)

        self.editor = QPlainTextEdit()
        self.editor.setFont(monospace_font(10))
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setPlaceholderText("Cole aqui o JSON ou o TSV gerado pelo Analyzer (Ctrl+V)…")
        self.editor.setStyleSheet(f"border: 1px solid {COLORS['border']}; padding: 8px;")

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)

        paste_button = QPushButton(icon("paste"), "  Colar da área de transferência")
        paste_button.clicked.connect(self._paste_from_clipboard)
        cancel_button = QPushButton("Cancelar")
        cancel_button.clicked.connect(self.reject)
        self.import_button = QPushButton(icon("import"), "  Importar")
        self.import_button.setObjectName("PrimaryButton")
        self.import_button.setDefault(True)
        self.import_button.clicked.connect(self.accept)

        hint = QLabel(
            f"Ao importar, o texto também é salvo como arquivo .json em:\n{save_dir}",
            objectName="MutedLabel",
        )
        hint.setWordWrap(True)

        buttons = QHBoxLayout()
        buttons.addWidget(paste_button)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(self.import_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Colar JSON/TSV", objectName="PageTitle"))
        layout.addWidget(hint)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.status)
        layout.addLayout(buttons)

        self._timer = QTimer(self, singleShot=True, interval=VALIDATION_DELAY_MS)
        self._timer.timeout.connect(self.validate)
        self.editor.textChanged.connect(self._timer.start)
        self.validate()

    def text(self) -> str:
        return self.editor.toPlainText()

    def set_text(self, text: str) -> None:
        self.editor.setPlainText(text)
        self.validate()

    def validate(self) -> bool:
        """Atualiza a mensagem de status e habilita "Importar" só para JSON/TSV válido."""
        self._timer.stop()
        text = self.text().strip()
        if not text:
            self._set_status("Nenhum conteúdo colado.", COLORS["muted"], valid=False)
            return False
        try:
            session = parse_analyzer_text(text).session
        except AnalyzerImportError as exc:
            self._set_status(exc.message, COLORS["negative"], valid=False)
            return False
        text_format = "TSV" if looks_like_tsv(text) else "JSON"
        summary = (
            f"✓ {text_format} válido — Hunt {format_text(session.session_id)} · "
            f"{format_text(session.player)} · {format_datetime(session.start_datetime)} · "
            f"{format_duration(session.duration_seconds)} · Profit {format_money(session.profit)}"
        )
        self._set_status(summary, COLORS["positive"], valid=True)
        return True

    def _set_status(self, text: str, color: str, valid: bool) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color};")
        self.import_button.setEnabled(valid)

    def _paste_from_clipboard(self) -> None:
        self.set_text(QApplication.clipboard().text())
