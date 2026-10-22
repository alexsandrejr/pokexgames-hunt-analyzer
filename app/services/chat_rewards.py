"""Leitura das mensagens "Você recebeu: ..." do chat do PokeXGames.

Recompensas de boss, Secret Lab, Subject 14, Tentacruel Chosen etc. podem vir numa
sacola aberta depois da sessão: os itens aparecem só no chat, não no JSON do
Analyzer. Este módulo extrai quantidade e nome de cada item da mensagem::

    Você recebeu: 15 Echo Shards, 2 Mystic Stars, 84 hundred dollars.

e aproxima o nome do item já conhecido no banco (``Echo Shards`` → ``Echo Shard``),
pois o chat usa plural e nem sempre a mesma grafia do Analyzer. Não conhece o
banco: os nomes conhecidos são passados por quem chama (``HuntService``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

# O texto depois de "Você recebeu:" até o fim da linha. Aceita o chat em inglês.
MESSAGE_PATTERN = re.compile(r"(?:voc[eê]\s+recebeu|you\s+received)\s*:\s*(.+)", re.IGNORECASE)
# Os itens são separados por vírgula; um trecho sem quantidade vai para ``invalid``.
ITEM_SEPARATOR = re.compile(r"\s*,\s*")
# "1380 tech data", "1.380 tech data", "1 10.000 carat emerald" (1 × "10.000 carat emerald").
ITEM_PATTERN = re.compile(r"^(\d{1,3}(?:\.\d{3})+|\d+)\s+(.+)$")
# Sufixo entre parênteses que não faz parte do plural: "Technological Crystal (Tier: 7)".
SUFFIX_PATTERN = re.compile(r"^(.*?)(\s*\(.*\))?$")

# Nomes do chat que diferem do nome do item no Analyzer (em minúsculas).
ALIASES: dict[str, str] = {
    "hundred dollars": "one hundred dollars",
    "hundred dollar": "one hundred dollars",
}


@dataclass(frozen=True)
class ChatItem:
    """Um item da mensagem, com o nome como veio no chat."""

    name: str
    count: int


@dataclass
class ParsedChatRewards:
    messages: list[str] = field(default_factory=list)  # uma por "Você recebeu:"
    items: list[ChatItem] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)  # trechos sem quantidade


def parse_chat_rewards(text: str) -> ParsedChatRewards:
    """Extrai os itens de uma ou mais mensagens "Você recebeu:" (uma por linha).

    Linhas sem a mensagem (horário, outras falas do chat) são ignoradas.
    """
    parsed = ParsedChatRewards()
    for match in MESSAGE_PATTERN.finditer(text):
        body = match.group(1).strip().rstrip(".").strip()
        if not body:
            continue
        parsed.messages.append(normalize_message(match.group(0)))
        for part in ITEM_SEPARATOR.split(body):
            part = part.strip()
            item = ITEM_PATTERN.match(part)
            if item is None:
                if part:
                    parsed.invalid.append(part)
                continue
            count = int(item.group(1).replace(".", ""))
            parsed.items.append(ChatItem(name=" ".join(item.group(2).split()), count=count))
    return parsed


def normalize_message(message: str) -> str:
    """Mensagem sem espaços repetidos nem ponto final (para reconhecer repetições)."""
    return " ".join(message.split()).rstrip(".").strip()


def resolve_item_name(name: str, count: int, known: Mapping[str, str]) -> tuple[str, bool]:
    """Nome do item no banco para o nome do chat. Retorna ``(nome, conhecido)``.

    ``known`` é ``{nome em minúsculas: nome como exibido}``. Tenta o nome exato,
    os apelidos e as formas no singular; se nenhuma for conhecida, um nome no
    plural (quantidade maior que 1) vai para o singular.
    """
    candidates = [name, *_singular_forms(name)]
    for candidate in candidates:
        key = candidate.lower()
        key = ALIASES.get(key, key)
        if key in known:
            return known[key], True
    alias = ALIASES.get(name.lower())
    if alias is not None:
        return alias, False
    if count > 1:
        return _default_singular(name), False
    return name, False


def _singular_forms(name: str) -> list[str]:
    head, suffix = _split_suffix(name)
    words = head.split(" ")
    last = words[-1]
    forms = []
    lower = last.lower()
    if lower.endswith("ies") and len(last) > 3:
        forms.append(last[:-3] + "y")
    if lower.endswith("es") and len(last) > 2:
        forms.append(last[:-2])
    if lower.endswith("s") and not lower.endswith("ss") and len(last) > 1:
        forms.append(last[:-1])
    return [" ".join([*words[:-1], form]) + suffix for form in forms]


def _default_singular(name: str) -> str:
    """Singular por regra simples, usado só para nomes que o banco ainda não conhece."""
    head, suffix = _split_suffix(name)
    words = head.split(" ")
    last = words[-1]
    lower = last.lower()
    if lower.endswith("ies") and len(last) > 3:
        last = last[:-3] + "y"
    elif lower.endswith(("ches", "shes", "sses", "xes", "zes")):
        last = last[:-2]
    elif lower.endswith("s") and not lower.endswith(("ss", "us", "is")) and len(last) > 1:
        last = last[:-1]
    return " ".join([*words[:-1], last]) + suffix


def _split_suffix(name: str) -> tuple[str, str]:
    match = SUFFIX_PATTERN.match(name)
    assert match is not None  # o padrão aceita qualquer texto
    return match.group(1), match.group(2) or ""
