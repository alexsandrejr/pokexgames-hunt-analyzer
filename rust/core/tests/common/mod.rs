//! Utilitários compartilhados pelos testes (equivale a `tests/helpers.py`).

#![allow(dead_code)]

use rusqlite::Connection;

/// `sqlite_master` no mesmo formato de `tests/fixtures/schema_python.sql`.
pub fn dump_schema(connection: &Connection) -> String {
    let version: i64 = connection.pragma_query_value(None, "user_version", |r| r.get(0)).unwrap();
    let mut statement = connection
        .prepare(
            "SELECT type, name, tbl_name, sql FROM sqlite_master \
             WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name",
        )
        .unwrap();
    let rows = statement
        .query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?,
                r.get::<_, String>(3)?))
        })
        .unwrap();
    let mut lines = vec![format!("-- user_version = {version}")];
    for row in rows {
        let (kind, name, table, sql) = row.unwrap();
        lines.push(format!("-- {kind} {name} ON {table}"));
        lines.push(format!("{};", sql.split_whitespace().collect::<Vec<_>>().join(" ")));
    }
    lines.join("\n") + "\n"
}

/// Sessão mínima com um drop e um supply, como a importação grava.
pub fn insert_hunt(connection: &Connection, session_id: i64) -> i64 {
    connection
        .execute(
            "INSERT INTO hunt_sessions (session_id, player, content_hash, raw_json, created_at) \
             VALUES (?1, 'Royalzxd', ?2, '{}', '2026-11-07 10:00:00.000000')",
            rusqlite::params![session_id, format!("hash-{session_id}")],
        )
        .unwrap();
    let hunt_id = connection.last_insert_rowid();
    for table in ["drops", "supplies"] {
        connection
            .execute(
                &format!(
                    "INSERT INTO {table} (hunt_id, item, count, unit_price, total_price) \
                     VALUES (?1, 'Nightmare Ore', 3, 1500.0, 4500)"
                ),
                [hunt_id],
            )
            .unwrap();
    }
    hunt_id
}

pub fn count_hunts(connection: &Connection) -> i64 {
    connection.query_row("SELECT COUNT(*) FROM hunt_sessions", [], |r| r.get(0)).unwrap()
}

/// Fixtures copiadas de `tests/fixtures` do app Python.
pub fn fixture(name: &str) -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fixtures").join(name)
}

pub fn sample_hunt_path() -> std::path::PathBuf {
    fixture("sample_hunt.json")
}

pub fn load_sample() -> serde_json::Value {
    serde_json::from_str(&std::fs::read_to_string(sample_hunt_path()).unwrap()).unwrap()
}

/// JSON de exemplo com campos da `Session` sobrescritos (como `sample_text` do Python).
pub fn sample_text(overrides: &[(&str, serde_json::Value)]) -> String {
    let mut data = load_sample();
    for (key, value) in overrides {
        data["Session"][*key] = value.clone();
    }
    data.to_string()
}

/// Sessão de exemplo com início, duração e listas trocadas (como `make_hunt` de
/// `tests/test_filters.py`, com player Royalzxd, 300 kills e profit 1.000.000).
pub fn hunt_text(
    session_id: i64,
    start: &str,
    duration: i64,
    drops: &[(&str, i64)],
    enemies: &[(&str, i64)],
    supplies: &[(&str, i64)],
) -> String {
    use serde_json::{Value, json};
    let (kills, profit) = (300_i64, 1_000_000_i64);
    let mut data = load_sample();
    let session = &mut data["Session"];
    session["Session ID"] = json!(session_id);
    session["Start"] = json!(start);
    session["Duration seconds"] = json!(duration);
    session["Kills"] = json!(kills);
    session["Kills per hour"] = json!(kills as f64 * 3600. / duration as f64);
    session["Profit"] = json!(profit);
    session["Profit per hour"] = json!(profit as f64 * 3600. / duration as f64);
    let entries = |values: &[(&str, i64)], key: &str| -> Value {
        Value::Array(values.iter().map(|(name, count)| {
            json!({key: name, "Count": count, "Player": "Royalzxd", "Unit price": 100, "Total price": 100 * count})
        }).collect())
    };
    data["Drops"] = entries(drops, "Item");
    data["Enemies Defeated"] = entries(enemies, "Enemy");
    data["Supplies"] = entries(supplies, "Item");
    data.to_string()
}
