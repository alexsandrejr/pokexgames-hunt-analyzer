//! Leitura de arquivos do Analyzer, num texto comparável com o de `rust/tools/parse_report.py`.
//!
//! ```text
//! cargo run -q -p pxg-core --example parse_report -- <arquivo.json|.tsv>...
//! cargo run -q -p pxg-core --example parse_report -- --db <cópia.db>
//! ```
//!
//! Com `--db`, lê o `raw_json` de cada sessão e confere o hash com o `content_hash` gravado.

use std::fmt::Write;
use std::path::Path;

use chrono::NaiveDateTime;
use pxg_core::hunts::analyzer::{ParsedHunt, parse_analyzer_json, parse_analyzer_text, read_analyzer_file};
use pxg_core::pyjson::python_float;
use sha2::{Digest, Sha256};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut out = String::new();
    if args.first().map(String::as_str) == Some("--db") {
        let connection = rusqlite::Connection::open_with_flags(&args[1], rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)?;
        let mut statement = connection.prepare("SELECT id, raw_json, content_hash FROM hunt_sessions ORDER BY id")?;
        let rows = statement.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?)))?;
        for row in rows {
            let (id, raw, stored) = row?;
            match parse_analyzer_json(&raw, None) {
                Ok(parsed) => {
                    writeln!(out, "## sessão {id}: hash {}", if parsed.content_hash == stored { "igual" } else { "DIFERENTE" })?;
                    report(&mut out, &parsed);
                }
                Err(error) => writeln!(out, "## sessão {id}: erro {} ({:?})", error.message, error.kind)?,
            }
        }
    } else {
        for path in &args {
            let name = Path::new(path).file_name().and_then(|n| n.to_str()).map(str::to_owned);
            writeln!(out, "## {}", name.clone().unwrap_or_default())?;
            match read_analyzer_file(Path::new(path)).and_then(|text| parse_analyzer_text(&text, name)) {
                Ok(parsed) => report(&mut out, &parsed),
                Err(error) => writeln!(out, "erro {}", error.message)?,
            }
        }
    }
    print!("{out}");
    Ok(())
}

fn int(value: Option<i64>) -> String {
    value.map_or("None".to_owned(), |v| v.to_string())
}

fn float(value: Option<f64>) -> String {
    value.map_or("None".to_owned(), python_float)
}

fn text(value: &Option<String>) -> String {
    value.as_ref().map_or("None".to_owned(), |v| serde_json::to_string(v).unwrap())
}

fn flag(value: Option<bool>) -> String {
    match value {
        Some(true) => "True",
        Some(false) => "False",
        None => "None",
    }
    .to_owned()
}

fn moment(value: Option<NaiveDateTime>) -> String {
    value.map_or("None".to_owned(), |v| v.format("%Y-%m-%d %H:%M:%S").to_string())
}

fn report(out: &mut String, parsed: &ParsedHunt) {
    let s = &parsed.session;
    let fields = [
        ("session_id", int(s.session_id)), ("player", text(&s.player)), ("start", moment(s.start_datetime)),
        ("duration", int(s.duration_seconds)), ("paused", int(s.paused_seconds)), ("status", text(&s.status)),
        ("type", text(&s.session_type)), ("kills", int(s.kills)), ("kills_h", float(s.kills_per_hour)),
        ("rare", int(s.rare_kills)), ("rare_h", float(s.rare_kills_per_hour)), ("xp", int(s.experience)),
        ("xp_h", float(s.experience_per_hour)), ("profit", int(s.profit)), ("profit_h", float(s.profit_per_hour)),
        ("supplies", int(s.supplies)), ("supplies_h", float(s.supplies_per_hour)), ("raw", int(s.raw_gains)),
        ("raw_h", float(s.raw_gains_per_hour)), ("dealt", int(s.damage_dealt)),
        ("dealt_s", float(s.damage_dealt_per_second)), ("taken", int(s.damage_taken)),
        ("taken_s", float(s.damage_taken_per_second)), ("next", text(&s.time_to_next_level)),
        ("next_s", int(s.time_to_next_level_seconds)),
    ];
    writeln!(out, "hash {}", parsed.content_hash).unwrap();
    writeln!(out, "source {}", text(&parsed.source_file)).unwrap();
    for (name, value) in fields {
        writeln!(out, "{name}={value}").unwrap();
    }
    for e in &parsed.enemies {
        writeln!(out, "enemy {} | {} | {} | {} | {}", text(&Some(e.enemy.clone())), e.count, text(&e.player), flag(e.rare), flag(e.ignored)).unwrap();
    }
    for (kind, items) in [("drop", &parsed.drops), ("supply", &parsed.supplies)] {
        for i in items {
            writeln!(out, "{kind} {} | {} | {} | {} | {} | {}", text(&Some(i.item.clone())), i.count, float(i.unit_price), int(i.total_price), text(&i.player), flag(i.ignored)).unwrap();
        }
    }
    for warning in &parsed.warnings {
        writeln!(out, "warning {warning}").unwrap();
    }
    let digest: String = Sha256::digest(parsed.raw_json.as_bytes()).iter().map(|b| format!("{b:02x}")).collect();
    writeln!(out, "raw_json {digest}").unwrap();
}
