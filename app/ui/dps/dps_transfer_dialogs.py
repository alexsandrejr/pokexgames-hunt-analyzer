"""Diálogos de exportação e importação dos cadastros da página DPS."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.dps_service import BossData, DamageSource, PokemonData, dummy_label
from app.services.dps_transfer import (
    BundleBoss,
    BundlePokemon,
    DpsBundle,
    ImportAction,
    ImportItem,
    ImportKind,
)
from app.ui.icons import icon
from app.utils.formatters import format_duration_long, format_number

KIND_COLUMN, NAME_COLUMN, CONTENT_COLUMN, STATUS_COLUMN, ACTION_COLUMN = range(5)
IMPORT_HEADERS = ["Tipo", "Nome", "Conteúdo", "Situação", "O que fazer"]
ACTION_LABELS = {
    ImportAction.CREATE: "Importar",
    ImportAction.SKIP: "Pular",
    ImportAction.REPLACE: "Substituir",
}
COPY_LABEL = "Criar cópia"
ACTION_WIDTH = 150  # cabe "Substituir" e "Criar cópia" no seletor


def _buttons(dialog: QDialog, confirm_text: str, confirm_icon: str) -> tuple[QHBoxLayout, QPushButton]:
    cancel_button = QPushButton("Cancelar")
    cancel_button.setAutoDefault(False)
    cancel_button.clicked.connect(dialog.reject)
    confirm_button = QPushButton(icon(confirm_icon), f"  {confirm_text}",
                                 objectName="PrimaryButton")
    confirm_button.setAutoDefault(False)
    confirm_button.clicked.connect(dialog.accept)
    row = QHBoxLayout()
    row.addStretch(1)
    row.addWidget(cancel_button)
    row.addWidget(confirm_button)
    return row, confirm_button


def _check_list(entries: Sequence[tuple[int, str]]) -> QListWidget:
    widget = QListWidget()
    widget.setSpacing(3)
    for entry_id, label in entries:
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, entry_id)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        widget.addItem(item)
    return widget


def _checked_ids(widget: QListWidget) -> set[int]:
    return {widget.item(row).data(Qt.ItemDataRole.UserRole) for row in range(widget.count())
            if widget.item(row).checkState() == Qt.CheckState.Checked}


def _set_all(widget: QListWidget, state: Qt.CheckState) -> None:
    for row in range(widget.count()):
        widget.item(row).setCheckState(state)


class DpsExportDialog(QDialog):
    """Marca o que vai no arquivo; tudo começa marcado."""

    def __init__(self, bosses: Sequence[BossData], pokemons: Sequence[PokemonData],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Exportar cadastros do DPS")
        self.setWindowIcon(icon("export"))
        self.resize(640, 520)

        self.bosses_list = _check_list([(boss.id, boss.name) for boss in bosses])
        self.pokemons_list = _check_list([(pokemon.id, pokemon.name) for pokemon in pokemons])
        lists = QHBoxLayout()
        lists.setSpacing(14)
        lists.addLayout(self._column("Bosses", self.bosses_list), 1)
        lists.addLayout(self._column("Pokémons", self.pokemons_list), 1)

        hint = QLabel("Os pokémons levam os testes, com as datas, e os nomes dos bosses em que "
                      "estão anexados. Os ajustes da página não entram no arquivo.",
                      objectName="MutedLabel")
        hint.setWordWrap(True)
        self.error_label = QLabel(objectName="ErrorLabel")
        self.error_label.setWordWrap(True)
        buttons, self.export_button = _buttons(self, "Exportar…", "export")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addLayout(lists, 1)
        layout.addWidget(hint)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

    @staticmethod
    def _column(title: str, widget: QListWidget) -> QVBoxLayout:
        check_button = QPushButton("Marcar todos")
        check_button.setAutoDefault(False)
        check_button.clicked.connect(lambda: _set_all(widget, Qt.CheckState.Checked))
        uncheck_button = QPushButton("Desmarcar todos")
        uncheck_button.setAutoDefault(False)
        uncheck_button.clicked.connect(lambda: _set_all(widget, Qt.CheckState.Unchecked))
        shortcuts = QHBoxLayout()
        shortcuts.addWidget(check_button)
        shortcuts.addWidget(uncheck_button)
        shortcuts.addStretch(1)
        column = QVBoxLayout()
        column.setSpacing(8)
        column.addWidget(QLabel(title, objectName="SectionTitle"))
        column.addLayout(shortcuts)
        column.addWidget(widget, 1)
        return column

    def boss_ids(self) -> set[int]:
        return _checked_ids(self.bosses_list)

    def pokemon_ids(self) -> set[int]:
        return _checked_ids(self.pokemons_list)

    def accept(self) -> None:
        if not self.boss_ids() and not self.pokemon_ids():
            self.error_label.setText("Marque ao menos um boss ou pokémon.")
            return
        super().accept()


def _boss_content(boss: BundleBoss) -> str:
    source = (f"Dummy {dummy_label(boss.dummy)}" if boss.damage_source is DamageSource.DUMMY
              else boss.damage_source.label)
    return f"{format_duration_long(boss.time_limit_seconds)} · {source}"


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{format_number(count)} {singular if count == 1 else plural}"


def _pokemon_content(pokemon: BundlePokemon) -> str:
    return (f"{_plural(len(pokemon.spec.skills), 'skill', 'skills')} · "
            f"{_plural(pokemon.test_count, 'teste', 'testes')}")


class DpsImportDialog(QDialog):
    """Mostra o que há no arquivo. Em cada nome repetido, a pessoa escolhe o que fazer."""

    def __init__(self, bundle: DpsBundle, items: Sequence[ImportItem],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items = list(items)
        self.setWindowTitle("Importar cadastros do DPS")
        self.setWindowIcon(icon("import"))
        self.resize(820, 560)

        new_count = sum(item.existing_id is None for item in items)
        summary = QLabel(f"{_plural(len(items), 'cadastro', 'cadastros')} no arquivo: "
                         f"{format_number(new_count)} novos e "
                         f"{format_number(len(items) - new_count)} com o nome já em uso. "
                         "Nada é gravado até você confirmar.", objectName="MutedLabel")
        summary.setWordWrap(True)

        self.table = QTableWidget(len(self._items), len(IMPORT_HEADERS))
        self.table.setHorizontalHeaderLabels(IMPORT_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setHighlightSections(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(NAME_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(CONTENT_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(ACTION_COLUMN, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(ACTION_COLUMN, ACTION_WIDTH)
        for row, item in enumerate(self._items):
            self._fill_row(row, item, bundle)

        self.replace_warning = QLabel(
            "Substituir troca a ficha e apaga os testes atuais desse cadastro. Antes de "
            "importar, o app faz um backup do banco.", objectName="WarningLabel")
        self.replace_warning.setWordWrap(True)
        self.replace_warning.hide()
        hint = QLabel("Criar cópia mantém o cadastro atual e adiciona “Nome (importado)”. Testes "
                      "feitos em um boss que não vem no arquivo e não existe aqui não entram.",
                      objectName="MutedLabel")
        hint.setWordWrap(True)
        buttons, self.import_button = _buttons(self, "Importar", "import")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(summary)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.replace_warning)
        layout.addWidget(hint)
        layout.addLayout(buttons)

    def _fill_row(self, row: int, item: ImportItem, bundle: DpsBundle) -> None:
        content = (_boss_content(bundle.bosses[item.index]) if item.kind is ImportKind.BOSS
                   else _pokemon_content(bundle.pokemons[item.index]))
        status = "Novo" if item.existing_id is None else "Nome já existe"
        for column, text in ((KIND_COLUMN, item.kind.label), (NAME_COLUMN, item.name),
                             (CONTENT_COLUMN, content), (STATUS_COLUMN, status)):
            cell = QTableWidgetItem(text)
            cell.setToolTip(text)
            self.table.setItem(row, column, cell)
        combo = QComboBox()
        for action in item.actions:
            label = (COPY_LABEL if action is ImportAction.CREATE and item.existing_id is not None
                     else ACTION_LABELS[action])
            combo.addItem(label, action)
        combo.setCurrentIndex(combo.findData(item.action))
        combo.currentIndexChanged.connect(self._update_warning)
        self.table.setCellWidget(row, ACTION_COLUMN, combo)

    def _update_warning(self) -> None:
        self.replace_warning.setVisible(
            any(item.action is ImportAction.REPLACE for item in self.chosen_items()))

    def chosen_items(self) -> list[ImportItem]:
        return [replace(item, action=self.table.cellWidget(row, ACTION_COLUMN).currentData())
                for row, item in enumerate(self._items)]
