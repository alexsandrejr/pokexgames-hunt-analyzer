"""Seletor de categorias analisadas (Hunts, bosses ou tudo) das páginas de relatório."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QWidget

from app.services.categories import BOSS_CATEGORIES, Category

# (rótulo, categorias); nenhuma categoria = todas.
SCOPES: tuple[tuple[str, tuple[Category, ...]], ...] = (
    ("Hunts", (Category.HUNT,)),
    ("Todos os bosses", BOSS_CATEGORIES),
    *((f"Bosses · {category.plural}", (category,)) for category in BOSS_CATEGORIES),
    ("Hunts e bosses", ()),
)


class CategoryScopeCombo(QComboBox):
    """Começa em "Hunts", para que os bosses não misturem as médias das Hunts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setToolTip("Quais sessões entram nas estatísticas desta página")
        for label, _categories in SCOPES:
            self.addItem(label)

    def categories(self) -> tuple[Category, ...]:
        # A tupla fica em SCOPES: o QComboBox não guarda tuplas de enums como dado do item.
        return SCOPES[max(0, self.currentIndex())][1]

    def set_categories(self, categories: tuple[Category, ...]) -> None:
        self.setCurrentIndex(next(i for i, (_label, c) in enumerate(SCOPES) if c == categories))

    def describe(self) -> str:
        return f"Categoria: {self.currentText()}"
