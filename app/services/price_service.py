"""Tabela global de preços personalizados dos itens.

Um preço personalizado substitui o preço unitário do Analyzer em todos os drops e
supplies com aquele nome (sem diferenciar maiúsculas), tanto nas Hunts já
importadas quanto nas futuras. O preço do Analyzer fica guardado em
``original_unit_price``/``original_total_price`` e volta a valer quando o preço
personalizado é removido.

Os totais de cada Hunt são ajustados pela diferença no valor do item:

* drop: ``Raw gains`` e ``Profit`` sobem ou descem junto;
* supply: ``Supplies`` acompanha e ``Profit`` vai no sentido contrário.

As taxas por hora são ajustadas na mesma proporção. Entradas marcadas como
ignoradas pelo Analyzer mudam de preço, mas não alteram os totais da Hunt.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from app.database.database import Database
from app.database.models import Drop, HuntSession, ItemPrice, Supply
from app.database.repositories import PriceRepository
from app.services.rates import rate_per_hour

ItemEntry = Drop | Supply


@dataclass(frozen=True)
class PricedItem:
    """Linha da tela de preços: um item e onde ele aparece."""

    name: str
    in_drops: bool
    in_supplies: bool
    analyzer_price: float | None  # preço do Analyzer na Hunt mais recente
    custom_price: float | None
    quantity: int
    hunt_count: int

    @property
    def sources(self) -> str:
        if self.in_drops and self.in_supplies:
            return "Drop e Supply"
        if self.in_drops:
            return "Drop"
        return "Supply" if self.in_supplies else "—"

    @property
    def has_custom_price(self) -> bool:
        return self.custom_price is not None


def item_key(name: str) -> str:
    return name.strip().lower()


def validate_price(unit_price: float) -> float:
    if not math.isfinite(unit_price) or unit_price < 0:
        raise ValueError("O preço precisa ser um número maior ou igual a zero.")
    return float(unit_price)


def reprice_entry(entry: ItemEntry, unit_price: float | None) -> None:
    """Aplica o preço à entrada (``None`` = preço do Analyzer) e ajusta a Hunt."""
    old_total = entry.total_price
    if unit_price is None:
        entry.unit_price = entry.original_unit_price
        entry.total_price = entry.original_total_price
    else:
        entry.unit_price = unit_price
        entry.total_price = int(round(unit_price * entry.count))
    delta = (entry.total_price or 0) - (old_total or 0)
    if not delta or entry.ignored:
        return
    hunt = entry.hunt
    if isinstance(entry, Drop):
        _shift(hunt, "raw_gains", "raw_gains_per_hour", delta)
        _shift(hunt, "profit", "profit_per_hour", delta)
    else:
        _shift(hunt, "supplies", "supplies_per_hour", delta)
        _shift(hunt, "profit", "profit_per_hour", -delta)


def _shift(hunt: HuntSession, total_attr: str, rate_attr: str, change: int) -> None:
    """Soma ``change`` ao total e a taxa equivalente à taxa por hora (se existirem)."""
    total = getattr(hunt, total_attr)
    if total is None:
        return
    setattr(hunt, total_attr, total + change)
    rate = getattr(hunt, rate_attr)
    rate_change = rate_per_hour(change, hunt.duration_seconds)
    if rate is not None and rate_change is not None:
        setattr(hunt, rate_attr, rate + rate_change)


def apply_custom_prices(hunt: HuntSession, prices: Mapping[str, float]) -> None:
    """Aplica a tabela de preços a uma Hunt recém-importada."""
    if not prices:
        return
    for entry in [*hunt.drops, *hunt.supplies_used]:
        price = prices.get(item_key(entry.item))
        if price is not None:
            reprice_entry(entry, price)


class PriceService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_items(self) -> list[PricedItem]:
        """Todos os itens já vistos em drops/supplies, mais os que só têm preço definido."""
        with self.database.session() as session:
            repository = PriceRepository(session)
            custom = {price.key: price for price in repository.all()}
            usage = {Drop: repository.item_usage(Drop), Supply: repository.item_usage(Supply)}

        names: dict[str, str] = {}
        in_drops: set[str] = set()
        in_supplies: set[str] = set()
        analyzer_price: dict[str, float | None] = {}
        quantity: dict[str, int] = {}
        hunts: dict[str, set[int]] = {}
        for model, rows in usage.items():
            for row in rows:
                key = item_key(row["item"])
                names.setdefault(key, row["item"])
                (in_drops if model is Drop else in_supplies).add(key)
                if row["original_unit_price"] is not None or key not in analyzer_price:
                    analyzer_price[key] = row["original_unit_price"]  # a mais recente vence
                quantity[key] = quantity.get(key, 0) + row["count"]
                hunts.setdefault(key, set()).add(row["hunt_id"])
        for key, price in custom.items():
            names.setdefault(key, price.item)

        return sorted(
            (PricedItem(
                name=name,
                in_drops=key in in_drops,
                in_supplies=key in in_supplies,
                analyzer_price=analyzer_price.get(key),
                custom_price=custom[key].unit_price if key in custom else None,
                quantity=quantity.get(key, 0),
                hunt_count=len(hunts.get(key, ())),
            ) for key, name in names.items()),
            key=lambda item: item.name.casefold(),
        )

    def custom_prices(self) -> dict[str, float]:
        with self.database.session() as session:
            return PriceRepository(session).price_map()

    def set_price(self, name: str, unit_price: float) -> int:
        """Define o preço do item e recalcula as Hunts. Retorna quantas Hunts mudaram."""
        name = name.strip()
        if not name:
            raise ValueError("Informe o nome do item.")
        unit_price = validate_price(unit_price)
        key = item_key(name)
        with self.database.session() as session:
            repository = PriceRepository(session)
            price = repository.get(key)
            if price is None:
                session.add(ItemPrice(key=key, item=name, unit_price=unit_price))
            else:
                price.unit_price = unit_price
            return self._reprice(repository, key, unit_price)

    def clear_price(self, name: str) -> int:
        """Remove o preço personalizado e volta ao preço do Analyzer em todas as Hunts."""
        key = item_key(name)
        with self.database.session() as session:
            repository = PriceRepository(session)
            price = repository.get(key)
            if price is None:
                return 0
            session.delete(price)
            return self._reprice(repository, key, None)

    @staticmethod
    def _reprice(repository: PriceRepository, key: str, unit_price: float | None) -> int:
        entries = repository.entries_for(key)
        for entry in entries:
            reprice_entry(entry, unit_price)
        return len({entry.hunt_id for entry in entries})
