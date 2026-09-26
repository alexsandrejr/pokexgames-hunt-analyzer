"""Diálogo de detalhes de uma Hunt (abas Resumo, Enemies, Drops, Supplies...)."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.database.models import HuntSession
from app.services.hunt_service import HuntService
from app.ui.hunts.detail_tabs import ChartsTab, DropsTab, EnemiesTab, JsonTab, SuppliesTab
from app.ui.icons import icon
from app.ui.widgets.cards import ResponsiveGrid, StatCard
from app.utils.formatters import (
    format_datetime,
    format_duration,
    format_money,
    format_number,
    format_text,
)

Field = tuple[str, str]


class FieldGroup(QFrame):
    """Card com um título e pares rótulo/valor."""

    def __init__(self, title: str, fields: Sequence[Field], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        grid = QGridLayout(self)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel(title, objectName="SectionTitle"), 0, 0, 1, 2)
        for row, (label, value) in enumerate(fields, start=1):
            value_label = QLabel(value, objectName="FieldValue")
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(QLabel(label, objectName="FieldLabel"), row, 0)
            grid.addWidget(value_label, row, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(len(fields) + 1, 1)


def summary_groups(hunt: HuntSession) -> list[tuple[str, list[Field]]]:
    return [
        ("Sessão", [
            ("Player", format_text(hunt.player)),
            ("Session ID", format_text(hunt.session_id)),
            ("Data", format_datetime(hunt.start_datetime)),
            ("Status", format_text(hunt.status)),
            ("Session Type", format_text(hunt.session_type)),
            ("Duração", format_duration(hunt.duration_seconds)),
            ("Paused seconds", format_number(hunt.paused_seconds)),
            ("Tempo p/ próximo nível", format_text(hunt.time_to_next_level)),
        ]),
        ("Kills e experiência", [
            ("Kills", format_number(hunt.kills)),
            ("Kills/h", format_number(hunt.kills_per_hour)),
            ("Rare kills", format_number(hunt.rare_kills)),
            ("Rare kills/h", format_number(hunt.rare_kills_per_hour, decimals=1)),
            ("Experience", format_number(hunt.experience)),
            ("Experience/h", format_number(hunt.experience_per_hour)),
        ]),
        ("Economia", [
            ("Profit", format_money(hunt.profit)),
            ("Profit/h", format_money(hunt.profit_per_hour)),
            ("Supplies", format_money(hunt.supplies)),
            ("Supplies/h", format_money(hunt.supplies_per_hour)),
            ("Raw gains", format_money(hunt.raw_gains)),
            ("Raw gains/h", format_money(hunt.raw_gains_per_hour)),
        ]),
        ("Dano", [
            ("Damage dealt", format_number(hunt.damage_dealt)),
            ("Damage dealt/s", format_number(hunt.damage_dealt_per_second)),
            ("Damage taken", format_number(hunt.damage_taken)),
            ("Damage taken/s", format_number(hunt.damage_taken_per_second)),
        ]),
        ("Importação", [
            ("Arquivo", format_text(hunt.source_file)),
            ("Importada em", format_datetime(hunt.created_at)),
            ("ID interno", format_text(hunt.id)),
        ]),
    ]


class SummaryTab(QScrollArea):
    def __init__(self, hunt: HuntSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)

        highlights = ResponsiveGrid([
            StatCard("Duração", format_duration(hunt.duration_seconds)),
            StatCard("Kills", format_number(hunt.kills),
                     f"{format_number(hunt.kills_per_hour)} por hora"),
            StatCard("Profit", format_money(hunt.profit),
                     f"{format_money(hunt.profit_per_hour)} por hora"),
            StatCard("Raw gains", format_money(hunt.raw_gains),
                     f"Supplies: {format_money(hunt.supplies)}"),
        ], min_item_width=170)
        groups = ResponsiveGrid(
            [FieldGroup(title, fields) for title, fields in summary_groups(hunt)],
            min_item_width=300, max_columns=3,
        )

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        layout.addWidget(highlights)
        layout.addWidget(groups)
        layout.addStretch(1)
        self.setWidget(content)


class HuntDetailsDialog(QDialog):
    """Janela não-modal: várias Hunts podem ficar abertas lado a lado."""

    def __init__(self, hunt: HuntSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hunt = hunt
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowIcon(icon("app"))
        self.setWindowTitle(self._title())
        self.resize(1040, 720)

        heading = QLabel(self._title(), objectName="PageTitle")
        subtitle = QLabel(
            f"{format_text(hunt.player)} · {format_datetime(hunt.start_datetime)} · "
            f"{format_duration(hunt.duration_seconds)}",
            objectName="PageSubtitle",
        )

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(False)
        self.tabs.addTab(SummaryTab(hunt), "Resumo")
        self.tabs.addTab(EnemiesTab(hunt.enemies), f"Enemies ({len(hunt.enemies)})")
        self.tabs.addTab(DropsTab(hunt.drops), f"Drops ({len(hunt.drops)})")
        self.tabs.addTab(SuppliesTab(hunt.supplies_used), f"Supplies ({len(hunt.supplies_used)})")
        self.tabs.addTab(ChartsTab(hunt.enemies, hunt.drops, hunt.supplies_used), "Gráficos")
        self.tabs.addTab(JsonTab(hunt.raw_json), "JSON Original")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(4)
        layout.addWidget(heading)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        layout.addWidget(self.tabs, 1)

    def _title(self) -> str:
        return f"Hunt {format_text(self.hunt.session_id)}"


def show_hunt_details(service: HuntService, hunt_id: int,
                      parent: QWidget | None) -> HuntDetailsDialog | None:
    """Abre o diálogo de detalhes; avisa se a Hunt não existir mais."""
    hunt = service.get_hunt_details(hunt_id)
    if hunt is None:
        QMessageBox.warning(parent, "Hunt não encontrada",
                            "A Hunt selecionada não existe mais no banco de dados.")
        return None
    dialog = HuntDetailsDialog(hunt, parent)
    dialog.show()
    return dialog
