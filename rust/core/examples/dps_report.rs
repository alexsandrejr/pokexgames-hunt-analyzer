//! Ranking de cada boss e exportação completa do DPS, num texto comparável com o de
//! `rust/tools/dps_report.py`. Use sempre uma cópia do banco.
//!
//! ```text
//! cargo run -q -p pxg-core --example dps_report -- <cópia.db> > rust.txt
//! ```

use std::collections::HashMap;

use chrono::NaiveDate;
use pxg_core::Database;
use pxg_core::dps::service::DpsService;
use pxg_core::dps::transfer::{build_bundle, bundle_to_json};
use pxg_core::format::NumberFormat;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = std::env::args().nth(1).ok_or("informe o caminho de uma cópia do banco")?;
    let database = Database::open(std::path::Path::new(&path))?;
    database.create_schema()?;
    let dps = DpsService::new(&database);
    let bosses = dps.list_bosses()?;
    for boss in &bosses {
        println!("== {} ({} s, {}, {})", boss.name, boss.time_limit_seconds, boss.damage_source.as_str(), boss.dummy);
        for entry in dps.ranking(boss.id, NumberFormat::PT_BR)? {
            println!(
                "{}. {} | total {:?} | dps {:?} | {:?} | sem teste {:?} | sem elemento {:?}",
                entry.position, entry.pokemon.name, entry.breakdown.total, entry.breakdown.dps,
                entry.share_of_leader, entry.missing, entry.no_element,
            );
            for line in &entry.breakdown.lines {
                println!("   {} | {} | {:?}", line.source, line.detail, line.total);
            }
        }
    }
    let names: HashMap<i64, String> = bosses.iter().map(|b| (b.id, b.name.clone())).collect();
    let bundle = build_bundle(&bosses, &dps.list_pokemons()?, &names);
    let moment = NaiveDate::from_ymd_opt(2026, 1, 1).unwrap().and_hms_opt(0, 0, 0);
    println!("{}", bundle_to_json(&bundle, moment).replace(pxg_core::APP_VERSION, "<versão>"));
    Ok(())
}
