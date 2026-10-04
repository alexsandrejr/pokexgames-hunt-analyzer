"""Objetos simples trocados entre serviços e interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from app.services.categories import Category


class ImportStatus(Enum):
    IMPORTED = "imported"
    DUPLICATE = "duplicate"
    ERROR = "error"


@dataclass
class ImportResult:
    status: ImportStatus
    source: str
    message: str
    hunt_id: int | None = None
    duplicate_of: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    detail: str | None = None
    saved_path: Path | None = None  # arquivo criado a partir de um JSON colado
    category: Category | None = None  # categoria em que a sessão foi gravada

    @property
    def source_name(self) -> str:
        return Path(self.source).name if self.source else ""


@dataclass(frozen=True)
class HuntSummary:
    """Linha da listagem de Hunts (sem JSON e sem listas relacionadas)."""

    id: int
    session_id: int | None
    player: str | None
    start_datetime: datetime | None
    duration_seconds: int | None
    status: str | None
    kills: int | None
    kills_per_hour: float | None
    profit: int | None
    profit_per_hour: float | None
    supplies: int | None
    supplies_per_hour: float | None
    raw_gains: int | None
    raw_gains_per_hour: float | None
    damage_dealt: int | None = None
    damage_dealt_per_second: float | None = None
    damage_taken: int | None = None
    damage_taken_per_second: float | None = None
    experience: int | None = None
    experience_per_hour: float | None = None
    source_file: str | None = None
    category: str = Category.HUNT.value


@dataclass(frozen=True)
class FilterOptions:
    """Valores conhecidos no banco, oferecidos nas listas do painel de filtros."""

    players: list[str] = field(default_factory=list)
    enemies: list[str] = field(default_factory=list)
    drop_items: list[str] = field(default_factory=list)
    supply_items: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RankedEntry:
    """Item ou inimigo somado sobre um conjunto de Hunts."""

    name: str
    quantity: int
    value: int | None
    hunt_count: int

    @property
    def average_per_hunt(self) -> float | None:
        return self.quantity / self.hunt_count if self.hunt_count else None
