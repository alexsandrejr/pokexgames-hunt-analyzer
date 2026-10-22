"""Diálogo para colar mensagens "Você recebeu:" do chat e somar os itens à sessão.

A prévia mostra cada item com o nome que será gravado (editável, para corrigir o
plural ou a grafia do chat), a quantidade e o preço que vai valer.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.dto import ChatRewardPreview, RewardLine
from app.services.hunt_service import HuntService
from app.ui.icons import icon
from app.ui.theme import COLORS
from app.utils.formatters import format_money, format_number

VALIDATION_DELAY_MS = 250
CHAT_COLUMN, ITEM_COLUMN, COUNT_COLUMN, PRICE_COLUMN, TOTAL_COLUMN = range(5)
HEADERS = ("No chat", "Item (editável)", "Quantidade", "Preço unitário", "Total")
_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


class ChatRewardsDialog(QDialog):
    def __init__(self, service: HuntService, hunt_id: int,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._hunt_id = hunt_id
        self.preview = ChatRewardPreview()
        self.setWindowTitle("Adicionar recompensas do chat")
        self.setWindowIcon(icon("app"))
        self.resize(820, 620)

        hint = QLabel(
            "Cole as mensagens do chat que começam com \"Você recebeu:\" (uma por linha). "
            "Os itens são somados aos drops desta sessão, e Raw gains e Profit sobem junto. "
            "O JSON original não é alterado.",
            objectName="MutedLabel",
        )
        hint.setWordWrap(True)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "Você recebeu: 15 Echo Shards, 2 Mystic Stars, 84 hundred dollars, 4 Heart Stones.")
        self.editor.setStyleSheet(f"border: 1px solid {COLORS['border']}; padding: 8px;")

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed
                                   | QAbstractItemView.EditTrigger.AnyKeyPressed)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for column in (COUNT_COLUMN, PRICE_COLUMN, TOTAL_COLUMN):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(self._on_item_changed)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)

        paste_button = QPushButton(icon("paste"), "  Colar da área de transferência")
        paste_button.clicked.connect(self._paste_from_clipboard)
        cancel_button = QPushButton("Cancelar")
        cancel_button.clicked.connect(self.reject)
        self.add_button = QPushButton(icon("check"), "  Adicionar à sessão")
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setDefault(True)
        self.add_button.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(paste_button)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(self.add_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Recompensas do chat", objectName="PageTitle"))
        layout.addWidget(hint)
        layout.addWidget(self.editor, 2)
        layout.addWidget(self.table, 3)
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

    def lines(self) -> list[RewardLine]:
        """Linhas da prévia com os nomes editados pelo usuário."""
        return list(self.preview.lines)

    def validate(self) -> bool:
        """Lê as mensagens, preenche a prévia e habilita "Adicionar" se houver itens."""
        self._timer.stop()
        self.preview = self._service.preview_chat_rewards(self._hunt_id, self.text())
        self._fill_table()
        self._update_status()
        return bool(self.preview.lines)

    def set_item_name(self, row: int, name: str) -> None:
        self.table.item(row, ITEM_COLUMN).setText(name)

    # ----------------------------------------------------------------- tabela

    def _fill_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.preview.lines))
        for row, line in enumerate(self.preview.lines):
            self._set_cell(row, CHAT_COLUMN, line.chat_name)
            self._set_cell(row, ITEM_COLUMN, line.item, editable=True)
            self._fill_numbers(row, line)
        self.table.blockSignals(False)

    def _fill_numbers(self, row: int, line: RewardLine) -> None:
        self._set_cell(row, COUNT_COLUMN, format_number(line.count), numeric=True)
        self._set_cell(row, PRICE_COLUMN, format_money(line.unit_price), numeric=True)
        self._set_cell(row, TOTAL_COLUMN, format_money(line.total_price), numeric=True)
        item_cell = self.table.item(row, ITEM_COLUMN)
        item_cell.setToolTip("" if line.known else
                             "Item ainda não visto em nenhuma sessão. Confira o nome; "
                             "o preço pode ser definido na página Preços.")
        item_cell.setData(Qt.ItemDataRole.ForegroundRole,
                          None if line.known else QBrush(QColor(COLORS["warning"])))

    def _set_cell(self, row: int, column: int, text: str, editable: bool = False,
                  numeric: bool = False) -> None:
        cell = QTableWidgetItem(text)
        flags = Qt.ItemFlag.ItemIsEnabled
        if editable:
            flags |= Qt.ItemFlag.ItemIsEditable
        cell.setFlags(flags)
        if numeric:
            cell.setTextAlignment(_RIGHT)
        self.table.setItem(row, column, cell)

    def _on_item_changed(self, cell: QTableWidgetItem) -> None:
        if cell.column() != ITEM_COLUMN:
            return
        row = cell.row()
        old = self.preview.lines[row]
        name = " ".join(cell.text().split()) or old.chat_name
        line = self._service.quote_reward_item(old.chat_name, name, old.count)
        self.preview.lines[row] = line
        self.table.blockSignals(True)
        if cell.text() != line.item:
            cell.setText(line.item)
        self._fill_numbers(row, line)
        self.table.blockSignals(False)
        self._update_status()

    # ----------------------------------------------------------------- status

    def _update_status(self) -> None:
        preview = self.preview
        self.add_button.setEnabled(bool(preview.lines))
        if not self.text().strip():
            self._set_status("Nenhuma mensagem colada.", COLORS["muted"])
            return
        if not preview.messages:
            self._set_status('Nenhuma mensagem "Você recebeu:" encontrada no texto.',
                             COLORS["negative"])
            return
        if not preview.lines:
            self._set_status("As mensagens não têm itens reconhecíveis.", COLORS["negative"])
            return
        value = sum(line.total_price or 0 for line in preview.lines)
        parts = [f"✓ {len(preview.messages)} mensagem(ns), {len(preview.lines)} item(ns) · "
                 f"valor {format_money(value)}"]
        unpriced = sum(1 for line in preview.lines if line.unit_price is None)
        if unpriced:
            parts.append(f"{unpriced} item(ns) sem preço (entram com valor 0; defina na "
                         "página Preços)")
        unknown = sum(1 for line in preview.lines if not line.known)
        if unknown:
            parts.append(f"{unknown} nome(s) novo(s), em destaque: confira antes de adicionar")
        color = COLORS["positive"]
        if preview.invalid:
            parts.append("ignorado(s), sem quantidade: " + ", ".join(preview.invalid))
            color = COLORS["warning"]
        if preview.repeated:
            parts.append(f"⚠ {len(preview.repeated)} mensagem(ns) já adicionada(s) a esta "
                         "sessão: adicionar de novo soma os itens outra vez")
            color = COLORS["warning"]
        self._set_status("\n".join(parts), color)

    def _set_status(self, text: str, color: str) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color};")

    def _paste_from_clipboard(self) -> None:
        self.set_text(QApplication.clipboard().text())
