//! Porta de `tests/test_statistics.py`, `tests/test_entity_report.py`,
//! `tests/test_advanced_search.py` e das estatísticas de `tests/test_bosses.py`.

mod common;

use chrono::NaiveDate;
use common::{fixture, hunt_text, sample_hunt_path, sample_text};
use pxg_core::Database;
use pxg_core::format::NumberFormat;
use pxg_core::hunts::advanced_search::{AdvancedQuery, parse_advanced_query};
use pxg_core::hunts::categories::Category;
use pxg_core::hunts::filters::{HuntFilter, ItemCondition, ItemSource, Metric, MetricCondition, Operator, QuantityCondition};
use pxg_core::hunts::model::FilterOptions;
use pxg_core::hunts::service::HuntService;
use pxg_core::hunts::statistics::{EntityKind, RateUnit, StatisticsService, damage_by_element, rate_per_hour};
use serde_json::{Value, json};

fn close(actual: Option<f64>, expected: f64) {
    let actual = actual.expect("valor presente");
    assert!((actual - expected).abs() < 1e-6, "{actual} ≠ {expected}");
}

fn import(database: &Database, text: &str, category: Option<Category>) {
    HuntService::new(database).import_text(text, "", false, category).unwrap();
}

fn nobody() -> HuntFilter {
    HuntFilter { player: Some("ninguém".into()), ..Default::default() }
}

fn duration(operator: Operator, value: f64) -> HuntFilter {
    HuntFilter { metrics: vec![MetricCondition { metric: Metric::Duration, operator, value }], ..Default::default() }
}

// ------------------------------------------------------------- estatísticas

#[test]
fn rate() {
    close(rate_per_hour(Some(1119522), Some(4310)), 935099.5823665893);
    assert_eq!(rate_per_hour(Some(100), Some(1800)), Some(200.));
    assert_eq!(rate_per_hour(Some(100), Some(0)), None);
    assert_eq!(rate_per_hour(Some(100), None), None);
    assert_eq!(rate_per_hour(None, Some(3600)), None);
}

#[test]
fn empty_database() {
    let database = Database::in_memory().unwrap();
    let overview = StatisticsService::new(&database).overview(None).unwrap();
    assert_eq!((overview.hunt_count, overview.total_profit), (0, 0));
    assert_eq!(overview.average_profit_per_hour, None);
    assert_eq!(overview.profit_per_total_hour(), None);
}

fn two_hunts(database: &Database, extra: bool) {
    type Fields = Vec<(&'static str, Value)>;
    let (a, b): (Fields, Fields) = if extra {
        (
            vec![("Kills", json!(300)), ("Kills per hour", json!(300)), ("Supplies", json!(100_000)), ("Raw gains", json!(1_100_000))],
            vec![("Kills", json!(600)), ("Kills per hour", json!(200)), ("Supplies", json!(300_000)), ("Raw gains", json!(1_800_000))],
        )
    } else {
        (vec![], vec![])
    };
    let mut first = vec![("Session ID", json!(1)), ("Start", json!("2026-09-01 10:00:00")), ("Duration seconds", json!(3600)),
        ("Profit", json!(1_000_000)), ("Profit per hour", json!(1_000_000))];
    first.extend(a);
    let mut second = vec![("Session ID", json!(2)), ("Start", json!("2026-09-02 10:00:00")), ("Duration seconds", json!(10800)),
        ("Profit", json!(1_500_000)), ("Profit per hour", json!(500_000))];
    second.extend(b);
    import(database, &sample_text(&first), None);
    import(database, &sample_text(&second), None);
}

#[test]
fn totals_and_both_kinds_of_average() {
    let database = Database::in_memory().unwrap();
    two_hunts(&database, true);
    let o = StatisticsService::new(&database).overview(None).unwrap();
    assert_eq!((o.hunt_count, o.total_duration_seconds, o.total_profit), (2, 14400, 2_500_000));
    assert_eq!((o.total_kills, o.total_supplies, o.total_raw_gains), (900, 400_000, 2_900_000));
    // Média simples dos Profit/h individuais ≠ Profit total ÷ tempo total.
    close(o.average_profit_per_hour, 750_000.);
    close(o.profit_per_total_hour(), 625_000.);
    close(o.average_kills_per_hour, 250.);
    close(o.kills_per_total_hour(), 225.);
    assert_eq!(o.first_start.unwrap().format("%d").to_string(), "01");
    assert_eq!(o.last_start.unwrap().format("%d").to_string(), "02");
    assert_eq!(o.average_duration_seconds(), Some(7200.));
}

#[test]
fn overview_respects_filter() {
    let database = Database::in_memory().unwrap();
    two_hunts(&database, false);
    let stats = StatisticsService::new(&database);
    let long = stats.overview(Some(&duration(Operator::Gt, 3600.))).unwrap();
    assert_eq!((long.hunt_count, long.total_profit), (1, 1_500_000));
    let empty = stats.overview(Some(&nobody())).unwrap();
    assert_eq!(empty.hunt_count, 0);
    assert_eq!(empty.average_duration_seconds(), None);
}

#[test]
fn metric_breakdown() {
    let database = Database::in_memory().unwrap();
    two_hunts(&database, false);
    let metrics = StatisticsService::new(&database).metric_breakdown(None).unwrap();
    let find = |key| metrics.iter().find(|m| m.key == key).unwrap();
    let profit = find("profit");
    assert_eq!(profit.total, Some(2_500_000));
    assert_eq!(profit.average, Some(1_250_000.));
    assert_eq!((profit.minimum, profit.maximum), (Some(1_000_000), Some(1_500_000)));
    close(profit.average_rate, 750_000.); // média dos Profit/h
    close(profit.rate_over_total_time, 625_000.); // total ÷ 4h
    let duration = find("duration");
    assert_eq!((duration.total, duration.minimum, duration.maximum), (Some(14400), Some(3600), Some(10800)));
    assert_eq!(duration.rate_over_total_time, None);
    let dealt = find("damage_dealt");
    assert_eq!(dealt.rate_unit, Some(RateUnit::Second));
    close(dealt.rate_over_total_time, 2. * 119470652. / 14400.);
    assert_eq!(metrics.iter().take(3).map(|m| m.key).collect::<Vec<_>>(), ["duration", "kills", "profit"]);
}

#[test]
fn metric_breakdown_empty() {
    let database = Database::in_memory().unwrap();
    let metrics = StatisticsService::new(&database).metric_breakdown(Some(&nobody())).unwrap();
    assert!(metrics.iter().all(|m| m.total.is_none() && m.rate_over_total_time.is_none()));
}

#[test]
fn top_entries() {
    let database = Database::in_memory().unwrap();
    two_hunts(&database, false);
    let stats = StatisticsService::new(&database);
    let drops = stats.top(EntityKind::Drops, None, 20).unwrap();
    assert_eq!(drops.iter().map(|d| d.name.as_str()).collect::<Vec<_>>(), ["metal scraps", "nightmare gem"]); // por valor
    assert_eq!((drops[0].quantity, drops[0].value, drops[0].hunt_count), (2 * 194, Some(2 * 388000), 2));
    assert_eq!(drops[0].average_per_hunt(), Some(194.));
    let enemies = stats.top(EntityKind::Enemies, None, 2).unwrap();
    assert_eq!(enemies.iter().map(|e| e.name.as_str()).collect::<Vec<_>>(), ["Mecha Charizard", "Mecha Abomasnow"]);
    assert_eq!(enemies[0].value, None);
    assert_eq!(stats.top(EntityKind::Supplies, None, 20).unwrap()[0].name, "Healing Elixir");
    assert_eq!(stats.top(EntityKind::Drops, Some(&duration(Operator::Eq, 3600.)), 20).unwrap()[0].quantity, 194);
    assert!(stats.top(EntityKind::Drops, Some(&nobody()), 20).unwrap().is_empty());
}

#[test]
fn boss_statistics() {
    let database = Database::in_memory().unwrap();
    let boss = |id: i64, start: &str, extra: &[(&str, Value)]| {
        let mut data: Value = serde_json::from_str(&std::fs::read_to_string(fixture("sample_boss.json")).unwrap()).unwrap();
        data["Session"]["Session ID"] = json!(id);
        data["Session"]["Start"] = json!(start);
        for (key, value) in extra {
            data["Session"][*key] = value.clone();
        }
        data.to_string()
    };
    import(&database, &boss(1, "2026-10-04 13:04:54", &[]), Some(Category::Terror));
    import(&database, &boss(2, "2026-10-05 10:00:00", &[("Kills", json!(3)), ("Profit", json!(300_000))]), Some(Category::Terror));
    HuntService::new(&database).import_file(&sample_hunt_path(), false, None).unwrap();
    let terrors = HuntFilter::default().scoped(&[Category::Terror]);
    let stats = StatisticsService::new(&database);
    let o = stats.overview(Some(&terrors)).unwrap();
    assert_eq!((o.hunt_count, o.total_kills), (2, 4));
    assert_eq!(o.profit_per_kill(), Some((147_900. + 300_000.) / 4.));
    assert_eq!(o.duration_per_kill(), Some(454. * 2. / 4.));
    let elements = stats.damage_by_element(Some(&terrors)).unwrap();
    let rows: Vec<(&str, i64, i64)> = elements.iter().map(|e| (e.element.as_str(), e.dealt, e.taken)).collect();
    assert_eq!(rows, [("Dragon", 2 * 1_883_827, 0), ("Neutral", 0, 2 * 188_003)]);
    assert_eq!(elements[0].dealt_share, Some(1.));
    assert_eq!(elements[1].taken_share, Some(1.));
}

#[test]
fn damage_by_element_ignores_missing_sections() {
    let damage = json!({"Damage": [
        {"Element": "Fire", "Damage dealt": 30, "Damage taken": 10},
        {"Element": "Water", "Damage dealt": 70},
        "inválido",
    ]})
    .to_string();
    let rows = damage_by_element([r#"{"Session": {}}"#, "não é json", damage.as_str()]);
    let summary: Vec<(&str, i64, i64)> = rows.iter().map(|r| (r.element.as_str(), r.dealt, r.taken)).collect();
    assert_eq!(summary, [("Water", 70, 0), ("Fire", 30, 10)]);
    close(rows[0].dealt_share, 0.7);
    assert!(damage_by_element([]).is_empty());
}

// ------------------------------------------------------- relatório de itens

fn entity_database() -> Database {
    let database = Database::in_memory().unwrap();
    // 1h, 40 ore; 2h, 80 ore; 30min, sem ore; 1h, 60 ore (nome com outra caixa)
    for text in [
        hunt_text(1, "2026-09-01 10:00:00", 3600, &[("nightmare ore", 40)], &[("Mecha Charizard", 30)], &[("Healing Elixir", 3)]),
        hunt_text(2, "2026-09-10 10:00:00", 7200, &[("nightmare ore", 80), ("nightmare gem", 5)], &[("Mecha Charizard", 50)], &[]),
        hunt_text(3, "2026-09-11 10:00:00", 1800, &[("metal scraps", 5)], &[("Mecha Venusaur", 20)], &[]),
        hunt_text(4, "2026-09-26 10:00:00", 3600, &[("Nightmare Ore", 60)], &[("Mecha Charizard", 40)], &[]),
    ] {
        import(&database, &text, None);
    }
    database
}

#[test]
fn entity_reports() {
    let database = entity_database();
    let stats = StatisticsService::new(&database);
    let r = stats.entity_report(EntityKind::Drops, "nightmare ore", None).unwrap();
    assert_eq!(r.rows.iter().map(|x| x.session_id.unwrap()).collect::<Vec<_>>(), [1, 2, 3, 4]); // cronológico
    assert_eq!(r.rows.iter().map(|x| x.quantity).collect::<Vec<_>>(), [40, 80, 0, 60]);
    assert_eq!((r.hunt_count(), r.present_count()), (4, 3));
    close(r.presence_ratio(), 0.75);
    assert_eq!(r.total_quantity(), 180);
    assert_eq!(r.total_value(), Some(180 * 100)); // preço 100
    assert_eq!(r.average_per_hunt(), Some(60.)); // nas sessões em que apareceu
    assert_eq!(r.average_value_per_hunt(), Some(6000.));
    assert_eq!(r.present_duration_seconds(), 4 * 3600);
    assert_eq!(r.per_hour(), Some(45.)); // 180 em 4h
    assert_eq!(r.max_row().unwrap().session_id, Some(2));
    assert_eq!(r.min_row().unwrap().session_id, Some(1));
    assert_eq!(r.rows[2].value, None);

    let enemy = stats.entity_report(EntityKind::Enemies, " Mecha Charizard ", None).unwrap();
    assert_eq!(enemy.name, "Mecha Charizard");
    assert_eq!((enemy.total_quantity(), enemy.present_count()), (120, 3));
    assert_eq!((enemy.total_value(), enemy.average_value_per_hunt()), (None, None));
    assert_eq!(enemy.average_per_hunt(), Some(40.));
    assert_eq!((enemy.min_row().unwrap().quantity, enemy.max_row().unwrap().quantity), (30, 50));

    let supply = stats.entity_report(EntityKind::Supplies, "Healing Elixir", None).unwrap();
    assert_eq!((supply.present_count(), supply.total_value()), (1, Some(300)));

    let from_10 = HuntFilter { date_from: NaiveDate::from_ymd_opt(2026, 9, 10), ..Default::default() };
    let filtered = stats.entity_report(EntityKind::Drops, "nightmare ore", Some(&from_10)).unwrap();
    assert_eq!(filtered.rows.iter().map(|x| x.quantity).collect::<Vec<_>>(), [80, 0, 60]);
    assert_eq!(filtered.total_quantity(), 140);

    let unknown = stats.entity_report(EntityKind::Drops, "não existe", None).unwrap();
    assert_eq!((unknown.hunt_count(), unknown.present_count()), (4, 0));
    assert_eq!((unknown.average_per_hunt(), unknown.per_hour()), (None, None));
    assert!(unknown.max_row().is_none());
    let nothing = stats.entity_report(EntityKind::Drops, "nightmare ore", Some(&nobody())).unwrap();
    assert!(nothing.rows.is_empty());
    assert_eq!(nothing.presence_ratio(), None);
}

#[test]
fn summaries_for_comparison() {
    let database = entity_database();
    let hunts = HuntService::new(&database);
    let ids: Vec<i64> = hunts.list_hunts(None).unwrap().iter().map(|h| h.id).collect(); // mais recentes primeiro
    let summaries = hunts.get_summaries(&ids[..3]).unwrap();
    assert_eq!(summaries.iter().map(|s| s.session_id.unwrap()).collect::<Vec<_>>(), [2, 3, 4]); // cronológico
    assert!(summaries[0].damage_dealt.is_some());
    assert!(hunts.get_summaries(&[]).unwrap().is_empty());
}

// --------------------------------------------------------- busca avançada

fn options() -> FilterOptions {
    let owned = |items: &[&str]| items.iter().map(|s| s.to_string()).collect();
    FilterOptions {
        players: owned(&["Royalzxd"]),
        enemies: owned(&["Mecha Charizard", "Mecha Blastoise"]),
        drop_items: owned(&["nightmare ore", "nightmare gem", "metal scraps"]),
        supply_items: owned(&["Healing Elixir"]),
    }
}

fn parse(text: &str) -> AdvancedQuery {
    parse_advanced_query(text, &options(), NumberFormat::PT_BR)
}

fn drop(name: &str, comparison: Option<(Operator, f64)>) -> ItemCondition {
    ItemCondition::drop(match comparison {
        Some((op, q)) => QuantityCondition::with(name, op, q),
        None => QuantityCondition::present(name),
    })
}

#[test]
fn spec_example() {
    let query = parse("Nightmare ore > 50 E Nightmare gem > 1000");
    assert!(query.ok(), "{:?}", query.errors);
    assert_eq!(query.items, [drop("nightmare ore", Some((Operator::Gt, 50.))), drop("nightmare gem", Some((Operator::Gt, 1000.)))]);
}

#[test]
fn presence_and_resolution_order() {
    let query = parse("Mecha Charizard; healing elixir; metal scraps");
    assert_eq!(query.enemies, [QuantityCondition::present("Mecha Charizard")]);
    assert_eq!(query.items, [
        ItemCondition { condition: QuantityCondition::present("Healing Elixir"), source: ItemSource::Supplies },
        drop("metal scraps", None),
    ]);
}

#[test]
fn metrics_with_game_notation() {
    let query = parse("profit/h >= 800k and kills/h > 300 & duração >= 1h30; profit < 1,2kk");
    assert!(query.ok(), "{:?}", query.errors);
    let m = |metric, operator, value| MetricCondition { metric, operator, value };
    assert_eq!(query.metrics, [
        m(Metric::ProfitPerHour, Operator::Ge, 800_000.),
        m(Metric::KillsPerHour, Operator::Gt, 300.),
        m(Metric::Duration, Operator::Ge, 5400.),
        m(Metric::Profit, Operator::Lt, 1_200_000.),
    ]);
}

#[test]
fn unicode_operators_and_spacing() {
    let query = parse("  nightmare   ore≥10 ;  mecha blastoise ≤ 5 ");
    assert_eq!(query.items, [drop("nightmare ore", Some((Operator::Ge, 10.)))]);
    assert_eq!(query.enemies, [QuantityCondition::with("Mecha Blastoise", Operator::Le, 5.)]);
}

#[test]
fn prefixes_force_type() {
    let query = parse("supply: Potion > 2; inimigo: Mecha Mew; drop: rare candy");
    assert!(query.ok(), "{:?}", query.errors);
    assert_eq!(query.items, [
        ItemCondition { condition: QuantityCondition::with("Potion", Operator::Gt, 2.), source: ItemSource::Supplies },
        drop("rare candy", None),
    ]);
    assert_eq!(query.enemies, [QuantityCondition::present("Mecha Mew")]);
}

#[test]
fn prefix_does_not_turn_metric_name_into_metric() {
    let query = parse("drop: kills");
    assert_eq!(query.items, [drop("kills", None)]);
    assert!(query.metrics.is_empty());
}

#[test]
fn errors() {
    for (text, message) in [
        ("unobtainium > 3", "não foi encontrado"),
        ("kills/h", "Informe operador"),
        ("profit > muito", "Valor inválido"),
        ("nightmare ore > x", "Quantidade inválida"),
        ("nightmare ore >", "Falta o valor"),
    ] {
        let query = parse(text);
        assert!(!query.ok(), "{text}");
        assert!(query.errors[0].contains(message), "{text}: {:?}", query.errors);
    }
}

#[test]
fn empty() {
    for text in ["", "  ", " ; ; "] {
        let query = parse(text);
        assert!(query.ok() && query.items.is_empty() && query.enemies.is_empty() && query.metrics.is_empty());
    }
}

#[test]
fn merge_keeps_existing_criteria() {
    let base = HuntFilter { player: Some("Royal".into()), items: vec![drop("metal scraps", None)], ..Default::default() };
    let merged = parse("nightmare ore > 50").merged_into(&base);
    assert_eq!(merged.player.as_deref(), Some("Royal"));
    assert_eq!(merged.items.len(), 2);
}

#[test]
fn query_against_database() {
    let database = Database::in_memory().unwrap();
    for text in [
        hunt_text(1, "2026-09-01 10:00:00", 3600, &[("nightmare ore", 40), ("nightmare gem", 1200)], &[], &[]),
        hunt_text(2, "2026-09-02 10:00:00", 3600, &[("nightmare ore", 80), ("nightmare gem", 900)], &[], &[]),
        hunt_text(3, "2026-09-03 10:00:00", 3600, &[("nightmare ore", 60), ("nightmare gem", 1500)], &[], &[]),
    ] {
        import(&database, &text, None);
    }
    let service = HuntService::new(&database);
    let query = parse_advanced_query("Nightmare ore > 50 e Nightmare gem > 1000", &service.filter_options().unwrap(), NumberFormat::PT_BR);
    let hunts = service.list_hunts(Some(&query.merged_into(&HuntFilter::default()))).unwrap();
    assert_eq!(hunts.iter().map(|h| h.session_id.unwrap()).collect::<Vec<_>>(), [3]);
}
