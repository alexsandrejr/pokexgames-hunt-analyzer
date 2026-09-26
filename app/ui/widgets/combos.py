"""Combos pesquisáveis (digitar filtra a lista, sem diferenciar maiúsculas)."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter, QSizePolicy


def searchable_combo(placeholder: str) -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    combo.lineEdit().setPlaceholderText(placeholder)
    combo.lineEdit().setClearButtonEnabled(True)
    completer = QCompleter(combo.model(), combo)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    combo.setCompleter(completer)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    combo.setMinimumWidth(140)
    return combo


def set_combo_options(combo: QComboBox, options: Sequence[str]) -> None:
    text = combo.currentText()
    combo.blockSignals(True)
    combo.clear()
    combo.addItems(list(options))
    combo.setCurrentIndex(-1)
    combo.setEditText(text)
    combo.blockSignals(False)
