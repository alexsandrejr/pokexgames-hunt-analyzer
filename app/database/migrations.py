"""Versionamento do esquema do banco (``PRAGMA user_version`` do SQLite).

As tabelas são criadas por ``Base.metadata.create_all`` (versão 1). Mudanças
posteriores entram como novas ``Migration`` no fim de ``MIGRATIONS``, com
comandos SQL idempotentes. Ao abrir um banco, as migrações com versão maior que
a gravada nele são aplicadas em ordem, e a versão é atualizada.

Tabelas novas são criadas pelo ``create_all``. Para adicionar uma coluna, declare-a
em ``models.py`` e em ``columns`` (ela só é criada se faltar, pois bancos novos já
a recebem do ``create_all``), por exemplo::

    Migration(4, "Coluna X", columns=(("hunt_sessions", "x", "INTEGER"),))
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection, text


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    statements: tuple[str, ...] = ()
    # (tabela, coluna, tipo SQL) criadas antes dos ``statements``, se ainda não existirem.
    columns: tuple[tuple[str, str, str], ...] = ()


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "Esquema inicial (tabelas criadas pelos modelos)"),
    Migration(2, "Índices sem diferenciar maiúsculas para filtros por item e inimigo", (
        "CREATE INDEX IF NOT EXISTS ix_drops_item_lower ON drops (lower(item))",
        "CREATE INDEX IF NOT EXISTS ix_supplies_item_lower ON supplies (lower(item))",
        "CREATE INDEX IF NOT EXISTS ix_enemies_defeated_enemy_lower "
        "ON enemies_defeated (lower(enemy))",
    )),
    Migration(3, "Preços personalizados de itens (preço do Analyzer preservado)", (
        "UPDATE drops SET original_unit_price = unit_price, original_total_price = total_price "
        "WHERE original_unit_price IS NULL AND original_total_price IS NULL",
        "UPDATE supplies SET original_unit_price = unit_price, "
        "original_total_price = total_price "
        "WHERE original_unit_price IS NULL AND original_total_price IS NULL",
    ), columns=(
        ("drops", "original_unit_price", "FLOAT"),
        ("drops", "original_total_price", "INTEGER"),
        ("supplies", "original_unit_price", "FLOAT"),
        ("supplies", "original_total_price", "INTEGER"),
    )),
    Migration(4, "Categoria da sessão (Hunt, Rift, bosses de energia e Terror)", (
        "CREATE INDEX IF NOT EXISTS ix_hunt_sessions_category ON hunt_sessions (category)",
    ), columns=(
        ("hunt_sessions", "category", "VARCHAR(20) NOT NULL DEFAULT 'hunt'"),
    )),
)

LATEST_VERSION = MIGRATIONS[-1].version


class SchemaTooNewError(RuntimeError):
    """O banco foi criado por uma versão mais nova do aplicativo."""


def schema_version(connection: Connection) -> int:
    return int(connection.execute(text("PRAGMA user_version")).scalar() or 0)


def pending_migrations(connection: Connection) -> list[Migration]:
    current = schema_version(connection)
    if current > LATEST_VERSION:
        raise SchemaTooNewError(
            f"O banco está na versão {current}, mas este aplicativo conhece até a "
            f"{LATEST_VERSION}. Atualize o aplicativo para abri-lo.")
    return [migration for migration in MIGRATIONS if migration.version > current]


def apply_migrations(connection: Connection) -> list[Migration]:
    """Aplica as migrações pendentes (na transação da conexão) e retorna as aplicadas."""
    applied = pending_migrations(connection)
    for migration in applied:
        for table, column, sql_type in migration.columns:
            if column not in _column_names(connection, table):
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
        for statement in migration.statements:
            connection.execute(text(statement))
    if applied:
        # PRAGMA não aceita parâmetros; o valor vem de uma constante do código.
        connection.execute(text(f"PRAGMA user_version = {applied[-1].version:d}"))
    return applied


def _column_names(connection: Connection, table: str) -> set[str]:
    # PRAGMA não aceita parâmetros; a tabela vem de uma constante do código.
    return {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}
