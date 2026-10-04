"""Categorias de sessão: Hunts comuns e os quatro tipos de boss do PokeXGames.

O JSON do Analyzer é igual para Hunts e bosses, então a categoria não vem no
arquivo: ela é decidida na importação (ver ``HuntService``) e pode ser trocada
depois. O valor do enum é o gravado na coluna ``hunt_sessions.category``.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class Category(Enum):
    HUNT = "hunt"
    RIFT = "rift"
    BOSS_RED = "boss_red"
    BOSS_BLUE = "boss_blue"
    TERROR = "terror"

    @classmethod
    def from_value(cls, value: str | None) -> Category:
        """Categoria gravada no banco; valores desconhecidos contam como Hunt."""
        try:
            return cls(value)
        except ValueError:
            return cls.HUNT

    @property
    def is_boss(self) -> bool:
        return self is not Category.HUNT

    @property
    def label(self) -> str:
        """Nome de uma sessão da categoria ("Terror")."""
        return CATEGORY_LABELS[self][0]

    @property
    def plural(self) -> str:
        """Nome da categoria em abas e listas ("Terrors")."""
        return CATEGORY_LABELS[self][1]

    @property
    def folder(self) -> str | None:
        """Subpasta de ``imports`` onde os JSONs colados são salvos (Hunts: a própria)."""
        return CATEGORY_LABELS[self][2]


# (singular, plural, subpasta dos JSONs colados)
CATEGORY_LABELS: dict[Category, tuple[str, str, str | None]] = {
    Category.HUNT: ("Hunt", "Hunts", None),
    Category.RIFT: ("Rift", "Rifts", "rifts"),
    Category.BOSS_RED: ("Boss de Energia Vermelha", "Energia Vermelha", "energia_vermelha"),
    Category.BOSS_BLUE: ("Boss de Energia Azul", "Energia Azul", "energia_azul"),
    Category.TERROR: ("Terror", "Terrors", "terrors"),
}

BOSS_CATEGORIES: tuple[Category, ...] = tuple(c for c in Category if c.is_boss)


def category_dir(imports_dir: Path, category: Category) -> Path:
    """Pasta dos JSONs colados da categoria."""
    return imports_dir / category.folder if category.folder else imports_dir


def category_from_folder(path: str | Path) -> Category | None:
    """Categoria indicada pela pasta do arquivo (``imports/terrors/x.json`` → Terror)."""
    folder = Path(path).parent.name.lower()
    return next((c for c in BOSS_CATEGORIES if c.folder == folder), None)
