"""Tradução de ``HuntFilter`` em condições SQL sobre ``hunt_sessions``."""

from __future__ import annotations

import operator as op
from collections.abc import Callable
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Float, exists, func, select

from app.database.models import Drop, EnemyDefeated, HuntSession, Supply
from app.services.filters import (
    EnemyCondition,
    HuntFilter,
    ItemCondition,
    ItemSource,
    Metric,
    MetricCondition,
    Operator,
)

OPERATORS: dict[Operator, Callable[[Any, Any], Any]] = {
    Operator.GT: op.gt,
    Operator.GE: op.ge,
    Operator.EQ: op.eq,
    Operator.LE: op.le,
    Operator.LT: op.lt,
}

ITEM_MODELS = {ItemSource.DROPS: Drop, ItemSource.SUPPLIES: Supply}


def hunt_filter_conditions(hunt_filter: HuntFilter | None) -> list[ColumnElement[bool]]:
    """Lista de condições (combinadas com E) para ``select(...).where(*conds)``."""
    if hunt_filter is None:
        return []
    conditions: list[ColumnElement[bool]] = []
    if hunt_filter.categories:
        conditions.append(HuntSession.category.in_([c.value for c in hunt_filter.categories]))
    if hunt_filter.date_from:
        start = datetime.combine(hunt_filter.date_from, time.min)
        conditions.append(HuntSession.start_datetime >= start)
    if hunt_filter.date_to:
        end = datetime.combine(hunt_filter.date_to + timedelta(days=1), time.min)
        conditions.append(HuntSession.start_datetime < end)
    if hunt_filter.player:
        pattern = f"%{_escape_like(hunt_filter.player.strip())}%"
        conditions.append(HuntSession.player.ilike(pattern, escape="\\"))
    conditions += [_enemy_condition(c) for c in hunt_filter.enemies]
    conditions += [_item_condition(c) for c in hunt_filter.items]
    conditions += [_metric_condition(c) for c in hunt_filter.metrics]
    return conditions


def filtered_hunt_ids(hunt_filter: HuntFilter | None):
    """Subconsulta com os ids das Hunts que passam no filtro."""
    return select(HuntSession.id).where(*hunt_filter_conditions(hunt_filter))


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _metric_condition(condition: MetricCondition) -> ColumnElement[bool]:
    column = getattr(HuntSession, condition.metric.value)
    compare = OPERATORS[condition.operator]
    if condition.operator is Operator.EQ and _is_rate(condition.metric):
        # Taxas são decimais (935099.58...): "=" compara o valor arredondado exibido.
        return func.round(column) == round(condition.value)
    return compare(column, condition.value)


def _is_rate(metric: Metric) -> bool:
    return isinstance(HuntSession.__table__.c[metric.value].type, Float)


def _enemy_condition(condition: EnemyCondition) -> ColumnElement[bool]:
    return _quantity_condition(EnemyDefeated, EnemyDefeated.enemy, condition)


def _item_condition(condition: ItemCondition) -> ColumnElement[bool]:
    model = ITEM_MODELS[condition.source]
    return _quantity_condition(model, model.item, condition)


def _quantity_condition(model: Any, name_column: Any,
                        condition: EnemyCondition | ItemCondition) -> ColumnElement[bool]:
    same_name = func.lower(name_column) == condition.name.strip().lower()
    belongs_to_hunt = model.hunt_id == HuntSession.id
    if not condition.has_quantity:
        return exists().where(belongs_to_hunt, same_name)
    total = (
        select(func.coalesce(func.sum(model.count), 0))
        .where(belongs_to_hunt, same_name)
        .scalar_subquery()
    )
    return OPERATORS[condition.operator](total, condition.quantity)
