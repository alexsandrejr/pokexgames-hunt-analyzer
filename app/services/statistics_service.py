"""Cálculos estatísticos sobre as Hunts armazenadas (sempre sobre um filtro).

Atenção à diferença entre as duas formas de "Profit/h":

* ``average_profit_per_hour``: média simples dos Profit/h de cada Hunt
  (cada Hunt pesa igual, seja de 10 minutos ou de 3 horas);
* ``profit_per_total_hour``: Profit total ÷ tempo total (ponderado pelo tempo).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.database.database import Database
from app.database.repositories import HuntRepository
from app.services.dto import RankedEntry
from app.services.entity_report import EntityHuntRow, EntityKind, EntityReport
from app.services.filters import HuntFilter, ItemSource
from app.services.rates import rate_per_hour, rate_per_second
from app.utils.formatters import ValueKind


@dataclass(frozen=True)
class OverviewStats:
    hunt_count: int = 0
    total_duration_seconds: int = 0
    total_kills: int = 0
    total_profit: int = 0
    total_supplies: int = 0
    total_raw_gains: int = 0
    total_experience: int = 0
    total_damage_dealt: int = 0
    total_damage_taken: int = 0
    average_profit: float | None = None
    average_profit_per_hour: float | None = None
    average_kills_per_hour: float | None = None
    average_supplies_per_hour: float | None = None
    average_damage_dealt_per_second: float | None = None
    first_start: datetime | None = None
    last_start: datetime | None = None

    @property
    def average_duration_seconds(self) -> float | None:
        return self.total_duration_seconds / self.hunt_count if self.hunt_count else None

    @property
    def average_kills(self) -> float | None:
        return self.total_kills / self.hunt_count if self.hunt_count else None

    @property
    def profit_per_total_hour(self) -> float | None:
        return rate_per_hour(self.total_profit, self.total_duration_seconds)

    @property
    def kills_per_total_hour(self) -> float | None:
        return rate_per_hour(self.total_kills, self.total_duration_seconds)

    @property
    def supplies_per_total_hour(self) -> float | None:
        return rate_per_hour(self.total_supplies, self.total_duration_seconds)

    @property
    def raw_gains_per_total_hour(self) -> float | None:
        return rate_per_hour(self.total_raw_gains, self.total_duration_seconds)


class RateUnit(Enum):
    HOUR = "/h"
    SECOND = "/s"


@dataclass(frozen=True)
class MetricStats:
    """Estatísticas de uma métrica sobre as Hunts filtradas."""

    key: str
    label: str
    kind: ValueKind
    rate_unit: RateUnit | None
    total: float | None
    average: float | None
    minimum: float | None
    maximum: float | None
    average_rate: float | None  # média simples das taxas individuais
    rate_over_total_time: float | None  # total ÷ tempo total


# (chave, rótulo, formato, unidade da taxa) na ordem exibida no relatório.
METRIC_DEFINITIONS: tuple[tuple[str, str, ValueKind, RateUnit | None], ...] = (
    ("duration", "Duração", ValueKind.DURATION, None),
    ("kills", "Kills", ValueKind.NUMBER, RateUnit.HOUR),
    ("profit", "Profit", ValueKind.MONEY, RateUnit.HOUR),
    ("supplies", "Supplies", ValueKind.MONEY, RateUnit.HOUR),
    ("raw_gains", "Raw gains", ValueKind.MONEY, RateUnit.HOUR),
    ("experience", "Experience", ValueKind.NUMBER, RateUnit.HOUR),
    ("damage_dealt", "Damage dealt", ValueKind.NUMBER, RateUnit.SECOND),
    ("damage_taken", "Damage taken", ValueKind.NUMBER, RateUnit.SECOND),
)


def build_metric_stats(values: dict) -> list[MetricStats]:
    """Converte o resultado de ``HuntRepository.aggregate_metrics`` em ``MetricStats``."""
    total_duration = values.get("duration_sum")
    stats = []
    for key, label, kind, unit in METRIC_DEFINITIONS:
        total = values.get(f"{key}_sum")
        if unit is RateUnit.HOUR:
            over_time = rate_per_hour(total, total_duration)
        elif unit is RateUnit.SECOND:
            over_time = rate_per_second(total, total_duration)
        else:
            over_time = None
        stats.append(MetricStats(
            key=key, label=label, kind=kind, rate_unit=unit,
            total=total,
            average=values.get(f"{key}_avg"),
            minimum=values.get(f"{key}_min"),
            maximum=values.get(f"{key}_max"),
            average_rate=values.get(f"{key}_rate_avg"),
            rate_over_total_time=over_time,
        ))
    return stats


class StatisticsService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def overview(self, hunt_filter: HuntFilter | None = None) -> OverviewStats:
        with self.database.session() as session:
            values = HuntRepository(session).aggregate_overview(hunt_filter)
        return OverviewStats(**values)

    def metric_breakdown(self, hunt_filter: HuntFilter | None = None) -> list[MetricStats]:
        with self.database.session() as session:
            values = HuntRepository(session).aggregate_metrics(hunt_filter)
        return build_metric_stats(values)

    def top_drops(self, hunt_filter: HuntFilter | None = None, limit: int = 20) -> list[RankedEntry]:
        return self._top(ItemSource.DROPS.value, hunt_filter, limit)

    def top_supplies(self, hunt_filter: HuntFilter | None = None,
                     limit: int = 20) -> list[RankedEntry]:
        return self._top(ItemSource.SUPPLIES.value, hunt_filter, limit)

    def top_enemies(self, hunt_filter: HuntFilter | None = None,
                    limit: int = 20) -> list[RankedEntry]:
        return self._top("enemies", hunt_filter, limit)

    def entity_report(self, kind: EntityKind, name: str,
                      hunt_filter: HuntFilter | None = None) -> EntityReport:
        with self.database.session() as session:
            rows = HuntRepository(session).entity_per_hunt(kind.value, name, hunt_filter)
        return EntityReport(kind, name.strip(), tuple(EntityHuntRow(**row) for row in rows))

    def _top(self, kind: str, hunt_filter: HuntFilter | None, limit: int) -> list[RankedEntry]:
        with self.database.session() as session:
            rows = HuntRepository(session).top_entries(kind, hunt_filter, limit)
        return [RankedEntry(**row) for row in rows]
