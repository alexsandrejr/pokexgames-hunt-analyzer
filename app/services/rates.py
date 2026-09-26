"""Taxas por unidade de tempo (usadas por estatísticas e relatórios)."""

from __future__ import annotations

from app.utils.constants import SECONDS_PER_HOUR


def rate_per_hour(total: float | None, duration_seconds: float | None) -> float | None:
    """Taxa por hora; ``None`` quando não há tempo para dividir."""
    if total is None or not duration_seconds or duration_seconds <= 0:
        return None
    return total * SECONDS_PER_HOUR / duration_seconds


def rate_per_second(total: float | None, duration_seconds: float | None) -> float | None:
    if total is None or not duration_seconds or duration_seconds <= 0:
        return None
    return total / duration_seconds
