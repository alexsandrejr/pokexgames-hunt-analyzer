//! Porta de `tests/test_price_service.py` e `tests/test_paste_import.py`.

mod common;

use std::collections::HashMap;
use std::path::PathBuf;

use chrono::NaiveDate;
use common::{fixture, load_sample, sample_hunt_path, sample_text};
use pxg_core::Database;
use pxg_core::hunts::analyzer::ParsedSession;
use pxg_core::hunts::files::{suggested_filename, write_new_json_file};
use pxg_core::hunts::model::{HuntDetails, ImportStatus, ItemRow};
use pxg_core::hunts::service::HuntService;
use pxg_core::prices::PriceService;
use serde_json::{Value, json};

// Valores da sessão do TSV de exemplo (duração: 7156 s).
const RAW_GAINS: i64 = 2790798;
const SUPPLIES: i64 = 419294;
const PROFIT: i64 = 2371504;
const DURATION: f64 = 7156.0;

struct Prices {
    database: Database,
    hunt_id: i64,
}

impl Prices {
    fn new() -> Self {
        let database = Database::in_memory().unwrap();
        let hunt_id = HuntService::new(&database)
            .import_file(&fixture("sample_hunt.tsv"), false, None)
            .unwrap()
            .hunt_id
            .unwrap();
        Self { database, hunt_id }
    }

    fn hunts(&self) -> HuntService<'_> {
        HuntService::new(&self.database)
    }

    fn prices(&self) -> PriceService<'_> {
        PriceService::new(&self.database)
    }

    fn hunt(&self, hunt_id: Option<i64>) -> HuntDetails {
        self.hunts().get_hunt_details(hunt_id.unwrap_or(self.hunt_id)).unwrap().unwrap()
    }
}

fn entry<'a>(entries: &'a [ItemRow], name: &str) -> &'a ItemRow {
    entries.iter().find(|e| e.item == name).unwrap()
}

fn close(actual: f64, expected: f64) {
    assert!((actual - expected).abs() < 1e-6, "{actual} ≠ {expected}");
}

#[test]
fn import_keeps_analyzer_prices() {
    let p = Prices::new();
    let gem = entry(&p.hunt(None).drops, "nightmare gem").clone();
    assert_eq!((gem.unit_price, gem.total_price), (Some(216.), Some(35424)));
    assert_eq!((gem.original_unit_price, gem.original_total_price), (Some(216.), Some(35424)));
}

#[test]
fn drop_price_updates_raw_gains_and_profit() {
    let p = Prices::new();
    assert_eq!(p.prices().set_price("Nightmare Gem", 300.).unwrap(), 1); // sem diferenciar maiúsculas
    let hunt = p.hunt(None);
    let gem = entry(&hunt.drops, "nightmare gem");
    assert_eq!((gem.unit_price, gem.total_price), (Some(300.), Some(164 * 300)));
    assert_eq!(gem.original_unit_price, Some(216.));
    let delta = 164 * (300 - 216);
    assert_eq!(hunt.session.raw_gains, Some(RAW_GAINS + delta));
    assert_eq!(hunt.session.supplies, Some(SUPPLIES));
    assert_eq!(hunt.session.profit, Some(PROFIT + delta));
    close(hunt.session.profit_per_hour.unwrap(), 1193042. + delta as f64 * 3600. / DURATION);
    assert_eq!(hunt.session.raw_gains, Some(hunt.drops.iter().map(|d| d.total_price.unwrap()).sum()));
}

#[test]
fn supply_price_updates_supplies_and_profit() {
    let p = Prices::new();
    p.prices().set_price("Healing Elixir", 10000.).unwrap();
    let hunt = p.hunt(None);
    assert_eq!(hunt.session.supplies, Some(SUPPLIES + 60000));
    assert_eq!(hunt.session.raw_gains, Some(RAW_GAINS));
    assert_eq!(hunt.session.profit, Some(PROFIT - 60000));
    assert_eq!(hunt.session.supplies, Some(hunt.supplies.iter().map(|s| s.total_price.unwrap()).sum()));
}

#[test]
fn changing_twice_and_clearing_restores_analyzer_values() {
    let p = Prices::new();
    p.prices().set_price("turtle spike", 9000.).unwrap();
    p.prices().set_price("turtle spike", 7000.).unwrap();
    assert_eq!(p.hunt(None).session.raw_gains, Some(RAW_GAINS + 183 * (7000 - 8000)));
    assert_eq!(p.prices().clear_price("TURTLE SPIKE").unwrap(), 1);
    let s = p.hunt(None).session;
    assert_eq!((s.raw_gains, s.supplies, s.profit), (Some(RAW_GAINS), Some(SUPPLIES), Some(PROFIT)));
    close(s.profit_per_hour.unwrap(), 1193042.);
    assert_eq!(p.prices().custom_prices().unwrap(), HashMap::new());
    assert_eq!(p.prices().clear_price("turtle spike").unwrap(), 0);
}

#[test]
fn price_applies_to_future_imports() {
    let p = Prices::new();
    p.prices().set_price("metal scraps", 2500.).unwrap();
    let id = p.hunts().import_text(&sample_text(&[]), "sample.json", false, None).unwrap().hunt_id;
    let hunt = p.hunt(id);
    let scraps = entry(&hunt.drops, "metal scraps");
    assert_eq!((scraps.unit_price, scraps.original_unit_price), (Some(2500.), Some(2000.)));
    assert_eq!(hunt.session.raw_gains, Some(1235972 + 194 * 500));
    assert_eq!(hunt.session.profit, Some(1119522 + 194 * 500));
}

#[test]
fn ignored_entries_do_not_change_totals() {
    let p = Prices::new();
    let mut data = load_sample();
    for drop in data["Drops"].as_array_mut().unwrap() {
        let ignored = drop["Item"] == json!("metal scraps");
        drop["Ignored"] = json!(ignored);
    }
    let id = p.hunts().import_text(&data.to_string(), "ignored.json", false, None).unwrap().hunt_id;
    p.prices().set_price("metal scraps", 5000.).unwrap();
    let hunt = p.hunt(id);
    assert_eq!(entry(&hunt.drops, "metal scraps").total_price, Some(194 * 5000));
    assert_eq!(hunt.session.raw_gains, Some(1235972));
}

#[test]
fn list_items() {
    let p = Prices::new();
    p.prices().set_price("Healing Elixir", 10000.).unwrap();
    p.prices().set_price("Item Futuro", 50.).unwrap();
    let items: HashMap<String, _> = p.prices().list_items().unwrap().into_iter().map(|i| (i.name.clone(), i)).collect();
    let elixir = &items["Healing Elixir"];
    assert_eq!((elixir.sources(), elixir.analyzer_price, elixir.custom_price), ("Supply", Some(0.), Some(10000.)));
    assert_eq!((elixir.quantity, elixir.hunt_count), (6, 1));
    assert_eq!(items["turtle spike"].sources(), "Drop");
    assert_eq!(items["turtle spike"].custom_price, None);
    let future = &items["Item Futuro"];
    assert_eq!((future.sources(), future.hunt_count, future.custom_price), ("—", 0, Some(50.)));
}

#[test]
fn invalid_prices_are_refused() {
    let p = Prices::new();
    for (name, price) in [("gem", -1.), ("gem", f64::NAN), ("  ", 10.)] {
        assert!(p.prices().set_price(name, price).is_err());
    }
    assert!(p.prices().custom_prices().unwrap().is_empty());
}

// ---------------------------------------------------------- texto colado

#[test]
fn suggested_filenames() {
    let session = ParsedSession {
        session_id: Some(1080),
        start_datetime: NaiveDate::from_ymd_opt(2026, 9, 26).unwrap().and_hms_opt(15, 24, 20),
        ..ParsedSession::default()
    };
    assert_eq!(suggested_filename(&session, None), "hunt_1080_2026-09-26_15-24-20.json");
    let now = NaiveDate::from_ymd_opt(2026, 9, 27).unwrap().and_hms_opt(8, 0, 0);
    assert_eq!(suggested_filename(&ParsedSession::default(), now), "hunt_2026-09-27_08-00-00.json");
}

#[test]
fn never_overwrites() {
    let dir = tempfile::tempdir().unwrap();
    let directory = dir.path().join("new");
    let names: Vec<String> = ["1", "2", "3"]
        .iter()
        .map(|text| write_new_json_file(&directory, "a.json", text).unwrap())
        .map(|p| p.file_name().unwrap().to_string_lossy().into_owned())
        .collect();
    assert_eq!(names, ["a.json", "a_2.json", "a_3.json"]);
    assert_eq!(std::fs::read_to_string(directory.join("a.json")).unwrap(), "1");
}

struct Paste {
    database: Database,
    _dir: tempfile::TempDir,
    save_dir: PathBuf,
    text: String,
}

impl Paste {
    fn new() -> Self {
        let dir = tempfile::tempdir().unwrap();
        let save_dir = dir.path().join("imports");
        let text = std::fs::read_to_string(sample_hunt_path()).unwrap().replace("\r\n", "\n");
        Self { database: Database::in_memory().unwrap(), _dir: dir, save_dir, text }
    }

    fn service(&self) -> HuntService<'_> {
        HuntService::new(&self.database)
    }

    fn paste(&self, text: &str, allow_duplicate: bool) -> pxg_core::hunts::model::ImportResult {
        self.service().import_pasted_text(text, &self.save_dir, allow_duplicate, None).unwrap()
    }

    fn saved_files(&self) -> Vec<String> {
        let Ok(entries) = std::fs::read_dir(&self.save_dir) else { return Vec::new() };
        let mut names: Vec<String> = entries
            .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
            .filter(|n| n.ends_with(".json"))
            .collect();
        names.sort();
        names
    }
}

#[test]
fn pasted_json_is_imported_and_saved() {
    let p = Paste::new();
    let result = p.paste(&format!("\n  {}\n\n", p.text), false);
    assert_eq!(result.status, ImportStatus::Imported, "{}", result.message);
    let saved = result.saved_path.clone().unwrap();
    assert_eq!(saved, p.save_dir.join("hunt_1080_2026-09-26_15-24-20.json"));
    let saved_text = std::fs::read_to_string(&saved).unwrap();
    assert_eq!(serde_json::from_str::<Value>(&saved_text).unwrap(), serde_json::from_str::<Value>(&p.text).unwrap());
    let hunt = p.service().get_hunt_details(result.hunt_id.unwrap()).unwrap().unwrap();
    assert_eq!(hunt.source_file.as_deref(), Some("hunt_1080_2026-09-26_15-24-20.json"));
    assert_eq!(hunt.raw_json, saved_text); // banco e arquivo idênticos
    assert_eq!(hunt.drops.len(), 2);
}

#[test]
fn saved_file_can_be_reimported_as_duplicate() {
    let p = Paste::new();
    let result = p.paste(&p.text, false);
    let again = p.service().import_file(&result.saved_path.unwrap(), false, None).unwrap();
    assert_eq!(again.status, ImportStatus::Duplicate);
}

#[test]
fn invalid_text_creates_no_file() {
    let p = Paste::new();
    for text in ["", "   ", "{ quebrado", r#"{"Drops": []}"#] {
        let result = p.paste(text, false);
        assert_eq!(result.status, ImportStatus::Error, "{text}");
        assert!(result.saved_path.is_none());
    }
    assert!(p.saved_files().is_empty());
    assert_eq!(p.service().count_hunts(None).unwrap(), 0);
}

#[test]
fn duplicate_not_confirmed_creates_no_file() {
    let p = Paste::new();
    p.service().import_file(&sample_hunt_path(), false, None).unwrap();
    let result = p.paste(&p.text, false);
    assert_eq!(result.status, ImportStatus::Duplicate);
    assert!(p.saved_files().is_empty());
    assert_eq!(p.service().count_hunts(None).unwrap(), 1);
}

#[test]
fn forced_duplicate_gets_new_file_name() {
    let p = Paste::new();
    p.paste(&p.text, false);
    assert_eq!(p.paste(&p.text, true).status, ImportStatus::Imported);
    assert_eq!(p.saved_files(), ["hunt_1080_2026-09-26_15-24-20.json", "hunt_1080_2026-09-26_15-24-20_2.json"]);
}

#[test]
fn different_hunts_get_different_files() {
    let p = Paste::new();
    p.paste(&p.text, false);
    let other = sample_text(&[("Session ID", json!(1081)), ("Start", json!("2026-09-26 17:00:00"))]);
    p.paste(&other, false);
    assert_eq!(p.saved_files(), ["hunt_1080_2026-09-26_15-24-20.json", "hunt_1081_2026-09-26_17-00-00.json"]);
}

#[test]
fn failed_save_leaves_no_file() {
    // Se a gravação no banco falha, o arquivo recém-criado é apagado.
    let p = Paste::new();
    p.database.with(|c| Ok(c.execute_batch("DROP TABLE enemies_defeated")?)).unwrap();
    assert!(p.service().import_pasted_text(&p.text, &p.save_dir, false, None).is_err());
    assert!(p.saved_files().is_empty());
}
