"""Regras de negócio de Hunts: importação, consulta e exclusão."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.database.database import Database
from app.database.models import Drop, EnemyDefeated, HuntSession, Supply
from app.database.repositories import HuntRepository, PriceRepository
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

    def import_file(self, path: str | Path, allow_duplicate: bool = False) -> ImportResult:
        """Importa um JSON ou TSV do Analyzer a partir de um arquivo.

        Nunca lança exceção para erros de conteúdo: o resultado informa o status
        (importada, duplicada ou erro) com a mensagem para o usuário.
        """
        source = str(path)
        try:
            text = read_analyzer_file(path)
        except AnalyzerImportError as exc:
            return _error_result(source, exc)
        return self.import_text(text, source=source, allow_duplicate=allow_duplicate)

    def import_text(
        self, text: str, source: str = "", allow_duplicate: bool = False
    ) -> ImportResult:
        try:
            parsed = parse_analyzer_text(text, source_file=Path(source).name or None)
        except AnalyzerImportError as exc:
            return _error_result(source, exc)
        return self._store(parsed, source, allow_duplicate)

    def import_pasted_text(
        self, text: str, save_dir: Path, allow_duplicate: bool = False
    ) -> ImportResult:
        """Importa um JSON ou TSV colado e o salva como arquivo ``.json`` em ``save_dir``.

        O arquivo só é criado se a Hunt for de fato gravada no banco: texto
        inválido ou duplicidade não confirmada não deixam arquivos para trás.
        Um TSV é salvo já convertido para JSON.
        """
        text = text.strip()
        try:
            parsed = parse_analyzer_text(text)
        except AnalyzerImportError as exc:
            return _error_result(PASTED_SOURCE, exc)
        return self._store(parsed, PASTED_SOURCE, allow_duplicate, save_dir=save_dir)

    def _store(
        self,
        parsed: ParsedHunt,
        source: str,
        allow_duplicate: bool,
        save_dir: Path | None = None,
    ) -> ImportResult:
        with self.database.session() as session:
            repository = HuntRepository(session)
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
                    save_dir, suggested_filename(parsed.session), parsed.raw_json
                )
                parsed.source_file = saved_path.name
                source = str(saved_path)
            try:
                hunt = _build_model(parsed)
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
                message=IMPORTED_MESSAGE,
                hunt_id=hunt.id,
                duplicate_of=duplicates,
                warnings=parsed.warnings,
                saved_path=saved_path,
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


def _error_result(source: str, error: AnalyzerImportError) -> ImportResult:
    return ImportResult(
        status=ImportStatus.ERROR, source=source, message=error.message, detail=error.detail
    )


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
