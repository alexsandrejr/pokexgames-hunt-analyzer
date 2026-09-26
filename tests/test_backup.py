import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from app.database.database import Database
from app.database.migrations import LATEST_VERSION
from app.database.models import Base
from app.services.backup_service import (
    BackupError,
    BackupKind,
    BackupService,
    inspect_backup,
)
from app.services.hunt_service import HuntService
from tests.helpers import SAMPLE_HUNT_PATH, memory_database, sample_text


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.database = Database.from_path(self.root / "data" / "hunts.db")
        self.database.create_schema()
        self.hunts = HuntService(self.database)
        self.hunts.import_file(SAMPLE_HUNT_PATH)
        self.service = BackupService(self.database, self.root / "data" / "backups")

    def tearDown(self) -> None:
        self.database.dispose()
        self._tmp.cleanup()

    def test_backup_is_a_consistent_copy(self) -> None:
        path = self.service.create_backup()
        self.assertTrue(path.name.startswith("hunts_backup_"))
        self.assertTrue(path.name.endswith("_manual.db"))
        self.assertEqual(inspect_backup(path), 1)
        [info] = self.service.list_backups()
        self.assertEqual(info.kind, BackupKind.MANUAL)
        self.assertEqual(info.kind_label, "Manual")
        self.assertGreater(info.size_bytes, 0)

    def test_backup_to_chosen_file(self) -> None:
        target = self.root / "pendrive" / "copia.db"
        self.service.create_backup(destination=target)
        self.assertEqual(inspect_backup(target), 1)
        self.service.create_backup(destination=target)  # sobrescreve sem erro
        self.assertEqual(self.service.list_backups(), [])  # fora da pasta padrão

    def test_same_second_backups_get_unique_names(self) -> None:
        first = self.service.create_backup()
        second = self.service.create_backup()
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.service.list_backups()), 2)
        self.assertTrue(all(b.kind == BackupKind.MANUAL for b in self.service.list_backups()))

    def test_restore_replaces_data_and_keeps_safety_copy(self) -> None:
        backup = self.service.create_backup()
        self.hunts.import_text(sample_text(**{"Session ID": 2, "Start": "2026-09-27 10:00:00"}))
        self.assertEqual(self.hunts.count_hunts(), 2)

        safety = self.service.restore(backup)

        self.assertEqual(self.hunts.count_hunts(), 1)  # o mesmo Database continua usável
        self.assertEqual(inspect_backup(safety), 2)  # estado anterior preservado
        self.assertIn(BackupKind.BEFORE_RESTORE, safety.name)
        self.hunts.import_text(sample_text(**{"Session ID": 3, "Start": "2026-09-28 10:00:00"}))
        self.assertEqual(self.hunts.count_hunts(), 2)

    def test_restore_of_old_version_backup_is_migrated(self) -> None:
        old_path = self.root / "antigo.db"
        old = Database.from_path(old_path)
        Base.metadata.create_all(old.engine)  # banco da Fase 1 (sem versão)
        old.dispose()
        self.service.restore(old_path)
        self.assertEqual(self.database.schema_version(), LATEST_VERSION)
        self.assertEqual(self.hunts.count_hunts(), 0)

    def test_invalid_restore_sources(self) -> None:
        not_sqlite = self.root / "texto.db"
        not_sqlite.write_text("isto não é um banco")
        other_db = self.root / "outro.db"
        other = Database(f"sqlite:///{other_db.as_posix()}")
        with other.engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE x (id INTEGER)")
        other.dispose()
        for source, message in ((self.root / "nao-existe.db", "não encontrado"),
                                (not_sqlite, "SQLite válido"),
                                (other_db, "não é um banco do"),
                                (self.database.file_path, "já é o banco em uso")):
            with self.subTest(source=source.name), self.assertRaises(BackupError) as ctx:
                self.service.restore(source)
            self.assertIn(message, str(ctx.exception))
        self.assertEqual(self.hunts.count_hunts(), 1)  # nada foi alterado
        self.assertEqual(self.service.list_backups(), [])  # nem backup de segurança

    def test_automatic_backup_once_per_day_and_pruning(self) -> None:
        first = self.service.automatic_backup_if_due(keep=3)
        self.assertIsNotNone(first)
        self.assertIsNone(self.service.automatic_backup_if_due(keep=3))  # já fez hoje
        # Backups automáticos antigos (dias anteriores), criados com nomes datados.
        for day in range(1, 6):
            stamp = datetime(2026, 9, day, 12).strftime("%Y-%m-%d_%H-%M-%S")
            (self.root / "data" / "backups" / f"hunts_backup_{stamp}_auto.db").write_bytes(
                first.read_bytes())
        manual = self.service.create_backup()
        removed = self.service.prune_automatic(keep=3)
        self.assertEqual(len(removed), 3)
        kinds = [b.kind for b in self.service.list_backups()]
        self.assertEqual(kinds.count(BackupKind.AUTOMATIC), 3)
        self.assertTrue(manual.exists())  # backups manuais nunca são apagados
        self.assertTrue(first.exists())  # o mais recente fica

    def test_automatic_backup_skips_empty_database(self) -> None:
        empty = Database.from_path(self.root / "vazio" / "hunts.db")
        empty.create_schema()
        service = BackupService(empty, self.root / "vazio" / "backups")
        self.assertIsNone(service.automatic_backup_if_due(keep=5, today=date(2026, 9, 26)))
        empty.dispose()

    def test_memory_database_cannot_be_backed_up(self) -> None:
        database = memory_database()
        with self.assertRaises(BackupError):
            BackupService(database, self.root / "b").create_backup()
        database.dispose()


if __name__ == "__main__":
    unittest.main()
