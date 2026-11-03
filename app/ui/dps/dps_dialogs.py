"""Diálogos da página DPS: pokémon, boss, pokémons do boss e ajustes."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.dps_calculator import (
    BasicAttackSpec,
    BuffSpec,
    EffectivenessLevel,
    Element,
    PokemonSpec,
    SkillReach,
    SkillShape,
    SkillSpec,
    validate_spec,
)
from app.services.dps_service import (
    DUMMY_OPTIONS,
    MAX_BOSS_ELEMENTS,
    NEUTRAL_DUMMY,
    BossData,
    DpsSettings,
    PokemonData,
    validate_boss_profile,
    validate_settings,
)
from app.ui.icons import icon
from app.utils.formatters import PLACEHOLDER, format_money, format_plain
from app.utils.validators import parse_user_number

NAME_COLUMN, SHAPE_COLUMN, REACH_COLUMN, ELEMENT_COLUMN, DAMAGE_COLUMN, COOLDOWN_COLUMN, \
    PERCENT_COLUMN = range(7)
SKILL_HEADERS = ["Nome (opcional)", "Forma", "Alcance", "Elemento", "Dano", "Recarga (s)",
                 "Aproveitamento (%)"]
SUGGESTION_ROLE = Qt.ItemDataRole.UserRole
SKILL_ID_ROLE = Qt.ItemDataRole.UserRole + 1
EFFECTIVENESS_COLUMNS = 3


def _number(text: str, label: str) -> float:
    value = parse_user_number(text)
    if value is None:
        raise ValueError(f"{label}: informe um número válido.")
    return value


def _seconds(text: str, label: str) -> float:
    return _number(text.strip().rstrip("sS"), label)


def _fraction(text: str, label: str) -> float:
    return _number(text.strip().rstrip("%"), label) / 100


def _percent_text(fraction: float) -> str:
    return format_plain(round(fraction * 100, 2))


def _element_combo(current: Element | None) -> QComboBox:
    combo = QComboBox()
    combo.addItem(PLACEHOLDER, None)
    for element in Element:
        combo.addItem(element.label, element)
    combo.setCurrentIndex(combo.findData(current) if current else 0)
    return combo


def _dialog_buttons(dialog: QDialog) -> tuple[QHBoxLayout, QPushButton]:
    cancel_button = QPushButton("Cancelar")
    cancel_button.setAutoDefault(False)
    cancel_button.clicked.connect(dialog.reject)
    save_button = QPushButton(icon("check"), "  Salvar")
    save_button.setObjectName("PrimaryButton")
    save_button.setAutoDefault(False)
    save_button.clicked.connect(dialog.accept)
    buttons = QHBoxLayout()
    buttons.addStretch(1)
    buttons.addWidget(cancel_button)
    buttons.addWidget(save_button)
    return buttons, save_button


class PokemonDialog(QDialog):
    """Nome, observação, ataque básico, buff e tabela de skills.

    O dano só é mostrado: vem dos testes, no dummy escolhido em "Ver dano no dummy".
    """

    def __init__(self, settings: DpsSettings, pokemon: PokemonData | None = None,
                 parent: QWidget | None = None, dummy: str = NEUTRAL_DUMMY) -> None:
        super().__init__(parent)
        self._settings = settings
        self._pokemon = pokemon
        self.setWindowTitle("Editar pokémon" if pokemon else "Novo pokémon")
        self.setWindowIcon(icon("dps"))
        self.resize(980, 800)

        self.name_edit = QLineEdit(pokemon.name if pokemon else "")
        self.name_edit.setPlaceholderText("Ex.: Chumbin")
        self.note_edit = QPlainTextEdit(pokemon.note if pokemon else "")
        self.note_edit.setPlaceholderText("Ex.: +70, X-Attack, dano medido no boss Terror")
        self.note_edit.setFixedHeight(56)
        self.note_edit.setTabChangesFocus(True)
        self.note_edit.setObjectName("DpsNote")
        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("Nome", self.name_edit)
        form.addRow("Observação", self.note_edit)

        self.dummy_combo = QComboBox()
        for value, label in DUMMY_OPTIONS:
            self.dummy_combo.addItem(label, value)
        self.dummy_combo.setCurrentIndex(self.dummy_combo.findData(dummy))
        self.dummy_combo.currentIndexChanged.connect(self._show_damages)

        extras = QHBoxLayout()
        extras.setSpacing(12)
        extras.addWidget(self._build_basic_card(pokemon), 2)
        extras.addWidget(self._build_buff_card(pokemon), 3)

        self.skills_table = self._build_skills_table()
        add_button = QPushButton("Adicionar skill")
        add_button.setAutoDefault(False)
        add_button.clicked.connect(self.add_empty_skill)
        remove_button = QPushButton(icon("trash"), "  Remover skill")
        remove_button.setObjectName("DangerButton")
        remove_button.setAutoDefault(False)
        remove_button.clicked.connect(self.remove_current_skill)
        skills_header = QHBoxLayout()
        skills_header.addWidget(QLabel("Skills", objectName="SectionTitle"))
        skills_header.addStretch(1)
        skills_header.addWidget(QLabel("Ver dano no dummy", objectName="FieldLabel"))
        skills_header.addWidget(self.dummy_combo)
        skills_header.addWidget(add_button)
        skills_header.addWidget(remove_button)

        self.error_label = QLabel(objectName="ErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        buttons, self.save_button = _dialog_buttons(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addLayout(extras)
        layout.addLayout(skills_header)
        layout.addWidget(self.skills_table, 1)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

        if pokemon is None:
            self.add_empty_skill()
        else:
            for skill in pokemon.spec.skills:
                self.add_skill(skill)
        self._show_damages()
        self.name_edit.setFocus()

    # ---------------------------------------------------------------- montagem

    def _build_basic_card(self, pokemon: PokemonData | None) -> QFrame:
        basic = pokemon.spec.basic if pokemon else None
        self.has_basic = QCheckBox("Tem ataque básico")
        self.has_basic.setChecked(basic is not None)
        self.basic_damage_label = QLabel()
        efficiency = basic.efficiency if basic else self._settings.basic_efficiency
        self.basic_percent_edit = QLineEdit(_percent_text(efficiency))
        fields = QWidget()
        form = QFormLayout(fields)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        form.addRow("Dano (dos testes)", self.basic_damage_label)
        form.addRow("Aproveitamento (%)", self.basic_percent_edit)
        self.basic_element_combo = _element_combo(basic.element if basic else None)
        form.addRow("Elemento", self.basic_element_combo)
        hint = QLabel(f"Um ataque a cada {format_plain(self._settings.basic_turn_seconds)}s "
                      "(ajuste o turno em Ajustes).", objectName="CardHint")
        hint.setWordWrap(True)
        self.has_basic.toggled.connect(fields.setEnabled)
        fields.setEnabled(basic is not None)
        return self._card(self.has_basic, fields, hint)

    def _build_buff_card(self, pokemon: PokemonData | None) -> QFrame:
        buff = pokemon.spec.buff if pokemon else None
        self.has_buff = QCheckBox("Tem buff")
        self.has_buff.setChecked(buff is not None)
        self.buff_cooldown_edit = QLineEdit(format_plain(buff.cooldown) if buff else "")
        self.buff_cooldown_edit.setPlaceholderText("Ex.: 50")
        self.buff_basic_edit = QLineEdit(format_plain(buff.basic_multiplier) if buff else "1")
        self.buff_duration_edit = QLineEdit(format_plain(buff.basic_duration) if buff else "0")
        self.buff_spell_edit = QLineEdit(format_plain(buff.next_spell_multiplier) if buff else "1")
        fields = QWidget()
        form = QFormLayout(fields)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        form.addRow("Recarga (s)", self.buff_cooldown_edit)
        form.addRow("Multiplicador do básico", self.buff_basic_edit)
        form.addRow("Duração no básico (s)", self.buff_duration_edit)
        form.addRow("Multiplicador da próxima magia", self.buff_spell_edit)
        hint = QLabel("Multiplicador: 1 = sem efeito, 1,5 = +50%, 2 = dobra. "
                      "A próxima magia é a que mais rende.", objectName="CardHint")
        hint.setWordWrap(True)
        self.has_buff.toggled.connect(fields.setEnabled)
        fields.setEnabled(buff is not None)
        return self._card(self.has_buff, fields, hint)

    @staticmethod
    def _card(*widgets: QWidget) -> QFrame:
        card = QFrame(objectName="Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        for widget in widgets:
            layout.addWidget(widget)
        layout.addStretch(1)
        return card

    @staticmethod
    def _build_skills_table() -> QTableWidget:
        table = QTableWidget(0, len(SKILL_HEADERS))
        table.setHorizontalHeaderLabels(SKILL_HEADERS)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(40)
        table.setShowGrid(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        table.setMinimumHeight(180)
        header = table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setHighlightSections(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for column in (SHAPE_COLUMN, REACH_COLUMN, ELEMENT_COLUMN):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(column, 110)
        return table

    # ------------------------------------------------------------------ skills

    def add_empty_skill(self) -> None:
        shape, reach = SkillShape.AREA, SkillReach.RANGED
        self.add_skill(SkillSpec("", shape, reach, 0, 0,
                                 self._settings.suggested_efficiency(shape, reach)), empty=True)
        self.skills_table.setCurrentCell(self.skills_table.rowCount() - 1, COOLDOWN_COLUMN)
        self._show_damages()

    def add_skill(self, skill: SkillSpec, empty: bool = False) -> None:
        table = self.skills_table
        row = table.rowCount()
        table.insertRow(row)
        name = QTableWidgetItem(skill.name)
        name.setData(SKILL_ID_ROLE, skill.skill_id)
        table.setItem(row, NAME_COLUMN, name)
        damage = QTableWidgetItem()
        damage.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        table.setItem(row, DAMAGE_COLUMN, damage)
        table.setItem(row, COOLDOWN_COLUMN,
                      QTableWidgetItem("" if empty else format_plain(skill.cooldown)))
        percent = QTableWidgetItem(_percent_text(skill.efficiency))
        percent.setData(SUGGESTION_ROLE, self._settings.suggested_efficiency(skill.shape, skill.reach))
        table.setItem(row, PERCENT_COLUMN, percent)
        table.setCellWidget(row, SHAPE_COLUMN, self._enum_combo(SkillShape, skill.shape))
        table.setCellWidget(row, REACH_COLUMN, self._enum_combo(SkillReach, skill.reach))
        table.setCellWidget(row, ELEMENT_COLUMN, _element_combo(skill.element))

    def _damage_text(self, skill_id: int | None) -> str:
        """Média no dummy escolhido; uma skill ainda não salva não tem testes."""
        damage = None
        if self._pokemon is not None and (skill_id is not None or self._pokemon.spec.basic):
            damage = self._pokemon.damage_on(skill_id, self.dummy_combo.currentData())
        return "sem teste" if damage is None else format_money(damage)

    def _show_damages(self) -> None:
        self.basic_damage_label.setText(self._damage_text(None))
        table = self.skills_table
        for row in range(table.rowCount()):
            skill_id = table.item(row, NAME_COLUMN).data(SKILL_ID_ROLE)
            text = "sem teste" if skill_id is None else self._damage_text(skill_id)
            table.item(row, DAMAGE_COLUMN).setText(text)

    def _enum_combo(self, enum_type: type[SkillShape] | type[SkillReach],
                    current: SkillShape | SkillReach) -> QComboBox:
        combo = QComboBox()
        for member in enum_type:
            combo.addItem(member.label, member)
        combo.setCurrentIndex(combo.findData(current))
        combo.currentIndexChanged.connect(lambda _index: self._on_class_changed(combo))
        return combo

    def _on_class_changed(self, combo: QComboBox) -> None:
        """Atualiza o % sugerido, a menos que o usuário já o tenha alterado."""
        table = self.skills_table
        for row in range(table.rowCount()):
            if combo in (table.cellWidget(row, SHAPE_COLUMN), table.cellWidget(row, REACH_COLUMN)):
                break
        else:
            return
        item = table.item(row, PERCENT_COLUMN)
        suggestion = self._settings.suggested_efficiency(table.cellWidget(row, SHAPE_COLUMN).currentData(),
                                                         table.cellWidget(row, REACH_COLUMN).currentData())
        if self._percent_is_untouched(item):
            item.setText(_percent_text(suggestion))
        item.setData(SUGGESTION_ROLE, suggestion)

    @staticmethod
    def _percent_is_untouched(item: QTableWidgetItem) -> bool:
        value = parse_user_number(item.text().strip().rstrip("%"))
        suggestion = item.data(SUGGESTION_ROLE)
        return value is not None and suggestion is not None and abs(value / 100 - suggestion) < 1e-9

    def remove_current_skill(self) -> None:
        table = self.skills_table
        row = table.currentRow() if table.currentRow() >= 0 else table.rowCount() - 1
        if row >= 0:
            table.removeRow(row)

    def _skill_at(self, row: int) -> SkillSpec:
        table = self.skills_table
        name = table.item(row, NAME_COLUMN).text().strip()
        label = name or f"Skill {row + 1}"
        return SkillSpec(
            name,
            table.cellWidget(row, SHAPE_COLUMN).currentData(),
            table.cellWidget(row, REACH_COLUMN).currentData(),
            0,
            _seconds(table.item(row, COOLDOWN_COLUMN).text(), f"{label}, recarga"),
            _fraction(table.item(row, PERCENT_COLUMN).text(), f"{label}, aproveitamento"),
            table.cellWidget(row, ELEMENT_COLUMN).currentData(),
            table.item(row, NAME_COLUMN).data(SKILL_ID_ROLE),
        )

    # ------------------------------------------------------------------ valores

    def pokemon_name(self) -> str:
        return self.name_edit.text().strip()

    def note(self) -> str:
        return self.note_edit.toPlainText().strip()

    def spec(self) -> PokemonSpec:
        """Lança ``ValueError`` com o primeiro problema do formulário."""
        skills = tuple(self._skill_at(row) for row in range(self.skills_table.rowCount()))
        basic = None
        if self.has_basic.isChecked():
            basic = BasicAttackSpec(
                0,
                _fraction(self.basic_percent_edit.text(), "Ataque básico, aproveitamento"),
                self.basic_element_combo.currentData())
        buff = None
        if self.has_buff.isChecked():
            buff = BuffSpec(
                _seconds(self.buff_cooldown_edit.text(), "Buff, recarga"),
                _number(self.buff_basic_edit.text(), "Buff, multiplicador do básico"),
                _seconds(self.buff_duration_edit.text(), "Buff, duração"),
                _number(self.buff_spell_edit.text(), "Buff, multiplicador da próxima magia"))
        spec = PokemonSpec(skills, basic, buff)
        validate_spec(spec)
        return spec

    def accept(self) -> None:
        # O foco no botão fecha o editor da célula, para o valor digitado entrar na conta.
        self.save_button.setFocus()
        try:
            if not self.pokemon_name():
                raise ValueError("Informe o nome do pokémon.")
            self.spec()
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        super().accept()


class BossDialog(QDialog):
    """Nome, tempo limite (em minutos), elementos e efetividade dos ataques contra o boss."""

    def __init__(self, bosses: Sequence[BossData], boss: BossData | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar boss" if boss else "Novo boss")
        self.setWindowIcon(icon("bosses"))
        self.setMinimumWidth(760)
        self._taken = {other.name.casefold() for other in bosses
                       if boss is None or other.id != boss.id}

        self.name_edit = QLineEdit(boss.name if boss else "")
        self.name_edit.setPlaceholderText("Ex.: Terror")
        minutes = boss.time_limit_seconds / 60 if boss else 7
        self.minutes_edit = QLineEdit(format_plain(round(minutes, 2)))
        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("Nome", self.name_edit)
        form.addRow("Tempo limite (min)", self.minutes_edit)
        elements = boss.elements if boss else ()
        self.element_combos = [_element_combo(elements[index] if index < len(elements) else None)
                               for index in range(MAX_BOSS_ELEMENTS)]
        element_row = QHBoxLayout()
        element_row.setSpacing(10)
        for combo in self.element_combos:
            element_row.addWidget(combo)
        element_row.addStretch(1)
        form.addRow("Elementos", element_row)
        self.error_label = QLabel(objectName="ErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        buttons, self.save_button = _dialog_buttons(self)

        hint = QLabel("Copie da Pokédex do jogo o resultado de cada ataque contra este boss. "
                      "Só o cálculo por Efetividade usa esta lista; os elementos do boss são "
                      "apenas informativos.", objectName="MutedLabel")
        hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(QLabel("Efetividade dos ataques", objectName="SectionTitle"))
        layout.addWidget(hint)
        layout.addLayout(self._build_effectiveness_grid(boss))
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

    def _build_effectiveness_grid(self, boss: BossData | None) -> QGridLayout:
        self.effectiveness_combos: dict[Element, QComboBox] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        for index, element in enumerate(Element):
            combo = QComboBox()
            for level in EffectivenessLevel:
                combo.addItem(f"{level.label} ({format_plain(level.multiplier)}x)", level)
            current = (boss.effectiveness.get(element, EffectivenessLevel.NORMAL) if boss
                       else EffectivenessLevel.NORMAL)
            combo.setCurrentIndex(combo.findData(current))
            self.effectiveness_combos[element] = combo
            row, group = divmod(index, EFFECTIVENESS_COLUMNS)
            grid.addWidget(QLabel(element.label), row, group * 2)
            grid.addWidget(combo, row, group * 2 + 1)
            grid.setColumnStretch(group * 2 + 1, 1)
        return grid

    def boss_name(self) -> str:
        return self.name_edit.text().strip()

    def time_limit_seconds(self) -> int:
        value = parse_user_number(self.minutes_edit.text())
        return int(round(value * 60)) if value is not None else 0

    def elements(self) -> tuple[Element, ...]:
        return tuple(combo.currentData() for combo in self.element_combos if combo.currentData())

    def effectiveness(self) -> dict[Element, EffectivenessLevel]:
        return {element: combo.currentData()
                for element, combo in self.effectiveness_combos.items()
                if combo.currentData() is not EffectivenessLevel.NORMAL}

    def accept(self) -> None:
        name = self.boss_name()
        try:
            validate_boss_profile(self.elements())
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        if not name:
            self.error_label.setText("Informe o nome do boss.")
        elif name.casefold() in self._taken:
            self.error_label.setText(f"Já existe um boss chamado {name}.")
        elif self.time_limit_seconds() <= 0:
            self.error_label.setText("O tempo limite precisa ser maior que zero.")
        else:
            super().accept()


class BossPokemonsDialog(QDialog):
    """Lista de marcação com os pokémons que podem lutar contra o boss."""

    def __init__(self, boss: BossData, pokemons: Sequence[PokemonData],
                 selected_ids: Collection[int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Pokémons de {boss.name}")
        self.setWindowIcon(icon("dps"))
        self.resize(460, 560)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Pesquisar pokémon…")
        self.search_edit.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_search)

        self.list_widget = QListWidget()
        self.list_widget.setSpacing(3)
        for pokemon in pokemons:
            label = f"{pokemon.name} — {pokemon.note}" if pokemon.note else pokemon.name
            item = QListWidgetItem(label.replace("\n", " "))
            item.setData(Qt.ItemDataRole.UserRole, pokemon.id)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if pokemon.id in selected_ids
                               else Qt.CheckState.Unchecked)
            self.list_widget.addItem(item)

        check_button = QPushButton("Marcar visíveis")
        check_button.setAutoDefault(False)
        check_button.clicked.connect(lambda: self._check_visible(Qt.CheckState.Checked))
        uncheck_button = QPushButton("Desmarcar visíveis")
        uncheck_button.setAutoDefault(False)
        uncheck_button.clicked.connect(lambda: self._check_visible(Qt.CheckState.Unchecked))
        shortcuts = QHBoxLayout()
        shortcuts.addWidget(check_button)
        shortcuts.addWidget(uncheck_button)
        shortcuts.addStretch(1)
        buttons, self.save_button = _dialog_buttons(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(self.search_edit)
        layout.addLayout(shortcuts)
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(buttons)

    def _items(self) -> list[QListWidgetItem]:
        return [self.list_widget.item(row) for row in range(self.list_widget.count())]

    def _apply_search(self, text: str) -> None:
        needle = text.strip().casefold()
        for item in self._items():
            item.setHidden(needle not in item.text().casefold())

    def _check_visible(self, state: Qt.CheckState) -> None:
        for item in self._items():
            if not item.isHidden():
                item.setCheckState(state)

    def selected_ids(self) -> set[int]:
        """Inclui os marcados que a pesquisa escondeu."""
        return {item.data(Qt.ItemDataRole.UserRole) for item in self._items()
                if item.checkState() == Qt.CheckState.Checked}


class DpsSettingsDialog(QDialog):
    """Turno do ataque básico e aproveitamentos sugeridos para novos cadastros."""

    def __init__(self, settings: DpsSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Ajustes do DPS")
        self.setWindowIcon(icon("settings"))
        self.setMinimumWidth(460)

        self.turn_edit = QLineEdit(format_plain(settings.basic_turn_seconds))
        self.target_edit = QLineEdit(_percent_text(settings.target_melee_efficiency))
        self.default_edit = QLineEdit(_percent_text(settings.default_efficiency))
        self.basic_edit = QLineEdit(_percent_text(settings.basic_efficiency))
        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("Turno do ataque básico (s)", self.turn_edit)
        form.addRow("Target + Melee (%)", self.target_edit)
        form.addRow("Demais skills (%)", self.default_edit)
        form.addRow("Ataque básico (%)", self.basic_edit)
        hint = QLabel("O turno vale para todos os pokémons e muda o ranking na hora. Os % são "
                      "só sugestões para novos cadastros: não alteram o que já foi salvo.",
                      objectName="MutedLabel")
        hint.setWordWrap(True)
        self.error_label = QLabel(objectName="ErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        buttons, self.save_button = _dialog_buttons(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

    def settings(self) -> DpsSettings:
        """Lança ``ValueError`` se algum campo for inválido."""
        settings = DpsSettings(
            _seconds(self.turn_edit.text(), "Turno do ataque básico"),
            _fraction(self.target_edit.text(), "Target + Melee"),
            _fraction(self.default_edit.text(), "Demais skills"),
            _fraction(self.basic_edit.text(), "Ataque básico"),
            self._settings.last_boss_id,
        )
        validate_settings(settings)
        return settings

    def accept(self) -> None:
        try:
            self.settings()
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        super().accept()
