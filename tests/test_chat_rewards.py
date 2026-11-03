"""Recompensas do chat ("Você recebeu: ...") somadas às sessões como drops."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from app.database.database import Database  # noqa: E402
from app.database.migrations import LATEST_VERSION  # noqa: E402
from app.database.models import ChatReward, Drop  # noqa: E402
from app.services.chat_rewards import parse_chat_rewards, resolve_item_name  # noqa: E402
from app.services.hunt_service import HuntService  # noqa: E402
from app.services.price_service import PriceService  # noqa: E402
from app.ui.hunts.chat_rewards_dialog import ITEM_COLUMN, ChatRewardsDialog  # noqa: E402
from app.ui.hunts.hunt_details import show_hunt_details  # noqa: E402
from app.ui.theme import apply_theme  # noqa: E402
from tests.helpers import FIXTURES_DIR, memory_database  # noqa: E402

SAMPLE_BOSS_PATH = FIXTURES_DIR / "sample_boss.json"
# Valores da sessão do boss de exemplo.
RAW_GAINS = PROFIT = 147900
DURATION = 454

SHARDS = ("Você recebeu: 1 Azure Shard, 1 Cerise Shard, 1 Scarlet Shard, 1 Kermes Shard, "
          "9 Technological Crystal (Tier: 7), 10 Technological Crystal (Tier: 8), "
          "1 Dark-Type TM (Shiny Honchkrow), 150 Rough Gemstone, 62 Star dust, "
          "208 Echo Shard.")
BAG = "Você recebeu: 15 Echo Shards, 2 Mystic Stars, 84 hundred dollars, 4 Heart Stones."
EMERALD = ("Você recebeu: 1 10.000 carat emerald, 1 Venom Stone, "
           "3 Shiny Tentacruel tentacles, 2 Water Stones, 1 giant fang.")


class ParseChatRewardsTests(unittest.TestCase):
    def test_parses_counts_and_names(self) -> None:
        parsed = parse_chat_rewards(SHARDS)
        self.assertEqual(len(parsed.messages), 1)
        self.assertEqual(len(parsed.items), 10)
        self.assertEqual((parsed.items[4].count, parsed.items[4].name),
                         (9, "Technological Crystal (Tier: 7)"))
        self.assertEqual(parsed.items[6].name, "Dark-Type TM (Shiny Honchkrow)")
        self.assertEqual((parsed.items[-1].count, parsed.items[-1].name), (208, "Echo Shard"))
        self.assertEqual(parsed.invalid, [])

    def test_number_inside_the_name_is_not_the_count(self) -> None:
        first = parse_chat_rewards(EMERALD).items[0]
        self.assertEqual((first.count, first.name), (1, "10.000 carat emerald"))
        self.assertEqual(parse_chat_rewards("Você recebeu: 1.380 tech data").items[0].count, 1380)

    def test_several_messages_among_other_chat_lines(self) -> None:
        text = (f"12:01 {BAG}\n"
                "12:02 Fulano: boa!\n"
                "You received: 2 Water Stones, alguma coisa\n")
        parsed = parse_chat_rewards(text)
        self.assertEqual(len(parsed.messages), 2)
        self.assertEqual([item.name for item in parsed.items][-1], "Water Stones")
        self.assertEqual(parsed.invalid, ["alguma coisa"])

    def test_text_without_message(self) -> None:
        parsed = parse_chat_rewards("15 Echo Shards, 2 Mystic Stars")
        self.assertEqual((parsed.messages, parsed.items), ([], []))


class ResolveItemNameTests(unittest.TestCase):
    KNOWN = {"echo shard": "Echo Shard", "one hundred dollars": "one hundred dollars",
             "water stone": "Water Stone", "chopped lum berry": "chopped Lum berry"}

    def resolve(self, name: str, count: int = 2) -> tuple[str, bool]:
        return resolve_item_name(name, count, self.KNOWN)

    def test_known_names_ignore_case_and_plural(self) -> None:
        self.assertEqual(self.resolve("echo shard"), ("Echo Shard", True))
        self.assertEqual(self.resolve("Echo Shards"), ("Echo Shard", True))
        self.assertEqual(self.resolve("Water Stones"), ("Water Stone", True))
        self.assertEqual(self.resolve("chopped Lum berries"), ("chopped Lum berry", True))

    def test_alias(self) -> None:
        self.assertEqual(self.resolve("hundred dollars", 84), ("one hundred dollars", True))
        self.assertEqual(resolve_item_name("hundred dollars", 84, {}),
                         ("one hundred dollars", False))

    def test_unknown_plural_goes_to_singular(self) -> None:
        self.assertEqual(self.resolve("big poison bottles", 403), ("big poison bottle", False))
        self.assertEqual(self.resolve("Shiny Tentacruel tentacles", 3),
                         ("Shiny Tentacruel tentacle", False))
        self.assertEqual(self.resolve("boxes"), ("box", False))
        self.assertEqual(self.resolve("Technological Crystals (Tier: 7)", 9),
                         ("Technological Crystal (Tier: 7)", False))

    def test_unknown_names_kept(self) -> None:
        self.assertEqual(self.resolve("giant fang", 1), ("giant fang", False))
        self.assertEqual(self.resolve("tech data", 1380), ("tech data", False))
        self.assertEqual(self.resolve("Heart Stones", 1), ("Heart Stones", False))


class ChatRewardServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = memory_database()
        self.service = HuntService(self.database)
        self.prices = PriceService(self.database)
        self.hunt_id = self.service.import_file(SAMPLE_BOSS_PATH).hunt_id

    def tearDown(self) -> None:
        self.database.dispose()

    def hunt(self):
        return self.service.get_hunt_details(self.hunt_id)

    def chat_drops(self) -> dict[str, Drop]:
        return {drop.item: drop for drop in self.hunt().drops if drop.from_chat}

    def test_preview_resolves_names_and_prices(self) -> None:
        preview = self.service.preview_chat_rewards(self.hunt_id, BAG)
        lines = {line.item: line for line in preview.lines}
        self.assertEqual(set(lines), {"Echo Shard", "Mystic Star", "one hundred dollars",
                                      "Heart Stone"})
        self.assertEqual((lines["Mystic Star"].unit_price, lines["Mystic Star"].total_price),
                         (50000, 100000))
        self.assertEqual(lines["one hundred dollars"].chat_name, "hundred dollars")
        self.assertIsNone(lines["Heart Stone"].unit_price)
        self.assertFalse(lines["Heart Stone"].known)
        self.assertEqual(preview.repeated, [])

    def test_same_item_in_two_messages_is_summed(self) -> None:
        preview = self.service.preview_chat_rewards(self.hunt_id, f"{SHARDS}\n{BAG}")
        [echo] = [line for line in preview.lines if line.item == "Echo Shard"]
        self.assertEqual(echo.count, 208 + 15)

    def test_add_creates_drops_and_raises_totals(self) -> None:
        original = self.hunt()
        self.assertEqual(self.service.add_chat_rewards(self.hunt_id, BAG), 4)

        hunt = self.hunt()
        drops = self.chat_drops()
        self.assertEqual(drops["Mystic Star"].count, 2)
        self.assertEqual(drops["one hundred dollars"].total_price, 8400)
        self.assertEqual(drops["Mystic Star"].original_unit_price, 50000)
        self.assertIsNone(drops["Heart Stone"].total_price)
        self.assertEqual(drops["Mystic Star"].player, "Rakanoth")
        self.assertEqual(len(hunt.drops), 5 + 4)
        self.assertEqual(hunt.raw_gains, RAW_GAINS + 108400)
        self.assertEqual(hunt.profit, PROFIT + 108400)
        self.assertAlmostEqual(hunt.profit_per_hour,
                               original.profit_per_hour + 108400 * 3600 / DURATION)
        self.assertEqual(hunt.supplies, original.supplies)
        # O JSON original fica intacto.
        self.assertEqual((hunt.raw_json, hunt.content_hash),
                         (original.raw_json, original.content_hash))
        [reward] = hunt.chat_rewards
        self.assertEqual(reward.messages, [BAG.rstrip(".")])

    def test_remove_restores_the_session(self) -> None:
        original = self.hunt()
        self.service.add_chat_rewards(self.hunt_id, f"{BAG}\n{EMERALD}")
        self.assertEqual(self.service.remove_chat_rewards(self.hunt_id), 4 + 5)

        hunt = self.hunt()
        self.assertEqual(len(hunt.drops), 5)
        self.assertEqual(hunt.chat_rewards, [])
        self.assertEqual((hunt.raw_gains, hunt.profit), (RAW_GAINS, PROFIT))
        self.assertAlmostEqual(hunt.profit_per_hour, original.profit_per_hour)
        self.assertEqual(self.service.remove_chat_rewards(self.hunt_id), 0)

    def test_custom_prices_apply_to_chat_drops(self) -> None:
        self.prices.set_price("Heart Stone", 1000)
        self.service.add_chat_rewards(self.hunt_id, BAG)
        heart = self.chat_drops()["Heart Stone"]
        self.assertEqual((heart.unit_price, heart.total_price), (1000, 4000))
        self.assertIsNone(heart.original_unit_price)
        self.assertEqual(self.hunt().profit, PROFIT + 108400 + 4000)

        self.prices.clear_price("Heart Stone")
        self.assertIsNone(self.chat_drops()["Heart Stone"].total_price)
        self.assertEqual(self.hunt().profit, PROFIT + 108400)

        self.prices.set_price("Mystic Star", 60000)  # depois de adicionar
        self.assertEqual(self.chat_drops()["Mystic Star"].total_price, 120000)
        self.assertEqual(self.hunt().profit, PROFIT + 2 * 10000 + 108400 + 2 * 10000)

    def test_uses_the_latest_analyzer_price(self) -> None:
        data = json.loads(SAMPLE_BOSS_PATH.read_text(encoding="utf-8"))
        data["Session"].update({"Session ID": 999, "Start": "2026-10-10 10:00:00"})
        data["Drops"][0]["Unit price"] = 55000  # Mystic Star
        self.service.import_text(json.dumps(data))
        [line] = self.service.preview_chat_rewards(None, "Você recebeu: 1 Mystic Star").lines
        self.assertEqual(line.unit_price, 55000)

    def test_edited_names_are_used(self) -> None:
        lines = self.service.preview_chat_rewards(self.hunt_id, BAG).lines
        edited = [self.service.quote_reward_item(line.chat_name, "Mystic Star", line.count)
                  if line.item == "Heart Stone" else line for line in lines]
        self.assertEqual(self.service.add_chat_rewards(self.hunt_id, BAG, edited), 3)
        self.assertEqual(self.chat_drops()["Mystic Star"].count, 2 + 4)

    def test_repeated_message_is_reported(self) -> None:
        self.service.add_chat_rewards(self.hunt_id, BAG)
        preview = self.service.preview_chat_rewards(self.hunt_id, f"{BAG}  \n{EMERALD}")
        self.assertEqual(preview.repeated, [BAG.rstrip(".")])

    def test_text_without_items_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.add_chat_rewards(self.hunt_id, "nada aqui")
        self.assertEqual(self.chat_drops(), {})

    def test_deleting_the_session_removes_its_chat_rewards(self) -> None:
        self.service.add_chat_rewards(self.hunt_id, BAG)
        self.service.delete_hunts([self.hunt_id])
        with self.database.session() as session:
            self.assertEqual(session.scalar(select(func.count(ChatReward.id))), 0)
            self.assertEqual(session.scalar(select(func.count(Drop.id))), 0)


class ChatRewardMigrationTests(unittest.TestCase):
    def test_version4_database_gets_chat_rewards(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "hunts.db"
            old = Database.from_path(path)
            old.create_schema()
            with old.engine.begin() as connection:
                # Tabelas como a versão 4 criava: drops sem chat_reward_id.
                connection.execute(text("DROP TABLE drops"))
                connection.execute(text("DROP TABLE chat_rewards"))
                connection.execute(text(
                    "CREATE TABLE drops (id INTEGER PRIMARY KEY, "
                    "hunt_id INTEGER NOT NULL REFERENCES hunt_sessions (id) ON DELETE CASCADE, "
                    "item VARCHAR(200) NOT NULL, count INTEGER NOT NULL, unit_price FLOAT, "
                    "total_price INTEGER, original_unit_price FLOAT, "
                    "original_total_price INTEGER, player VARCHAR(200), ignored BOOLEAN)"))
                connection.execute(text("PRAGMA user_version = 4"))
            old.dispose()

            database = Database.from_path(path)
            try:
                self.assertEqual([m.version for m in database.create_schema()],
                                 list(range(5, LATEST_VERSION + 1)))
                service = HuntService(database)
                hunt_id = service.import_file(SAMPLE_BOSS_PATH).hunt_id
                self.assertEqual(service.add_chat_rewards(hunt_id, BAG), 4)
                self.assertEqual(service.get_hunt_details(hunt_id).raw_gains,
                                 RAW_GAINS + 108400)
            finally:
                database.dispose()


class ChatRewardsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.database = memory_database()
        self.service = HuntService(self.database)
        self.hunt_id = self.service.import_file(SAMPLE_BOSS_PATH).hunt_id

    def tearDown(self) -> None:
        self.database.dispose()

    def test_dialog_preview_and_name_editing(self) -> None:
        dialog = ChatRewardsDialog(self.service, self.hunt_id)
        self.assertFalse(dialog.add_button.isEnabled())
        dialog.set_text(BAG)
        self.assertTrue(dialog.add_button.isEnabled())
        self.assertEqual(dialog.table.rowCount(), 4)
        row = [line.item for line in dialog.lines()].index("Heart Stone")
        self.assertIn("sem preço", dialog.status.text())

        dialog.set_item_name(row, "  Water   Stone ")
        line = dialog.lines()[row]
        self.assertEqual((line.item, line.unit_price, line.known), ("Water Stone", 5000, True))
        self.assertEqual(dialog.table.item(row, ITEM_COLUMN).text(), "Water Stone")
        self.assertNotIn("sem preço", dialog.status.text())

        dialog.set_text("texto qualquer")
        self.assertFalse(dialog.add_button.isEnabled())
        dialog.close()

    def test_details_dialog_adds_and_removes(self) -> None:
        details = show_hunt_details(self.service, self.hunt_id, None)
        changed: list[int] = []
        details.hunt_changed.connect(changed.append)
        self.assertFalse(details.remove_chat_button.isEnabled())

        chat_dialog = details.open_chat_rewards_dialog()
        chat_dialog.set_text(BAG)
        chat_dialog.accept()
        self.assertEqual(changed, [self.hunt_id])
        self.assertEqual(details.tabs.tabText(2), "Drops (9)")
        self.assertEqual(details.tabs.currentIndex(), 2)
        self.assertEqual(details.hunt.profit, PROFIT + 108400)
        self.assertTrue(details.remove_chat_button.isEnabled())

        with mock.patch.object(QMessageBox, "question",
                               return_value=QMessageBox.StandardButton.Yes):
            self.assertEqual(details.remove_chat_rewards(), 4)
        self.assertEqual(details.tabs.tabText(2), "Drops (5)")
        self.assertEqual(details.hunt.profit, PROFIT)
        self.assertFalse(details.remove_chat_button.isEnabled())
        details.close()


if __name__ == "__main__":
    unittest.main()
