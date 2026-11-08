//! Porta de `tests/test_chat_rewards.py` (sem os testes das telas, que vêm na fase 4).

mod common;

use std::collections::HashMap;

use common::fixture;
use pxg_core::Database;
use pxg_core::db::migrations::LATEST_VERSION;
use pxg_core::hunts::chat_rewards::{parse_chat_rewards, resolve_item_name};
use pxg_core::hunts::model::{HuntDetails, ItemRow};
use pxg_core::hunts::service::HuntService;
use pxg_core::prices::PriceService;
use serde_json::{Value, json};

// Valores da sessão do boss de exemplo.
const RAW_GAINS: i64 = 147900;
const PROFIT: i64 = 147900;
const DURATION: f64 = 454.0;

const SHARDS: &str = "Você recebeu: 1 Azure Shard, 1 Cerise Shard, 1 Scarlet Shard, 1 Kermes Shard, \
    9 Technological Crystal (Tier: 7), 10 Technological Crystal (Tier: 8), \
    1 Dark-Type TM (Shiny Honchkrow), 150 Rough Gemstone, 62 Star dust, 208 Echo Shard.";
const BAG: &str = "Você recebeu: 15 Echo Shards, 2 Mystic Stars, 84 hundred dollars, 4 Heart Stones.";
const EMERALD: &str = "Você recebeu: 1 10.000 carat emerald, 1 Venom Stone, \
    3 Shiny Tentacruel tentacles, 2 Water Stones, 1 giant fang.";

fn bag_message() -> String {
    BAG.trim_end_matches('.').to_owned()
}

// ----------------------------------------------------------------- leitura

#[test]
fn parses_counts_and_names() {
    let parsed = parse_chat_rewards(SHARDS);
    assert_eq!(parsed.messages.len(), 1);
    assert_eq!(parsed.items.len(), 10);
    assert_eq!((parsed.items[4].count, parsed.items[4].name.as_str()), (9, "Technological Crystal (Tier: 7)"));
    assert_eq!(parsed.items[6].name, "Dark-Type TM (Shiny Honchkrow)");
    let last = parsed.items.last().unwrap();
    assert_eq!((last.count, last.name.as_str()), (208, "Echo Shard"));
    assert!(parsed.invalid.is_empty());
}

#[test]
fn number_inside_the_name_is_not_the_count() {
    let first = parse_chat_rewards(EMERALD).items.remove(0);
    assert_eq!((first.count, first.name.as_str()), (1, "10.000 carat emerald"));
    assert_eq!(parse_chat_rewards("Você recebeu: 1.380 tech data").items[0].count, 1380);
}

#[test]
fn several_messages_among_other_chat_lines() {
    let text = format!("12:01 {BAG}\n12:02 Fulano: boa!\nYou received: 2 Water Stones, alguma coisa\n");
    let parsed = parse_chat_rewards(&text);
    assert_eq!(parsed.messages.len(), 2);
    assert_eq!(parsed.items.last().unwrap().name, "Water Stones");
    assert_eq!(parsed.invalid, ["alguma coisa"]);
}

#[test]
fn text_without_message() {
    let parsed = parse_chat_rewards("15 Echo Shards, 2 Mystic Stars");
    assert!(parsed.messages.is_empty() && parsed.items.is_empty());
}

fn known() -> HashMap<String, String> {
    [("echo shard", "Echo Shard"), ("one hundred dollars", "one hundred dollars"),
        ("water stone", "Water Stone"), ("chopped lum berry", "chopped Lum berry")]
        .into_iter()
        .map(|(k, v)| (k.to_owned(), v.to_owned()))
        .collect()
}

fn resolve(name: &str, count: i64) -> (String, bool) {
    resolve_item_name(name, count, &known())
}

fn pair(name: &str, known: bool) -> (String, bool) {
    (name.to_owned(), known)
}

#[test]
fn known_names_ignore_case_and_plural() {
    assert_eq!(resolve("echo shard", 2), pair("Echo Shard", true));
    assert_eq!(resolve("Echo Shards", 2), pair("Echo Shard", true));
    assert_eq!(resolve("Water Stones", 2), pair("Water Stone", true));
    assert_eq!(resolve("chopped Lum berries", 2), pair("chopped Lum berry", true));
}

#[test]
fn alias() {
    assert_eq!(resolve("hundred dollars", 84), pair("one hundred dollars", true));
    assert_eq!(resolve_item_name("hundred dollars", 84, &HashMap::new()), pair("one hundred dollars", false));
}

#[test]
fn unknown_plural_goes_to_singular() {
    assert_eq!(resolve("big poison bottles", 403), pair("big poison bottle", false));
    assert_eq!(resolve("Shiny Tentacruel tentacles", 3), pair("Shiny Tentacruel tentacle", false));
    assert_eq!(resolve("boxes", 2), pair("box", false));
    assert_eq!(resolve("Technological Crystals (Tier: 7)", 9), pair("Technological Crystal (Tier: 7)", false));
}

#[test]
fn unknown_names_kept() {
    assert_eq!(resolve("giant fang", 1), pair("giant fang", false));
    assert_eq!(resolve("tech data", 1380), pair("tech data", false));
    assert_eq!(resolve("Heart Stones", 1), pair("Heart Stones", false));
}

// ----------------------------------------------------------------- serviço

struct Fixture {
    database: Database,
    hunt_id: i64,
}

impl Fixture {
    fn new() -> Self {
        let database = Database::in_memory().unwrap();
        let hunt_id = HuntService::new(&database)
            .import_file(&fixture("sample_boss.json"), false, None)
            .unwrap()
            .hunt_id
            .unwrap();
        Self { database, hunt_id }
    }

    fn service(&self) -> HuntService<'_> {
        HuntService::new(&self.database)
    }

    fn hunt(&self) -> HuntDetails {
        self.service().get_hunt_details(self.hunt_id).unwrap().unwrap()
    }

    fn chat_drops(&self) -> HashMap<String, ItemRow> {
        self.hunt().drops.into_iter().filter(ItemRow::from_chat).map(|d| (d.item.clone(), d)).collect()
    }

    fn add(&self, text: &str) -> usize {
        self.service().add_chat_rewards(self.hunt_id, text, None).unwrap()
    }
}

fn close(actual: f64, expected: f64) {
    assert!((actual - expected).abs() < 1e-6, "{actual} ≠ {expected}");
}

#[test]
fn preview_resolves_names_and_prices() {
    let f = Fixture::new();
    let preview = f.service().preview_chat_rewards(Some(f.hunt_id), BAG).unwrap();
    let lines: HashMap<String, _> = preview.lines.iter().map(|l| (l.item.clone(), l.clone())).collect();
    let mut names: Vec<&str> = lines.keys().map(String::as_str).collect();
    names.sort();
    assert_eq!(names, ["Echo Shard", "Heart Stone", "Mystic Star", "one hundred dollars"]);
    let star = &lines["Mystic Star"];
    assert_eq!((star.unit_price, star.total_price()), (Some(50000.), Some(100000)));
    assert_eq!(lines["one hundred dollars"].chat_name, "hundred dollars");
    assert_eq!(lines["Heart Stone"].unit_price, None);
    assert!(!lines["Heart Stone"].known);
    assert!(preview.repeated.is_empty());
}

#[test]
fn same_item_in_two_messages_is_summed() {
    let f = Fixture::new();
    let preview = f.service().preview_chat_rewards(Some(f.hunt_id), &format!("{SHARDS}\n{BAG}")).unwrap();
    let echo: Vec<_> = preview.lines.iter().filter(|l| l.item == "Echo Shard").collect();
    assert_eq!(echo.len(), 1);
    assert_eq!(echo[0].count, 208 + 15);
}

#[test]
fn add_creates_drops_and_raises_totals() {
    let f = Fixture::new();
    let original = f.hunt();
    assert_eq!(f.add(BAG), 4);
    let hunt = f.hunt();
    let drops = f.chat_drops();
    assert_eq!(drops["Mystic Star"].count, 2);
    assert_eq!(drops["one hundred dollars"].total_price, Some(8400));
    assert_eq!(drops["Mystic Star"].original_unit_price, Some(50000.));
    assert_eq!(drops["Heart Stone"].total_price, None);
    assert_eq!(drops["Mystic Star"].player.as_deref(), Some("Rakanoth"));
    assert_eq!(hunt.drops.len(), 5 + 4);
    assert_eq!(hunt.session.raw_gains, Some(RAW_GAINS + 108400));
    assert_eq!(hunt.session.profit, Some(PROFIT + 108400));
    close(hunt.session.profit_per_hour.unwrap(), original.session.profit_per_hour.unwrap() + 108400. * 3600. / DURATION);
    assert_eq!(hunt.session.supplies, original.session.supplies);
    // O JSON original fica intacto.
    assert_eq!((&hunt.raw_json, &hunt.content_hash), (&original.raw_json, &original.content_hash));
    assert_eq!(hunt.chat_rewards.len(), 1);
    assert_eq!(hunt.chat_rewards[0].messages(), [bag_message()]);
}

#[test]
fn remove_restores_the_session() {
    let f = Fixture::new();
    let original = f.hunt();
    f.add(&format!("{BAG}\n{EMERALD}"));
    assert_eq!(f.service().remove_chat_rewards(f.hunt_id).unwrap(), 4 + 5);
    let hunt = f.hunt();
    assert_eq!(hunt.drops.len(), 5);
    assert!(hunt.chat_rewards.is_empty());
    assert_eq!((hunt.session.raw_gains, hunt.session.profit), (Some(RAW_GAINS), Some(PROFIT)));
    close(hunt.session.profit_per_hour.unwrap(), original.session.profit_per_hour.unwrap());
    assert_eq!(f.service().remove_chat_rewards(f.hunt_id).unwrap(), 0);
}

#[test]
fn custom_prices_apply_to_chat_drops() {
    let f = Fixture::new();
    let prices = PriceService::new(&f.database);
    prices.set_price("Heart Stone", 1000.).unwrap();
    f.add(BAG);
    let heart = f.chat_drops()["Heart Stone"].clone();
    assert_eq!((heart.unit_price, heart.total_price), (Some(1000.), Some(4000)));
    assert_eq!(heart.original_unit_price, None);
    assert_eq!(f.hunt().session.profit, Some(PROFIT + 108400 + 4000));

    prices.clear_price("Heart Stone").unwrap();
    assert_eq!(f.chat_drops()["Heart Stone"].total_price, None);
    assert_eq!(f.hunt().session.profit, Some(PROFIT + 108400));

    prices.set_price("Mystic Star", 60000.).unwrap(); // depois de adicionar
    assert_eq!(f.chat_drops()["Mystic Star"].total_price, Some(120000));
    assert_eq!(f.hunt().session.profit, Some(PROFIT + 2 * 10000 + 108400 + 2 * 10000));
}

#[test]
fn uses_the_latest_analyzer_price() {
    let f = Fixture::new();
    let mut data: Value = serde_json::from_str(&std::fs::read_to_string(fixture("sample_boss.json")).unwrap()).unwrap();
    data["Session"]["Session ID"] = json!(999);
    data["Session"]["Start"] = json!("2026-10-10 10:00:00");
    data["Drops"][0]["Unit price"] = json!(55000); // Mystic Star
    f.service().import_text(&data.to_string(), "", false, None).unwrap();
    let lines = f.service().preview_chat_rewards(None, "Você recebeu: 1 Mystic Star").unwrap().lines;
    assert_eq!(lines.len(), 1);
    assert_eq!(lines[0].unit_price, Some(55000.));
}

#[test]
fn edited_names_are_used() {
    let f = Fixture::new();
    let lines = f.service().preview_chat_rewards(Some(f.hunt_id), BAG).unwrap().lines;
    let edited: Vec<_> = lines
        .into_iter()
        .map(|line| {
            if line.item == "Heart Stone" {
                f.service().quote_reward_item(&line.chat_name, "Mystic Star", line.count).unwrap()
            } else {
                line
            }
        })
        .collect();
    assert_eq!(f.service().add_chat_rewards(f.hunt_id, BAG, Some(&edited)).unwrap(), 3);
    assert_eq!(f.chat_drops()["Mystic Star"].count, 2 + 4);
}

#[test]
fn repeated_message_is_reported() {
    let f = Fixture::new();
    f.add(BAG);
    let preview = f.service().preview_chat_rewards(Some(f.hunt_id), &format!("{BAG}  \n{EMERALD}")).unwrap();
    assert_eq!(preview.repeated, [bag_message()]);
}

#[test]
fn text_without_items_is_rejected() {
    let f = Fixture::new();
    assert!(f.service().add_chat_rewards(f.hunt_id, "nada aqui", None).is_err());
    assert!(f.chat_drops().is_empty());
}

#[test]
fn deleting_the_session_removes_its_chat_rewards() {
    let f = Fixture::new();
    f.add(BAG);
    f.service().delete_hunts(&[f.hunt_id]).unwrap();
    for table in ["chat_rewards", "drops"] {
        let count: i64 = f.database.with(|c| Ok(c.query_row(&format!("SELECT count(*) FROM {table}"), [], |r| r.get(0))?)).unwrap();
        assert_eq!(count, 0, "{table}");
    }
}

#[test]
fn version4_database_gets_chat_rewards() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("hunts.db");
    {
        let old = Database::open(&path).unwrap();
        old.create_schema().unwrap();
        old.with(|c| {
            // Tabelas como a versão 4 criava: drops sem chat_reward_id.
            c.execute_batch(
                "DROP TABLE drops; DROP TABLE chat_rewards;
                 CREATE TABLE drops (id INTEGER PRIMARY KEY,
                     hunt_id INTEGER NOT NULL REFERENCES hunt_sessions (id) ON DELETE CASCADE,
                     item VARCHAR(200) NOT NULL, count INTEGER NOT NULL, unit_price FLOAT,
                     total_price INTEGER, original_unit_price FLOAT, original_total_price INTEGER,
                     player VARCHAR(200), ignored BOOLEAN);
                 PRAGMA user_version = 4;",
            )?;
            Ok(())
        })
        .unwrap();
    }
    let database = Database::open(&path).unwrap();
    let applied: Vec<i64> = database.create_schema().unwrap().iter().map(|m| m.version).collect();
    assert_eq!(applied, (5..=LATEST_VERSION).collect::<Vec<_>>());
    let service = HuntService::new(&database);
    let hunt_id = service.import_file(&fixture("sample_boss.json"), false, None).unwrap().hunt_id.unwrap();
    assert_eq!(service.add_chat_rewards(hunt_id, BAG, None).unwrap(), 4);
    assert_eq!(service.get_hunt_details(hunt_id).unwrap().unwrap().session.raw_gains, Some(RAW_GAINS + 108400));
}
