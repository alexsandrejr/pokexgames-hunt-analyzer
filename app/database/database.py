"""Conexão com o banco e gerenciamento de sessões SQLAlchemy."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.database.migrations import (
    Migration,
    apply_migrations,
    pending_migrations,
    schema_version,
)
from app.database.models import Base


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    # O SQLite só aplica ON DELETE CASCADE com foreign_keys ativado por conexão.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Database:
    """Encapsula engine e fábrica de sessões.

    Uso::

        db = Database.from_path(Path("data/hunts.db"))
        db.create_schema()
        with db.session() as session:
            ...  # commit automático ao sair, rollback em caso de erro
    """

    def __init__(self, url: str, echo: bool = False) -> None:
        self.url = url
        self.engine = create_engine(url, echo=echo)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)
        # expire_on_commit=False: objetos continuam legíveis após fechar a sessão.
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    @classmethod
    def from_path(cls, path: Path, echo: bool = False) -> Database:
        path.parent.mkdir(parents=True, exist_ok=True)
        return cls(f"sqlite:///{path.resolve().as_posix()}", echo=echo)

    @property
    def file_path(self) -> Path | None:
        database = self.engine.url.database
        return Path(database) if database and database != ":memory:" else None

    def create_schema(self) -> list[Migration]:
        """Cria as tabelas que faltam e aplica as migrações pendentes (idempotente).

        Retorna as migrações aplicadas nesta chamada.
        """
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            return apply_migrations(connection)

    def pending_migrations(self) -> list[Migration]:
        with self.engine.connect() as connection:
            return pending_migrations(connection)

    def schema_version(self) -> int:
        with self.engine.connect() as connection:
            return schema_version(connection)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
