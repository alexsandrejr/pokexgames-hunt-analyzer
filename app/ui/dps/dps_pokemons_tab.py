"""Aba Pokémons da página DPS: todos os cadastrados, em qualquer boss ou em nenhum."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.dps_calculator import BuffSpec, SkillSpec, skill_label
from app.services.dps_service import DUMMY_OPTIONS, DpsService, PokemonData
from app.ui.dps.dps_dialogs import PokemonDialog
from app.ui.dps.dps_tests_dialog import DamageTestsDialog
from app.ui.icons import icon
from app.ui.widgets.page import EmptyState
from app.ui.widgets.record_table import Column, RecordTable
from app.utils.formatters import PLACEHOLDER, format_money, format_number, format_plain

SkillRow = tuple[int, SkillSpec]


def announce(widget: QWidget, message: str) -> None:
    window = widget.window()
    if hasattr(window, "statusBar"):
        window.statusBar().showMessage(message, 8000)


def _percent(fraction: float) -> str:
    return f"{format_plain(round(fraction * 100, 2))}%"


def _damage_text(damage: float | None) -> str:
    return "sem teste" if damage is None else format_money(damage)


def _basic_summary(pokemon: PokemonData) -> str:
    basic = pokemon.spec.basic
    if basic is None:
        return PLACEHOLDER
    parts = [_percent(basic.efficiency)]
    if basic.element:
        parts.append(basic.element.label)
    return " · ".join(parts)


def _buff_summary(buff: BuffSpec | None) -> str:
    if buff is None:
        return PLACEHOLDER
    effects = []
    if buff.basic_multiplier > 1:
        effects.append(f"básico ×{format_plain(buff.basic_multiplier)} "
                       f"por {format_plain(buff.basic_duration)}s")
    if buff.next_spell_multiplier > 1:
        effects.append(f"magia ×{format_plain(buff.next_spell_multiplier)}")
    return f"{' + '.join(effects)} / {format_plain(buff.cooldown)}s"


class PokemonsTab(QWidget):
    data_changed = Signal()

    def __init__(self, service: DpsService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._pokemons: list[PokemonData] = []
        self._boss_names: dict[int, str] = {}

        self._table = RecordTable(self._columns())
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._table.doubleClicked.connect(lambda _index: self.edit_selected())
        self._table.selectionModel().selectionChanged.connect(self._show_details)

        self._detail_name = QLabel(objectName="SectionTitle")
        self._detail_name.setTextFormat(Qt.TextFormat.PlainText)
        self._detail_basic = QLabel(objectName="MutedLabel")
        self._dummy_combo = QComboBox()
        for value, label in DUMMY_OPTIONS:
            self._dummy_combo.addItem(label, value)
        self._dummy_combo.currentIndexChanged.connect(lambda _index: self._show_details())
        self._detail_note = QLabel(objectName="MutedLabel")
        self._detail_note.setWordWrap(True)
        self._detail_note.setTextFormat(Qt.TextFormat.PlainText)
        self._skills_table = RecordTable(self._skill_columns())
        self._skills_table.set_sortable(False)  # na ordem do cadastro
        self._skills_table.horizontalHeader().setMinimumSectionSize(60)  # 8 colunas na janela mínima

        self._stack = QStackedWidget()
        self._stack.addWidget(EmptyState("Nenhum pokémon cadastrado",
                                         "Use “Novo” para cadastrar o primeiro."))
        self._stack.addWidget(self._build_list_view())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(self._build_toolbar())
        layout.addWidget(self._stack, 1)

        QShortcut(QKeySequence(Qt.Key.Key_Return), self._table, activated=self.edit_selected)
        QShortcut(QKeySequence.StandardKey.Delete, self._table, activated=self.delete_selected)
        self._update_buttons()

    # --------------------------------------------------------------- montagem

    def _columns(self) -> list[Column[PokemonData]]:
        return [
            Column("Nome", lambda p: p.name),
            Column("Skills", lambda p: len(p.spec.skills), format_number, numeric=True,
                   fit_contents=True),
            Column("Básico", _basic_summary, fit_contents=True,
                   tooltip="Aproveitamento · elemento"),
            Column("Buff", lambda p: _buff_summary(p.spec.buff), fit_contents=True,
                   tooltip="Efeitos / recarga; “magia” é a próxima magia"),
            Column("Bosses", self._boss_list),
            Column("Observação", lambda p: p.note.replace("\n", " ")),
        ]

    def _skill_columns(self) -> list[Column[SkillRow]]:
        return [
            Column("Skill", lambda row: skill_label(row[1], row[0])),
            Column("Forma", lambda row: row[1].shape.label),
            Column("Alcance", lambda row: row[1].reach.label),
            Column("Elemento", lambda row: row[1].element.label if row[1].element else None),
            Column("Dano", self._skill_damage, _damage_text, numeric=True),
            Column("Recarga (s)", lambda row: row[1].cooldown, format_plain, numeric=True),
            Column("Aproveitamento", lambda row: row[1].efficiency, _percent, numeric=True,
                   fit_contents=True),
            Column("Testes", self._skill_test_count, format_number, numeric=True,
                   fit_contents=True,
                   tooltip="Quantos dummies e bosses foram testados nesta skill"),
        ]

    def _skill_damage(self, row: SkillRow) -> float | None:
        pokemon = self.selected_pokemon()
        return pokemon.damage_on(row[1].skill_id, self._dummy_combo.currentData()) if pokemon else None

    def _skill_test_count(self, row: SkillRow) -> int:
        pokemon = self.selected_pokemon()
        return len(pokemon.tests.get(row[1].skill_id, ())) if pokemon else 0

    def _boss_list(self, pokemon: PokemonData) -> str:
        names = sorted((self._boss_names[boss_id] for boss_id in pokemon.boss_ids
                        if boss_id in self._boss_names), key=str.casefold)
        return ", ".join(names) or PLACEHOLDER

    def _build_toolbar(self) -> QHBoxLayout:
        self._search = QLineEdit()
        self._search.setPlaceholderText("Pesquisar pokémon…")
        self._search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumWidth(130)
        self._search.setMaximumWidth(300)
        self._search.textChanged.connect(self._on_search)
        self._count_label = QLabel(objectName="MutedLabel")

        self._new_button = QPushButton("Novo", objectName="PrimaryButton")
        self._new_button.clicked.connect(self.new_pokemon)
        self._edit_button = QPushButton("Editar")
        self._edit_button.clicked.connect(self.edit_selected)
        self._tests_button = QPushButton("Testes")
        self._tests_button.setToolTip("Danos medidos nos dummies e nos bosses, por skill e no "
                                      "ataque básico")
        self._tests_button.clicked.connect(self.open_tests)
        self._duplicate_button = QPushButton(icon("copy"), "  Duplicar")
        self._duplicate_button.setToolTip("Copiar o pokémon, para comparar outra build")
        self._duplicate_button.clicked.connect(self.duplicate_selected)
        self._delete_button = QPushButton(icon("trash"), "  Excluir", objectName="DangerButton")
        self._delete_button.clicked.connect(self.delete_selected)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        toolbar.addWidget(self._search, 1)
        toolbar.addWidget(self._count_label)
        toolbar.addStretch(1)
        for button in (self._delete_button, self._duplicate_button, self._tests_button,
                       self._edit_button, self._new_button):
            toolbar.addWidget(button)
        return toolbar

    def _build_list_view(self) -> QWidget:
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._table, 3)
        title = QHBoxLayout()
        title.setSpacing(10)
        title.addWidget(self._detail_name)
        title.addWidget(self._detail_basic)
        title.addStretch(1)
        title.addWidget(QLabel("Ver dano no dummy", objectName="FieldLabel"))
        title.addWidget(self._dummy_combo)
        layout.addLayout(title)
        layout.addWidget(self._detail_note)
        layout.addWidget(self._skills_table, 2)
        return view

    # ------------------------------------------------------------------ dados

    def selected_pokemon(self) -> PokemonData | None:
        selected = self._table.selected_records()
        return selected[0] if selected else None

    def refresh(self) -> None:
        selected = self.selected_pokemon()
        self._boss_names = {boss.id: boss.name for boss in self._service.list_bosses()}
        self._pokemons = self._service.list_pokemons()
        self._table.set_records(self._pokemons)
        self._stack.setCurrentIndex(1 if self._pokemons else 0)
        self.select_pokemon(selected.id if selected else None)
        self._update_count()

    def select_pokemon(self, pokemon_id: int | None) -> None:
        """Seleciona o pokémon pedido, ou o primeiro visível se ele não estiver na lista."""
        records = self._table.visible_records()
        row = next((row for row, pokemon in enumerate(records) if pokemon.id == pokemon_id), 0)
        self._table.clearSelection()
        if records:
            self._table.selectRow(row)
            self._table.scrollTo(self._table.proxy.index(row, 0))
        self._show_details()

    def _on_search(self, text: str) -> None:
        selected = self.selected_pokemon()
        self._table.set_search_text(text)
        self.select_pokemon(selected.id if selected else None)
        self._update_count()

    def _update_count(self) -> None:
        self._count_label.setText(f"{self._table.visible_row_count()} de "
                                  f"{len(self._pokemons)} pokémons")

    def _show_details(self) -> None:
        pokemon = self.selected_pokemon()
        self._detail_name.setText(pokemon.name if pokemon else "")
        self._detail_note.setText(pokemon.note if pokemon else "")
        self._detail_note.setVisible(bool(pokemon and pokemon.note))
        self._detail_basic.setText(self._basic_damage_text(pokemon))
        skills = list(enumerate(pokemon.spec.skills, 1)) if pokemon else []
        self._skills_table.set_records(skills)
        self._update_buttons()

    def _basic_damage_text(self, pokemon: PokemonData | None) -> str:
        if pokemon is None or pokemon.spec.basic is None:
            return ""
        damage = pokemon.damage_on(None, self._dummy_combo.currentData())
        return f"Ataque básico: {_damage_text(damage)}"

    def _update_buttons(self) -> None:
        has_selection = self.selected_pokemon() is not None
        for button in (self._edit_button, self._tests_button, self._duplicate_button,
                       self._delete_button):
            button.setEnabled(has_selection)

    def _after_change(self, pokemon_id: int | None, message: str) -> None:
        self.data_changed.emit()
        if pokemon_id is not None:
            self.select_pokemon(pokemon_id)
        announce(self, message)

    # ------------------------------------------------------------------ ações

    def new_pokemon(self) -> None:
        dialog = PokemonDialog(self._service.settings(), parent=self)
        if dialog.exec() != PokemonDialog.DialogCode.Accepted:
            return
        pokemon_id = self._service.save_pokemon(None, dialog.pokemon_name(), dialog.note(),
                                                dialog.spec())
        self._after_change(pokemon_id, f"{dialog.pokemon_name()} cadastrado. "
                                       "Anexe-o a um boss na aba Ranking.")

    def edit_selected(self) -> None:
        pokemon = self.selected_pokemon()
        if pokemon is None:
            return
        dialog = PokemonDialog(self._service.settings(), pokemon, self)
        if dialog.exec() != PokemonDialog.DialogCode.Accepted:
            return
        self._service.save_pokemon(pokemon.id, dialog.pokemon_name(), dialog.note(), dialog.spec())
        self._after_change(pokemon.id, f"{dialog.pokemon_name()} salvo.")

    def open_tests(self) -> None:
        pokemon = self.selected_pokemon()
        if pokemon is None:
            return
        DamageTestsDialog(self._service, pokemon, self).exec()
        self._after_change(pokemon.id, f"Testes de {pokemon.name} salvos.")

    def duplicate_selected(self) -> None:
        pokemon = self.selected_pokemon()
        if pokemon is not None:
            copy_id = self._service.duplicate_pokemon(pokemon.id)
            self._after_change(copy_id, f"{pokemon.name} duplicado.")

    def delete_selected(self) -> None:
        pokemon = self.selected_pokemon()
        if pokemon is None:
            return
        answer = QMessageBox.question(
            self, "Excluir pokémon",
            f"Excluir {pokemon.name}?\n\nEle será apagado de todos os bosses.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_pokemon(pokemon.id)

    def delete_pokemon(self, pokemon_id: int) -> None:
        self._service.delete_pokemon(pokemon_id)
        self._after_change(None, "Pokémon excluído.")
