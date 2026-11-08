//! Porta de `tests/test_filters.py`: filtros executados contra o SQLite real (em memória).
//! Os testes de `parse_user_number` e `parse_user_duration` ficam em `parse.rs`.

mod common;

use chrono::NaiveDate;
use common::load_sample;
use pxg_core::Database;
use pxg_core::format::NumberFormat;
use pxg_core::hunts::filters::{
    DatePreset, HuntFilter, ItemCondition, ItemSource, Metric, MetricCondition, Operator,
    QuantityCondition, preset_range,
};
use pxg_core::hunts::service::HuntService;
use serde_json::{Value, json};

struct Hunt<'a> {
    session_id: i64,
    start: &'a str,
    player: &'a str,
    duration: i64,
    kills: i64,
    profit: i64,
    drops: &'a [(&'a str, i64)],
    enemies: &'a [(&'a str, i64)],
    supplies: &'a [(&'a str, i64)],
}

fn make_hunt(h: &Hunt<'_>) -> String {
    let mut data = load_sample();
    let session = &mut data["Session"];
    session["Session ID"] = json!(h.session_id);
    session["Start"] = json!(h.start);
    session["Duration seconds"] = json!(h.duration);
    session["Kills"] = json!(h.kills);
    session["Kills per hour"] = json!(h.kills as f64 * 3600. / h.duration as f64);
    session["Profit"] = json!(h.profit);
    session["Profit per hour"] = json!(h.profit as f64 * 3600. / h.duration as f64);
    let entries = |values: &[(&str, i64)], name_key: &str| -> Value {
        Value::Array(
            values
                .iter()
                .map(|(name, count)| {
                    json!({name_key: name, "Count": count, "Player": h.player, "Unit price": 100, "Total price": 100 * count})
                })
                .collect(),
        )
    };
    data["Drops"] = entries(h.drops, "Item");
    data["Enemies Defeated"] = entries(h.enemies, "Enemy");
    data["Supplies"] = entries(h.supplies, "Item");
    data.to_string()
}

fn database() -> Database {
    let database = Database::in_memory().unwrap();
    let base = Hunt { session_id: 0, start: "", player: "Royalzxd", duration: 3600, kills: 300, profit: 1_000_000, drops: &[], enemies: &[], supplies: &[] };
    let hunts = [
        Hunt { session_id: 1, start: "2026-09-01 10:00:00", duration: 3600, kills: 250, profit: 800_000,
            drops: &[("nightmare ore", 40), ("nightmare gem", 1200)], enemies: &[("Mecha Charizard", 30)], ..base },
        Hunt { session_id: 2, start: "2026-09-10 23:59:59", duration: 7200, kills: 640, profit: 2_000_000,
            drops: &[("nightmare ore", 80)], enemies: &[("Mecha Charizard", 50), ("Mecha Blastoise", 12)], ..base },
        Hunt { session_id: 3, start: "2026-09-11 00:00:00", player: "OutroPlayer", duration: 1800, kills: 160,
            profit: -50_000, drops: &[("metal scraps", 5)], enemies: &[("Mecha Venusaur", 20)],
            supplies: &[("Healing Elixir", 4)] },
        Hunt { session_id: 4, start: "2026-09-26 15:24:20", duration: 4310, kills: 368, profit: 1_119_522,
            drops: &[("nightmare gem", 900), ("Nightmare Ore", 60)], enemies: &[("Mecha Charizard", 40)], ..base },
    ];
    let service = HuntService::new(&database);
    for hunt in &hunts {
        assert!(service.import_text(&make_hunt(hunt), "", false, None).unwrap().hunt_id.is_some());
    }
    database
}

fn session_ids(database: &Database, filter: &HuntFilter) -> Vec<i64> {
    let mut ids: Vec<i64> = HuntService::new(database)
        .list_hunts(Some(filter))
        .unwrap()
        .iter()
        .map(|h| h.session_id.unwrap())
        .collect();
    ids.sort();
    ids
}

fn day(d: u32) -> Option<NaiveDate> {
    NaiveDate::from_ymd_opt(2026, 9, d)
}

#[test]
fn empty_filter_returns_all() {
    let db = database();
    assert_eq!(session_ids(&db, &HuntFilter::default()), [1, 2, 3, 4]);
    assert!(HuntFilter::default().is_empty());
}

#[test]
fn date_range_is_inclusive_by_day() {
    let db = database();
    let f = HuntFilter { date_from: day(10), date_to: day(10), ..Default::default() };
    assert_eq!(session_ids(&db, &f), [2]); // 23:59:59 do dia 10 entra; 00:00 do 11 não
    assert_eq!(session_ids(&db, &HuntFilter { date_from: day(11), ..Default::default() }), [3, 4]);
    assert_eq!(session_ids(&db, &HuntFilter { date_to: day(10), ..Default::default() }), [1, 2]);
}

#[test]
fn player_contains_case_insensitive() {
    let db = database();
    let player = |p: &str| HuntFilter { player: Some(p.to_owned()), ..Default::default() };
    assert_eq!(session_ids(&db, &player("royal")), [1, 2, 4]);
    assert_eq!(session_ids(&db, &player("OUTRO")), [3]);
    assert!(session_ids(&db, &player("100%")).is_empty());
}

#[test]
fn metric_operators() {
    let db = database();
    let ids = |metric, operator, value| {
        session_ids(&db, &HuntFilter { metrics: vec![MetricCondition { metric, operator, value }], ..Default::default() })
    };
    assert_eq!(ids(Metric::Profit, Operator::Gt, 1_000_000.), [2, 4]);
    assert_eq!(ids(Metric::Profit, Operator::Ge, 800_000.), [1, 2, 4]);
    assert_eq!(ids(Metric::Profit, Operator::Lt, 0.), [3]);
    assert_eq!(ids(Metric::Kills, Operator::Eq, 368.), [4]);
    assert_eq!(ids(Metric::Kills, Operator::Le, 250.), [1, 3]);
    // Sessão 3: 160 kills em 30 min = 320/h.
    assert_eq!(ids(Metric::KillsPerHour, Operator::Gt, 300.), [2, 3, 4]);
    assert_eq!(ids(Metric::Duration, Operator::Ge, 3600.), [1, 2, 4]);
    // Taxas decimais: "=" compara o valor arredondado (1119522×3600/4310 ≈ 935099,58).
    assert_eq!(ids(Metric::ProfitPerHour, Operator::Eq, 935_100.), [4]);
}

fn item(name: &str, comparison: Option<(Operator, f64)>, source: ItemSource) -> ItemCondition {
    let condition = match comparison {
        Some((operator, quantity)) => QuantityCondition::with(name, operator, quantity),
        None => QuantityCondition::present(name),
    };
    ItemCondition { condition, source }
}

#[test]
fn item_presence_and_quantity() {
    let db = database();
    let ids = |items: Vec<ItemCondition>| session_ids(&db, &HuntFilter { items, ..Default::default() });
    let drop = |name, comparison| item(name, comparison, ItemSource::Drops);
    assert_eq!(ids(vec![drop("Nightmare ore", None)]), [1, 2, 4]); // sem diferenciar caixa
    assert_eq!(ids(vec![drop("nightmare ore", Some((Operator::Gt, 50.)))]), [2, 4]);
    // Sessões sem o item contam como 0 em comparações de quantidade.
    assert_eq!(ids(vec![drop("nightmare ore", Some((Operator::Lt, 50.)))]), [1, 3]);
    assert_eq!(
        ids(vec![drop("nightmare ore", Some((Operator::Gt, 50.))), drop("nightmare gem", Some((Operator::Gt, 800.)))]),
        [4]
    );
    assert!(ids(vec![drop("Healing Elixir", None)]).is_empty()); // só em supplies
    assert_eq!(ids(vec![item("Healing Elixir", None, ItemSource::Supplies)]), [3]);
}

#[test]
fn enemy_presence_and_quantity() {
    let db = database();
    let ids = |enemies: Vec<QuantityCondition>| session_ids(&db, &HuntFilter { enemies, ..Default::default() });
    assert_eq!(ids(vec![QuantityCondition::present("mecha charizard")]), [1, 2, 4]);
    assert_eq!(ids(vec![QuantityCondition::with("Mecha Charizard", Operator::Ge, 40.)]), [2, 4]);
    assert_eq!(
        ids(vec![QuantityCondition::present("Mecha Charizard"), QuantityCondition::present("Mecha Blastoise")]),
        [2]
    );
}

#[test]
fn all_criteria_combined() {
    let db = database();
    let metrics = vec![
        MetricCondition { metric: Metric::ProfitPerHour, operator: Operator::Gt, value: 800_000. },
        MetricCondition { metric: Metric::KillsPerHour, operator: Operator::Gt, value: 250. },
    ];
    let f = HuntFilter {
        date_from: day(1),
        date_to: day(26),
        player: Some("Royalzxd".into()),
        items: vec![item("nightmare ore", Some((Operator::Gt, 50.)), ItemSource::Drops)],
        metrics: metrics.clone(),
        ..Default::default()
    };
    assert_eq!(session_ids(&db, &f), [2, 4]);
    // Remover o critério de item não traz a sessão 3 (player e profit/h a excluem).
    assert_eq!(session_ids(&db, &HuntFilter { player: Some("Royalzxd".into()), metrics, ..Default::default() }), [2, 4]);
    assert_eq!(HuntService::new(&db).count_hunts(Some(&f)).unwrap(), 2);
}

#[test]
fn describe() {
    let f = HuntFilter {
        date_from: day(1),
        date_to: day(26),
        player: Some("Royalzxd".into()),
        enemies: vec![QuantityCondition::present("Mecha Charizard")],
        items: vec![item("nightmare ore", Some((Operator::Gt, 50.)), ItemSource::Drops)],
        metrics: vec![
            MetricCondition { metric: Metric::KillsPerHour, operator: Operator::Gt, value: 250. },
            MetricCondition { metric: Metric::Duration, operator: Operator::Ge, value: 3600. },
        ],
        ..Default::default()
    };
    assert_eq!(f.describe(NumberFormat::PT_BR), [
        "Data: 01/09/2026 a 26/09/2026", "Player: Royalzxd", "Inimigo: Mecha Charizard",
        "Drop: nightmare ore > 50", "Kills/h > 250", "Duração >= 01:00:00",
    ]);
    assert!(!f.is_empty());
}

#[test]
fn filter_options() {
    let db = database();
    let options = HuntService::new(&db).filter_options().unwrap();
    assert_eq!(options.players, ["OutroPlayer", "Royalzxd"]);
    assert!(options.enemies.contains(&"Mecha Blastoise".to_owned()));
    assert!(options.drop_items.contains(&"nightmare gem".to_owned()));
    assert_eq!(options.supply_items, ["Healing Elixir"]);
}

#[test]
fn presets() {
    let date = |y, m, d| NaiveDate::from_ymd_opt(y, m, d).unwrap();
    let today = date(2026, 9, 26);
    let range = |preset, today| preset_range(preset, today);
    assert_eq!(range(DatePreset::All, today), (None, None));
    assert_eq!(range(DatePreset::Today, today), (Some(today), Some(today)));
    assert_eq!(range(DatePreset::Last7Days, today), (Some(date(2026, 9, 20)), Some(today)));
    assert_eq!(range(DatePreset::Last30Days, today), (Some(date(2026, 8, 28)), Some(today)));
    assert_eq!(range(DatePreset::ThisMonth, today), (Some(date(2026, 9, 1)), Some(today)));
    assert_eq!(range(DatePreset::LastMonth, today), (Some(date(2026, 8, 1)), Some(date(2026, 8, 31))));
    assert_eq!(range(DatePreset::LastMonth, date(2026, 3, 15)), (Some(date(2026, 2, 1)), Some(date(2026, 2, 28))));
    assert_eq!(range(DatePreset::LastMonth, date(2026, 1, 5)), (Some(date(2025, 12, 1)), Some(date(2025, 12, 31))));
}
