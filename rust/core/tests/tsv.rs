//! Porta de `tests/test_tsv_importer.py`.

mod common;

use chrono::NaiveDate;
use common::{fixture, sample_hunt_path};
use pxg_core::Database;
use pxg_core::hunts::analyzer::{ImportErrorKind, parse_analyzer_text, read_analyzer_file};
use pxg_core::hunts::files::collect_analyzer_files;
use pxg_core::hunts::model::ImportStatus;
use pxg_core::hunts::service::HuntService;
use pxg_core::hunts::tsv::{looks_like_tsv, tsv_to_document};
use serde_json::{Value, json};

fn text() -> String {
    read_analyzer_file(&fixture("sample_hunt.tsv")).unwrap()
}

fn document() -> Value {
    Value::Object(tsv_to_document(&text()).unwrap())
}

#[test]
fn sections_are_translated() {
    let keys: Vec<String> = document().as_object().unwrap().keys().cloned().collect();
    assert_eq!(keys, ["Session", "Experience", "Drops", "Supplies", "Enemies Defeated", "Damage"]);
}

#[test]
fn session_fields_are_translated_and_typed() {
    let session = &document()["Session"];
    assert_eq!(session["Session ID"], json!(198));
    assert_eq!(session["Start"], json!("2026-09-20 09:11:03"));
    assert_eq!(session["Duration"], json!("01:59:16"));
    assert_eq!(session["Profit per hour"], json!(1193042));
    assert_eq!(session["Status"], json!("Pausado"));
}

#[test]
fn rows_use_json_keys() {
    let document = document();
    assert_eq!(document["Drops"][0], json!({
        "Player": "Avg Sandrinhas", "Item": "pot of lava", "Count": 368,
        "Unit price": 18, "Total price": 6624, "Ignored": null,
    }));
    assert_eq!(document["Enemies Defeated"][0], json!({
        "Player": "Avg Sandrinhas", "Enemy": "Nightmare Shiny Torkoal", "Count": 2,
        "Rare": true, "Ignored": false,
    }));
    assert_eq!(document["Damage"][0]["Element"], json!("Melee"));
}

#[test]
fn english_labels_pass_through() {
    let text = "Session\nField\tValue\nSession ID\t5\nDuration seconds\t60\n\n\
        Drops\nPlayer\tItem\tCount\tUnit price\tTotal price\tIgnored\nAsh\tgem\t2\t10\t20\tfalse\n";
    let document = Value::Object(tsv_to_document(text).unwrap());
    assert_eq!(document["Session"], json!({"Session ID": 5, "Duration seconds": 60}));
    assert_eq!(document["Drops"][0]["Ignored"], json!(false));
}

#[test]
fn detection() {
    assert!(looks_like_tsv(&text()));
    assert!(!looks_like_tsv(&std::fs::read_to_string(sample_hunt_path()).unwrap()));
    assert!(!looks_like_tsv("{\"a\":\t1}"));
}

#[test]
fn session_and_lists() {
    let parsed = parse_analyzer_text(&text(), Some("sample_hunt.tsv".into())).unwrap();
    let s = &parsed.session;
    assert_eq!(s.session_id, Some(198));
    assert_eq!(s.player.as_deref(), Some("Avg Sandrinhas"));
    assert_eq!(s.start_datetime, NaiveDate::from_ymd_opt(2026, 9, 20).unwrap().and_hms_opt(9, 11, 3));
    assert_eq!(s.duration_seconds, Some(7156));
    assert_eq!(s.experience, Some(7992903));
    assert_eq!(s.profit, Some(2371504));
    assert_eq!(s.kills, Some(610));
    assert_eq!(s.rare_kills, Some(2));
    assert_eq!(s.damage_dealt_per_second, Some(31236.));
    assert_eq!(s.time_to_next_level.as_deref(), Some("03:10:33"));
    assert_eq!(s.time_to_next_level_seconds, Some(11433));

    assert_eq!(parsed.drops.len(), 16);
    assert_eq!(parsed.supplies.len(), 18);
    let enemies: Vec<&str> = parsed.enemies.iter().map(|e| e.enemy.as_str()).collect();
    assert_eq!(enemies, ["Nightmare Shiny Torkoal", "Nightmare Turtonator"]);
    assert_eq!(parsed.enemies.iter().map(|e| e.rare).collect::<Vec<_>>(), [Some(true), Some(false)]);
    let spike = parsed.drops.iter().find(|d| d.item == "turtle spike").unwrap();
    assert_eq!((spike.count, spike.unit_price, spike.total_price), (183, Some(8000.), Some(1464000)));
    assert_eq!(spike.ignored, None);
    assert!(parsed.warnings.is_empty());
}

#[test]
fn raw_json_keeps_every_section() {
    let parsed = parse_analyzer_text(&text(), None).unwrap();
    let data: Value = serde_json::from_str(&parsed.raw_json).unwrap();
    assert_eq!(data, document());
    assert_eq!(data["Damage"].as_array().unwrap().len(), 16);
}

#[test]
fn hash_ignores_line_endings() {
    let lf = parse_analyzer_text(&text(), None).unwrap();
    let crlf = parse_analyzer_text(&text().replace('\n', "\r\n"), None).unwrap();
    assert_eq!(crlf.content_hash, lf.content_hash);
}

#[test]
fn invalid_texts() {
    let error = parse_analyzer_text("a\tb\tc", None).unwrap_err();
    assert_eq!((error.kind, error.message.as_str()), (ImportErrorKind::InvalidTsv, "TSV inválido."));
    assert_eq!(parse_analyzer_text("isto não é nada", None).unwrap_err().kind, ImportErrorKind::InvalidJson);
}

#[test]
fn import_file_and_detect_duplicate() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    let result = service.import_file(&fixture("sample_hunt.tsv"), false, None).unwrap();
    assert_eq!(result.status, ImportStatus::Imported, "{}", result.message);
    let hunt = service.get_hunt_details(result.hunt_id.unwrap()).unwrap().unwrap();
    assert_eq!(hunt.source_file.as_deref(), Some("sample_hunt.tsv"));
    assert_eq!(hunt.session.session_id, Some(198));
    assert_eq!(hunt.drops.len(), 16);
    assert_eq!(service.import_file(&fixture("sample_hunt.tsv"), false, None).unwrap().status, ImportStatus::Duplicate);
}

#[test]
fn pasted_tsv_is_saved_as_json() {
    let database = Database::in_memory().unwrap();
    let dir = tempfile::tempdir().unwrap();
    let result = HuntService::new(&database).import_pasted_text(&text(), &dir.path().join("imports"), false, None).unwrap();
    assert_eq!(result.status, ImportStatus::Imported, "{}", result.message);
    let saved = result.saved_path.unwrap();
    assert_eq!(saved.file_name().unwrap(), "hunt_198_2026-09-20_09-11-03.json");
    let data: Value = serde_json::from_str(&std::fs::read_to_string(saved).unwrap()).unwrap();
    assert_eq!(data["Session"]["Session ID"], json!(198));
}

#[test]
fn folder_collects_json_and_tsv() {
    let dir = tempfile::tempdir().unwrap();
    let folder = dir.path().join("exports");
    std::fs::create_dir(&folder).unwrap();
    for name in ["a.json", "b.TSV", "notas.txt"] {
        std::fs::write(folder.join(name), "x").unwrap();
    }
    let names: Vec<String> = collect_analyzer_files(&[folder])
        .iter()
        .map(|p| p.file_name().unwrap().to_string_lossy().into_owned())
        .collect();
    assert_eq!(names, ["a.json", "b.TSV"]);
}
