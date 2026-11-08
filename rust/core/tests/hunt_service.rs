//! Porta de `tests/test_hunt_service.py`.

mod common;

use std::path::Path;

use common::{count_hunts, load_sample, sample_hunt_path, sample_text};
use pxg_core::Database;
use pxg_core::hunts::model::ImportStatus;
use pxg_core::hunts::service::HuntService;
use serde_json::{Value, json};

fn count(database: &Database, table: &str) -> i64 {
    database
        .with(|c| Ok(c.query_row(&format!("SELECT count(*) FROM {table}"), [], |r| r.get(0))?))
        .unwrap()
}

fn import(service: &HuntService<'_>, text: &str) -> ImportStatus {
    service.import_text(text, "", false, None).unwrap().status
}

#[test]
fn import_file_persists_everything() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    let result = service.import_file(&sample_hunt_path(), false, None).unwrap();
    assert_eq!(result.status, ImportStatus::Imported, "{}", result.message);
    let hunt = service.get_hunt_details(result.hunt_id.unwrap()).unwrap().unwrap();
    assert_eq!(hunt.session.session_id, Some(1080));
    assert_eq!(hunt.session.player.as_deref(), Some("Royalzxd"));
    assert_eq!(hunt.session.profit, Some(1119522));
    assert_eq!(hunt.source_file.as_deref(), Some("sample_hunt.json"));
    let file = std::fs::read_to_string(sample_hunt_path()).unwrap().replace("\r\n", "\n");
    assert_eq!(hunt.raw_json, file);
    assert_eq!(hunt.enemies.len(), 3);
    assert_eq!(hunt.drops.len(), 2);
    assert_eq!(hunt.supplies.len(), 1);
    assert_eq!(hunt.drops.iter().map(|d| d.total_price.unwrap()).sum::<i64>(), 262872 + 388000);
    assert!(hunt.created_at.is_some());
}

#[test]
fn invalid_json_returns_error_result() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    let result = service.import_text("{ not json", "broken.json", false, None).unwrap();
    assert_eq!(result.status, ImportStatus::Error);
    assert_eq!(result.message, "JSON inválido.");
    assert_eq!(service.count_hunts(None).unwrap(), 0);
}

#[test]
fn missing_session_returns_error_result() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    let result = service.import_text(&json!({"Drops": []}).to_string(), "x.json", false, None).unwrap();
    assert_eq!(result.status, ImportStatus::Error);
    assert_eq!(result.message, "O arquivo não possui uma sessão válida do Analyzer.");
}

#[test]
fn missing_file_returns_error_result() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    let result = service.import_file(Path::new("nao-existe.json"), false, None).unwrap();
    assert_eq!(result.status, ImportStatus::Error);
    assert_eq!(service.count_hunts(None).unwrap(), 0);
}

#[test]
fn duplicate_is_detected() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    let first = service.import_file(&sample_hunt_path(), false, None).unwrap();
    let second = service.import_file(&sample_hunt_path(), false, None).unwrap();
    assert_eq!(second.status, ImportStatus::Duplicate);
    assert_eq!(second.message, "Esta Hunt já foi importada.");
    assert_eq!(second.duplicate_of, [first.hunt_id.unwrap()]);
    assert_eq!(service.count_hunts(None).unwrap(), 1);
}

#[test]
fn same_session_exported_later_is_duplicate() {
    // Mesmo session_id/player/início com números diferentes (re-exportação).
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    service.import_file(&sample_hunt_path(), false, None).unwrap();
    let later = sample_text(&[("Duration seconds", json!(5000)), ("Kills", json!(400))]);
    assert_eq!(import(&service, &later), ImportStatus::Duplicate);
}

#[test]
fn same_session_id_other_start_is_not_duplicate() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    service.import_file(&sample_hunt_path(), false, None).unwrap();
    let other = sample_text(&[("Start", json!("2026-09-27 10:00:00"))]);
    assert_eq!(import(&service, &other), ImportStatus::Imported);
}

#[test]
fn same_session_id_other_player_is_not_duplicate() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    service.import_file(&sample_hunt_path(), false, None).unwrap();
    let mut data = load_sample();
    for section in ["Enemies Defeated", "Drops", "Supplies"] {
        for entry in data[section].as_array_mut().unwrap() {
            entry["Player"] = json!("OtherPlayer");
        }
    }
    assert_eq!(import(&service, &data.to_string()), ImportStatus::Imported);
}

#[test]
fn force_import_duplicate() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    let first = service.import_file(&sample_hunt_path(), false, None).unwrap();
    let forced = service.import_file(&sample_hunt_path(), true, None).unwrap();
    assert_eq!(forced.status, ImportStatus::Imported);
    assert_eq!(forced.duplicate_of, [first.hunt_id.unwrap()]);
    assert_eq!(service.count_hunts(None).unwrap(), 2);
}

#[test]
fn delete_cascades_to_related_rows() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    let keep = service.import_file(&sample_hunt_path(), false, None).unwrap().hunt_id.unwrap();
    let remove = service.import_file(&sample_hunt_path(), true, None).unwrap().hunt_id.unwrap();
    assert_eq!(count(&database, "enemies_defeated"), 6);
    assert_eq!(service.delete_hunts(&[remove]).unwrap(), 1);
    assert_eq!(service.count_hunts(None).unwrap(), 1);
    assert_eq!(count(&database, "enemies_defeated"), 3);
    assert_eq!(count(&database, "drops"), 2);
    assert_eq!(count(&database, "supplies"), 1);
    assert!(service.get_hunt_details(keep).unwrap().is_some());
    assert!(service.get_hunt_details(remove).unwrap().is_none());
}

#[test]
fn list_hunts_newest_first() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    import(&service, &sample_text(&[("Start", json!("2026-09-01 10:00:00"))]));
    import(&service, &sample_text(&[("Start", json!("2026-09-20 10:00:00"))]));
    import(&service, &sample_text(&[("Start", Value::Null), ("Session ID", json!(7))]));
    let hunts = service.list_hunts(None).unwrap();
    assert_eq!(hunts.len(), 3);
    assert_eq!(hunts[0].start_datetime.unwrap().format("%d").to_string(), "20");
    assert_eq!(hunts[0].profit, Some(1119522));
}

#[test]
fn hunt_without_start_can_be_imported() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    let text = sample_text(&[("Start", Value::Null)]);
    assert_eq!(import(&service, &text), ImportStatus::Imported);
    // Sem data não há chave de identidade, mas o conteúdo idêntico é detectado.
    assert_eq!(import(&service, &text), ImportStatus::Duplicate);
}

#[test]
fn data_survives_reopening() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("sub").join("hunts.db");
    {
        let database = Database::open(&path).unwrap();
        database.create_schema().unwrap();
        HuntService::new(&database).import_file(&sample_hunt_path(), false, None).unwrap();
    }
    let reopened = Database::open(&path).unwrap();
    reopened.create_schema().unwrap();
    let hunts = HuntService::new(&reopened).list_hunts(None).unwrap();
    assert!(path.exists());
    assert_eq!(hunts.len(), 1);
    assert_eq!(hunts[0].session_id, Some(1080));
    assert_eq!(reopened.with(|c| Ok(count_hunts(c))).unwrap(), 1);
}
