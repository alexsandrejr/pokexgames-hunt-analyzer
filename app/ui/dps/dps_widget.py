"""Página DPS: aba Ranking (dano no boss) e aba Pokémons (cadastro)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.dps_calculator import DamageLine, EffectivenessLevel, Element
from app.services.dps_service import (
    DUMMY_OPTIONS,
    NEUTRAL_DUMMY,
    BossData,
    DamageSource,
    DpsService,
    RankingEntry,
    dummy_label,
)
from app.ui.dps.dps_dialogs import (
    BossDialog,
    BossPokemonsDialog,
    DpsSettingsDialog,
    PokemonDialog,
)
from app.ui.dps.dps_pokemons_tab import PokemonsTab, announce
from app.ui.icons import icon
from app.ui.theme import COLORS, ELEMENT_COLORS
from app.ui.widgets.elided_label import ElidedLabel
from app.ui.widgets.page import PAGE_MARGINS, EmptyState, PageHeader
from app.ui.widgets.record_table import Column, RecordTable
from app.utils.formatters import format_duration_long, format_money, format_percent, format_plain

BAR_RESOLUTION = 1000

EMPTY_TITLE = "Nenhum pokémon neste boss"
EMPTY_MESSAGE = "Use “Adicionar” para anexar os pokémons cadastrados na aba Pokémons."
NO_WEAKNESSES_WARNING = ("Marque as fraquezas em Gerenciar bosses → Editar boss: por enquanto, "
                         "todos os ataques contam como Normal (1x).")


class DpsPage(QWidget):
    def __init__(self, service: DpsService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service

        self._header = PageHeader("DPS", "Dano estimado no tempo limite do boss")
        settings_button = QPushButton(icon("settings"), "  Ajustes")
        settings_button.setToolTip("Turno do ataque básico e aproveitamentos sugeridos")
        settings_button.clicked.connect(self.edit_settings)
        self._header.add_action(settings_button)

        self.ranking_tab = RankingTab(service)
        self.pokemons_tab = PokemonsTab(service)
        self.ranking_tab.data_changed.connect(self.refresh)
        self.pokemons_tab.data_changed.connect(self.refresh)
        self.tabs = QTabWidget(objectName="CategoryTabs")
        self.tabs.addTab(self.ranking_tab, "Ranking")
        self.tabs.addTab(self.pokemons_tab, "Pokémons")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.setSpacing(12)
        layout.addWidget(self._header)
        layout.addWidget(self.tabs, 1)

    def refresh(self) -> None:
        self.ranking_tab.refresh()
        self.pokemons_tab.refresh()

    def edit_settings(self) -> None:
        dialog = DpsSettingsDialog(self._service.settings(), self)
        if dialog.exec() == DpsSettingsDialog.DialogCode.Accepted:
            self._service.update_settings(dialog.settings())
            self.refresh()


class RankingRow(QWidget):
    """Posição, nome, dano total e DPS, com barra proporcional ao 1º colocado."""

    def __init__(self, entry: RankingEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        name = ElidedLabel(f"{entry.position}º  {entry.pokemon.name}", objectName="FieldValue")
        total = QLabel(format_money(entry.breakdown.total), objectName="FieldValue")
        dps = QLabel(f"{format_money(entry.breakdown.dps)} DPS", objectName="MutedLabel")
        bar = QProgressBar(objectName="RankingBar")
        bar.setRange(0, BAR_RESOLUTION)
        bar.setValue(round(entry.share_of_leader * BAR_RESOLUTION))
        bar.setTextVisible(False)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(name, 1)
        top.addWidget(total)
        top.addWidget(dps)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)
        layout.addLayout(top)
        layout.addWidget(bar)
        warnings = []
        if entry.missing:
            warnings.append(f"{len(entry.missing)} sem teste")
        if entry.no_element:
            warnings.append(f"{len(entry.no_element)} sem elemento")
        if warnings:
            layout.addWidget(QLabel(" · ".join(warnings), objectName="WarningLabel"))
        if entry.pokemon.note:
            self.setToolTip(entry.pokemon.note)


class RankingTab(QWidget):
    """Ranking dos pokémons anexados ao boss e de onde vem o dano de cada um."""

    data_changed = Signal()

    def __init__(self, service: DpsService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._bosses: list[BossData] = []
        self._entries: list[RankingEntry] = []
        self._selected_id: int | None = None

        self._ranking = QListWidget(objectName="DpsRanking")
        self._ranking.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._ranking.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._ranking.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._ranking.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._ranking.currentRowChanged.connect(self._on_row_changed)
        self._ranking.itemDoubleClicked.connect(lambda _item: self.edit_selected())

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_empty_view())
        self._stack.addWidget(self._build_results_view())

        self._boss_summary = QLabel()
        self._boss_summary.setWordWrap(True)
        self._boss_summary.setTextFormat(Qt.TextFormat.RichText)
        self._boss_warning = QLabel(NO_WEAKNESSES_WARNING, objectName="WarningLabel")
        self._boss_warning.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(self._build_boss_bar())
        layout.addWidget(self._boss_summary)
        layout.addWidget(self._boss_warning)
        layout.addWidget(self._stack, 1)

        QShortcut(QKeySequence(Qt.Key.Key_Return), self._ranking, activated=self.edit_selected)
        QShortcut(QKeySequence.StandardKey.Delete, self._ranking, activated=self.remove_selected)
        self._update_buttons()

    # --------------------------------------------------------------- montagem

    def _build_boss_bar(self) -> QVBoxLayout:
        self.boss_combo = QComboBox()
        self.boss_combo.setMinimumWidth(150)
        self.boss_combo.currentIndexChanged.connect(self._on_boss_changed)
        self.source_combo = QComboBox()
        self.source_combo.setToolTip(
            "Efetividade: teste no dummy Neutro × fraqueza do boss\n"
            "Dummy: teste no dummy escolhido\n"
            "Dano real: teste feito dentro deste boss")
        for source in DamageSource:
            self.source_combo.addItem(source.label, source)
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        self.dummy_combo = QComboBox()
        self.dummy_combo.setToolTip("De qual dummy vem o dano no ranking deste boss")
        for value, label in DUMMY_OPTIONS:
            self.dummy_combo.addItem(label, value)
        self.dummy_combo.currentIndexChanged.connect(self._on_dummy_changed)

        menu = QMenu(self)
        menu.addAction("Novo boss…", self.new_boss)
        menu.addAction("Editar boss…", self.edit_boss)
        self._delete_boss_action: QAction = menu.addAction("Excluir boss…", self.delete_boss)
        bosses_button = QPushButton(icon("bosses"), "  Gerenciar bosses  ")
        bosses_button.setMenu(menu)

        self._add_button = QPushButton("Adicionar pokémon", objectName="PrimaryButton")
        self._add_button.setToolTip("Marcar quais pokémons podem lutar contra este boss")
        self._add_button.clicked.connect(self.choose_boss_pokemons)

        # Em duas linhas: em uma só, os seletores não cabem na janela mínima.
        boss_row = QHBoxLayout()
        boss_row.setSpacing(10)
        boss_row.addWidget(QLabel("Boss", objectName="FieldLabel"))
        boss_row.addWidget(self.boss_combo)
        boss_row.addWidget(bosses_button)
        boss_row.addStretch(1)
        boss_row.addWidget(self._add_button)

        source_row = QHBoxLayout()
        source_row.setSpacing(10)
        source_row.addWidget(QLabel("Calcular por", objectName="FieldLabel"))
        source_row.addWidget(self.source_combo)
        self._dummy_label = QLabel("Dummy", objectName="FieldLabel")
        source_row.addWidget(self._dummy_label)
        source_row.addWidget(self.dummy_combo)
        source_row.addStretch(1)

        bar = QVBoxLayout()
        bar.setSpacing(8)
        bar.addLayout(boss_row)
        bar.addLayout(source_row)
        return bar

    def _build_empty_view(self) -> QWidget:
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.addWidget(EmptyState(EMPTY_TITLE, EMPTY_MESSAGE))
        layout.addStretch(1)
        return view

    def _build_results_view(self) -> QWidget:
        self._detail_name = QLabel(objectName="SectionTitle")
        self._detail_name.setTextFormat(Qt.TextFormat.PlainText)
        self._detail_summary = QLabel(objectName="MutedLabel")
        self._detail_note = QLabel(objectName="MutedLabel")
        self._detail_note.setWordWrap(True)
        self._detail_note.setTextFormat(Qt.TextFormat.PlainText)
        self._detail_warning = QLabel(objectName="WarningLabel")
        self._detail_warning.setWordWrap(True)
        self._detail_warning.setTextFormat(Qt.TextFormat.PlainText)
        self._lines_table = RecordTable(self._line_columns())
        self._lines_table.sortByColumn(2, Qt.SortOrder.DescendingOrder)

        edit_button = QPushButton(icon("open"), "  Editar")
        edit_button.setToolTip("Editar o cadastro deste pokémon")
        edit_button.clicked.connect(self.edit_selected)
        self._remove_button = QPushButton(icon("close"), "  Remover")
        self._remove_button.setToolTip("Tirar o pokémon deste boss, sem apagar o cadastro")
        self._remove_button.clicked.connect(self.remove_selected)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self._detail_name)
        titles.addWidget(self._detail_summary)
        heading = QHBoxLayout()
        heading.setSpacing(8)
        heading.addLayout(titles, 1)
        heading.addWidget(edit_button)
        heading.addWidget(self._remove_button)

        detail = QVBoxLayout()
        detail.setSpacing(8)
        detail.addLayout(heading)
        detail.addWidget(self._detail_note)
        detail.addWidget(self._detail_warning)
        detail.addWidget(self._lines_table, 1)

        view = QWidget()
        layout = QHBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self._ranking.setMinimumWidth(280)
        layout.addWidget(self._ranking, 1)
        layout.addLayout(detail, 2)
        return view

    def _line_columns(self) -> list[Column[DamageLine]]:
        return [
            Column("Origem", lambda line: line.source, fit_contents=True),
            Column("Detalhe", lambda line: line.detail,
                   tooltip="Dano / recarga · aproveitamento"),
            Column("Dano total", lambda line: line.total, format_money, numeric=True,
                   fit_contents=True),
            Column("% do total", self._line_share, format_percent, numeric=True,
                   fit_contents=True),
        ]

    def _line_share(self, line: DamageLine) -> float | None:
        entry = self.selected_entry()
        return line.total / entry.breakdown.total if entry and entry.breakdown.total else None

    # ------------------------------------------------------------------ dados

    @property
    def current_boss(self) -> BossData | None:
        boss_id = self.boss_combo.currentData()
        return next((boss for boss in self._bosses if boss.id == boss_id), None)

    def selected_entry(self) -> RankingEntry | None:
        row = self._ranking.currentRow()
        return self._entries[row] if 0 <= row < len(self._entries) else None

    def refresh(self) -> None:
        self._bosses = self._service.list_bosses()
        current_id = self.boss_combo.currentData()
        if current_id is None:
            current_id = self._service.settings().last_boss_id
        self.boss_combo.blockSignals(True)
        self.boss_combo.clear()
        for boss in self._bosses:
            self.boss_combo.addItem(f"{boss.name} · {_format_time(boss.time_limit_seconds)}",
                                    boss.id)
        index = self.boss_combo.findData(current_id)
        self.boss_combo.setCurrentIndex(index if index >= 0 else 0)
        self.boss_combo.blockSignals(False)
        self._delete_boss_action.setEnabled(len(self._bosses) > 1)
        self._show_ranking()

    def _on_boss_changed(self, _index: int) -> None:
        boss = self.current_boss
        if boss is not None:
            self._service.remember_boss(boss.id)
        self._show_ranking()

    def _on_dummy_changed(self, _index: int) -> None:
        boss = self.current_boss
        if boss is not None:
            self._service.set_boss_dummy(boss.id, self.dummy_combo.currentData())
            self.refresh()

    def _on_source_changed(self, _index: int) -> None:
        boss = self.current_boss
        if boss is not None:
            self._service.set_boss_damage_source(boss.id, self.source_combo.currentData())
            self.refresh()

    def _show_boss_options(self, boss: BossData) -> None:
        self.source_combo.blockSignals(True)
        self.source_combo.setCurrentIndex(self.source_combo.findData(boss.damage_source))
        self.source_combo.blockSignals(False)
        self.dummy_combo.blockSignals(True)
        self.dummy_combo.setCurrentIndex(self.dummy_combo.findData(boss.dummy))
        self.dummy_combo.blockSignals(False)
        uses_dummy = boss.damage_source is DamageSource.DUMMY
        self._dummy_label.setVisible(uses_dummy)
        self.dummy_combo.setVisible(uses_dummy)
        summary = _boss_summary_text(boss)
        self._boss_summary.setText(summary)
        self._boss_summary.setVisible(bool(summary))
        self._boss_warning.setVisible(boss.damage_source is DamageSource.EFFECTIVENESS
                                      and not boss.effectiveness)

    def _show_ranking(self) -> None:
        boss = self.current_boss
        self._entries = self._service.ranking(boss.id) if boss else []
        if boss is not None:
            self._show_boss_options(boss)

        selected_id = self._selected_id
        self._ranking.blockSignals(True)
        self._ranking.clear()
        for entry in self._entries:
            row = RankingRow(entry)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, row.sizeHint().height()))  # largura: a da lista
            self._ranking.addItem(item)
            self._ranking.setItemWidget(item, row)
        current = next((row for row, entry in enumerate(self._entries)
                        if entry.pokemon.id == selected_id), 0 if self._entries else -1)
        self._ranking.setCurrentRow(current)
        self._ranking.blockSignals(False)

        self._stack.setCurrentIndex(1 if self._entries else 0)
        self._show_details()

    def _on_row_changed(self, _row: int) -> None:
        self._show_details()

    def _show_details(self) -> None:
        entry = self.selected_entry()
        self._selected_id = entry.pokemon.id if entry else self._selected_id
        if entry is None:
            self._lines_table.set_records([])
        else:
            self._detail_name.setText(entry.pokemon.name)
            self._detail_summary.setText(
                f"Dano total: {format_money(entry.breakdown.total)} · "
                f"DPS: {format_money(entry.breakdown.dps)}")
            self._detail_note.setText(entry.pokemon.note)
            self._detail_note.setVisible(bool(entry.pokemon.note))
            self._detail_warning.setText(self._missing_text(entry))
            self._detail_warning.setVisible(bool(entry.missing or entry.no_element))
            self._lines_table.set_records(entry.breakdown.lines)
        self._update_buttons()

    def _missing_text(self, entry: RankingEntry) -> str:
        boss = self.current_boss
        if boss is None:
            return ""
        parts = []
        if entry.missing:
            where = ("neste boss" if boss.damage_source is DamageSource.REAL
                     else f"no dummy {dummy_label(boss.base_dummy)}")
            parts.append(f"Sem teste {where}: {', '.join(entry.missing)}.")
        if entry.no_element:
            parts.append(f"Sem elemento: {', '.join(entry.no_element)}.")
        return " ".join(parts)

    def _update_buttons(self) -> None:
        self._remove_button.setEnabled(self.selected_entry() is not None)

    # --------------------------------------------------------- ações: pokémons

    def edit_selected(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            return
        boss = self.current_boss
        dialog = PokemonDialog(self._service.settings(), entry.pokemon, self,
                               boss.base_dummy if boss else NEUTRAL_DUMMY)
        if dialog.exec() != PokemonDialog.DialogCode.Accepted:
            return
        self._service.save_pokemon(entry.pokemon.id, dialog.pokemon_name(), dialog.note(),
                                   dialog.spec())
        self.data_changed.emit()
        announce(self, f"{dialog.pokemon_name()} salvo.")

    def remove_selected(self) -> None:
        entry, boss = self.selected_entry(), self.current_boss
        if entry is None or boss is None:
            return
        self._service.set_boss_pokemons(boss.id, boss.pokemon_ids - {entry.pokemon.id})
        self.data_changed.emit()
        announce(self, f"{entry.pokemon.name} removido de {boss.name}.")

    def choose_boss_pokemons(self) -> None:
        boss = self.current_boss
        if boss is None:
            return
        pokemons = self._service.list_pokemons()
        if not pokemons:
            QMessageBox.information(self, "Adicionar ao boss",
                                    "Cadastre um pokémon na aba Pokémons primeiro.")
            return
        dialog = BossPokemonsDialog(boss, pokemons, boss.pokemon_ids, self)
        if dialog.exec() == BossPokemonsDialog.DialogCode.Accepted:
            self._service.set_boss_pokemons(boss.id, dialog.selected_ids())
            self.data_changed.emit()

    # ----------------------------------------------------------- ações: bosses

    def new_boss(self) -> None:
        dialog = BossDialog(self._bosses, parent=self)
        if dialog.exec() == BossDialog.DialogCode.Accepted:
            self.save_boss(None, dialog.boss_name(), dialog.time_limit_seconds(),
                           dialog.elements(), dialog.effectiveness())

    def edit_boss(self) -> None:
        boss = self.current_boss
        if boss is None:
            return
        dialog = BossDialog(self._bosses, boss, self)
        if dialog.exec() == BossDialog.DialogCode.Accepted:
            self.save_boss(boss.id, dialog.boss_name(), dialog.time_limit_seconds(),
                           dialog.elements(), dialog.effectiveness())

    def save_boss(self, boss_id: int | None, name: str, time_limit_seconds: int,
                  elements: Sequence[Element] | None = None,
                  effectiveness: Mapping[Element, EffectivenessLevel] | None = None) -> None:
        saved_id = self._service.save_boss(boss_id, name, time_limit_seconds, elements,
                                           effectiveness)
        self.data_changed.emit()
        self.show_boss(saved_id)

    def show_boss(self, boss_id: int) -> None:
        index = self.boss_combo.findData(boss_id)
        if index >= 0:
            self.boss_combo.setCurrentIndex(index)

    def delete_boss(self) -> None:
        boss = self.current_boss
        if boss is None or len(self._bosses) <= 1:
            return
        answer = QMessageBox.question(
            self, "Excluir boss",
            f"Excluir o boss {boss.name}?\n\nOs pokémons continuam cadastrados.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._service.delete_boss(boss.id)
            self.data_changed.emit()


def _element_tag(element: Element) -> str:
    """Etiqueta com a cor do tipo; o texto escuro ou branco é o que contrasta mais."""
    color = ELEMENT_COLORS[element.label]
    red, green, blue = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    text = "#15192a" if 0.299 * red + 0.587 * green + 0.114 * blue > 140 else "#ffffff"
    return (f'<span style="background-color:{color}; color:{text};">'
            f"&nbsp;{element.label}&nbsp;</span>")


def _boss_summary_text(boss: BossData) -> str:
    """Elementos do boss e os ataques fora do Normal, agrupados como no jogo."""
    groups = []
    if boss.elements:
        groups.append(("Elemento", boss.elements))
    for level in EffectivenessLevel:
        elements = [element for element in Element if boss.effectiveness.get(element) is level]
        if elements:
            groups.append((f"{level.label} {format_plain(level.multiplier)}x".replace(
                " ", "&nbsp;"), elements))
    return "&nbsp;&nbsp;&nbsp; ".join(
        f'<span style="color:{COLORS["muted"]};">{title}</span>&nbsp;'
        + "&nbsp;".join(_element_tag(element) for element in elements)
        for title, elements in groups)


def _format_time(seconds: int) -> str:
    if seconds % 60 == 0:
        return format_duration_long(seconds)
    return f"{format_plain(seconds)}s"
