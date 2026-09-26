"""Pesquisa avançada em texto: ``nightmare ore > 50 e nightmare gem > 1000; kills/h >= 300``.

Sintaxe
-------
* Condições separadas por ``e``, ``and``, ``;`` ou ``&``; todas combinadas com E.
* Cada condição: ``[prefixo:] nome [operador valor]``.
* Operadores: ``>``, ``>=``, ``=``, ``<=``, ``<`` (também ``≥`` e ``≤``).
* Métricas (exigem operador): ``profit``, ``profit/h``, ``kills``, ``kills/h``,
  ``duração``, ``supplies``, ``supplies/h``, ``raw gains``, ``raw gains/h``.
* Sem prefixo, o nome é procurado nos drops, depois nos inimigos e nos supplies
  conhecidos. Prefixos forçam o tipo: ``drop:``, ``supply:``, ``inimigo:``.
* Sem operador, basta o item/inimigo aparecer na Hunt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.dto import FilterOptions
from app.services.filters import (
    EnemyCondition,
    HuntFilter,
    ItemCondition,
    ItemSource,
    Metric,
    MetricCondition,
    Operator,
)
from app.utils.validators import parse_user_duration, parse_user_number

_SEPARATORS = re.compile(r"\s+(?:e|and)\s+|;|&&?", re.IGNORECASE)
_CONDITION = re.compile(
    r"^(?:(?P<prefix>[^\W\d_]+)\s*:\s*)?(?P<name>.+?)"
    r"(?:\s*(?P<op>>=|<=|≥|≤|=|>|<)\s*(?P<value>.*))?$"
)
_OPERATOR_SYMBOLS = {">": Operator.GT, ">=": Operator.GE, "≥": Operator.GE, "=": Operator.EQ,
                     "<=": Operator.LE, "≤": Operator.LE, "<": Operator.LT}

METRIC_ALIASES: dict[str, Metric] = {
    "profit": Metric.PROFIT, "lucro": Metric.PROFIT,
    "profit/h": Metric.PROFIT_PER_HOUR, "lucro/h": Metric.PROFIT_PER_HOUR,
    "kills": Metric.KILLS, "kills/h": Metric.KILLS_PER_HOUR, "k/h": Metric.KILLS_PER_HOUR,
    "duração": Metric.DURATION, "duracao": Metric.DURATION, "duration": Metric.DURATION,
    "tempo": Metric.DURATION,
    "supplies": Metric.SUPPLIES, "supplies/h": Metric.SUPPLIES_PER_HOUR,
    "raw gains": Metric.RAW_GAINS, "raw gains/h": Metric.RAW_GAINS_PER_HOUR,
}

_PREFIXES: dict[str, str] = {
    "drop": "drop", "drops": "drop", "item": "drop",
    "supply": "supply",
    "inimigo": "enemy", "enemy": "enemy", "pokemon": "enemy", "pokémon": "enemy",
}


@dataclass
class AdvancedQuery:
    enemies: list[EnemyCondition] = field(default_factory=list)
    items: list[ItemCondition] = field(default_factory=list)
    metrics: list[MetricCondition] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def merged_into(self, hunt_filter: HuntFilter) -> HuntFilter:
        """Soma estas condições às do filtro (tudo continua combinado com E)."""
        return HuntFilter(
            date_from=hunt_filter.date_from,
            date_to=hunt_filter.date_to,
            player=hunt_filter.player,
            enemies=(*hunt_filter.enemies, *self.enemies),
            items=(*hunt_filter.items, *self.items),
            metrics=(*hunt_filter.metrics, *self.metrics),
        )


def parse_advanced_query(text: str, options: FilterOptions) -> AdvancedQuery:
    query = AdvancedQuery()
    for part in _SEPARATORS.split(text or ""):
        part = part.strip()
        if part:
            _parse_condition(part, options, query)
    return query


def _parse_condition(text: str, options: FilterOptions, query: AdvancedQuery) -> None:
    match = _CONDITION.match(text)
    prefix_raw = (match.group("prefix") or "").lower() if match else ""
    if not match or (prefix_raw and prefix_raw not in _PREFIXES):
        # Um "prefixo" desconhecido provavelmente faz parte do nome.
        match = _CONDITION.match(text.replace(":", " ", 1)) if match else None
        prefix_raw = ""
    if not match:
        query.errors.append(f"Não entendi “{text}”.")
        return

    name = " ".join(match.group("name").split())
    symbol = match.group("op")
    value_text = (match.group("value") or "").strip()
    operator = _OPERATOR_SYMBOLS.get(symbol) if symbol else None
    if symbol and not value_text:
        query.errors.append(f"Falta o valor em “{text}”.")
        return

    metric = None if prefix_raw else METRIC_ALIASES.get(name.lower())
    if metric is not None:
        _add_metric(metric, operator, value_text, text, query)
        return

    quantity = None
    if operator is not None:
        quantity = parse_user_number(value_text)
        if quantity is None:
            query.errors.append(f"Quantidade inválida em “{text}”.")
            return

    kind, canonical = _resolve_name(name, _PREFIXES.get(prefix_raw), options)
    if kind is None:
        query.errors.append(
            f"“{name}” não foi encontrado nos drops, inimigos ou supplies importados. "
            "Use drop:, supply: ou inimigo: para forçar o tipo.")
        return
    if kind == "enemy":
        query.enemies.append(EnemyCondition(canonical, operator, quantity))
    else:
        source = ItemSource.SUPPLIES if kind == "supply" else ItemSource.DROPS
        query.items.append(ItemCondition(canonical, operator, quantity, source=source))


def _add_metric(metric: Metric, operator: Operator | None, value_text: str, text: str,
                query: AdvancedQuery) -> None:
    if operator is None:
        query.errors.append(f"Informe operador e valor para {metric.label} (ex.: "
                            f"{metric.label.lower()} > 100).")
        return
    value = (parse_user_duration(value_text) if metric.is_duration
             else parse_user_number(value_text))
    if value is None:
        query.errors.append(f"Valor inválido em “{text}”.")
        return
    query.metrics.append(MetricCondition(metric, operator, value))


def _resolve_name(name: str, forced: str | None,
                  options: FilterOptions) -> tuple[str | None, str]:
    """Descobre se o nome é drop, inimigo ou supply (nessa ordem de preferência)."""
    lists = {"drop": options.drop_items, "enemy": options.enemies,
             "supply": options.supply_items}
    lowered = name.lower()
    for kind in ([forced] if forced else ["drop", "enemy", "supply"]):
        for known in lists[kind]:
            if known.lower() == lowered:
                return kind, known
    if forced:  # tipo explícito: aceita mesmo sem registros (resultado pode ser vazio)
        return forced, name
    return None, name
