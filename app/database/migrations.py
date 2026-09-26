"""Versionamento do esquema do banco (``PRAGMA user_version`` do SQLite).

As tabelas são criadas por ``Base.metadata.create_all`` (versão 1). Mudanças
posteriores entram como novas ``Migration`` no fim de ``MIGRATIONS``, com
comandos SQL idempotentes. Ao abrir um banco, as migrações com versão maior que
a gravada nele são aplicadas em ordem, e a versão é atualizada.

Para adicionar uma coluna no futuro, por exemplo::

    Migration(3, "Coluna X", ("ALTER TABLE hunt_sessions ADD COLUMN x INTEGER",))

e acrescentar o campo correspondente em ``models.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection, text


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    statements: tuple[str, ...] = ()


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "Esquema inicial (tabelas criadas pelos modelos)"),
    Migration(2, "Índices sem diferenciar maiúsculas para filtros por item e inimigo", (
        "CREATE INDEX IF NOT EXISTS ix_drops_item_lower ON drops (lower(item))",
        "CREATE INDEX IF NOT EXISTS ix_supplies_item_lower ON supplies (lower(item))",
        "CREATE INDEX IF NOT EXISTS ix_enemies_defeated_enemy_lower "
        "ON enemies_defeated (lower(enemy))",
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
        for statement in migration.statements:
            connection.execute(text(statement))
    if applied:
        # PRAGMA não aceita parâmetros; o valor vem de uma constante do código.
        connection.execute(text(f"PRAGMA user_version = {applied[-1].version:d}"))
    return applied
