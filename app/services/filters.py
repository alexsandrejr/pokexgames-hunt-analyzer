"""Critérios de filtro de Hunts (independentes de banco e de interface).

Um ``HuntFilter`` combina todos os critérios com **E**: só passam as Hunts que
atendem a todos. Listas de condições (inimigos, itens, métricas) permitem
consultas como "Nightmare ore > 50 E Nightmare gem > 1000".
O repositório traduz o filtro em SQL (``app/database/query_filters.py``).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

from app.utils.formatters import format_date, format_duration, format_number


class Operator(Enum):
    GT = ">"
    GE = ">="
    EQ = "="
    LE = "<="
    LT = "<"


class Metric(Enum):
    """Métricas numéricas filtráveis. O valor é o nome da coluna em ``HuntSession``."""

    PROFIT = "profit"
    PROFIT_PER_HOUR = "profit_per_hour"
    KILLS = "kills"
    KILLS_PER_HOUR = "kills_per_hour"
    DURATION = "duration_seconds"
    SUPPLIES = "supplies"
    SUPPLIES_PER_HOUR = "supplies_per_hour"
    RAW_GAINS = "raw_gains"
    RAW_GAINS_PER_HOUR = "raw_gains_per_hour"

    @property
    def label(self) -> str:
        return METRIC_LABELS[self]

    @property
    def is_duration(self) -> bool:
        return self is Metric.DURATION


METRIC_LABELS: dict[Metric, str] = {
    Metric.PROFIT: "Profit",
    Metric.PROFIT_PER_HOUR: "Profit/h",
    Metric.KILLS: "Kills",
    Metric.KILLS_PER_HOUR: "Kills/h",
    Metric.DURATION: "Duração",
    Metric.SUPPLIES: "Supplies",
    Metric.SUPPLIES_PER_HOUR: "Supplies/h",
    Metric.RAW_GAINS: "Raw gains",
    Metric.RAW_GAINS_PER_HOUR: "Raw gains/h",
}


class ItemSource(Enum):
    DROPS = "drops"
    SUPPLIES = "supplies"

    @property
    def label(self) -> str:
        return "Drop" if self is ItemSource.DROPS else "Supply"


@dataclass(frozen=True)
class MetricCondition:
    metric: Metric
    operator: Operator
    value: float  # duração em segundos

    def describe(self) -> str:
        value = (format_duration(self.value) if self.metric.is_duration
                 else format_number(self.value))
        return f"{self.metric.label} {self.operator.value} {value}"


@dataclass(frozen=True)
class QuantityCondition:
    """Presença de um inimigo/item na Hunt, opcionalmente com quantidade.

    Sem ``operator``/``quantity``: basta aparecer na Hunt. Com quantidade, a soma
    na Hunt é comparada (Hunts em que o nome não aparece contam como 0).
    """

    name: str
    operator: Operator | None = None
    quantity: float | None = None

    @property
    def has_quantity(self) -> bool:
        return self.operator is not None and self.quantity is not None

    def _describe(self, prefix: str) -> str:
        if self.has_quantity:
            return f"{prefix}: {self.name} {self.operator.value} {format_number(self.quantity)}"
        return f"{prefix}: {self.name}"


@dataclass(frozen=True)
class EnemyCondition(QuantityCondition):
    def describe(self) -> str:
        return self._describe("Inimigo")


@dataclass(frozen=True)
class ItemCondition(QuantityCondition):
    source: ItemSource = ItemSource.DROPS

    def describe(self) -> str:
        return self._describe(self.source.label)


@dataclass(frozen=True)
class HuntFilter:
    date_from: date | None = None
    date_to: date | None = None
    player: str | None = None  # contém, sem diferenciar maiúsculas
    enemies: tuple[EnemyCondition, ...] = field(default_factory=tuple)
    items: tuple[ItemCondition, ...] = field(default_factory=tuple)
    metrics: tuple[MetricCondition, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not self.describe()

    def describe(self) -> list[str]:
        """Descrição legível de cada critério ativo (usada nos resumos da interface)."""
        parts: list[str] = []
        if self.date_from and self.date_to:
            parts.append(f"Data: {format_date(self.date_from)} a {format_date(self.date_to)}")
        elif self.date_from:
            parts.append(f"Data: a partir de {format_date(self.date_from)}")
        elif self.date_to:
            parts.append(f"Data: até {format_date(self.date_to)}")
        if self.player:
            parts.append(f"Player: {self.player}")
        parts += [condition.describe() for condition in self.enemies]
        parts += [condition.describe() for condition in self.items]
        parts += [condition.describe() for condition in self.metrics]
        return parts


EMPTY_FILTER = HuntFilter()


class DatePreset(Enum):
    ALL = "Todo o período"
    TODAY = "Hoje"
    LAST_7_DAYS = "Últimos 7 dias"
    LAST_30_DAYS = "Últimos 30 dias"
    THIS_MONTH = "Este mês"
    LAST_MONTH = "Mês passado"
    CUSTOM = "Personalizado"


def preset_range(preset: DatePreset, today: date) -> tuple[date | None, date | None]:
    """Intervalo (inclusivo) de um período pré-definido."""
    if preset is DatePreset.TODAY:
        return today, today
    if preset is DatePreset.LAST_7_DAYS:
        return today - timedelta(days=6), today
    if preset is DatePreset.LAST_30_DAYS:
        return today - timedelta(days=29), today
    if preset is DatePreset.THIS_MONTH:
        return today.replace(day=1), today
    if preset is DatePreset.LAST_MONTH:
        last_day_previous = today.replace(day=1) - timedelta(days=1)
        first = last_day_previous.replace(day=1)
        days = calendar.monthrange(first.year, first.month)[1]
        return first, first.replace(day=days)
    return None, None
