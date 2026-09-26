"""Relatório de um item (drop/supply) ou inimigo ao longo das Hunts filtradas.

As médias por Hunt e por hora consideram **as Hunts em que o nome apareceu**:
é a resposta para "quando esse item cai, quanto cai?". A presença (em quantas
das Hunts filtradas ele apareceu) é informada à parte.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.services.rates import rate_per_hour


class EntityKind(Enum):
    DROPS = "drops"
    SUPPLIES = "supplies"
    ENEMIES = "enemies"

    @property
    def label(self) -> str:
        return {"drops": "Drop", "supplies": "Supply", "enemies": "Inimigo"}[self.value]

    @property
    def has_value(self) -> bool:
        """Inimigos não têm preço."""
        return self is not EntityKind.ENEMIES


@dataclass(frozen=True)
class EntityHuntRow:
    hunt_id: int
    session_id: int | None
    start_datetime: datetime | None
    duration_seconds: int | None
    quantity: int
    value: int | None

    @property
    def present(self) -> bool:
        return self.quantity > 0


@dataclass(frozen=True)
class EntityReport:
    kind: EntityKind
    name: str
    rows: tuple[EntityHuntRow, ...]  # todas as Hunts filtradas, em ordem cronológica

    @property
    def present_rows(self) -> tuple[EntityHuntRow, ...]:
        return tuple(row for row in self.rows if row.present)

    @property
    def hunt_count(self) -> int:
        return len(self.rows)

    @property
    def present_count(self) -> int:
        return len(self.present_rows)

    @property
    def presence_ratio(self) -> float | None:
        return self.present_count / self.hunt_count if self.hunt_count else None

    @property
    def total_quantity(self) -> int:
        return sum(row.quantity for row in self.rows)

    @property
    def total_value(self) -> int | None:
        if not self.kind.has_value:
            return None
        return sum(row.value or 0 for row in self.rows)

    @property
    def average_per_hunt(self) -> float | None:
        return self.total_quantity / self.present_count if self.present_count else None

    @property
    def average_value_per_hunt(self) -> float | None:
        total = self.total_value
        return total / self.present_count if total is not None and self.present_count else None

    @property
    def present_duration_seconds(self) -> int:
        return sum(row.duration_seconds or 0 for row in self.present_rows)

    @property
    def per_hour(self) -> float | None:
        return rate_per_hour(self.total_quantity, self.present_duration_seconds)

    @property
    def value_per_hour(self) -> float | None:
        return rate_per_hour(self.total_value, self.present_duration_seconds)

    @property
    def max_row(self) -> EntityHuntRow | None:
        return max(self.present_rows, key=lambda row: row.quantity, default=None)

    @property
    def min_row(self) -> EntityHuntRow | None:
        return min(self.present_rows, key=lambda row: row.quantity, default=None)
