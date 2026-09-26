import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select, text

from app.database.database import Database
from app.database.migrations import LATEST_VERSION, SchemaTooNewError
from app.database.models import Base, HuntSession
from app.database.query_filters import hunt_filter_conditions
from app.services.filters import HuntFilter, ItemCondition
from app.services.hunt_service import HuntService
from tests.helpers import SAMPLE_HUNT_PATH


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "hunts.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def open(self) -> Database:
        database = Database.from_path(self.path)
        self.addCleanup(database.dispose)  # libera o arquivo mesmo se o teste falhar
        return database

    def _indexes(self, database: Database, table: str) -> set[str]:
        # O inspetor do SQLAlchemy ignora índices de expressão; consulta direta.
        with database.engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = :t"),
                {"t": table})
            return {row[0] for row in rows}

    def test_new_database_is_created_at_latest_version(self) -> None:
        database = self.open()
        applied = database.create_schema()
        self.assertEqual([m.version for m in applied], list(range(1, LATEST_VERSION + 1)))
        self.assertEqual(database.schema_version(), LATEST_VERSION)
        self.assertIn("ix_drops_item_lower", self._indexes(database, "drops"))
        self.assertIn("ix_enemies_defeated_enemy_lower",
                      self._indexes(database, "enemies_defeated"))
        self.assertEqual(database.create_schema(), [])  # idempotente
        database.dispose()

    def test_phase1_database_is_upgraded_keeping_data(self) -> None:
        # Banco como a Fase 1 criava: só create_all, sem versão (user_version = 0).
        old = self.open()
        Base.metadata.create_all(old.engine)
        HuntService(old).import_file(SAMPLE_HUNT_PATH)
        self.assertEqual(old.schema_version(), 0)
        old.dispose()

        database = self.open()
        self.assertEqual([m.version for m in database.pending_migrations()], [1, 2])
        database.create_schema()
        self.assertEqual(database.schema_version(), LATEST_VERSION)
        self.assertEqual(HuntService(database).count_hunts(), 1)
        self.assertEqual(database.pending_migrations(), [])
        database.dispose()

    def test_item_filter_uses_new_index(self) -> None:
        database = self.open()
        database.create_schema()
        conditions = hunt_filter_conditions(HuntFilter(items=(ItemCondition("Nightmare Ore"),)))
        stmt = select(HuntSession.id).where(*conditions)
        compiled = stmt.compile(database.engine, compile_kwargs={"literal_binds": True})
        with database.engine.connect() as connection:
            plan = " ".join(str(row) for row in connection.execute(
                text(f"EXPLAIN QUERY PLAN {compiled}")))
        self.assertIn("ix_drops_item_lower", plan)
        database.dispose()

    def test_database_from_newer_app_is_refused(self) -> None:
        database = self.open()
        database.create_schema()
        with database.engine.begin() as connection:
            connection.execute(text(f"PRAGMA user_version = {LATEST_VERSION + 1}"))
        with self.assertRaises(SchemaTooNewError):
            database.create_schema()
        database.dispose()


if __name__ == "__main__":
    unittest.main()
