"""Formatação de valores para exibição.

O separador de milhar/decimal segue o formato ativo (``set_number_format``):
pt-BR (1.119.522 / 12,5, padrão) ou en-US (1,119,522 / 12.5).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

PLACEHOLDER = "—"


@dataclass(frozen=True)
class NumberFormat:
    name: str
    thousands: str
    decimal: str

    @property
    def translation(self) -> dict[int, str]:
        # Converte a saída do Python ("1,234.5") para este formato.
        return str.maketrans({",": self.thousands, ".": self.decimal})

    @property
    def example(self) -> str:
        return f"1{self.thousands}234{self.thousands}567{self.decimal}89"


NUMBER_FORMATS: dict[str, NumberFormat] = {
    "pt-BR": NumberFormat("pt-BR", ".", ","),
    "en-US": NumberFormat("en-US", ",", "."),
}
DEFAULT_NUMBER_FORMAT = "pt-BR"
_active_format = NUMBER_FORMATS[DEFAULT_NUMBER_FORMAT]
_active_translation = _active_format.translation


def set_number_format(name: str) -> NumberFormat:
    """Troca o formato usado por toda a aplicação (nomes desconhecidos → pt-BR)."""
    global _active_format, _active_translation
    _active_format = NUMBER_FORMATS.get(name, NUMBER_FORMATS[DEFAULT_NUMBER_FORMAT])
    _active_translation = _active_format.translation
    return _active_format


def number_format() -> NumberFormat:
    return _active_format

_COMPACT_UNITS: tuple[tuple[float, str], ...] = (
    (1_000_000_000_000, "T"),
    (1_000_000_000, "B"),
    (1_000_000, "M"),
    (1_000, "K"),
)


def _as_finite_number(value: object) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def format_number(value: float | int | None, decimals: int = 0) -> str:
    """``1119522`` → ``"1.119.522"``; ``12.5`` com 1 casa → ``"12,5"``."""
    number = _as_finite_number(value)
    if number is None:
        return PLACEHOLDER
    if isinstance(number, int) and decimals == 0:
        text = f"{number:,}"
    else:
        text = f"{number:,.{decimals}f}"
        if text.lstrip("-").strip("0.,") == "":
            text = text.lstrip("-")  # evita "-0"
    return text.translate(_active_translation)


def format_money(value: float | int | None) -> str:
    """Valores em dinheiro do jogo são exibidos sem casas decimais."""
    return format_number(value, decimals=0)


def format_compact(value: float | int | None, decimals: int = 1) -> str:
    """Grandes números de forma legível: ``119470652`` → ``"119,5 M"``."""
    number = _as_finite_number(value)
    if number is None:
        return PLACEHOLDER
    for threshold, suffix in _COMPACT_UNITS:
        if abs(number) >= threshold:
            return f"{format_number(number / threshold, decimals)} {suffix}"
    return format_number(number)


def format_duration(seconds: int | float | None) -> str:
    """``4310`` → ``"01:11:50"`` (horas podem passar de 24)."""
    number = _as_finite_number(seconds)
    if number is None or number < 0:
        return PLACEHOLDER
    total = int(round(number))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_duration_long(seconds: int | float | None) -> str:
    """Totais de tempo: ``152280`` → ``"42h 18min"``."""
    number = _as_finite_number(seconds)
    if number is None or number < 0:
        return PLACEHOLDER
    total_minutes = int(number // 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{format_number(hours)}h {minutes:02d}min" if hours else f"{minutes}min"


def format_datetime(value: datetime | None) -> str:
    return value.strftime("%d/%m/%Y %H:%M:%S") if value else PLACEHOLDER


def format_datetime_short(value: datetime | None) -> str:
    return value.strftime("%d/%m/%Y %H:%M") if value else PLACEHOLDER


def format_date(value: datetime | None) -> str:
    return value.strftime("%d/%m/%Y") if value else PLACEHOLDER


def format_bool(value: bool | None) -> str:
    if value is None:
        return PLACEHOLDER
    return "Sim" if value else "Não"


def format_text(value: object) -> str:
    return PLACEHOLDER if value is None or value == "" else str(value)


def pretty_json(text: str, indent: int = 4) -> str:
    """Reindenta um JSON mantendo a ordem original das chaves.

    Se o texto não for JSON válido, é devolvido sem alterações.
    """
    try:
        return json.dumps(json.loads(text), indent=indent, ensure_ascii=False)
    except (TypeError, ValueError):
        return text


class ValueKind(Enum):
    """Natureza de um valor: define a formatação na tela, no PDF e nas planilhas."""

    TEXT = "text"
    NUMBER = "number"  # inteiro ou taxa exibida sem casas decimais
    MONEY = "money"
    DURATION = "duration"  # segundos
    DATETIME = "datetime"
    PERCENT = "percent"  # fração 0–1


def format_percent(value: float | None) -> str:
    number = _as_finite_number(value)
    return PLACEHOLDER if number is None else f"{format_number(number * 100, decimals=1)}%"


def format_value(kind: ValueKind, value: object) -> str:
    if kind is ValueKind.MONEY:
        return format_money(value)  # type: ignore[arg-type]
    if kind is ValueKind.NUMBER:
        return format_number(value)  # type: ignore[arg-type]
    if kind is ValueKind.DURATION:
        return format_duration(value)  # type: ignore[arg-type]
    if kind is ValueKind.DATETIME:
        return format_datetime(value) if isinstance(value, datetime) else format_text(value)
    if kind is ValueKind.PERCENT:
        return format_percent(value)  # type: ignore[arg-type]
    return format_text(value)
