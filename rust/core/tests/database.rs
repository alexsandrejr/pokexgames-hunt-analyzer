//! Porta de `tests/test_migrations.py`, mais a paridade do esquema com o app Python.

mod common;

use pxg_core::db::migrations::{LATEST_VERSION, column_names};
use pxg_core::db::{Database, open_and_migrate, schema};
use pxg_core::Error;

const PYTHON_SCHEMA: &str = include_str!("fixtures/schema_python.sql");

struct Fixture {
    dir: tempfile::TempDir,
}

impl Fixture {
    fn new() -> Self {
        Self { dir: tempfile::tempdir().unwrap() }
    }

    fn path(&self) -> std::path::PathBuf {
        self.dir.path().join("hunts.db")
    }

    fn open(&self) -> Database {
        Database::open(&self.path()).unwrap()
    }
}

fn versions(applied: &[&pxg_core::db::migrations::Migration]) -> Vec<i64> {
    applied.iter().map(|m| m.version).collect()
}

fn indexes(database: &Database, table: &str) -> Vec<String> {
    database
        .with(|c| {
            let mut statement =
                c.prepare("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ?1")?;
            let names = statement.query_map([table], |r| r.get(0))?;
            Ok(names.collect::<rusqlite::Result<_>>()?)
        })
        .unwrap()
}

#[test]
fn new_database_is_identical_to_the_one_python_creates() {
    // A referência é gerada pelo app Python (ver docs/migracao-rust.md). Se um dia o Python
    // mudar o esquema, gere-a de novo e faça a mesma mudança aqui.
    let fixture = Fixture::new();
    let database = fixture.open();
    database.create_schema().unwrap();
    let dump = database.with(|c| Ok(common::dump_schema(c))).unwrap();
    assert_eq!(dump, PYTHON_SCHEMA.replace("\r\n", "\n"));
    let boss: (String, i64, String, String) = database
        .with(|c| {
            Ok(c.query_row(
                "SELECT name, time_limit_seconds, dummy, damage_source FROM dps_bosses",
                [],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
            )?)
        })
        .unwrap();
    assert_eq!(boss, ("Padrão".to_owned(), 420, "neutral".to_owned(), "dummy".to_owned()));
}

#[test]
fn new_database_is_created_at_latest_version() {
    let fixture = Fixture::new();
    let database = fixture.open();
    let applied = database.create_schema().unwrap();
    assert_eq!(versions(&applied), (1..=LATEST_VERSION).collect::<Vec<_>>());
    assert_eq!(database.schema_version().unwrap(), LATEST_VERSION);
    assert!(indexes(&database, "drops").contains(&"ix_drops_item_lower".to_owned()));
    assert!(indexes(&database, "enemies_defeated")
        .contains(&"ix_enemies_defeated_enemy_lower".to_owned()));
    assert!(database.create_schema().unwrap().is_empty()); // idempotente
}

#[test]
fn phase1_database_is_upgraded_keeping_data() {
    // Banco como a Fase 1 criava: só as tabelas, sem versão (user_version = 0).
    let fixture = Fixture::new();
    {
        let old = fixture.open();
        old.with(|c| {
            for table in schema::TABLES.iter() {
                for statement in &table.statements {
                    c.execute_batch(statement)?;
                }
            }
            common::insert_hunt(c, 1080);
            Ok(())
        })
        .unwrap();
        assert_eq!(old.schema_version().unwrap(), 0);
    }
    let database = fixture.open();
    assert_eq!(versions(&database.pending_migrations().unwrap()), (1..=LATEST_VERSION).collect::<Vec<_>>());
    database.create_schema().unwrap();
    assert_eq!(database.schema_version().unwrap(), LATEST_VERSION);
    assert_eq!(database.with(|c| Ok(common::count_hunts(c))).unwrap(), 1);
    assert!(database.pending_migrations().unwrap().is_empty());
}

#[test]
fn version2_database_gets_original_price_columns() {
    // Banco da versão 2: drops e supplies ainda sem as colunas de preço original.
    let fixture = Fixture::new();
    {
        let old = fixture.open();
        old.create_schema().unwrap();
        old.with(|c| {
            common::insert_hunt(c, 1080);
            for table in ["drops", "supplies"] {
                for column in ["original_unit_price", "original_total_price"] {
                    c.execute_batch(&format!("ALTER TABLE {table} DROP COLUMN {column}"))?;
                }
            }
            c.pragma_update(None, "user_version", 2)?;
            Ok(())
        })
        .unwrap();
    }
    let database = fixture.open();
    assert_eq!(versions(&database.create_schema().unwrap()), (3..=LATEST_VERSION).collect::<Vec<_>>());
    let rows: Vec<(f64, f64, i64, i64)> = database
        .with(|c| {
            let mut statement = c.prepare(
                "SELECT unit_price, original_unit_price, total_price, original_total_price \
                 FROM drops",
            )?;
            let rows = statement.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))?;
            Ok(rows.collect::<rusqlite::Result<_>>()?)
        })
        .unwrap();
    assert!(!rows.is_empty());
    for (unit, original_unit, total, original_total) in rows {
        assert_eq!((original_unit, original_total), (unit, total));
    }
}

#[test]
fn version7_database_loses_the_typed_damage_columns() {
    // A migração 8 apaga as colunas de dano digitado do DPS.
    let fixture = Fixture::new();
    {
        let old = fixture.open();
        old.create_schema().unwrap();
        old.with(|c| {
            c.execute_batch(
                "ALTER TABLE dps_skills ADD COLUMN damage FLOAT; \
                 ALTER TABLE dps_pokemons ADD COLUMN basic_damage FLOAT; \
                 ALTER TABLE dps_bosses DROP COLUMN dummy;",
            )?;
            c.pragma_update(None, "user_version", 7)?;
            Ok(())
        })
        .unwrap();
    }
    let database = fixture.open();
    database.create_schema().unwrap();
    let skills = database.with(|c| column_names(c, "dps_skills")).unwrap();
    let pokemons = database.with(|c| column_names(c, "dps_pokemons")).unwrap();
    let bosses = database.with(|c| column_names(c, "dps_bosses")).unwrap();
    assert!(!skills.contains(&"damage".to_owned()));
    assert!(!pokemons.contains(&"basic_damage".to_owned()));
    assert!(bosses.contains(&"dummy".to_owned()));
}

#[test]
fn item_filter_uses_the_lowercase_index() {
    let database = Database::in_memory().unwrap();
    let plan: String = database
        .with(|c| {
            let mut statement = c.prepare(
                "EXPLAIN QUERY PLAN SELECT hunt_id FROM drops WHERE lower(item) = 'nightmare ore'",
            )?;
            let rows = statement.query_map([], |r| r.get::<_, String>(3))?;
            Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?.join(" "))
        })
        .unwrap();
    assert!(plan.contains("ix_drops_item_lower"), "{plan}");
}

#[test]
fn database_from_newer_app_is_refused_without_changes() {
    let fixture = Fixture::new();
    let database = fixture.open();
    database.create_schema().unwrap();
    database
        .with(|c| Ok(c.pragma_update(None, "user_version", LATEST_VERSION + 1)?))
        .unwrap();
    match database.create_schema() {
        Err(Error::SchemaTooNew { current, latest }) => {
            assert_eq!((current, latest), (LATEST_VERSION + 1, LATEST_VERSION));
        }
        other => panic!("esperava SchemaTooNew, veio {other:?}"),
    }
    let message = database.create_schema().unwrap_err().to_string();
    assert!(message.contains("Atualize o aplicativo"), "{message}");
}

#[test]
fn foreign_keys_cascade() {
    let database = Database::in_memory().unwrap();
    let remaining: i64 = database
        .with(|c| {
            let hunt = common::insert_hunt(c, 1);
            c.execute("DELETE FROM hunt_sessions WHERE id = ?1", [hunt])?;
            Ok(c.query_row("SELECT COUNT(*) FROM drops", [], |r| r.get(0))?)
        })
        .unwrap();
    assert_eq!(remaining, 0);
}

#[test]
fn transaction_is_undone_on_error() {
    let database = Database::in_memory().unwrap();
    let result: pxg_core::Result<()> = database.transaction(|tx| {
        common::insert_hunt(tx, 1);
        Err(Error::user("falhou no meio"))
    });
    assert!(result.is_err());
    assert_eq!(database.with(|c| Ok(common::count_hunts(c))).unwrap(), 0);
}

#[test]
fn opening_an_old_database_makes_a_backup_first() {
    let fixture = Fixture::new();
    {
        let old = fixture.open();
        old.create_schema().unwrap();
        old.with(|c| Ok(c.pragma_update(None, "user_version", 9)?)).unwrap();
    }
    let database = open_and_migrate(&fixture.path()).unwrap();
    assert_eq!(database.schema_version().unwrap(), LATEST_VERSION);
    let backups: Vec<String> = std::fs::read_dir(fixture.dir.path().join("backups"))
        .unwrap()
        .map(|e| e.unwrap().file_name().into_string().unwrap())
        .collect();
    assert_eq!(backups.len(), 1);
    assert!(backups[0].ends_with("_antes-atualizacao.db"), "{backups:?}");

    // Um banco novo, sem dados, não ganha backup.
    let fresh = fixture.dir.path().join("novo").join("hunts.db");
    open_and_migrate(&fresh).unwrap();
    assert!(!fixture.dir.path().join("novo").join("backups").exists());
}
