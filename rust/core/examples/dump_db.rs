//! Abre um banco pelo Rust (migrando, se precisar) e escreve o esquema e todos os dados num
//! texto comparável com o de `rust/tools/dump_db.py`. Use sempre uma cópia do banco.
//!
//! ```text
//! cargo run -p pxg-core --example dump_db -- <cópia.db> > rust.txt
//! ```

use std::fmt::Write;

use pxg_core::Database;
use rusqlite::types::ValueRef;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = std::env::args().nth(1).ok_or("informe o caminho de uma cópia do banco")?;
    let database = Database::open(std::path::Path::new(&path))?;
    database.create_schema()?;
    let text = database.with(|c| Ok(dump(c)?))?;
    print!("{text}");
    Ok(())
}

fn dump(connection: &rusqlite::Connection) -> rusqlite::Result<String> {
    let mut out = String::new();
    let version: i64 = connection.pragma_query_value(None, "user_version", |r| r.get(0))?;
    writeln!(out, "-- user_version = {version}").unwrap();
    let mut objects = connection.prepare(
        "SELECT type, name, tbl_name, sql FROM sqlite_master \
         WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name",
    )?;
    let mut tables = Vec::new();
    let rows = objects.query_map([], |r| {
        Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?,
            r.get::<_, String>(3)?))
    })?;
    for row in rows {
        let (kind, name, table, sql) = row?;
        writeln!(out, "-- {kind} {name} ON {table}").unwrap();
        writeln!(out, "{};", sql.split_whitespace().collect::<Vec<_>>().join(" ")).unwrap();
        if kind == "table" {
            tables.push(name);
        }
    }
    for table in tables {
        writeln!(out, "== {table}").unwrap();
        let mut statement = connection.prepare(&format!("SELECT * FROM {table} ORDER BY rowid"))?;
        let columns = statement.column_count();
        let mut rows = statement.query([])?;
        while let Some(row) = rows.next()? {
            let values: Vec<String> = (0..columns)
                .map(|i| row.get_ref(i).map(value_text))
                .collect::<rusqlite::Result<_>>()?;
            writeln!(out, "{}", values.join(" | ")).unwrap();
        }
    }
    Ok(out)
}

fn value_text(value: ValueRef<'_>) -> String {
    match value {
        ValueRef::Null => "NULL".to_owned(),
        ValueRef::Integer(i) => i.to_string(),
        ValueRef::Real(f) => pxg_core::pyjson::python_float(f),
        ValueRef::Text(t) => serde_json::to_string(&String::from_utf8_lossy(t)).unwrap(),
        ValueRef::Blob(b) => format!("x'{}'", b.iter().map(|x| format!("{x:02x}")).collect::<String>()),
    }
}
