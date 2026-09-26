"""Painel de filtros reutilizável (uma única instância, movida entre as páginas).

O painel só monta um ``HuntFilter`` a partir dos campos; aplicar o filtro é
responsabilidade do ``FilterController``. Campos vazios não filtram nada.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.services.advanced_search import parse_advanced_query
from app.services.dto import FilterOptions
from app.services.filters import (
    DatePreset,
    EnemyCondition,
    HuntFilter,
    ItemCondition,
    ItemSource,
    Metric,
    MetricCondition,
    Operator,
    preset_range,
)
from app.ui.filters.filter_controller import FilterController
from app.ui.icons import icon
from app.ui.widgets.cards import ResponsiveGrid
from app.ui.widgets.combos import searchable_combo, set_combo_options
from app.ui.widgets.elided_label import ElidedLabel
from app.utils.validators import parse_user_duration, parse_user_number

ADVANCED_HELP = "\n".join((
    "Condições separadas por “e”, “;” ou “&”, todas combinadas.",
    "• Item ou inimigo: nightmare ore > 50   ·   Mecha Charizard >= 40   ·   metal scraps",
    "• Métricas: profit/h >= 800k   ·   kills/h > 300   ·   duração >= 1h30",
    "• Operadores: >  >=  =  <=  <",
    "• Para forçar o tipo: drop: nome   ·   supply: nome   ·   inimigo: nome",
))

# Métricas oferecidas no painel, na ordem exibida.
PANEL_METRICS = (Metric.PROFIT, Metric.PROFIT_PER_HOUR, Metric.KILLS,
                 Metric.KILLS_PER_HOUR, Metric.DURATION)
METRIC_PLACEHOLDERS = {
    Metric.PROFIT: "ex.: 1kk", Metric.PROFIT_PER_HOUR: "ex.: 800k",
    Metric.KILLS: "ex.: 300", Metric.KILLS_PER_HOUR: "ex.: 250",
    Metric.DURATION: "ex.: 1:30 ou 90",
}


def _operator_combo(default: Operator) -> QComboBox:
    combo = QComboBox()
    for operator in Operator:
        combo.addItem(operator.value, operator)
    combo.setCurrentIndex(combo.findData(default))
    combo.setFixedWidth(64)
    return combo


def _mark_invalid(widget: QWidget, invalid: bool) -> None:
    widget.setProperty("invalid", invalid)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _row(*widgets: QWidget, stretch_index: int | None = None) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, 1 if index == stretch_index else 0)
    return container


@dataclass
class _QuantityInputs:
    name: QComboBox
    operator: QComboBox
    quantity: QLineEdit


class FilterPanel(QFrame):
    """Cabeçalho recolhível com resumo dos filtros ativos + formulário de critérios."""

    def __init__(self, controller: FilterController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FilterPanel")
        # Nunca cresce além do conteúdo (senão sobra espaço quando a lista abaixo está vazia).
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._controller = controller
        self._options = FilterOptions()

        self._toggle = QToolButton(objectName="FilterToggle")
        self._toggle.setText("  Filtros")
        self._toggle.setIcon(icon("filter"))
        self._toggle.setIconSize(QSize(16, 16))
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setCheckable(True)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.toggled.connect(self.set_expanded)

        self._badge = QLabel(objectName="FilterBadge")
        self._summary = ElidedLabel(objectName="MutedLabel")
        self._clear_button = QPushButton(icon("close"), "  Limpar")
        self._clear_button.setObjectName("GhostButton")
        self._clear_button.clicked.connect(self.clear)
        self._chevron = QToolButton(objectName="FilterChevron")
        self._chevron.setCheckable(True)
        self._chevron.setIconSize(QSize(16, 16))
        self._chevron.toggled.connect(self._toggle.setChecked)
        self._toggle.toggled.connect(self._chevron.setChecked)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(self._toggle)
        header.addWidget(self._badge)
        header.addWidget(self._summary, 1)
        header.addWidget(self._clear_button)
        header.addWidget(self._chevron)

        self._body = self._build_body()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 10, 8)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self._body)

        controller.changed.connect(self._show_summary)
        self._show_summary(controller.current)
        self.set_expanded(False)

    # ------------------------------------------------------------ construção

    def _build_body(self) -> QWidget:
        self._preset = QComboBox()
        for preset in DatePreset:
            self._preset.addItem(preset.value, preset)
        self._preset.currentIndexChanged.connect(self._on_preset_changed)
        self._date_from = self._date_edit()
        self._date_to = self._date_edit()
        self._player = searchable_combo("Qualquer player")
        self._enemy = _QuantityInputs(searchable_combo("Qualquer inimigo"),
                                      _operator_combo(Operator.GE), self._line_edit("qtd."))
        self._item_source = QComboBox()
        for source in ItemSource:
            self._item_source.addItem(source.label + "s", source)
        self._item_source.currentIndexChanged.connect(self._refresh_item_options)
        self._item = _QuantityInputs(searchable_combo("Qualquer item"),
                                     _operator_combo(Operator.GE), self._line_edit("qtd."))
        for inputs in (self._enemy, self._item):
            inputs.quantity.setFixedWidth(90)

        general = QFormLayout()
        self._configure_form(general)
        general.addRow("Período", _row(self._preset, self._date_from, QLabel("a"),
                                       self._date_to, stretch_index=0))
        general.addRow("Player", self._player)
        general.addRow("Inimigo", _row(self._enemy.name, self._enemy.operator,
                                       self._enemy.quantity, stretch_index=0))
        general.addRow("Item", _row(self._item_source, self._item.name, self._item.operator,
                                    self._item.quantity, stretch_index=1))

        self._metric_inputs: dict[Metric, tuple[QComboBox, QLineEdit]] = {}
        metrics = QFormLayout()
        self._configure_form(metrics)
        for metric in PANEL_METRICS:
            operator = _operator_combo(Operator.GE)
            value = self._line_edit(METRIC_PLACEHOLDERS[metric])
            self._metric_inputs[metric] = (operator, value)
            metrics.addRow(metric.label, _row(operator, value, stretch_index=1))

        columns = ResponsiveGrid([self._form_widget(general), self._form_widget(metrics)],
                                 min_item_width=380, max_columns=2)

        self._advanced = self._line_edit(
            "Pesquisa avançada — ex.: nightmare ore > 50 e nightmare gem > 1000; kills/h >= 300")
        self._advanced.setToolTip(ADVANCED_HELP)
        advanced = QFormLayout()
        self._configure_form(advanced)
        advanced.addRow("Avançada", self._advanced)

        self._error = QLabel(objectName="ErrorLabel")
        self._error.setWordWrap(True)
        hint = QLabel("Todos os critérios são combinados (E). Campos vazios não filtram. "
                      "Valores aceitam 800k, 1,2kk ou 1.000.000.", objectName="CardHint")
        hint.setWordWrap(True)
        apply_button = QPushButton("Aplicar filtros")
        apply_button.setObjectName("PrimaryButton")
        apply_button.clicked.connect(self.apply)

        footer = QHBoxLayout()
        footer.addWidget(hint, 1)
        footer.addWidget(self._error, 1)
        footer.addWidget(apply_button)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(2, 6, 4, 4)
        layout.setSpacing(10)
        layout.addWidget(columns)
        layout.addLayout(advanced)
        layout.addLayout(footer)
        self._on_preset_changed()
        return body

    @staticmethod
    def _configure_form(form: QFormLayout) -> None:
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

    @staticmethod
    def _form_widget(form: QFormLayout) -> QWidget:
        widget = QWidget()
        widget.setLayout(form)
        return widget

    def _line_edit(self, placeholder: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setClearButtonEnabled(True)
        edit.returnPressed.connect(self.apply)
        edit.textChanged.connect(lambda _text, e=edit: _mark_invalid(e, False))
        return edit

    @staticmethod
    def _date_edit() -> QDateEdit:
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("dd/MM/yyyy")
        edit.setDate(QDate.currentDate())
        edit.setFixedWidth(120)
        return edit

    # --------------------------------------------------------------- estado

    def set_expanded(self, expanded: bool) -> None:
        self._body.setVisible(expanded)
        self._chevron.setIcon(icon("chevron-down" if expanded else "chevron-right"))
        if self._toggle.isChecked() != expanded:
            self._toggle.setChecked(expanded)

    def set_options(self, options: FilterOptions) -> None:
        """Atualiza as listas de players, inimigos e itens conhecidos."""
        self._options = options
        set_combo_options(self._player, options.players)
        set_combo_options(self._enemy.name, options.enemies)
        self._refresh_item_options()

    def _refresh_item_options(self) -> None:
        source = self._item_source.currentData()
        items = (self._options.supply_items if source is ItemSource.SUPPLIES
                 else self._options.drop_items)
        set_combo_options(self._item.name, items)

    def _on_preset_changed(self) -> None:
        preset = self._preset.currentData()
        custom = preset is DatePreset.CUSTOM
        self._date_from.setEnabled(custom)
        self._date_to.setEnabled(custom)
        if not custom:
            start, end = preset_range(preset, date.today())
            if start and end:
                self._date_from.setDate(QDate(start.year, start.month, start.day))
                self._date_to.setDate(QDate(end.year, end.month, end.day))

    # ------------------------------------------------------------ aplicação

    def apply(self) -> bool:
        hunt_filter, errors = self.build_filter()
        self._error.setText(" ".join(errors))
        if hunt_filter is None:
            return False
        self._controller.set_filter(hunt_filter)
        return True

    def clear(self) -> None:
        self._preset.setCurrentIndex(0)
        for combo in (self._player, self._enemy.name, self._item.name):
            combo.setEditText("")
        for edit in (self._enemy.quantity, self._item.quantity, self._advanced,
                     *(value for _op, value in self._metric_inputs.values())):
            edit.clear()
        self._error.clear()
        self._controller.clear()

    def build_filter(self) -> tuple[HuntFilter | None, list[str]]:
        """Monta o filtro dos campos; retorna ``(None, erros)`` se algo for inválido."""
        errors: list[str] = []
        date_from, date_to = self._date_range()
        if date_from and date_to and date_from > date_to:
            errors.append("A data inicial é posterior à final.")

        enemy = self._quantity_condition(self._enemy, "inimigo", errors)
        item = self._quantity_condition(self._item, "item", errors)
        metrics = []
        for metric, (operator, edit) in self._metric_inputs.items():
            text = edit.text().strip()
            if not text:
                continue
            value = parse_user_duration(text) if metric.is_duration else parse_user_number(text)
            _mark_invalid(edit, value is None)
            if value is None:
                errors.append(f"Valor inválido em {metric.label}.")
            else:
                metrics.append(MetricCondition(metric, operator.currentData(), value))

        advanced = parse_advanced_query(self._advanced.text(), self._options)
        _mark_invalid(self._advanced, not advanced.ok)
        errors += advanced.errors

        if errors:
            return None, errors
        return advanced.merged_into(HuntFilter(
            date_from=date_from,
            date_to=date_to,
            player=self._player.currentText().strip() or None,
            enemies=(EnemyCondition(*enemy),) if enemy else (),
            items=(ItemCondition(*item, source=self._item_source.currentData()),) if item else (),
            metrics=tuple(metrics),
        )), []

    def _date_range(self) -> tuple[date | None, date | None]:
        preset = self._preset.currentData()
        if preset is DatePreset.CUSTOM:
            return self._date_from.date().toPython(), self._date_to.date().toPython()
        return preset_range(preset, date.today())

    @staticmethod
    def _quantity_condition(inputs: _QuantityInputs, label: str,
                            errors: list[str]) -> tuple | None:
        name = inputs.name.currentText().strip()
        text = inputs.quantity.text().strip()
        quantity = parse_user_number(text) if text else None
        invalid = bool(text) and (quantity is None or not name)
        _mark_invalid(inputs.quantity, invalid)
        if invalid:
            errors.append(f"Quantidade inválida para {label}." if name
                          else f"Escolha um {label} para usar a quantidade.")
            return None
        if not name:
            return None
        return (name, inputs.operator.currentData(), quantity) if text else (name,)

    # --------------------------------------------------------------- resumo

    def _show_summary(self, hunt_filter: HuntFilter) -> None:
        parts = hunt_filter.describe()
        self._badge.setText(str(len(parts)))
        self._badge.setVisible(bool(parts))
        self._clear_button.setVisible(bool(parts))
        self._summary.set_full_text("  ·  ".join(parts) if parts
                                    else "Nenhum filtro ativo: exibindo todas as Hunts")
        self._summary.setToolTip("\n".join(parts))

    def mousePressEvent(self, event) -> None:  # clicar no cabeçalho alterna o painel
        if event.position().y() < 44:
            self._toggle.toggle()
        super().mousePressEvent(event)
