//! A mesma sequência de operações de `rust/tools/hunts_scenario.py`, num banco novo.
//!
//! ```text
//! cargo run -q -p pxg-core --example hunts_scenario -- <banco-novo.db> <arquivo>...
//! ```

use std::path::Path;

use pxg_core::Database;
use pxg_core::hunts::categories::Category;
use pxg_core::hunts::model::ImportStatus;
use pxg_core::hunts::service::HuntService;
use pxg_core::prices::PriceService;

const CHAT: &str = "Você recebeu: 15 Echo Shards, 2 Mystic Stars, 84 hundred dollars, 4 Heart Stones, \
    3 nightmare gems, 2 metal scraps.";
const PRICES: [(&str, f64); 5] = [("nightmare gem", 333.5), ("Metal Scraps", 2500.), ("Healing Elixir", 9999.),
    ("turtle spike", 7000.25), ("Heart Stone", 1000.)];

fn list(ids: &[i64]) -> String {
    format!("[{}]", ids.iter().map(i64::to_string).collect::<Vec<_>>().join(", "))
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let database = Database::open(Path::new(&args[0]))?;
    database.create_schema()?;
    let (hunts, prices) = (HuntService::new(&database), PriceService::new(&database));
    let mut log = Vec::new();
    for (index, path) in args[1..].iter().enumerate() {
        let category = [None, Some(Category::Terror), None, Some(Category::Rift)][index % 4];
        let result = hunts.import_file(Path::new(path), index % 5 == 4, category)?;
        let status = match result.status {
            ImportStatus::Imported => "imported",
            ImportStatus::Duplicate => "duplicate",
            ImportStatus::Error => "error",
        };
        let name = Path::new(path).file_name().unwrap().to_string_lossy();
        let category = result.category.map_or("None", Category::as_str);
        log.push(format!("{name}: {status} {} {} {category}", result.message, list(&result.duplicate_of)));
    }
    let ids: Vec<i64> = hunts.list_hunts(None)?.iter().map(|h| h.id).collect();
    for (name, price) in &PRICES[..3] {
        log.push(format!("preço {name}: {}", prices.set_price(name, *price)?));
    }
    for hunt_id in ids.iter().take(3) {
        match hunts.add_chat_rewards(*hunt_id, CHAT, None) {
            Ok(count) => log.push(format!("chat {hunt_id}: {count}")),
            Err(pxg_core::Error::User(error)) => log.push(format!("chat {hunt_id}: {error}")),
            Err(error) => return Err(error.into()),
        }
    }
    for (name, price) in &PRICES[3..] {
        log.push(format!("preço {name}: {}", prices.set_price(name, *price)?));
    }
    if !ids.is_empty() {
        log.push(format!("remover chat {}: {}", ids[0], hunts.remove_chat_rewards(ids[0])?));
        log.push(format!("limpar preço: {}", prices.clear_price("NIGHTMARE GEM")?));
        log.push(format!("categoria: {}", hunts.set_category(&ids[ids.len().saturating_sub(2)..], Category::BossBlue)?));
        log.push(format!("excluir: {}", hunts.delete_hunts(&ids[ids.len() - 1..])?));
    }
    database.with(|c| {
        for (table, column) in [("hunt_sessions", "created_at"), ("chat_rewards", "created_at"), ("item_prices", "updated_at")] {
            c.execute(&format!("UPDATE {table} SET {column} = '2000-01-01 00:00:00.000000'"), [])?;
        }
        Ok(())
    })?;
    println!("{}", log.join("\n"));
    Ok(())
}
