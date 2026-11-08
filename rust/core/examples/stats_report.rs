//! Estatísticas num texto comparável com o de `rust/tools/stats_report.py`.
//!
//! ```text
//! cargo run -q -p pxg-core --example stats_report -- <cópia.db>
//! ```

use std::fmt::Display;

use pxg_core::Database;
use pxg_core::format::NumberFormat;
use pxg_core::hunts::advanced_search::parse_advanced_query;
use pxg_core::hunts::categories::Category;
use pxg_core::hunts::filters::HuntFilter;
use pxg_core::hunts::service::HuntService;
use pxg_core::hunts::statistics::{EntityKind, StatisticsService};
use pxg_core::pyjson::python_float;

const QUERIES: [&str; 8] = ["nightmare gem > 100 e kills/h >= 300", "profit/h > 1kk; duração >= 1h", "drop: kills",
    "inimigo: mecha mew > 2", "metal scraps", "unobtainium > 3", "lucro < -0,5kk", "tempo ≤ 30min"];

fn f(value: Option<f64>) -> String {
    value.map_or("None".to_owned(), python_float)
}

fn i<T: Display>(value: Option<T>) -> String {
    value.map_or("None".to_owned(), |v| v.to_string())
}

/// Lista como o `repr` do Python a escreve.
fn py_list<T: Display>(items: impl IntoIterator<Item = T>, quote: bool) -> String {
    let items: Vec<String> = items
        .into_iter()
        .map(|x| if quote { format!("'{x}'") } else { x.to_string() })
        .collect();
    format!("[{}]", items.join(", "))
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = std::env::args().nth(1).ok_or("informe uma cópia do banco")?;
    let database = Database::open(std::path::Path::new(&path))?;
    let (hunts, stats) = (HuntService::new(&database), StatisticsService::new(&database));
    let mut lines = Vec::new();
    let mut scopes = vec![("todas".to_owned(), HuntFilter::default())];
    scopes.extend(Category::ALL.iter().map(|c| (c.as_str().to_owned(), HuntFilter::default().scoped(&[*c]))));
    for (scope, filter) in &scopes {
        lines.push(format!("== {scope}"));
        let o = stats.overview(Some(filter))?;
        let moment = |m: Option<chrono::NaiveDateTime>| m.map_or("None".to_owned(), |m| m.format("%Y-%m-%d %H:%M:%S").to_string());
        let fields = [
            ("hunt_count", o.hunt_count.to_string()), ("total_duration_seconds", o.total_duration_seconds.to_string()),
            ("total_kills", o.total_kills.to_string()), ("total_profit", o.total_profit.to_string()),
            ("total_supplies", o.total_supplies.to_string()), ("total_raw_gains", o.total_raw_gains.to_string()),
            ("total_experience", o.total_experience.to_string()), ("total_damage_dealt", o.total_damage_dealt.to_string()),
            ("total_damage_taken", o.total_damage_taken.to_string()), ("average_profit", f(o.average_profit)),
            ("average_profit_per_hour", f(o.average_profit_per_hour)), ("average_kills_per_hour", f(o.average_kills_per_hour)),
            ("average_supplies_per_hour", f(o.average_supplies_per_hour)),
            ("average_damage_dealt_per_second", f(o.average_damage_dealt_per_second)),
            ("first_start", moment(o.first_start)), ("last_start", moment(o.last_start)),
            ("average_duration_seconds", f(o.average_duration_seconds())), ("average_kills", f(o.average_kills())),
            ("profit_per_total_hour", f(o.profit_per_total_hour())), ("kills_per_total_hour", f(o.kills_per_total_hour())),
            ("supplies_per_total_hour", f(o.supplies_per_total_hour())),
            ("raw_gains_per_total_hour", f(o.raw_gains_per_total_hour())), ("duration_per_kill", f(o.duration_per_kill())),
            ("profit_per_kill", f(o.profit_per_kill())), ("supplies_per_kill", f(o.supplies_per_kill())),
            ("raw_gains_per_kill", f(o.raw_gains_per_kill())), ("experience_per_kill", f(o.experience_per_kill())),
        ];
        lines.extend(fields.iter().map(|(name, value)| format!("{name}={value}")));
        for m in stats.metric_breakdown(Some(filter))? {
            lines.push(format!(
                "metric {} | {} | {} | {} | {} | {} | {}",
                m.key, i(m.total), f(m.average), i(m.minimum), i(m.maximum), f(m.average_rate), f(m.rate_over_total_time)
            ));
        }
        for kind in [EntityKind::Drops, EntityKind::Supplies, EntityKind::Enemies] {
            let key = match kind { EntityKind::Drops => "drops", EntityKind::Supplies => "supplies", EntityKind::Enemies => "enemies" };
            let entries = stats.top(kind, Some(filter), 20)?;
            for e in &entries {
                lines.push(format!("top {key} | {} | {} | {} | {} | {}", e.name, e.quantity, i(e.value), e.hunt_count, f(e.average_per_hunt())));
            }
            for e in entries.iter().take(3) {
                let r = stats.entity_report(kind, &e.name, Some(filter))?;
                let values = [
                    r.hunt_count().to_string(), r.present_count().to_string(), f(r.presence_ratio()),
                    r.total_quantity().to_string(), i(r.total_value()), f(r.average_per_hunt()),
                    f(r.average_value_per_hunt()), r.present_duration_seconds().to_string(), f(r.per_hour()), f(r.value_per_hour()),
                ];
                let extremes = format!("[{}, {}]", i(r.max_row().map(|x| x.hunt_id)), i(r.min_row().map(|x| x.hunt_id)));
                let rows = py_list(r.rows.iter().map(|x| format!("({}, {}, {})", x.hunt_id, x.quantity, i(x.value))), false);
                lines.push(format!("report {key} {} | {} | {extremes} | {rows}", e.name, values.join(" | ")));
            }
        }
        for d in stats.damage_by_element(Some(filter))? {
            lines.push(format!("damage {} | {} | {} | {} | {}", d.element, d.dealt, d.taken, f(d.dealt_share), f(d.taken_share)));
        }
    }
    let options = hunts.filter_options()?;
    for text in QUERIES {
        let query = parse_advanced_query(text, &options, NumberFormat::PT_BR);
        let merged = query.merged_into(&HuntFilter::default());
        let ids: Vec<i64> = if query.ok() { hunts.list_hunts(Some(&merged))?.iter().map(|h| h.id).collect() } else { Vec::new() };
        lines.push(format!(
            "query {text} | {} | {} {} {} | {} | {}",
            py_list(&query.errors, true), query.items.len(), query.enemies.len(), query.metrics.len(),
            py_list(merged.describe(NumberFormat::PT_BR), true), py_list(ids, false)
        ));
    }
    println!("{}", lines.join("\n"));
    Ok(())
}
