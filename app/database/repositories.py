"""Acesso a dados. Toda consulta SQL da aplicação fica concentrada aqui."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, delete, func, null, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.database.models import Drop, EnemyDefeated, HuntSession, ItemPrice, Supply
from app.database.query_filters import filtered_hunt_ids, hunt_filter_conditions
from app.services.filters import HuntFilter, ItemSource

# Colunas carregadas na listagem de Hunts (evita trazer o raw_json de cada linha).
SUMMARY_COLUMNS = (
    HuntSession.id,
    HuntSession.session_id,
    HuntSession.player,
    HuntSession.start_datetime,
    HuntSession.duration_seconds,
    HuntSession.status,
    HuntSession.kills,
    HuntSession.kills_per_hour,
    HuntSession.profit,
    HuntSession.profit_per_hour,
    HuntSession.supplies,
    HuntSession.supplies_per_hour,
    HuntSession.raw_gains,
    HuntSession.raw_gains_per_hour,
    HuntSession.damage_dealt,
    HuntSession.damage_dealt_per_second,
    HuntSession.damage_taken,
    HuntSession.damage_taken_per_second,
    HuntSession.experience,
    HuntSession.experience_per_hour,
    HuntSession.source_file,
    HuntSession.category,
)

# (chave, coluna do total, coluna da taxa) usadas no relatório de métricas.
METRIC_AGGREGATES = (
    ("kills", HuntSession.kills, HuntSession.kills_per_hour),
    ("profit", HuntSession.profit, HuntSession.profit_per_hour),
    ("supplies", HuntSession.supplies, HuntSession.supplies_per_hour),
    ("raw_gains", HuntSession.raw_gains, HuntSession.raw_gains_per_hour),
    ("experience", HuntSession.experience, HuntSession.experience_per_hour),
    ("damage_dealt", HuntSession.damage_dealt, HuntSession.damage_dealt_per_second),
    ("damage_taken", HuntSession.damage_taken, HuntSession.damage_taken_per_second),
    ("duration", HuntSession.duration_seconds, None),
)

ENTRY_MODELS = {
    "enemies": (EnemyDefeated, EnemyDefeated.enemy),
    ItemSource.DROPS.value: (Drop, Drop.item),
    ItemSource.SUPPLIES.value: (Supply, Supply.item),
}


def _equals_or_null(column: Any, value: Any) -> ColumnElement[bool]:
    return column.is_(None) if value is None else column == value


def _sum_or_zero(column: Any) -> ColumnElement[Any]:
    return func.coalesce(func.sum(column), 0)


class HuntRepository:
    """Operações de persistência de ``HuntSession`` e dados relacionados.

    Os métodos de consulta aceitam um ``HuntFilter`` opcional; sem filtro,
    consideram todas as Hunts.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, hunt: HuntSession) -> HuntSession:
        self.session.add(hunt)
        self.session.flush()  # garante o id gerado
        return hunt

    def get_with_details(self, hunt_id: int) -> HuntSession | None:
        """Carrega a Hunt com inimigos, drops e supplies (para uso fora da sessão)."""
        stmt = (
            select(HuntSession)
            .where(HuntSession.id == hunt_id)
            .options(
                selectinload(HuntSession.enemies),
                selectinload(HuntSession.drops),
                selectinload(HuntSession.supplies_used),
            )
        )
        return self.session.scalars(stmt).one_or_none()

    def list_summaries(self, hunt_filter: HuntFilter | None = None) -> Sequence[Any]:
        """Linhas leves para a tabela de Hunts, mais recentes primeiro."""
        stmt = (
            select(*SUMMARY_COLUMNS)
            .where(*hunt_filter_conditions(hunt_filter))
            .order_by(HuntSession.start_datetime.desc(), HuntSession.id.desc())
        )
        return self.session.execute(stmt).mappings().all()

    def count(self, hunt_filter: HuntFilter | None = None) -> int:
        stmt = select(func.count(HuntSession.id)).where(*hunt_filter_conditions(hunt_filter))
        return self.session.scalar(stmt) or 0

    def find_duplicate_ids(
        self,
        session_id: int | None,
        player: str | None,
        start_datetime: datetime | None,
        content_hash: str,
    ) -> list[int]:
        """Hunts já importadas que representam a mesma sessão.

        Considera duplicada quando o conteúdo é idêntico OU quando a combinação
        ``session_id + player + start`` coincide. O ``Session ID`` sozinho não é
        usado, pois não há garantia de que seja único entre players/servidores.
        """
        conditions = [HuntSession.content_hash == content_hash]
        if session_id is not None and start_datetime is not None:
            conditions.append(
                (HuntSession.session_id == session_id)
                & _equals_or_null(HuntSession.player, player)
                & (HuntSession.start_datetime == start_datetime)
            )
        stmt = select(HuntSession.id).where(or_(*conditions)).order_by(HuntSession.id)
        return list(self.session.scalars(stmt))

    def set_category(self, hunt_ids: Iterable[int], category: str) -> int:
        ids = list(hunt_ids)
        if not ids:
            return 0
        result = self.session.execute(
            update(HuntSession).where(HuntSession.id.in_(ids)).values(category=category))
        return result.rowcount or 0

    def enemy_categories(self, names: Iterable[str]) -> dict[str, set[str]]:
        """``{nome em minúsculas: categorias das sessões em que o inimigo apareceu}``."""
        keys = {name.strip().lower() for name in names}
        if not keys:
            return {}
        enemy = func.lower(EnemyDefeated.enemy)
        stmt = (
            select(enemy, HuntSession.category)
            .join(HuntSession, HuntSession.id == EnemyDefeated.hunt_id)
            .where(enemy.in_(keys))
            .distinct()
        )
        found: dict[str, set[str]] = {}
        for name, category in self.session.execute(stmt):
            found.setdefault(name, set()).add(category)
        return found

    def raw_documents(self, hunt_filter: HuntFilter | None = None) -> list[str]:
        """JSON original das Hunts filtradas (para seções que não têm tabela própria)."""
        stmt = select(HuntSession.raw_json).where(*hunt_filter_conditions(hunt_filter))
        return list(self.session.scalars(stmt))

    def delete_many(self, hunt_ids: Iterable[int]) -> int:
        ids = list(hunt_ids)
        if not ids:
            return 0
        result = self.session.execute(delete(HuntSession).where(HuntSession.id.in_(ids)))
        return result.rowcount or 0

    # ------------------------------------------------------------ agregações

    def aggregate_overview(self, hunt_filter: HuntFilter | None = None) -> dict[str, Any]:
        """Totais e médias calculados diretamente no SQLite."""
        total = _sum_or_zero
        stmt = select(
            func.count(HuntSession.id).label("hunt_count"),
            total(HuntSession.duration_seconds).label("total_duration_seconds"),
            total(HuntSession.kills).label("total_kills"),
            total(HuntSession.profit).label("total_profit"),
            total(HuntSession.supplies).label("total_supplies"),
            total(HuntSession.raw_gains).label("total_raw_gains"),
            total(HuntSession.experience).label("total_experience"),
            total(HuntSession.damage_dealt).label("total_damage_dealt"),
            total(HuntSession.damage_taken).label("total_damage_taken"),
            func.avg(HuntSession.profit).label("average_profit"),
            func.avg(HuntSession.profit_per_hour).label("average_profit_per_hour"),
            func.avg(HuntSession.kills_per_hour).label("average_kills_per_hour"),
            func.avg(HuntSession.supplies_per_hour).label("average_supplies_per_hour"),
            func.avg(HuntSession.damage_dealt_per_second).label(
                "average_damage_dealt_per_second"
            ),
            func.min(HuntSession.start_datetime).label("first_start"),
            func.max(HuntSession.start_datetime).label("last_start"),
        ).where(*hunt_filter_conditions(hunt_filter))
        return dict(self.session.execute(stmt).mappings().one())

    def aggregate_metrics(self, hunt_filter: HuntFilter | None = None) -> dict[str, Any]:
        """Para cada métrica: ``<m>_sum``, ``_avg``, ``_min``, ``_max``, ``_count``, ``_rate_avg``."""
        columns = [func.count(HuntSession.id).label("hunt_count")]
        for key, total, rate in METRIC_AGGREGATES:
            columns += [
                func.sum(total).label(f"{key}_sum"),
                func.avg(total).label(f"{key}_avg"),
                func.min(total).label(f"{key}_min"),
                func.max(total).label(f"{key}_max"),
                func.count(total).label(f"{key}_count"),
            ]
            if rate is not None:
                columns.append(func.avg(rate).label(f"{key}_rate_avg"))
        stmt = select(*columns).where(*hunt_filter_conditions(hunt_filter))
        return dict(self.session.execute(stmt).mappings().one())

    def top_entries(self, kind: str, hunt_filter: HuntFilter | None = None,
                    limit: int = 20) -> Sequence[Any]:
        """Itens (``drops``/``supplies``) ou inimigos (``enemies``) somados nas Hunts filtradas.

        Colunas: ``name``, ``quantity``, ``value`` (None para inimigos), ``hunt_count``.
        """
        model, name_column = ENTRY_MODELS[kind]
        value = (func.sum(model.total_price) if hasattr(model, "total_price")
                 else null())
        stmt = (
            select(
                name_column.label("name"),
                func.sum(model.count).label("quantity"),
                value.label("value"),
                func.count(model.hunt_id.distinct()).label("hunt_count"),
            )
            .where(model.hunt_id.in_(filtered_hunt_ids(hunt_filter)))
            .group_by(name_column)
            .order_by((value if kind != "enemies" else func.sum(model.count)).desc())
            .limit(limit)
        )
        return self.session.execute(stmt).mappings().all()

    def entity_per_hunt(self, kind: str, name: str,
                        hunt_filter: HuntFilter | None = None) -> Sequence[Any]:
        """Quantidade (e valor) de um item/inimigo em cada Hunt filtrada, em ordem cronológica.

        Hunts em que o nome não aparece vêm com ``quantity = 0`` e ``value = None``.
        """
        model, name_column = ENTRY_MODELS[kind]
        value = func.sum(model.total_price) if hasattr(model, "total_price") else null()
        per_hunt = (
            select(model.hunt_id.label("hunt_id"),
                   func.sum(model.count).label("quantity"),
                   value.label("value"))
            .where(func.lower(name_column) == name.strip().lower())
            .group_by(model.hunt_id)
            .subquery()
        )
        stmt = (
            select(
                HuntSession.id.label("hunt_id"),
                HuntSession.session_id,
                HuntSession.start_datetime,
                HuntSession.duration_seconds,
                func.coalesce(per_hunt.c.quantity, 0).label("quantity"),
                per_hunt.c.value.label("value"),
            )
            .outerjoin(per_hunt, per_hunt.c.hunt_id == HuntSession.id)
            .where(*hunt_filter_conditions(hunt_filter))
            .order_by(HuntSession.start_datetime.is_(None), HuntSession.start_datetime,
                      HuntSession.id)
        )
        return self.session.execute(stmt).mappings().all()

    def list_summaries_by_ids(self, hunt_ids: Iterable[int]) -> Sequence[Any]:
        """Resumo das Hunts informadas, em ordem cronológica (usado na comparação)."""
        stmt = (
            select(*SUMMARY_COLUMNS)
            .where(HuntSession.id.in_(list(hunt_ids)))
            .order_by(HuntSession.start_datetime.is_(None), HuntSession.start_datetime,
                      HuntSession.id)
        )
        return self.session.execute(stmt).mappings().all()

    # ------------------------------------------------------ opções de filtro

    def distinct_players(self) -> list[str]:
        stmt = (select(HuntSession.player).where(HuntSession.player.is_not(None))
                .distinct().order_by(HuntSession.player))
        return list(self.session.scalars(stmt))

    def distinct_names(self, kind: str) -> list[str]:
        """Nomes distintos de inimigos (``enemies``) ou itens (``drops``/``supplies``)."""
        _model, name_column = ENTRY_MODELS[kind]
        stmt = select(name_column).distinct().order_by(func.lower(name_column))
        return list(self.session.scalars(stmt))


class PriceRepository:
    """Tabela de preços personalizados e os drops/supplies afetados por ela."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def all(self) -> list[ItemPrice]:
        return list(self.session.scalars(select(ItemPrice).order_by(ItemPrice.key)))

    def get(self, key: str) -> ItemPrice | None:
        return self.session.scalars(select(ItemPrice).where(ItemPrice.key == key)).one_or_none()

    def price_map(self) -> dict[str, float]:
        """``{nome em minúsculas: preço}``."""
        rows = self.session.execute(select(ItemPrice.key, ItemPrice.unit_price))
        return {key: price for key, price in rows}

    def entries_for(self, key: str) -> list[Drop | Supply]:
        """Drops e supplies com o nome informado (em minúsculas), com a Hunt carregada."""
        entries: list[Drop | Supply] = []
        for model in (Drop, Supply):
            stmt = (select(model).where(func.lower(model.item) == key)
                    .options(selectinload(model.hunt)))
            entries.extend(self.session.scalars(stmt))
        return entries

    def item_usage(self, model: type[Drop] | type[Supply]) -> Sequence[Any]:
        """Uma linha por entrada: ``item``, ``count``, ``hunt_id``, ``original_unit_price``.

        Ordenadas da Hunt mais antiga para a mais recente.
        """
        stmt = (
            select(model.item, model.count, model.hunt_id, model.original_unit_price)
            .join(HuntSession, HuntSession.id == model.hunt_id)
            .order_by(HuntSession.start_datetime.is_(None), HuntSession.start_datetime,
                      HuntSession.id)
        )
        return self.session.execute(stmt).mappings().all()
