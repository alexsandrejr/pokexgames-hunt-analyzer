"""Constantes compartilhadas: nomes da aplicação e chaves do JSON do Analyzer."""

APP_NAME = "PokeXGames Hunt Analyzer"
APP_VERSION = "1.0.0"
ORGANIZATION_NAME = "PokeXGames Hunt Analyzer"


class AnalyzerKeys:
    """Chaves de primeiro nível do JSON exportado pelo Analyzer."""

    SESSION = "Session"
    ENEMIES = "Enemies Defeated"
    DROPS = "Drops"
    SUPPLIES = "Supplies"
    EXPERIENCE = "Experience"


class EntryKeys:
    """Chaves usadas nos itens das listas (Enemies, Drops e Supplies)."""

    ENEMY = "Enemy"
    ITEM = "Item"
    PLAYER = "Player"
    COUNT = "Count"
    RARE = "Rare"
    IGNORED = "Ignored"
    UNIT_PRICE = "Unit price"
    TOTAL_PRICE = "Total price"


# Formatos aceitos para o campo "Start" da sessão (o primeiro é o atual do Analyzer).
ANALYZER_DATETIME_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
)

SECONDS_PER_HOUR = 3600
