import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import func, select

from app.database.database import Database
from app.database.models import Drop, EnemyDefeated, Supply
from app.services.dto import ImportStatus
from app.services.hunt_service import HuntService
from tests.helpers import SAMPLE_HUNT_PATH, load_sample, memory_database, sample_text


class ImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = memory_database()
        self.service = HuntService(self.database)

    def tearDown(self) -> None:
        self.database.dispose()

    def _count(self, model) -> int:
        with self.database.session() as session:
            return session.scalar(select(func.count()).select_from(model))

    def test_import_file_persists_everything(self) -> None:
        result = self.service.import_file(SAMPLE_HUNT_PATH)
        self.assertEqual(result.status, ImportStatus.IMPORTED, result.message)
        self.assertIsNotNone(result.hunt_id)

        hunt = self.service.get_hunt_details(result.hunt_id)
        self.assertEqual(hunt.session_id, 1080)
        self.assertEqual(hunt.player, "Royalzxd")
        self.assertEqual(hunt.profit, 1119522)
        self.assertEqual(hunt.source_file, "sample_hunt.json")
        self.assertEqual(hunt.raw_json, SAMPLE_HUNT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(hunt.enemies), 3)
        self.assertEqual(len(hunt.drops), 2)
        self.assertEqual(len(hunt.supplies_used), 1)
        self.assertEqual(sum(d.total_price for d in hunt.drops), 262872 + 388000)
        self.assertIsNotNone(hunt.created_at)

    def test_invalid_json_returns_error_result(self) -> None:
        result = self.service.import_text("{ not json", source="broken.json")
        self.assertEqual(result.status, ImportStatus.ERROR)
        self.assertEqual(result.message, "JSON inválido.")
        self.assertEqual(self.service.count_hunts(), 0)

    def test_missing_session_returns_error_result(self) -> None:
        result = self.service.import_text(json.dumps({"Drops": []}), source="x.json")
        self.assertEqual(result.status, ImportStatus.ERROR)
        self.assertEqual(result.message, "O arquivo não possui uma sessão válida do Analyzer.")

    def test_missing_file_returns_error_result(self) -> None:
        result = self.service.import_file(Path("nao-existe.json"))
        self.assertEqual(result.status, ImportStatus.ERROR)
        self.assertEqual(self.service.count_hunts(), 0)

    def test_duplicate_is_detected(self) -> None:
        first = self.service.import_file(SAMPLE_HUNT_PATH)
        second = self.service.import_file(SAMPLE_HUNT_PATH)
        self.assertEqual(second.status, ImportStatus.DUPLICATE)
        self.assertEqual(second.message, "Esta Hunt já foi importada.")
        self.assertEqual(second.duplicate_of, [first.hunt_id])
        self.assertEqual(self.service.count_hunts(), 1)

    def test_same_session_exported_later_is_duplicate(self) -> None:
        """Mesmo session_id/player/início com números diferentes (re-exportação)."""
        self.service.import_file(SAMPLE_HUNT_PATH)
        later = sample_text(**{"Duration seconds": 5000, "Kills": 400})
        self.assertEqual(self.service.import_text(later).status, ImportStatus.DUPLICATE)

    def test_same_session_id_other_start_is_not_duplicate(self) -> None:
        self.service.import_file(SAMPLE_HUNT_PATH)
        other = sample_text(**{"Start": "2026-09-27 10:00:00"})
        self.assertEqual(self.service.import_text(other).status, ImportStatus.IMPORTED)

    def test_same_session_id_other_player_is_not_duplicate(self) -> None:
        self.service.import_file(SAMPLE_HUNT_PATH)
        data = load_sample()
        for section in ("Enemies Defeated", "Drops", "Supplies"):
            for entry in data[section]:
                entry["Player"] = "OtherPlayer"
        result = self.service.import_text(json.dumps(data))
        self.assertEqual(result.status, ImportStatus.IMPORTED)

    def test_force_import_duplicate(self) -> None:
        first = self.service.import_file(SAMPLE_HUNT_PATH)
        forced = self.service.import_file(SAMPLE_HUNT_PATH, allow_duplicate=True)
        self.assertEqual(forced.status, ImportStatus.IMPORTED)
        self.assertEqual(forced.duplicate_of, [first.hunt_id])
        self.assertEqual(self.service.count_hunts(), 2)

    def test_delete_cascades_to_related_rows(self) -> None:
        keep = self.service.import_file(SAMPLE_HUNT_PATH)
        remove = self.service.import_file(SAMPLE_HUNT_PATH, allow_duplicate=True)
        self.assertEqual(self._count(EnemyDefeated), 6)

        self.assertEqual(self.service.delete_hunts([remove.hunt_id]), 1)

        self.assertEqual(self.service.count_hunts(), 1)
        self.assertEqual(self._count(EnemyDefeated), 3)
        self.assertEqual(self._count(Drop), 2)
        self.assertEqual(self._count(Supply), 1)
        self.assertIsNotNone(self.service.get_hunt_details(keep.hunt_id))
        self.assertIsNone(self.service.get_hunt_details(remove.hunt_id))

    def test_list_hunts_newest_first(self) -> None:
        self.service.import_text(sample_text(**{"Start": "2026-09-01 10:00:00"}))
        self.service.import_text(sample_text(**{"Start": "2026-09-20 10:00:00"}))
        self.service.import_text(sample_text(**{"Start": None, "Session ID": 7}))
        hunts = self.service.list_hunts()
        self.assertEqual(len(hunts), 3)
        self.assertEqual(hunts[0].start_datetime.day, 20)
        self.assertEqual(hunts[0].profit, 1119522)

    def test_hunt_without_start_can_be_imported(self) -> None:
        text = sample_text(**{"Start": None})
        self.assertEqual(self.service.import_text(text).status, ImportStatus.IMPORTED)
        # Sem data não há chave de identidade, mas o conteúdo idêntico é detectado.
        self.assertEqual(self.service.import_text(text).status, ImportStatus.DUPLICATE)


class FileDatabaseTests(unittest.TestCase):
    """Verifica o fluxo com um arquivo SQLite real, reabrindo o banco."""

    def test_data_survives_reopening(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "hunts.db"
            database = Database.from_path(path)
            database.create_schema()
            HuntService(database).import_file(SAMPLE_HUNT_PATH)
            database.dispose()

            reopened = Database.from_path(path)
            reopened.create_schema()
            hunts = HuntService(reopened).list_hunts()
            reopened.dispose()

            self.assertTrue(path.exists())
            self.assertEqual(len(hunts), 1)
            self.assertEqual(hunts[0].session_id, 1080)


if __name__ == "__main__":
    unittest.main()
