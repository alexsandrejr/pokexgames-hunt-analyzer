"""Conversão do TSV do Analyzer (texto separado por tabulações) para o documento JSON.

O Analyzer também exporta a sessão como tabelas em texto, uma por seção::

    Sessão
    Campo	Valor
    ID da sessão	198
    ...

    Saques
    Jogador	Item	Contagem	Preço unitário	Preço total	Ignoradas
    Avg Sandrinhas	pot of lava	368	18	6624

As seções são separadas por uma linha em branco: título, cabeçalho e linhas.
Títulos, cabeçalhos e campos em português são traduzidos para as chaves do JSON
(``Saques`` → ``Drops``, ``Contagem`` → ``Count``...); nomes já em inglês passam
direto. O resultado tem a mesma estrutura do JSON e segue pelo mesmo importador.
"""

from __future__ import annotations

import re
from typing import Any

from app.utils.constants import AnalyzerKeys, EntryKeys
from app.utils.validators import to_bool

FIELD_COLUMN = "Field"
VALUE_COLUMN = "Value"

SECTION_NAMES = {
    "Sessão": AnalyzerKeys.SESSION,
    "Experiência": AnalyzerKeys.EXPERIENCE,
    "Saques": AnalyzerKeys.DROPS,
    "Suprimentos": AnalyzerKeys.SUPPLIES,
    "Inimigos Derrotados": AnalyzerKeys.ENEMIES,
    "Dano": "Damage",
}

COLUMN_NAMES = {
    "Campo": FIELD_COLUMN,
    "Valor": VALUE_COLUMN,
    "Jogador": EntryKeys.PLAYER,
    "Item": EntryKeys.ITEM,
    "Contagem": EntryKeys.COUNT,
    "Preço unitário": EntryKeys.UNIT_PRICE,
    "Preço total": EntryKeys.TOTAL_PRICE,
    "Ignoradas": EntryKeys.IGNORED,
    "Ignorado": EntryKeys.IGNORED,
    "Inimigo": EntryKeys.ENEMY,
    "Raro": EntryKeys.RARE,
    "Elemento": "Element",
    "Experiência": "Experience",
    "Dano recebido": "Damage taken",
    "Dano causado": "Damage dealt",
}

SESSION_FIELD_NAMES = {
    "Tipo de sessão": "Session type",
    "ID da sessão": "Session ID",
    "Status": "Status",
    "Começar": "Start",
    "Início": "Start",
    "Duração": "Duration",
    "Duração em segundos": "Duration seconds",
    "Tempo pausado em segundos": "Paused seconds",
    "Experiência": "Experience",
    "Experiência por hora": "Experience per hour",
    "Tempo até o próximo nível": "Time to next level",
    "Tempo em segundos até o próximo nível": "Time to next level seconds",
    "Ganho bruto": "Raw gains",
    "Ganho bruto por hora": "Raw gains per hour",
    "Suprimentos": "Supplies",
    "Suprimentos por hora": "Supplies per hour",
    "Lucro": "Profit",
    "Lucro por hora": "Profit per hour",
    "Eliminações": "Kills",
    "Eliminações por hora": "Kills per hour",
    "Raros derrotados": "Rare kills",
    "Raros derrotados por hora": "Rare kills per hour",
    "Dano recebido": "Damage taken",
    "Dano recebido por segundo": "Damage taken per second",
    "Dano causado": "Damage dealt",
    "Dano causado por segundo": "Damage dealt per second",
}

# Colunas "Sim"/"Não" que viram true/false no documento.
BOOLEAN_COLUMNS = {EntryKeys.RARE, EntryKeys.IGNORED}

_INT_PATTERN = re.compile(r"-?\d+")
_FLOAT_PATTERN = re.compile(r"-?\d+\.\d+")


class TsvFormatError(ValueError):
    """O texto não tem nenhuma seção reconhecível do TSV do Analyzer."""


def looks_like_tsv(text: str) -> bool:
    """TSV: tem tabulações e não começa como JSON (``{`` ou ``[``)."""
    stripped = text.lstrip()
    return "\t" in stripped and not stripped.startswith(("{", "["))


def tsv_to_document(text: str) -> dict[str, Any]:
    """Converte o TSV no dicionário equivalente ao JSON do Analyzer.

    Seções com cabeçalho ``Campo``/``Valor`` viram objetos; as demais, listas de
    objetos (uma por linha). Células ausentes no fim da linha viram ``None``.
    """
    document: dict[str, Any] = {}
    for block in _blocks(text):
        if len(block) < 2 or "\t" in block[0]:
            continue  # sem título ou sem cabeçalho
        title, header_line, *rows = block
        section = SECTION_NAMES.get(title.strip(), title.strip())
        header = [COLUMN_NAMES.get(name, name) for name in _cells(header_line)]
        if header[:2] == [FIELD_COLUMN, VALUE_COLUMN]:
            document[section] = _field_values(rows, section)
        else:
            document[section] = [_row_object(header, row) for row in rows]
    if not document:
        raise TsvFormatError("Nenhuma seção (título + cabeçalho) foi encontrada no texto.")
    return document


def _blocks(text: str) -> list[list[str]]:
    """Grupos de linhas separados por linhas em branco."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in [*text.splitlines(), ""]:
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    return blocks


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.split("\t")]


def _field_values(rows: list[str], section: str) -> dict[str, Any]:
    names = SESSION_FIELD_NAMES if section == AnalyzerKeys.SESSION else {}
    values: dict[str, Any] = {}
    for row in rows:
        field, value, *_ = [*_cells(row), ""]
        if field:
            values[names.get(field, field)] = _convert(value)
    return values


def _row_object(header: list[str], row: str) -> dict[str, Any]:
    cells = _cells(row)
    cells += [""] * (len(header) - len(cells))
    return {
        column: to_bool(cell) if column in BOOLEAN_COLUMNS else _convert(cell)
        for column, cell in zip(header, cells)
    }


def _convert(value: str) -> Any:
    """Números viram ``int``/``float``, vazio vira ``None``; o resto fica como texto."""
    if not value:
        return None
    if _INT_PATTERN.fullmatch(value):
        return int(value)
    if _FLOAT_PATTERN.fullmatch(value):
        return float(value)
    return value
