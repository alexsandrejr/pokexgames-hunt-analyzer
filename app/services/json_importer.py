"""Leitura, validação e extração dos JSONs gerados pelo Analyzer do PokeXGames.

O TSV do Analyzer também é aceito: ``parse_analyzer_text`` detecta o formato e
converte o TSV no JSON equivalente (ver ``tsv_importer``) antes de extrair.

Este módulo não conhece o banco de dados: ele transforma o texto JSON em um
``ParsedHunt`` (dataclasses simples). A persistência fica a cargo do
``HuntService``. Isso permite reutilizar o parser para importação de arquivo
único, múltiplos arquivos, pastas ou drag and drop.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.tsv_importer import TsvFormatError, looks_like_tsv, tsv_to_document
from app.utils.constants import SECONDS_PER_HOUR, AnalyzerKeys, EntryKeys
from app.utils.validators import (
    parse_datetime,
    parse_duration,
    to_bool,
    to_float,
    to_int,
    to_str,
)


class AnalyzerImportError(Exception):
    """Erro de importação com mensagem pronta para exibir ao usuário."""

    default_message = "Não foi possível importar o arquivo."

    def __init__(self, message: str | None = None, detail: str | None = None) -> None:
        self.message = message or self.default_message
        self.detail = detail
        super().__init__(self.message)


class FileReadError(AnalyzerImportError):
    default_message = "Não foi possível ler o arquivo."


class InvalidJsonError(AnalyzerImportError):
    default_message = "JSON inválido."


class InvalidTsvError(AnalyzerImportError):
    default_message = "TSV inválido."


class InvalidAnalyzerSessionError(AnalyzerImportError):
    default_message = "O arquivo não possui uma sessão válida do Analyzer."


@dataclass
class ParsedSession:
    """Campos da seção ``Session``. Nomes iguais às colunas de ``HuntSession``."""

    session_id: int | None = None
    player: str | None = None
    start_datetime: datetime | None = None
    duration_seconds: int | None = None
    paused_seconds: int | None = None
    status: str | None = None
    session_type: str | None = None
    kills: int | None = None
    kills_per_hour: float | None = None
    rare_kills: int | None = None
    rare_kills_per_hour: float | None = None
    experience: int | None = None
    experience_per_hour: float | None = None
    profit: int | None = None
    profit_per_hour: float | None = None
    supplies: int | None = None
    supplies_per_hour: float | None = None
    raw_gains: int | None = None
    raw_gains_per_hour: float | None = None
    damage_dealt: int | None = None
    damage_dealt_per_second: float | None = None
    damage_taken: int | None = None
    damage_taken_per_second: float | None = None
    time_to_next_level: str | None = None
    time_to_next_level_seconds: int | None = None


@dataclass(frozen=True)
class ParsedEnemy:
    enemy: str
    count: int
    player: str | None
    rare: bool | None
    ignored: bool | None


@dataclass(frozen=True)
class ParsedItem:
    """Entrada de ``Drops`` ou ``Supplies``."""

    item: str
    count: int
    unit_price: float | None
    total_price: int | None
    player: str | None
    ignored: bool | None


@dataclass
class ParsedHunt:
    session: ParsedSession
    enemies: list[ParsedEnemy]
    drops: list[ParsedItem]
    supplies: list[ParsedItem]
    raw_json: str
    content_hash: str
    source_file: str | None = None
    warnings: list[str] = field(default_factory=list)


# (atributo em ParsedSession, chave no JSON, conversor). Para suportar um novo
# campo do Analyzer basta acrescentar uma linha aqui e a coluna no modelo.
SESSION_FIELDS: tuple[tuple[str, str, Callable[[Any], Any]], ...] = (
    ("session_id", "Session ID", to_int),
    ("player", "Player", to_str),
    ("start_datetime", "Start", parse_datetime),
    ("duration_seconds", "Duration seconds", to_int),
    ("paused_seconds", "Paused seconds", to_int),
    ("status", "Status", to_str),
    ("session_type", "Session type", to_str),
    ("kills", "Kills", to_int),
    ("kills_per_hour", "Kills per hour", to_float),
    ("rare_kills", "Rare kills", to_int),
    ("rare_kills_per_hour", "Rare kills per hour", to_float),
    ("experience", "Experience", to_int),
    ("experience_per_hour", "Experience per hour", to_float),
    ("profit", "Profit", to_int),
    ("profit_per_hour", "Profit per hour", to_float),
    ("supplies", "Supplies", to_int),
    ("supplies_per_hour", "Supplies per hour", to_float),
    ("raw_gains", "Raw gains", to_int),
    ("raw_gains_per_hour", "Raw gains per hour", to_float),
    ("damage_dealt", "Damage dealt", to_int),
    ("damage_dealt_per_second", "Damage dealt per second", to_float),
    ("damage_taken", "Damage taken", to_int),
    ("damage_taken_per_second", "Damage taken per second", to_float),
    ("time_to_next_level", "Time to next level", to_str),
    ("time_to_next_level_seconds", "Time to next level seconds", to_int),
)

# Pelo menos uma destas chaves precisa existir para considerar a sessão válida.
REQUIRED_SESSION_KEYS = ("Session ID", "Start", "Duration seconds", "Duration")

# (taxa, total, segundos da unidade): taxas ausentes são derivadas do total.
DERIVED_RATES: tuple[tuple[str, str, int], ...] = (
    ("kills_per_hour", "kills", SECONDS_PER_HOUR),
    ("rare_kills_per_hour", "rare_kills", SECONDS_PER_HOUR),
    ("experience_per_hour", "experience", SECONDS_PER_HOUR),
    ("profit_per_hour", "profit", SECONDS_PER_HOUR),
    ("supplies_per_hour", "supplies", SECONDS_PER_HOUR),
    ("raw_gains_per_hour", "raw_gains", SECONDS_PER_HOUR),
    ("damage_dealt_per_second", "damage_dealt", 1),
    ("damage_taken_per_second", "damage_taken", 1),
)


def read_analyzer_file(path: str | Path) -> str:
    """Lê o arquivo como texto UTF-8 (tolerando BOM)."""
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidJsonError(detail=f"Codificação inválida: {exc}") from exc
    except OSError as exc:
        raise FileReadError(detail=str(exc)) from exc


def load_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise InvalidJsonError(detail=str(exc)) from exc


def compute_content_hash(data: Any) -> str:
    """Hash do JSON canônico (ignora espaços e ordem das chaves)."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_analyzer_document(data: Any) -> dict[str, Any]:
    """Garante que o documento tem uma seção ``Session`` utilizável."""
    if not isinstance(data, dict):
        raise InvalidAnalyzerSessionError(detail="A raiz do JSON não é um objeto.")
    session = data.get(AnalyzerKeys.SESSION)
    if not isinstance(session, dict) or not session:
        raise InvalidAnalyzerSessionError(detail="Seção 'Session' ausente ou vazia.")
    if not any(session.get(key) is not None for key in REQUIRED_SESSION_KEYS):
        raise InvalidAnalyzerSessionError(
            detail="A seção 'Session' não contém identificação, início ou duração."
        )
    return session


def parse_analyzer_text(text: str, source_file: str | None = None) -> ParsedHunt:
    """Valida e extrai uma Hunt do texto do Analyzer, em JSON ou TSV.

    O TSV é convertido e guardado como JSON (``raw_json``), com todas as seções.
    """
    if not looks_like_tsv(text):
        return parse_analyzer_json(text, source_file)
    try:
        data = tsv_to_document(text)
    except TsvFormatError as exc:
        raise InvalidTsvError(detail=str(exc)) from exc
    raw_json = json.dumps(data, ensure_ascii=False, indent=2)
    return _parse_document(data, raw_json, source_file)


def parse_analyzer_json(text: str, source_file: str | None = None) -> ParsedHunt:
    """Valida e extrai uma Hunt a partir do texto JSON do Analyzer."""
    return _parse_document(load_json(text), text, source_file)


def _parse_document(data: Any, raw_json: str, source_file: str | None) -> ParsedHunt:
    session_data = validate_analyzer_document(data)
    warnings: list[str] = []

    session = _parse_session(session_data)
    enemies = _parse_entries(data, AnalyzerKeys.ENEMIES, _parse_enemy, warnings)
    drops = _parse_entries(data, AnalyzerKeys.DROPS, _parse_item, warnings)
    supplies = _parse_entries(data, AnalyzerKeys.SUPPLIES, _parse_item, warnings)

    if session.player is None:
        session.player = _infer_player([*enemies, *drops, *supplies])

    return ParsedHunt(
        session=session,
        enemies=enemies,
        drops=drops,
        supplies=supplies,
        raw_json=raw_json,
        content_hash=compute_content_hash(data),
        source_file=source_file,
        warnings=warnings,
    )


def _parse_session(data: dict[str, Any]) -> ParsedSession:
    session = ParsedSession(
        **{attr: convert(data.get(key)) for attr, key, convert in SESSION_FIELDS}
    )
    if session.duration_seconds is None:
        session.duration_seconds = parse_duration(data.get("Duration"))

    duration = session.duration_seconds
    if duration and duration > 0:
        for rate_attr, total_attr, unit_seconds in DERIVED_RATES:
            total = getattr(session, total_attr)
            if getattr(session, rate_attr) is None and total is not None:
                setattr(session, rate_attr, total * unit_seconds / duration)
    return session


def _parse_entries(
    data: dict[str, Any],
    key: str,
    parse_entry: Callable[[dict[str, Any]], Any],
    warnings: list[str],
) -> list[Any]:
    raw_entries = data.get(key)
    if raw_entries is None:
        return []
    if not isinstance(raw_entries, list):
        warnings.append(f"'{key}' não é uma lista e foi ignorado.")
        return []

    entries = []
    skipped = 0
    for raw in raw_entries:
        entry = parse_entry(raw) if isinstance(raw, dict) else None
        if entry is None:
            skipped += 1
        else:
            entries.append(entry)
    if skipped:
        warnings.append(f"{skipped} registro(s) inválido(s) em '{key}' foram ignorados.")
    return entries


def _parse_enemy(raw: dict[str, Any]) -> ParsedEnemy | None:
    name = to_str(raw.get(EntryKeys.ENEMY))
    if name is None:
        return None
    return ParsedEnemy(
        enemy=name,
        count=to_int(raw.get(EntryKeys.COUNT), default=0),
        player=to_str(raw.get(EntryKeys.PLAYER)),
        rare=to_bool(raw.get(EntryKeys.RARE)),
        ignored=to_bool(raw.get(EntryKeys.IGNORED)),
    )


def _parse_item(raw: dict[str, Any]) -> ParsedItem | None:
    name = to_str(raw.get(EntryKeys.ITEM))
    if name is None:
        return None
    count = to_int(raw.get(EntryKeys.COUNT), default=0)
    unit_price = to_float(raw.get(EntryKeys.UNIT_PRICE))
    total_price = to_int(raw.get(EntryKeys.TOTAL_PRICE))
    if total_price is None and unit_price is not None:
        total_price = int(round(unit_price * count))
    return ParsedItem(
        item=name,
        count=count,
        unit_price=unit_price,
        total_price=total_price,
        player=to_str(raw.get(EntryKeys.PLAYER)),
        ignored=to_bool(raw.get(EntryKeys.IGNORED)),
    )


def _infer_player(entries: list[ParsedEnemy | ParsedItem]) -> str | None:
    """A seção Session não traz o player; ele é obtido das listas.

    Em sessões com mais de um player, os nomes são unidos em ordem de aparição.
    """
    players = dict.fromkeys(entry.player for entry in entries if entry.player)
    return ", ".join(players) if players else None
