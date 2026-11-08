//! Porta de `tests/test_bosses.py`: categorias na importação, nos filtros e na migração. As
//! estatísticas de boss entram com o serviço de estatísticas, e as telas, na fase 4.

mod common;

use std::path::Path;

use common::{fixture, sample_hunt_path};
use pxg_core::Database;
use pxg_core::db::migrations::LATEST_VERSION;
use pxg_core::format::NumberFormat;
use pxg_core::hunts::categories::Category;
use pxg_core::hunts::filters::HuntFilter;
use pxg_core::hunts::service::{HuntService, IMPORTED_MESSAGE};
use serde_json::{Value, json};

fn boss_text(session_id: i64, start: &str, extra: &[(&str, Value)]) -> String {
    let mut data: Value = serde_json::from_str(&std::fs::read_to_string(fixture("sample_boss.json")).unwrap()).unwrap();
    data["Session"]["Session ID"] = json!(session_id);
    data["Session"]["Start"] = json!(start);
    for (key, value) in extra {
        data["Session"][*key] = value.clone();
    }
    data.to_string()
}

fn default_boss() -> String {
    boss_text(651, "2026-10-04 13:04:54", &[])
}

fn scoped(category: Category) -> HuntFilter {
    HuntFilter::default().scoped(&[category])
}

fn category_of(service: &HuntService<'_>, hunt_id: i64) -> Category {
    Category::from_value(Some(&service.get_hunt_details(hunt_id).unwrap().unwrap().category))
}

#[test]
fn labels_and_folders() {
    let plurals: Vec<&str> = Category::bosses().map(Category::plural).collect();
    assert_eq!(plurals, ["Rifts", "Energia Vermelha", "Energia Azul", "Terrors"]);
}

#[test]
fn category_from_folder() {
    use pxg_core::hunts::categories::category_from_folder as from;
    assert_eq!(from(Path::new("x/imports/Terrors/a.json")), Some(Category::Terror));
    assert_eq!(from(Path::new("x/imports/energia_azul/a.json")), Some(Category::BossBlue));
    assert_eq!(from(Path::new("x/imports/a.json")), None);
    assert_eq!(from(Path::new("Texto colado")), None);
}

#[test]
fn scope_is_not_a_user_filter() {
    let filter = scoped(Category::Terror);
    assert_eq!(filter.categories, [Category::Terror]);
    assert!(filter.is_empty());
    assert!(filter.describe(NumberFormat::PT_BR).is_empty());
    let user = HuntFilter { player: Some("x".into()), ..Default::default() };
    assert!(user.scoped(&[]).categories.is_empty());
}

#[test]
fn hunt_is_the_default() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    let result = service.import_file(&sample_hunt_path(), false, None).unwrap();
    assert_eq!(result.category, Some(Category::Hunt));
    assert_eq!(result.message, IMPORTED_MESSAGE);
    assert_eq!(category_of(&service, result.hunt_id.unwrap()), Category::Hunt);
}

#[test]
fn requested_category() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    let result = service.import_file(&fixture("sample_boss.json"), false, Some(Category::Terror)).unwrap();
    assert_eq!(result.category, Some(Category::Terror));
    assert_eq!(result.message, "Sessão importada em Terrors.");
    assert_eq!(category_of(&service, result.hunt_id.unwrap()), Category::Terror);
}

#[test]
fn folder_wins_over_requested_category() {
    let database = Database::in_memory().unwrap();
    let dir = tempfile::tempdir().unwrap();
    let folder = dir.path().join("rifts");
    std::fs::create_dir(&folder).unwrap();
    let path = folder.join("boss.json");
    std::fs::write(&path, default_boss()).unwrap();
    let result = HuntService::new(&database).import_file(&path, false, Some(Category::Terror)).unwrap();
    assert_eq!(result.category, Some(Category::Rift));
}

#[test]
fn known_boss_enemies_are_detected() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    service.import_text(&boss_text(1, "2026-10-04 13:04:54", &[]), "", false, Some(Category::BossRed)).unwrap();
    let result = service.import_text(&boss_text(2, "2026-10-05 10:00:00", &[]), "", false, None).unwrap();
    assert_eq!(result.category, Some(Category::BossRed));
}

#[test]
fn enemy_also_seen_in_hunts_is_not_detected() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    service.import_text(&boss_text(1, "2026-10-04 13:04:54", &[]), "", false, Some(Category::Terror)).unwrap();
    service.import_text(&boss_text(2, "2026-10-05 10:00:00", &[]), "", false, Some(Category::Hunt)).unwrap();
    let result = service.import_text(&boss_text(3, "2026-10-06 10:00:00", &[]), "", false, None).unwrap();
    assert_eq!(result.category, Some(Category::Hunt));
}

#[test]
fn pasted_boss_is_saved_in_category_folder() {
    let database = Database::in_memory().unwrap();
    let dir = tempfile::tempdir().unwrap();
    let result = HuntService::new(&database)
        .import_pasted_text(&default_boss(), dir.path(), false, Some(Category::BossBlue))
        .unwrap();
    let saved = result.saved_path.unwrap();
    assert_eq!(saved.parent().unwrap(), dir.path().join("energia_azul"));
    // O arquivo salvo volta para a mesma categoria, mesmo importado fora da aba.
    let other = Database::in_memory().unwrap();
    assert_eq!(HuntService::new(&other).import_file(&saved, false, None).unwrap().category, Some(Category::BossBlue));
}

#[test]
fn pasted_hunt_stays_in_imports_root() {
    let database = Database::in_memory().unwrap();
    let dir = tempfile::tempdir().unwrap();
    let text = std::fs::read_to_string(sample_hunt_path()).unwrap();
    let result = HuntService::new(&database).import_pasted_text(&text, dir.path(), false, None).unwrap();
    assert_eq!(result.saved_path.unwrap().parent().unwrap(), dir.path());
}

#[test]
fn scoped_queries_and_set_category() {
    let database = Database::in_memory().unwrap();
    let service = HuntService::new(&database);
    let hunt = service.import_file(&sample_hunt_path(), false, None).unwrap().hunt_id.unwrap();
    let boss = service.import_file(&fixture("sample_boss.json"), false, Some(Category::Terror)).unwrap().hunt_id.unwrap();
    let ids: Vec<i64> = service.list_hunts(Some(&scoped(Category::Hunt))).unwrap().iter().map(|h| h.id).collect();
    assert_eq!(ids, [hunt]);
    assert_eq!(service.count_hunts(Some(&scoped(Category::Terror))).unwrap(), 1);
    assert_eq!(service.count_hunts(None).unwrap(), 2);

    assert_eq!(service.set_category(&[boss], Category::Rift).unwrap(), 1);
    assert_eq!(service.count_hunts(Some(&scoped(Category::Terror))).unwrap(), 0);
    let summaries = service.list_hunts(Some(&scoped(Category::Rift))).unwrap();
    assert_eq!(summaries.len(), 1);
    assert_eq!((summaries[0].id, summaries[0].category.as_str()), (boss, "rift"));
}

#[test]
fn version3_database_gets_category_column() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("hunts.db");
    {
        let old = Database::open(&path).unwrap();
        old.create_schema().unwrap();
        HuntService::new(&old).import_file(&sample_hunt_path(), false, None).unwrap();
        old.with(|c| {
            c.execute_batch(
                "DROP INDEX ix_hunt_sessions_category;
                 ALTER TABLE hunt_sessions DROP COLUMN category;
                 PRAGMA user_version = 3;",
            )?;
            Ok(())
        })
        .unwrap();
    }
    let database = Database::open(&path).unwrap();
    let applied: Vec<i64> = database.create_schema().unwrap().iter().map(|m| m.version).collect();
    assert_eq!(applied, (4..=LATEST_VERSION).collect::<Vec<_>>());
    let service = HuntService::new(&database);
    let summaries = service.list_hunts(None).unwrap();
    assert_eq!(summaries.len(), 1);
    assert_eq!(summaries[0].category, "hunt");
    let boss = service.import_file(&fixture("sample_boss.json"), false, Some(Category::Rift)).unwrap();
    assert_eq!(service.count_hunts(Some(&scoped(Category::Rift))).unwrap(), 1);
    assert!(boss.hunt_id.is_some());
}
