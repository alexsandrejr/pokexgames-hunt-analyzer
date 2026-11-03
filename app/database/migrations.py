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
    # (tabela, coluna) apagadas depois dos ``statements``, se ainda existirem.
    dropped_columns: tuple[tuple[str, str], ...] = ()


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
    Migration(5, 'Recompensas do chat ("Você recebeu:") como drops da sessão', (
        "CREATE INDEX IF NOT EXISTS ix_drops_chat_reward_id ON drops (chat_reward_id)",
    ), columns=(
        ("drops", "chat_reward_id",
         "INTEGER REFERENCES chat_rewards (id) ON DELETE CASCADE"),
    )),
    Migration(6, "Página DPS: boss inicial (tabelas criadas pelos modelos)", (
        "INSERT INTO dps_bosses (name, time_limit_seconds) SELECT 'Padrão', 420 "
        "WHERE NOT EXISTS (SELECT 1 FROM dps_bosses)",
    )),
    Migration(7, "Página DPS: elemento dos golpes (testes em dummies criados pelos modelos)",
              columns=(
        ("dps_skills", "element", "VARCHAR(20)"),
        ("dps_pokemons", "basic_element", "VARCHAR(20)"),
    )),
    Migration(8, "Página DPS: o dano passa a vir dos testes, no dummy escolhido em cada boss",
              columns=(
        ("dps_bosses", "dummy", "VARCHAR(20) NOT NULL DEFAULT 'neutral'"),
    ), dropped_columns=(
        ("dps_skills", "damage"),
        ("dps_pokemons", "basic_damage"),
    )),
    Migration(9, "Página DPS: origem do dano, elementos do boss e testes dentro do boss", (
        "CREATE INDEX IF NOT EXISTS ix_dps_damage_tests_boss_id ON dps_damage_tests (boss_id)",
    ), columns=(
        ("dps_bosses", "damage_source", "VARCHAR(20) NOT NULL DEFAULT 'dummy'"),
        ("dps_bosses", "element_1", "VARCHAR(20)"),
        ("dps_bosses", "element_2", "VARCHAR(20)"),
        ("dps_damage_tests", "boss_id",
         "INTEGER REFERENCES dps_bosses (id) ON DELETE CASCADE"),
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
        for table, column in migration.dropped_columns:
            if column in _column_names(connection, table):
                connection.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
    if applied:
        # PRAGMA não aceita parâmetros; o valor vem de uma constante do código.
        connection.execute(text(f"PRAGMA user_version = {applied[-1].version:d}"))
    return applied


def _column_names(connection: Connection, table: str) -> set[str]:
    # PRAGMA não aceita parâmetros; a tabela vem de uma constante do código.
    return {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}
