//! Porta de `tests/test_json_importer.py`.

mod common;

use chrono::NaiveDate;
use common::{load_sample, sample_hunt_path, sample_text};
use pxg_core::hunts::analyzer::{ImportErrorKind, ParsedHunt, compute_content_hash, parse_analyzer_json, read_analyzer_file};
use serde_json::{Value, json};

fn sample() -> (String, ParsedHunt) {
    let text = std::fs::read_to_string(sample_hunt_path()).unwrap();
    let parsed = parse_analyzer_json(&text, Some("sample_hunt.json".into())).unwrap();
    (text, parsed)
}

fn parse(text: &str) -> ParsedHunt {
    parse_analyzer_json(text, None).unwrap()
}

fn error_kind(text: &str) -> ImportErrorKind {
    parse_analyzer_json(text, None).unwrap_err().kind
}

fn close(actual: f64, expected: f64) {
    assert!((actual - expected).abs() < 1e-6, "{actual} ≠ {expected}");
}

#[test]
fn session_fields() {
    let s = sample().1.session;
    assert_eq!(s.session_id, Some(1080));
    assert_eq!(s.start_datetime, NaiveDate::from_ymd_opt(2026, 9, 26).unwrap().and_hms_opt(15, 24, 20));
    assert_eq!(s.duration_seconds, Some(4310));
    assert_eq!(s.status.as_deref(), Some("Active"));
    assert_eq!(s.session_type.as_deref(), Some("player"));
    assert_eq!(s.kills, Some(368));
    assert_eq!(s.kills_per_hour, Some(307.));
    assert_eq!(s.profit, Some(1119522));
    assert_eq!(s.profit_per_hour, Some(935099.));
    assert_eq!(s.supplies, Some(116450));
    assert_eq!(s.raw_gains, Some(1235972));
    assert_eq!(s.damage_dealt, Some(119470652));
    assert_eq!(s.damage_taken, Some(1460258));
    assert_eq!(s.paused_seconds, Some(0));
    assert_eq!(s.time_to_next_level, None);
    assert_eq!(s.time_to_next_level_seconds, None);
}

#[test]
fn player_is_inferred_from_lists() {
    assert_eq!(sample().1.session.player.as_deref(), Some("Royalzxd"));
}

#[test]
fn lists() {
    let parsed = sample().1;
    let enemies: Vec<&str> = parsed.enemies.iter().map(|e| e.enemy.as_str()).collect();
    assert_eq!(enemies, ["Mecha Abomasnow", "Mecha Blastoise", "Mecha Charizard"]);
    assert_eq!(parsed.enemies[2].count, 40);
    assert_eq!(parsed.enemies[0].rare, Some(false));
    let gem = &parsed.drops[0];
    assert_eq!((gem.item.as_str(), gem.count, gem.unit_price, gem.total_price), ("nightmare gem", 1217, Some(216.), Some(262872)));
    assert_eq!(gem.ignored, None);
    assert_eq!(parsed.supplies.len(), 1);
    assert_eq!(parsed.supplies[0].total_price, Some(30000));
}

#[test]
fn raw_json_preserved_exactly() {
    let (text, parsed) = sample();
    assert_eq!(parsed.raw_json, text);
    assert!(parsed.warnings.is_empty());
}

#[test]
fn unknown_fields_are_kept_in_raw_json() {
    let mut data = load_sample();
    data["NewField"] = json!(123);
    data["Session"]["Brand new metric"] = json!(9);
    let parsed = parse(&data.to_string());
    let raw: Value = serde_json::from_str(&parsed.raw_json).unwrap();
    assert_eq!(raw["NewField"], json!(123));
    assert_eq!(parsed.session.session_id, Some(1080));
}

#[test]
fn content_hash_ignores_formatting() {
    let (_, parsed) = sample();
    let data = load_sample();
    assert_eq!(parse(&data.to_string()).content_hash, parsed.content_hash);
    assert_eq!(compute_content_hash(&data), parsed.content_hash);
}

#[test]
fn invalid_documents() {
    let error = parse_analyzer_json(r#"{"Session": {"#, None).unwrap_err();
    assert_eq!((error.kind, error.message.as_str()), (ImportErrorKind::InvalidJson, "JSON inválido."));
    assert_eq!(error_kind(""), ImportErrorKind::InvalidJson);
    let error = parse_analyzer_json("[1, 2, 3]", None).unwrap_err();
    assert_eq!(error.kind, ImportErrorKind::InvalidSession);
    assert_eq!(error.message, "O arquivo não possui uma sessão válida do Analyzer.");
    let mut data = load_sample();
    data.as_object_mut().unwrap().remove("Session");
    assert_eq!(error_kind(&data.to_string()), ImportErrorKind::InvalidSession);
    for value in [Value::Null, json!([]), json!("x"), json!({})] {
        assert_eq!(error_kind(&json!({"Session": value}).to_string()), ImportErrorKind::InvalidSession);
    }
    assert_eq!(error_kind(&json!({"Session": {"Kills": 10}}).to_string()), ImportErrorKind::InvalidSession);
}

#[test]
fn minimal_session_only() {
    let parsed = parse(&json!({"Session": {"Session ID": 5}}).to_string());
    assert_eq!(parsed.session.session_id, Some(5));
    assert_eq!(parsed.session.player, None);
    assert_eq!(parsed.session.start_datetime, None);
    assert!(parsed.enemies.is_empty() && parsed.drops.is_empty() && parsed.supplies.is_empty());
}

#[test]
fn null_values_are_safe() {
    let nulls: Vec<(&str, Value)> = ["Kills", "Profit", "Start", "Profit per hour", "Kills per hour"]
        .into_iter()
        .map(|k| (k, Value::Null))
        .collect();
    let s = parse(&sample_text(&nulls)).session;
    assert_eq!((s.kills, s.profit, s.profit_per_hour, s.start_datetime), (None, None, None, None));
}

#[test]
fn duration_from_text_when_seconds_missing() {
    assert_eq!(parse(&sample_text(&[("Duration seconds", Value::Null)])).session.duration_seconds, Some(4310));
}

#[test]
fn missing_rates_are_derived() {
    let s = parse(&sample_text(&[("Profit per hour", Value::Null), ("Damage dealt per second", Value::Null)])).session;
    close(s.profit_per_hour.unwrap(), 1119522. * 3600. / 4310.);
    close(s.damage_dealt_per_second.unwrap(), 119470652. / 4310.);
}

#[test]
fn numeric_strings_are_converted() {
    let s = parse(&sample_text(&[("Session ID", json!("1080")), ("Kills", json!("368"))])).session;
    assert_eq!((s.session_id, s.kills), (Some(1080), Some(368)));
}

#[test]
fn bad_list_types_and_entries_generate_warnings() {
    let mut data = load_sample();
    data["Drops"] = json!({"not": "a list"});
    let enemies = data["Enemies Defeated"].as_array_mut().unwrap();
    enemies.push(json!("garbage"));
    enemies.push(json!({"Count": 3})); // sem nome
    data["Supplies"].as_array_mut().unwrap().push(json!({"Item": "Potion", "Count": 4, "Unit price": 50}));
    let parsed = parse(&data.to_string());
    assert!(parsed.drops.is_empty());
    assert_eq!(parsed.enemies.len(), 3);
    assert_eq!(parsed.supplies.last().unwrap().total_price, Some(200)); // derivado de count × preço
    assert_eq!(parsed.warnings.len(), 2);
}

#[test]
fn null_lists() {
    let mut data = load_sample();
    data["Drops"] = Value::Null;
    let parsed = parse(&data.to_string());
    assert!(parsed.drops.is_empty() && parsed.warnings.is_empty());
}

#[test]
fn multiple_players() {
    let mut data = load_sample();
    data["Drops"][1]["Player"] = json!("Partner");
    assert_eq!(parse(&data.to_string()).session.player.as_deref(), Some("Royalzxd, Partner"));
}

#[test]
fn reads_file_with_bom_missing_and_binary() {
    let dir = tempfile::tempdir().unwrap();
    let bom = dir.path().join("bom.json");
    std::fs::write(&bom, format!("\u{feff}{}", std::fs::read_to_string(sample_hunt_path()).unwrap())).unwrap();
    assert_eq!(parse(&read_analyzer_file(&bom).unwrap()).session.session_id, Some(1080));
    assert_eq!(read_analyzer_file(&dir.path().join("nao-existe.json")).unwrap_err().kind, ImportErrorKind::FileRead);
    let binary = dir.path().join("binary.json");
    std::fs::write(&binary, b"\xff\xfe\x00\x81\x82").unwrap();
    assert_eq!(read_analyzer_file(&binary).unwrap_err().kind, ImportErrorKind::InvalidJson);
}
