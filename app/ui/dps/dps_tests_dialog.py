"""Testes de um pokémon: até 3 danos por dummy ou boss, em cada skill e no ataque básico."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.dps_calculator import Element, skill_label
from app.services.dps_service import (
    DAMAGES_PER_TEST,
    DUMMY_OPTIONS,
    DamageTest,
    DpsService,
    PokemonData,
    damage_average,
)
from app.ui.icons import icon
from app.utils.formatters import (
    PLACEHOLDER,
    format_date,
    format_datetime_short,
    format_money,
    format_number,
)
from app.utils.validators import parse_user_number

DUMMY_COLUMN = 0
AVERAGE_COLUMN = DAMAGES_PER_TEST + 1
CREATED_COLUMN = AVERAGE_COLUMN + 1
UPDATED_COLUMN = CREATED_COLUMN + 1
HEADERS = ["Testado em", *(f"Dano {n}" for n in range(1, DAMAGES_PER_TEST + 1)), "Média",
           "Cadastrado", "Modificado"]


@dataclass
class _Target:
    """Uma skill ou o ataque básico (``skill_id`` ``None``)."""

    skill_id: int | None
    label: str
    element: Element | None


def _targets(pokemon: PokemonData) -> list[_Target]:
    targets = []
    basic = pokemon.spec.basic
    if basic is not None:
        targets.append(_Target(None, "Ataque básico", basic.element))
    for position, skill in enumerate(pokemon.spec.skills, 1):
        targets.append(_Target(skill.skill_id, skill_label(skill, position), skill.element))
    return targets


def _place_label(combo: QComboBox) -> str:
    """Onde o teste foi feito, para as mensagens de erro."""
    return combo.currentText() if isinstance(combo.currentData(), int) else f"Dummy {combo.currentText()}"


def _read_only_item(text: str, tooltip: str = "") -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setToolTip(tooltip)
    return item


def _date_item(moment: datetime | None, tooltip_if_empty: str) -> QTableWidgetItem:
    """A data na célula, com a hora na dica."""
    return _read_only_item(format_date(moment),
                           format_datetime_short(moment) if moment else tooltip_if_empty)


def _cell_damage(text: str, place: str) -> int | None:
    """Dano de uma célula; vazia é ``None``. Lança ``ValueError`` se for inválida."""
    if not text.strip():
        return None
    value = parse_user_number(text)
    if value is None:
        raise ValueError(f"{place}: “{text.strip()}” não é um dano válido.")
    return int(round(value))


class DamageTestsDialog(QDialog):
    """Grava os testes ao trocar de skill e ao fechar."""

    def __init__(self, service: DpsService, pokemon: PokemonData,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._pokemon = pokemon
        self._targets = _targets(pokemon)
        self._bosses = service.list_bosses()
        self._tests = {skill_id: list(tests) for skill_id, tests in pokemon.tests.items()}
        self._current_row = -1
        self.setWindowTitle(f"Testes de {pokemon.name}")
        self.setWindowIcon(icon("dps"))
        self.resize(960, 520)

        self.targets_list = QListWidget()
        self.targets_list.setFixedWidth(210)
        self.targets_list.setSpacing(3)
        self.targets_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for row in range(len(self._targets)):
            self.targets_list.addItem(self._target_text(row))

        self.current_label = QLabel(objectName="SectionTitle")
        self.current_label.setTextFormat(Qt.TextFormat.PlainText)
        self.table = self._build_table()
        self.table.itemChanged.connect(self._on_item_changed)

        add_button = QPushButton("Adicionar teste")
        add_button.setAutoDefault(False)
        add_button.clicked.connect(lambda: self.add_test())
        remove_button = QPushButton(icon("trash"), "  Remover teste", objectName="DangerButton")
        remove_button.setAutoDefault(False)
        remove_button.clicked.connect(self.remove_test)
        actions = QHBoxLayout()
        actions.addWidget(add_button)
        actions.addWidget(remove_button)
        actions.addStretch(1)

        self.error_label = QLabel(objectName="ErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        hint = QLabel("Escolha um dummy ou, para o dano real, “Boss: nome”. O ranking usa a média "
                      "conforme o “Calcular por” de cada boss, considerando só os danos "
                      "preenchidos. Modificado muda só quando os danos mudam; passe o mouse sobre "
                      "uma data para ver a hora.", objectName="MutedLabel")
        hint.setWordWrap(True)

        panel = QVBoxLayout()
        panel.setSpacing(10)
        panel.addWidget(self.current_label)
        panel.addWidget(self.table, 1)
        panel.addLayout(actions)
        panel.addWidget(hint)
        panel.addWidget(self.error_label)
        content = QHBoxLayout()
        content.setSpacing(14)
        content.addWidget(self.targets_list)
        content.addLayout(panel, 1)

        close_button = QPushButton(icon("check"), "  Fechar", objectName="PrimaryButton")
        close_button.setAutoDefault(False)
        close_button.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addLayout(content, 1)
        layout.addLayout(footer)

        self.targets_list.currentRowChanged.connect(self._on_target_changed)
        self.targets_list.setCurrentRow(0)

    @staticmethod
    def _build_table() -> QTableWidget:
        table = QTableWidget(0, len(HEADERS))
        table.setHorizontalHeaderLabels(HEADERS)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(40)
        table.setShowGrid(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        header = table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setHighlightSections(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(DUMMY_COLUMN, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(DUMMY_COLUMN, 170)
        for column in (CREATED_COLUMN, UPDATED_COLUMN):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        return table

    # ------------------------------------------------------------------ dados

    @property
    def _target(self) -> _Target:
        return self._targets[self._current_row]

    def _target_text(self, row: int) -> str:
        target = self._targets[row]
        count = len(self._tests.get(target.skill_id, []))
        return f"{target.label} ({count})" if count else target.label

    def _on_target_changed(self, row: int) -> None:
        if self._current_row >= 0 and not self.save_current():
            self.targets_list.blockSignals(True)
            self.targets_list.setCurrentRow(self._current_row)
            self.targets_list.blockSignals(False)
            return
        self._current_row = row
        self.table.setRowCount(0)
        for test in self._tests.get(self._target.skill_id, []):
            self.add_test(test)
        if self.table.rowCount():
            self.table.setCurrentCell(0, 1)
        self._update_current_label()

    def _update_current_label(self) -> None:
        target = self._target
        element = target.element.label if target.element else PLACEHOLDER
        self.current_label.setText(f"{target.label} · Elemento: {element}")

    def _read_tests(self) -> list[DamageTest]:
        """Testes da tabela, sem as linhas vazias. Lança ``ValueError`` se houver dano inválido."""
        tests = []
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, DUMMY_COLUMN)
            damages = tuple(_cell_damage(self.table.item(row, column).text(), _place_label(combo))
                            for column in range(1, AVERAGE_COLUMN))
            if any(damage is not None for damage in damages):
                place = combo.currentData()
                tests.append(DamageTest.in_boss(place, damages) if isinstance(place, int)
                             else DamageTest(place, damages))
        return tests

    def save_current(self) -> bool:
        """Grava os testes da skill aberta; se forem inválidos, mostra o erro e retorna False."""
        try:
            saved = self._service.save_damage_tests(self._pokemon.id, self._target.skill_id,
                                                    self._read_tests())
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return False
        self.error_label.setText("")
        self._tests[self._target.skill_id] = list(saved)
        self.targets_list.item(self._current_row).setText(self._target_text(self._current_row))
        return True

    # ------------------------------------------------------------------ tabela

    def add_test(self, test: DamageTest | None = None) -> None:
        table = self.table
        row = table.rowCount()
        if test is None:
            place = self._free_dummy()
        else:
            place = test.dummy if test.boss_id is None else test.boss_id
        table.blockSignals(True)
        table.insertRow(row)
        combo = QComboBox()
        for value, label in DUMMY_OPTIONS:
            combo.addItem(label, value)
        if self._bosses:
            combo.insertSeparator(combo.count())
        for boss in self._bosses:
            combo.addItem(f"Boss: {boss.name}", boss.id)
        combo.setCurrentIndex(combo.findData(place))
        table.setCellWidget(row, DUMMY_COLUMN, combo)
        damages = test.damages if test else (None,) * DAMAGES_PER_TEST
        for column, damage in enumerate(damages, 1):
            table.setItem(row, column, QTableWidgetItem(
                "" if damage is None else format_number(damage)))
        table.setItem(row, AVERAGE_COLUMN, _read_only_item(format_money(damage_average(damages))))
        table.setItem(row, CREATED_COLUMN, _date_item(
            test.created_at if test else None,
            "Teste anterior ao registro de datas." if test else "Ainda não foi salvo."))
        table.setItem(row, UPDATED_COLUMN, _date_item(
            test.updated_at if test else None,
            "Os danos não mudaram desde o cadastro." if test else "Ainda não foi salvo."))
        table.blockSignals(False)
        if test is None:
            table.setCurrentCell(row, 1)

    def _free_dummy(self) -> str:
        """O primeiro dummy ainda sem teste nesta skill."""
        used = {self.table.cellWidget(row, DUMMY_COLUMN).currentData()
                for row in range(self.table.rowCount())}
        return next((value for value, _label in DUMMY_OPTIONS if value not in used),
                    DUMMY_OPTIONS[0][0])

    def remove_test(self) -> None:
        row = self.table.currentRow() if self.table.currentRow() >= 0 else self.table.rowCount() - 1
        if row >= 0:
            self.table.removeRow(row)

    def _row_average(self, row: int) -> float | None:
        combo = self.table.cellWidget(row, DUMMY_COLUMN)
        try:
            return damage_average(_cell_damage(self.table.item(row, column).text(), _place_label(combo))
                                  for column in range(1, AVERAGE_COLUMN))
        except ValueError:
            return None

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() < AVERAGE_COLUMN:
            self.table.item(item.row(), AVERAGE_COLUMN).setText(
                format_money(self._row_average(item.row())))

    # ------------------------------------------------------------------ ações

    def accept(self) -> None:
        if self.save_current():
            super().accept()

    def reject(self) -> None:
        # Fechar pelo X ou com Esc também grava: não há o que descartar nesta janela.
        if self.save_current():
            super().reject()
