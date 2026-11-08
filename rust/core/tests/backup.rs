//! Porta de `tests/test_backup.py`.

mod common;

use std::path::{Path, PathBuf};

use chrono::NaiveDate;
use pxg_core::backup::{BackupKind, BackupService, inspect_backup};
use pxg_core::db::migrations::LATEST_VERSION;
use pxg_core::db::schema;
use pxg_core::{Database, Error};

struct Fixture {
    _dir: tempfile::TempDir,
    root: PathBuf,
    database: Database,
}

impl Fixture {
    fn new() -> Self {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().to_path_buf();
        let database = Database::open(&root.join("data").join("hunts.db")).unwrap();
        database.create_schema().unwrap();
        database.with(|c| Ok(common::insert_hunt(c, 1080))).unwrap();
        Self { _dir: dir, root, database }
    }

    fn service(&self) -> BackupService<'_> {
        BackupService::new(&self.database, self.root.join("data").join("backups"))
    }

    fn count(&self) -> i64 {
        self.database.with(|c| Ok(common::count_hunts(c))).unwrap()
    }

    fn add_hunt(&self, session_id: i64) {
        self.database.with(|c| Ok(common::insert_hunt(c, session_id))).unwrap();
    }
}

fn name(path: &Path) -> String {
    path.file_name().unwrap().to_string_lossy().into_owned()
}

fn user_message(error: Error) -> String {
    match error {
        Error::User(error) => error.0,
        other => panic!("esperava erro para o usuário, veio {other:?}"),
    }
}

#[test]
fn backup_is_a_consistent_copy() {
    let f = Fixture::new();
    let path = f.service().create_backup(BackupKind::Manual, None).unwrap();
    assert!(name(&path).starts_with("hunts_backup_"));
    assert!(name(&path).ends_with("_manual.db"));
    assert_eq!(inspect_backup(&path).unwrap(), 1);
    let backups = f.service().list_backups().unwrap();
    assert_eq!(backups.len(), 1);
    assert_eq!(backups[0].kind, BackupKind::Manual);
    assert_eq!(backups[0].kind.label(), "Manual");
    assert!(backups[0].size_bytes > 0);
}

#[test]
fn backup_to_chosen_file() {
    let f = Fixture::new();
    let target = f.root.join("pendrive").join("copia.db");
    f.service().create_backup(BackupKind::Manual, Some(&target)).unwrap();
    assert_eq!(inspect_backup(&target).unwrap(), 1);
    f.service().create_backup(BackupKind::Manual, Some(&target)).unwrap(); // sobrescreve sem erro
    assert!(f.service().list_backups().unwrap().is_empty()); // fora da pasta padrão
}

#[test]
fn same_second_backups_get_unique_names() {
    let f = Fixture::new();
    let first = f.service().create_backup(BackupKind::Manual, None).unwrap();
    let second = f.service().create_backup(BackupKind::Manual, None).unwrap();
    assert_ne!(first, second);
    let backups = f.service().list_backups().unwrap();
    assert_eq!(backups.len(), 2);
    assert!(backups.iter().all(|b| b.kind == BackupKind::Manual));
}

#[test]
fn restore_replaces_data_and_keeps_safety_copy() {
    let f = Fixture::new();
    let backup = f.service().create_backup(BackupKind::Manual, None).unwrap();
    f.add_hunt(2);
    assert_eq!(f.count(), 2);

    let safety = f.service().restore(&backup).unwrap();

    assert_eq!(f.count(), 1); // o mesmo Database continua usável
    assert_eq!(inspect_backup(&safety).unwrap(), 2); // estado anterior preservado
    assert!(name(&safety).contains("antes-restauracao"));
    f.add_hunt(3);
    assert_eq!(f.count(), 2);
}

#[test]
fn restore_of_old_version_backup_is_migrated() {
    let f = Fixture::new();
    let old_path = f.root.join("antigo.db");
    {
        let old = Database::open(&old_path).unwrap(); // banco da Fase 1 (sem versão)
        old.with(|c| {
            for table in schema::TABLES.iter() {
                for statement in &table.statements {
                    c.execute_batch(statement)?;
                }
            }
            Ok(())
        })
        .unwrap();
    }
    f.service().restore(&old_path).unwrap();
    assert_eq!(f.database.schema_version().unwrap(), LATEST_VERSION);
    assert_eq!(f.count(), 0);
}

#[test]
fn invalid_restore_sources() {
    let f = Fixture::new();
    let not_sqlite = f.root.join("texto.db");
    std::fs::write(&not_sqlite, "isto não é um banco").unwrap();
    let other_db = f.root.join("outro.db");
    rusqlite::Connection::open(&other_db).unwrap().execute_batch("CREATE TABLE x (id INTEGER)").unwrap();
    let newer = f.root.join("mais-novo.db");
    f.service().create_backup(BackupKind::Manual, Some(&newer)).unwrap();
    rusqlite::Connection::open(&newer).unwrap().pragma_update(None, "user_version", LATEST_VERSION + 1).unwrap();

    let current = f.database.path().unwrap().to_path_buf();
    let cases = [
        (f.root.join("nao-existe.db"), "não encontrado"),
        (not_sqlite, "SQLite válido"),
        (other_db, "não é um banco do"),
        (current, "já é o banco em uso"),
        (newer, "Atualize o aplicativo"),
    ];
    for (source, expected) in cases {
        let message = user_message(f.service().restore(&source).unwrap_err());
        assert!(message.contains(expected), "{}: {message}", source.display());
    }
    assert_eq!(f.count(), 1); // nada foi alterado
    assert!(f.service().list_backups().unwrap().is_empty()); // nem backup de segurança
}

#[test]
fn automatic_backup_once_per_day_and_pruning() {
    let f = Fixture::new();
    let first = f.service().automatic_backup_if_due(3, None).unwrap().expect("backup do dia");
    assert!(f.service().automatic_backup_if_due(3, None).unwrap().is_none()); // já fez hoje
    // Backups automáticos antigos (dias anteriores), criados com nomes datados.
    for day in 1..=5 {
        let target = f.root.join("data").join("backups")
            .join(format!("hunts_backup_2026-09-0{day}_12-00-00_auto.db"));
        std::fs::copy(&first, target).unwrap();
    }
    let manual = f.service().create_backup(BackupKind::Manual, None).unwrap();
    let removed = f.service().prune_automatic(3).unwrap();
    assert_eq!(removed.len(), 3);
    let kinds: Vec<BackupKind> = f.service().list_backups().unwrap().into_iter().map(|b| b.kind).collect();
    assert_eq!(kinds.iter().filter(|k| **k == BackupKind::Automatic).count(), 3);
    assert!(manual.exists()); // backups manuais nunca são apagados
    assert!(first.exists()); // o mais recente fica
}

#[test]
fn automatic_backup_skips_empty_database() {
    let dir = tempfile::tempdir().unwrap();
    let empty = Database::open(&dir.path().join("vazio").join("hunts.db")).unwrap();
    empty.create_schema().unwrap();
    let service = BackupService::new(&empty, dir.path().join("vazio").join("backups"));
    let day = NaiveDate::from_ymd_opt(2026, 9, 26);
    assert!(service.automatic_backup_if_due(5, day).unwrap().is_none());
}

#[test]
fn memory_database_cannot_be_backed_up() {
    let dir = tempfile::tempdir().unwrap();
    let database = Database::in_memory().unwrap();
    let error = BackupService::new(&database, dir.path().join("b"))
        .create_backup(BackupKind::Manual, None)
        .unwrap_err();
    assert!(user_message(error).contains("banco em memória"));
}

#[test]
fn names_from_other_versions_are_listed() {
    let f = Fixture::new();
    let folder = f.root.join("data").join("backups");
    std::fs::create_dir_all(&folder).unwrap();
    for file in ["hunts_backup_2026-11-02_19-18-01_antes-atualizacao.db",
        "hunts_backup_2026-11-02_19-18-01_auto_2.db", "hunts_backup_2026-11-02_19-18-01.db",
        "hunts_backup_quebrado.db", "outro.db"]
    {
        std::fs::write(folder.join(file), b"x").unwrap();
    }
    let kinds: Vec<BackupKind> = f.service().list_backups().unwrap().into_iter().map(|b| b.kind).collect();
    assert_eq!(kinds.len(), 3);
    assert!(kinds.contains(&BackupKind::BeforeMigration));
    assert!(kinds.contains(&BackupKind::Automatic));
    assert!(kinds.contains(&BackupKind::Manual));
}
