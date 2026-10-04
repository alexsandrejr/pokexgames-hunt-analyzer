"""Regras de negócio de Hunts: importação, consulta e exclusão.

Toda sessão importada recebe uma categoria (Hunt ou um tipo de boss). Como o JSON
do Analyzer não a informa, ela é decidida nesta ordem:

1. a pasta do arquivo (``imports/terrors/x.json`` → Terror, ver ``category_from_folder``);
2. a categoria pedida na importação (a aba de Bosses aberta);
3. os inimigos da sessão, se todos já apareceram só numa mesma categoria de boss;
4. Hunt.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.database.database import Database
from app.database.models import Drop, EnemyDefeated, HuntSession, Supply
from app.database.repositories import HuntRepository, PriceRepository
from app.services.categories import Category, category_dir, category_from_folder
from app.services.dto import FilterOptions, HuntSummary, ImportResult, ImportStatus
from app.services.filters import HuntFilter, ItemSource
from app.services.json_files import suggested_filename, write_new_json_file
from app.services.json_importer import (
    AnalyzerImportError,
    ParsedHunt,
    ParsedItem,
    parse_analyzer_text,
    read_analyzer_file,
)
from app.services.price_service import apply_custom_prices

DUPLICATE_MESSAGE = "Esta Hunt já foi importada."
IMPORTED_MESSAGE = "Hunt importada com sucesso."
PASTED_SOURCE = "Texto colado"


class HuntService:
    def __init__(self, database: Database) -> None:
        self.database = database

    # ------------------------------------------------------------------ import

    def import_file(self, path: str | Path, allow_duplicate: bool = False,
                    category: Category | None = None) -> ImportResult:
        """Importa um JSON ou TSV do Analyzer a partir de um arquivo.

        Nunca lança exceção para erros de conteúdo: o resultado informa o status
        (importada, duplicada ou erro) com a mensagem para o usuário.
        """
        source = str(path)
        try:
            text = read_analyzer_file(path)
        except AnalyzerImportError as exc:
            return _error_result(source, exc)
        return self.import_text(text, source=source, allow_duplicate=allow_duplicate,
                                category=category)

    def import_text(
        self, text: str, source: str = "", allow_duplicate: bool = False,
        category: Category | None = None,
    ) -> ImportResult:
        try:
            parsed = parse_analyzer_text(text, source_file=Path(source).name or None)
        except AnalyzerImportError as exc:
            return _error_result(source, exc)
        return self._store(parsed, source, allow_duplicate,
                           category=category_from_folder(source) or category)

    def import_pasted_text(
        self, text: str, save_dir: Path, allow_duplicate: bool = False,
        category: Category | None = None,
    ) -> ImportResult:
        """Importa um JSON ou TSV colado e o salva como arquivo ``.json``.

        Hunts são salvas em ``save_dir``; bosses, na subpasta da categoria
        (``save_dir/terrors``...). O arquivo só é criado se a sessão for de fato
        gravada no banco: texto inválido ou duplicidade não confirmada não deixam
        arquivos para trás. Um TSV é salvo já convertido para JSON.
        """
        text = text.strip()
        try:
            parsed = parse_analyzer_text(text)
        except AnalyzerImportError as exc:
            return _error_result(PASTED_SOURCE, exc)
        return self._store(parsed, PASTED_SOURCE, allow_duplicate, save_dir=save_dir,
                           category=category)

    def _store(
        self,
        parsed: ParsedHunt,
        source: str,
        allow_duplicate: bool,
        save_dir: Path | None = None,
        category: Category | None = None,
    ) -> ImportResult:
        with self.database.session() as session:
            repository = HuntRepository(session)
            category = category or _known_boss_category(repository, parsed) or Category.HUNT
            duplicates = repository.find_duplicate_ids(
                parsed.session.session_id,
                parsed.session.player,
                parsed.session.start_datetime,
                parsed.content_hash,
            )
            if duplicates and not allow_duplicate:
                return ImportResult(
                    status=ImportStatus.DUPLICATE,
                    source=source,
                    message=DUPLICATE_MESSAGE,
                    duplicate_of=duplicates,
                    warnings=parsed.warnings,
                )
            saved_path = None
            if save_dir is not None:
                saved_path = write_new_json_file(
                    category_dir(save_dir, category), suggested_filename(parsed.session),
                    parsed.raw_json,
                )
                parsed.source_file = saved_path.name
                source = str(saved_path)
            try:
                hunt = _build_model(parsed)
                hunt.category = category.value
                apply_custom_prices(hunt, PriceRepository(session).price_map())
                repository.add(hunt)
                session.commit()
            except Exception:
                if saved_path is not None:
                    saved_path.unlink(missing_ok=True)
                raise
            return ImportResult(
                status=ImportStatus.IMPORTED,
                source=source,
                message=(f"Sessão importada em {category.plural}." if category.is_boss
                         else IMPORTED_MESSAGE),
                hunt_id=hunt.id,
                duplicate_of=duplicates,
                warnings=parsed.warnings,
                saved_path=saved_path,
                category=category,
            )

    # ------------------------------------------------------------------ queries

    def list_hunts(self, hunt_filter: HuntFilter | None = None) -> list[HuntSummary]:
        with self.database.session() as session:
            rows = HuntRepository(session).list_summaries(hunt_filter)
            return [HuntSummary(**row) for row in rows]

    def get_summaries(self, hunt_ids: Iterable[int]) -> list[HuntSummary]:
        """Resumos das Hunts informadas, da mais antiga para a mais recente."""
        with self.database.session() as session:
            rows = HuntRepository(session).list_summaries_by_ids(hunt_ids)
            return [HuntSummary(**row) for row in rows]

    def get_hunt_details(self, hunt_id: int) -> HuntSession | None:
        """Hunt completa (com inimigos, drops, supplies e JSON original).

        O objeto retornado já está totalmente carregado e desanexado da sessão,
        podendo ser lido com segurança pela interface.
        """
        with self.database.session() as session:
            return HuntRepository(session).get_with_details(hunt_id)

    def count_hunts(self, hunt_filter: HuntFilter | None = None) -> int:
        with self.database.session() as session:
            return HuntRepository(session).count(hunt_filter)

    def filter_options(self) -> FilterOptions:
        with self.database.session() as session:
            repository = HuntRepository(session)
            return FilterOptions(
                players=repository.distinct_players(),
                enemies=repository.distinct_names("enemies"),
                drop_items=repository.distinct_names(ItemSource.DROPS.value),
                supply_items=repository.distinct_names(ItemSource.SUPPLIES.value),
            )

    def delete_hunts(self, hunt_ids: Iterable[int]) -> int:
        with self.database.session() as session:
            return HuntRepository(session).delete_many(hunt_ids)

    def set_category(self, hunt_ids: Iterable[int], category: Category) -> int:
        """Move as sessões para outra categoria (ex.: um boss importado como Hunt)."""
        with self.database.session() as session:
            return HuntRepository(session).set_category(hunt_ids, category.value)


def _error_result(source: str, error: AnalyzerImportError) -> ImportResult:
    return ImportResult(
        status=ImportStatus.ERROR, source=source, message=error.message, detail=error.detail
    )


def _known_boss_category(repository: HuntRepository, parsed: ParsedHunt) -> Category | None:
    """Categoria de boss em que todos os inimigos da sessão já apareceram (e só nela).

    Assim, depois que um boss é importado na aba certa uma vez, as próximas
    sessões dele vão para lá sozinhas, mesmo importadas fora da aba.
    """
    names = {enemy.enemy.strip().lower() for enemy in parsed.enemies}
    if not names:
        return None
    seen = repository.enemy_categories(names)
    categories: set[str] = set()
    for name in names:
        found = seen.get(name)
        if not found or Category.HUNT.value in found:
            return None
        categories |= found
    if len(categories) != 1:
        return None
    category = Category.from_value(categories.pop())
    return category if category.is_boss else None


def _build_model(parsed: ParsedHunt) -> HuntSession:
    hunt = HuntSession(
        **asdict(parsed.session),
        raw_json=parsed.raw_json,
        content_hash=parsed.content_hash,
        source_file=parsed.source_file,
    )
    hunt.enemies = [EnemyDefeated(**asdict(enemy)) for enemy in parsed.enemies]
    hunt.drops = [Drop(**_item_fields(item)) for item in parsed.drops]
    hunt.supplies_used = [Supply(**_item_fields(item)) for item in parsed.supplies]
    return hunt


def _item_fields(item: ParsedItem) -> dict[str, Any]:
    """Colunas de Drop/Supply, guardando também o preço original do Analyzer."""
    return {**asdict(item), "original_unit_price": item.unit_price,
            "original_total_price": item.total_price}
