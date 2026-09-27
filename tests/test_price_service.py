import json
import unittest

from app.services.hunt_service import HuntService
from app.services.price_service import PriceService
from tests.helpers import FIXTURES_DIR, load_sample, memory_database, sample_text

SAMPLE_TSV_PATH = FIXTURES_DIR / "sample_hunt.tsv"

# Valores da sessão do TSV de exemplo (duração: 7156 s).
RAW_GAINS, SUPPLIES, PROFIT = 2790798, 419294, 2371504
DURATION = 7156


class PriceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = memory_database()
        self.hunts = HuntService(self.database)
        self.prices = PriceService(self.database)
        self.hunt_id = self.hunts.import_file(SAMPLE_TSV_PATH).hunt_id

    def tearDown(self) -> None:
        self.database.dispose()

    def hunt(self, hunt_id: int | None = None):
        return self.hunts.get_hunt_details(hunt_id or self.hunt_id)

    def entry(self, entries, name):
        return next(entry for entry in entries if entry.item == name)

    def test_import_keeps_analyzer_prices(self) -> None:
        gem = self.entry(self.hunt().drops, "nightmare gem")
        self.assertEqual((gem.unit_price, gem.total_price), (216, 35424))
        self.assertEqual((gem.original_unit_price, gem.original_total_price), (216, 35424))

    def test_drop_price_updates_raw_gains_and_profit(self) -> None:
        affected = self.prices.set_price("Nightmare Gem", 300)  # sem diferenciar maiúsculas
        self.assertEqual(affected, 1)
        hunt = self.hunt()
        gem = self.entry(hunt.drops, "nightmare gem")
        self.assertEqual((gem.unit_price, gem.total_price), (300, 164 * 300))
        self.assertEqual(gem.original_unit_price, 216)
        delta = 164 * (300 - 216)
        self.assertEqual(hunt.raw_gains, RAW_GAINS + delta)
        self.assertEqual(hunt.supplies, SUPPLIES)
        self.assertEqual(hunt.profit, PROFIT + delta)
        self.assertAlmostEqual(hunt.profit_per_hour, 1193042 + delta * 3600 / DURATION)
        self.assertEqual(hunt.raw_gains, sum(drop.total_price for drop in hunt.drops))

    def test_supply_price_updates_supplies_and_profit(self) -> None:
        self.prices.set_price("Healing Elixir", 10000)
        hunt = self.hunt()
        self.assertEqual(hunt.supplies, SUPPLIES + 60000)
        self.assertEqual(hunt.raw_gains, RAW_GAINS)
        self.assertEqual(hunt.profit, PROFIT - 60000)
        self.assertEqual(hunt.supplies, sum(s.total_price for s in hunt.supplies_used))

    def test_changing_twice_and_clearing_restores_analyzer_values(self) -> None:
        self.prices.set_price("turtle spike", 9000)
        self.prices.set_price("turtle spike", 7000)
        self.assertEqual(self.hunt().raw_gains, RAW_GAINS + 183 * (7000 - 8000))
        self.assertEqual(self.prices.clear_price("TURTLE SPIKE"), 1)
        hunt = self.hunt()
        self.assertEqual((hunt.raw_gains, hunt.supplies, hunt.profit),
                         (RAW_GAINS, SUPPLIES, PROFIT))
        self.assertAlmostEqual(hunt.profit_per_hour, 1193042)
        self.assertEqual(self.prices.custom_prices(), {})
        self.assertEqual(self.prices.clear_price("turtle spike"), 0)

    def test_price_applies_to_future_imports(self) -> None:
        self.prices.set_price("metal scraps", 2500)
        result = self.hunts.import_text(sample_text(), source="sample.json")
        hunt = self.hunt(result.hunt_id)
        scraps = self.entry(hunt.drops, "metal scraps")
        self.assertEqual((scraps.unit_price, scraps.original_unit_price), (2500, 2000))
        self.assertEqual(hunt.raw_gains, 1235972 + 194 * 500)
        self.assertEqual(hunt.profit, 1119522 + 194 * 500)

    def test_ignored_entries_do_not_change_totals(self) -> None:
        data = load_sample()
        for drop in data["Drops"]:
            drop["Ignored"] = drop["Item"] == "metal scraps"
        hunt_id = self.hunts.import_text(json.dumps(data), source="ignored.json").hunt_id
        self.prices.set_price("metal scraps", 5000)
        hunt = self.hunt(hunt_id)
        self.assertEqual(self.entry(hunt.drops, "metal scraps").total_price, 194 * 5000)
        self.assertEqual(hunt.raw_gains, 1235972)

    def test_list_items(self) -> None:
        self.prices.set_price("Healing Elixir", 10000)
        self.prices.set_price("Item Futuro", 50)
        items = {item.name: item for item in self.prices.list_items()}
        elixir = items["Healing Elixir"]
        self.assertEqual((elixir.sources, elixir.analyzer_price, elixir.custom_price),
                         ("Supply", 0, 10000))
        self.assertEqual((elixir.quantity, elixir.hunt_count), (6, 1))
        self.assertEqual(items["turtle spike"].sources, "Drop")
        self.assertIsNone(items["turtle spike"].custom_price)
        future = items["Item Futuro"]
        self.assertEqual((future.sources, future.hunt_count, future.custom_price),
                         ("—", 0, 50))

    def test_invalid_prices_are_refused(self) -> None:
        for name, price in (("gem", -1), ("gem", float("nan")), ("  ", 10)):
            with self.assertRaises(ValueError):
                self.prices.set_price(name, price)
        self.assertEqual(self.prices.custom_prices(), {})


if __name__ == "__main__":
    unittest.main()
