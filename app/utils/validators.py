"""Conversões seguras de valores vindos do JSON do Analyzer.

Todas as funções toleram ``None``, tipos inesperados e strings malformadas,
retornando ``None`` (ou o ``default`` informado) em vez de lançar exceções.
Isso evita que um único campo estranho quebre a importação inteira.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from app.utils.constants import ANALYZER_DATETIME_FORMATS
from app.utils.formatters import number_format

_TRUE_STRINGS = {"true", "1", "yes", "sim", "y", "s"}
_FALSE_STRINGS = {"false", "0", "no", "nao", "não", "n"}


def to_float(value: Any, default: float | None = None) -> float | None:
    """Converte para ``float`` finito; valores inválidos viram ``default``."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip().replace(" ", "")
        if not text:
            return default
        try:
            number = float(text)
        except ValueError:
            return default
    else:
        return default
    return number if math.isfinite(number) else default


def to_int(value: Any, default: int | None = None) -> int | None:
    """Converte para ``int`` (arredondando decimais); inválidos viram ``default``."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    number = to_float(value)
    return default if number is None else int(round(number))


def to_bool(value: Any, default: bool | None = None) -> bool | None:
    """Converte flags como ``true``/``false``/``1``/``0``; ``null`` vira ``default``."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE_STRINGS:
            return True
        if text in _FALSE_STRINGS:
            return False
    return default


def to_str(value: Any, default: str | None = None) -> str | None:
    """Converte para string sem espaços nas pontas; vazio vira ``default``."""
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip()
        return text or default
    if isinstance(value, (int, float, bool)):
        return str(value)
    return default


def parse_datetime(value: Any) -> datetime | None:
    """Interpreta a data/hora de início da sessão nos formatos conhecidos."""
    text = to_str(value)
    if text is None:
        return None
    for fmt in ANALYZER_DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


_SUFFIX_MULTIPLIERS = (("kkk", 1_000_000_000), ("kk", 1_000_000), ("k", 1_000))
_DURATION_WORDS = re.compile(r"^(?:(\d+)\s*h)?\s*(?:(\d+)\s*(?:min|m)?)?$")


def parse_user_number(text: str | None) -> float | None:
    """Número digitado pelo usuário, no formato ativo e na notação do jogo.

    pt-BR: ``"1.000.000"``, ``"12,5"``; en-US: ``"1,000,000"``, ``"12.5"``. Em ambos:
    ``"800k"``, ``"1,2kk"``, ``"1.5kk"``, ``"2kkk"``. Texto vazio ou inválido → ``None``.
    """
    if text is None:
        return None
    cleaned = text.strip().lower().replace(" ", "")
    if not cleaned:
        return None
    multiplier = 1
    for suffix, factor in _SUFFIX_MULTIPLIERS:
        if cleaned.endswith(suffix):
            cleaned, multiplier = cleaned[: -len(suffix)], factor
            break
    thousands = number_format().thousands
    if re.fullmatch(rf"-?\d{{1,3}}({re.escape(thousands)}\d{{3}})+", cleaned):
        cleaned = cleaned.replace(thousands, "")
    elif cleaned.count(",") == 1 and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    number = to_float(cleaned)
    return None if number is None else number * multiplier


def parse_user_duration(text: str | None) -> int | None:
    """Duração digitada pelo usuário, em segundos.

    ``"1:30"`` (h:mm), ``"1:30:00"``, ``"90"`` (minutos), ``"1h30"``, ``"2h"``, ``"45min"``.
    """
    if text is None:
        return None
    cleaned = text.strip().lower()
    if not cleaned:
        return None
    if ":" in cleaned:
        parts = cleaned.split(":")
        if len(parts) == 2:
            parts.append("0")
        seconds = parse_duration(":".join(parts))
        return seconds
    match = _DURATION_WORDS.match(cleaned)
    if not match or not any(match.groups()):
        return None
    hours, minutes = (int(group) if group else 0 for group in match.groups())
    if hours and minutes >= 60:
        return None
    return hours * 3600 + minutes * 60


def parse_duration(value: Any) -> int | None:
    """Converte ``"HH:MM:SS"`` (ou ``"MM:SS"``) em segundos.

    Horas acima de 24 são aceitas (ex.: ``"25:10:00"``).
    """
    text = to_str(value)
    if text is None:
        return None
    parts = text.split(":")
    if not 2 <= len(parts) <= 3 or not all(part.strip().isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    if len(numbers) == 2:
        numbers.insert(0, 0)
    hours, minutes, seconds = numbers
    if minutes >= 60 or seconds >= 60:
        return None
    return hours * 3600 + minutes * 60 + seconds
