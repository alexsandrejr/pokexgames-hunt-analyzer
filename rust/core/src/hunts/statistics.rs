//! Estatísticas sobre as sessões, sempre sobre um filtro (equivale a
//! `app/services/statistics_service.py`, `app/services/entity_report.py`, `app/services/rates.py`
//! e às agregações do `HuntRepository`).
//!
//! Atenção à diferença entre as duas formas de "Profit/h":
//!
//! * `average_profit_per_hour`: média simples dos Profit/h de cada sessão;
//! * `profit_per_total_hour`: Profit total ÷ tempo total (ponderado pelo tempo).

use std::collections::HashMap;

use chrono::NaiveDateTime;
use rusqlite::{Connection, params_from_iter};
use serde::Serialize;
use serde_json::Value;

use super::filters::{HuntFilter, ItemSource};
use super::query::hunt_filter_conditions;
use super::repository::{self as repo, CHRONOLOGICAL};
use crate::db::Database;
use crate::error::Result;
use crate::parse::{int_true_div, to_int, to_str};
use crate::text::py_strip;
pub use crate::format::ValueKind;

/// Taxa por hora; `None` quando não há tempo para dividir.
pub fn rate_per_hour(total: Option<i64>, duration_seconds: Option<i64>) -> Option<f64> {
    let duration = duration_seconds.filter(|d| *d > 0)?;
    Some(int_true_div(i128::from(total?) * 3600, i128::from(duration)))
}

pub fn rate_per_second(total: Option<i64>, duration_seconds: Option<i64>) -> Option<f64> {
    let duration = duration_seconds.filter(|d| *d > 0)?;
    Some(int_true_div(i128::from(total?), i128::from(duration)))
}

/// `total / divisor` entre inteiros, como o Python; `None` se o divisor for zero.
fn ratio(total: i64, divisor: i64) -> Option<f64> {
    (divisor != 0).then(|| int_true_div(i128::from(total), i128::from(divisor)))
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct OverviewStats {
    pub hunt_count: i64,
    pub total_duration_seconds: i64,
    pub total_kills: i64,
    pub total_profit: i64,
    pub total_supplies: i64,
    pub total_raw_gains: i64,
    pub total_experience: i64,
    pub total_damage_dealt: i64,
    pub total_damage_taken: i64,
    pub average_profit: Option<f64>,
    pub average_profit_per_hour: Option<f64>,
    pub average_kills_per_hour: Option<f64>,
    pub average_supplies_per_hour: Option<f64>,
    pub average_damage_dealt_per_second: Option<f64>,
    pub first_start: Option<NaiveDateTime>,
    pub last_start: Option<NaiveDateTime>,
}

impl OverviewStats {
    pub fn average_duration_seconds(&self) -> Option<f64> {
        ratio(self.total_duration_seconds, self.hunt_count)
    }

    pub fn average_kills(&self) -> Option<f64> {
        ratio(self.total_kills, self.hunt_count)
    }

    fn per_total_hour(&self, total: i64) -> Option<f64> {
        rate_per_hour(Some(total), Some(self.total_duration_seconds))
    }

    pub fn profit_per_total_hour(&self) -> Option<f64> {
        self.per_total_hour(self.total_profit)
    }

    pub fn kills_per_total_hour(&self) -> Option<f64> {
        self.per_total_hour(self.total_kills)
    }

    pub fn supplies_per_total_hour(&self) -> Option<f64> {
        self.per_total_hour(self.total_supplies)
    }

    pub fn raw_gains_per_total_hour(&self) -> Option<f64> {
        self.per_total_hour(self.total_raw_gains)
    }

    // Por kill: em sessões de boss, quanto rende (e quanto custa) cada boss derrotado.

    pub fn duration_per_kill(&self) -> Option<f64> {
        ratio(self.total_duration_seconds, self.total_kills)
    }

    pub fn profit_per_kill(&self) -> Option<f64> {
        ratio(self.total_profit, self.total_kills)
    }

    pub fn supplies_per_kill(&self) -> Option<f64> {
        ratio(self.total_supplies, self.total_kills)
    }

    pub fn raw_gains_per_kill(&self) -> Option<f64> {
        ratio(self.total_raw_gains, self.total_kills)
    }

    pub fn experience_per_kill(&self) -> Option<f64> {
        ratio(self.total_experience, self.total_kills)
    }
}


#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum RateUnit {
    #[serde(rename = "/h")]
    Hour,
    #[serde(rename = "/s")]
    Second,
}

impl RateUnit {
    pub fn suffix(self) -> &'static str {
        match self {
            Self::Hour => "/h",
            Self::Second => "/s",
        }
    }
}

/// Estatísticas de uma métrica sobre as sessões filtradas.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct MetricStats {
    pub key: &'static str,
    pub label: &'static str,
    pub kind: ValueKind,
    pub rate_unit: Option<RateUnit>,
    pub total: Option<i64>,
    pub average: Option<f64>,
    pub minimum: Option<i64>,
    pub maximum: Option<i64>,
    /// Média simples das taxas individuais.
    pub average_rate: Option<f64>,
    /// Total ÷ tempo total.
    pub rate_over_total_time: Option<f64>,
}

/// (chave, rótulo, formato, unidade, coluna do total, coluna da taxa).
type MetricDefinition = (&'static str, &'static str, ValueKind, Option<RateUnit>, &'static str, Option<&'static str>);
/// Soma, média, mínimo, máximo e média da taxa de uma métrica, como vêm do SQLite.
type MetricRow = (Option<i64>, Option<f64>, Option<i64>, Option<i64>, Option<f64>);

/// As métricas na ordem do relatório.
const METRICS: [MetricDefinition; 8] = [
    ("duration", "Duração", ValueKind::Duration, None, "duration_seconds", None),
    ("kills", "Kills", ValueKind::Number, Some(RateUnit::Hour), "kills", Some("kills_per_hour")),
    ("profit", "Profit", ValueKind::Money, Some(RateUnit::Hour), "profit", Some("profit_per_hour")),
    ("supplies", "Supplies", ValueKind::Money, Some(RateUnit::Hour), "supplies", Some("supplies_per_hour")),
    ("raw_gains", "Raw gains", ValueKind::Money, Some(RateUnit::Hour), "raw_gains", Some("raw_gains_per_hour")),
    ("experience", "Experience", ValueKind::Number, Some(RateUnit::Hour), "experience", Some("experience_per_hour")),
    ("damage_dealt", "Damage dealt", ValueKind::Number, Some(RateUnit::Second), "damage_dealt", Some("damage_dealt_per_second")),
    ("damage_taken", "Damage taken", ValueKind::Number, Some(RateUnit::Second), "damage_taken", Some("damage_taken_per_second")),
];

/// Item ou inimigo somado sobre um conjunto de sessões.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct RankedEntry {
    pub name: String,
    pub quantity: i64,
    pub value: Option<i64>,
    pub hunt_count: i64,
}

impl RankedEntry {
    pub fn average_per_hunt(&self) -> Option<f64> {
        ratio(self.quantity, self.hunt_count)
    }
}

/// Dano causado e recebido de um elemento, somado nas sessões (seção `Damage`).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ElementDamage {
    pub element: String,
    pub dealt: i64,
    pub taken: i64,
    /// Fração do dano causado total.
    pub dealt_share: Option<f64>,
    /// Fração do dano recebido total.
    pub taken_share: Option<f64>,
}

/// Soma a seção `Damage` dos JSONs originais, do elemento que mais causou dano ao menor.
///
/// A seção não tem tabela própria no banco; JSONs sem ela (ou inválidos) são ignorados.
pub fn damage_by_element<'a>(documents: impl IntoIterator<Item = &'a str>) -> Vec<ElementDamage> {
    let mut order: Vec<String> = Vec::new();
    let mut totals: HashMap<String, (i64, i64)> = HashMap::new();
    for text in documents {
        let Ok(document) = serde_json::from_str::<Value>(text) else { continue };
        let Some(entries) = document.get("Damage").and_then(Value::as_array) else { continue };
        for entry in entries.iter().filter_map(Value::as_object) {
            let get = |key| entry.get(key).unwrap_or(&Value::Null);
            let element = to_str(get("Element")).unwrap_or_else(|| "Sem elemento".to_owned());
            let pair = totals.entry(element.clone()).or_insert_with(|| {
                order.push(element);
                (0, 0)
            });
            pair.0 += to_int(get("Damage dealt")).unwrap_or(0);
            pair.1 += to_int(get("Damage taken")).unwrap_or(0);
        }
    }
    let all_dealt: i64 = totals.values().map(|p| p.0).sum();
    let all_taken: i64 = totals.values().map(|p| p.1).sum();
    let mut rows: Vec<ElementDamage> = order
        .into_iter()
        .map(|element| {
            let (dealt, taken) = totals[&element];
            ElementDamage {
                dealt_share: ratio(dealt, all_dealt),
                taken_share: ratio(taken, all_taken),
                element,
                dealt,
                taken,
            }
        })
        .collect();
    rows.sort_by_cached_key(|r| (-r.dealt, -r.taken, r.element.to_lowercase()));
    rows
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EntityKind {
    Drops,
    Supplies,
    Enemies,
}

impl EntityKind {
    pub fn label(self) -> &'static str {
        match self {
            Self::Drops => "Drop",
            Self::Supplies => "Supply",
            Self::Enemies => "Inimigo",
        }
    }

    /// Inimigos não têm preço.
    pub fn has_value(self) -> bool {
        self != Self::Enemies
    }

    fn source(self) -> Option<ItemSource> {
        match self {
            Self::Drops => Some(ItemSource::Drops),
            Self::Supplies => Some(ItemSource::Supplies),
            Self::Enemies => None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct EntityHuntRow {
    pub hunt_id: i64,
    pub session_id: Option<i64>,
    pub start_datetime: Option<NaiveDateTime>,
    pub duration_seconds: Option<i64>,
    pub quantity: i64,
    pub value: Option<i64>,
}

impl EntityHuntRow {
    pub fn present(&self) -> bool {
        self.quantity > 0
    }
}

/// Um item ou inimigo ao longo das sessões filtradas.
///
/// As médias por sessão e por hora consideram **as sessões em que o nome apareceu**: é a
/// resposta para "quando esse item cai, quanto cai?". A presença vem à parte.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct EntityReport {
    pub kind: EntityKind,
    pub name: String,
    /// Todas as sessões filtradas, em ordem cronológica.
    pub rows: Vec<EntityHuntRow>,
}

impl EntityReport {
    pub fn present_rows(&self) -> impl Iterator<Item = &EntityHuntRow> {
        self.rows.iter().filter(|r| r.present())
    }

    pub fn hunt_count(&self) -> usize {
        self.rows.len()
    }

    pub fn present_count(&self) -> usize {
        self.present_rows().count()
    }

    pub fn presence_ratio(&self) -> Option<f64> {
        ratio(self.present_count() as i64, self.hunt_count() as i64)
    }

    pub fn total_quantity(&self) -> i64 {
        self.rows.iter().map(|r| r.quantity).sum()
    }

    pub fn total_value(&self) -> Option<i64> {
        self.kind.has_value().then(|| self.rows.iter().map(|r| r.value.unwrap_or(0)).sum())
    }

    pub fn average_per_hunt(&self) -> Option<f64> {
        ratio(self.total_quantity(), self.present_count() as i64)
    }

    pub fn average_value_per_hunt(&self) -> Option<f64> {
        self.total_value().and_then(|total| ratio(total, self.present_count() as i64))
    }

    pub fn present_duration_seconds(&self) -> i64 {
        self.present_rows().map(|r| r.duration_seconds.unwrap_or(0)).sum()
    }

    pub fn per_hour(&self) -> Option<f64> {
        rate_per_hour(Some(self.total_quantity()), Some(self.present_duration_seconds()))
    }

    pub fn value_per_hour(&self) -> Option<f64> {
        rate_per_hour(self.total_value(), Some(self.present_duration_seconds()))
    }

    /// A sessão com mais quantidade (no empate, a primeira, como o `max` do Python).
    pub fn max_row(&self) -> Option<&EntityHuntRow> {
        self.present_rows().fold(None, |best, row| match best {
            Some(b) if b.quantity >= row.quantity => Some(b),
            _ => Some(row),
        })
    }

    /// A sessão com menos quantidade (no empate, a primeira, como o `min` do Python).
    pub fn min_row(&self) -> Option<&EntityHuntRow> {
        self.present_rows().fold(None, |best, row| match best {
            Some(b) if b.quantity <= row.quantity => Some(b),
            _ => Some(row),
        })
    }
}

// ----------------------------------------------------------------- SQL

fn overview(c: &Connection, filter: Option<&HuntFilter>) -> Result<OverviewStats> {
    let conditions = hunt_filter_conditions(filter);
    let total = |column: &str| format!("coalesce(sum(hunt_sessions.{column}), 0)");
    let sql = format!(
        "SELECT count(hunt_sessions.id), {}, {}, {}, {}, {}, {}, {}, {}, \
         avg(hunt_sessions.profit), avg(hunt_sessions.profit_per_hour), \
         avg(hunt_sessions.kills_per_hour), avg(hunt_sessions.supplies_per_hour), \
         avg(hunt_sessions.damage_dealt_per_second), min(hunt_sessions.start_datetime), \
         max(hunt_sessions.start_datetime) FROM hunt_sessions {}",
        total("duration_seconds"), total("kills"), total("profit"), total("supplies"),
        total("raw_gains"), total("experience"), total("damage_dealt"), total("damage_taken"),
        conditions.where_clause()
    );
    Ok(c.query_row(&sql, params_from_iter(conditions.params), |r| {
        Ok(OverviewStats {
            hunt_count: r.get(0)?,
            total_duration_seconds: r.get(1)?,
            total_kills: r.get(2)?,
            total_profit: r.get(3)?,
            total_supplies: r.get(4)?,
            total_raw_gains: r.get(5)?,
            total_experience: r.get(6)?,
            total_damage_dealt: r.get(7)?,
            total_damage_taken: r.get(8)?,
            average_profit: r.get(9)?,
            average_profit_per_hour: r.get(10)?,
            average_kills_per_hour: r.get(11)?,
            average_supplies_per_hour: r.get(12)?,
            average_damage_dealt_per_second: r.get(13)?,
            first_start: repo::datetime(r, 14)?,
            last_start: repo::datetime(r, 15)?,
        })
    })?)
}

fn metric_breakdown(c: &Connection, filter: Option<&HuntFilter>) -> Result<Vec<MetricStats>> {
    let conditions = hunt_filter_conditions(filter);
    let mut columns = vec!["count(hunt_sessions.id)".to_owned()];
    for (_, _, _, _, total, rate) in METRICS {
        let column = format!("hunt_sessions.{total}");
        columns.extend([
            format!("sum({column})"),
            format!("avg({column})"),
            format!("min({column})"),
            format!("max({column})"),
        ]);
        columns.push(rate.map_or("NULL".to_owned(), |r| format!("avg(hunt_sessions.{r})")));
    }
    let sql = format!("SELECT {} FROM hunt_sessions {}", columns.join(", "), conditions.where_clause());
    let raw: Vec<MetricRow> =
        c.query_row(&sql, params_from_iter(conditions.params), |r| {
            (0..METRICS.len())
                .map(|i| {
                    let b = 1 + i * 5;
                    Ok((r.get(b)?, r.get(b + 1)?, r.get(b + 2)?, r.get(b + 3)?, r.get(b + 4)?))
                })
                .collect()
        })?;
    let total_duration = raw[0].0;
    Ok(METRICS
        .iter()
        .zip(raw)
        .map(|(&(key, label, kind, unit, _, _), (total, average, minimum, maximum, average_rate))| MetricStats {
            key,
            label,
            kind,
            rate_unit: unit,
            total,
            average,
            minimum,
            maximum,
            average_rate,
            rate_over_total_time: match unit {
                Some(RateUnit::Hour) => rate_per_hour(total, total_duration),
                Some(RateUnit::Second) => rate_per_second(total, total_duration),
                None => None,
            },
        })
        .collect())
}

/// Itens ou inimigos somados nas sessões filtradas, do maior para o menor.
fn top_entries(c: &Connection, kind: EntityKind, filter: Option<&HuntFilter>, limit: i64) -> Result<Vec<RankedEntry>> {
    let (table, column) = repo::entry_table(kind.source());
    let conditions = hunt_filter_conditions(filter);
    let value = if kind.has_value() { format!("sum({table}.total_price)") } else { "NULL".to_owned() };
    let order = if kind.has_value() { value.clone() } else { format!("sum({table}.count)") };
    let sql = format!(
        "SELECT {table}.{column} AS name, sum({table}.count) AS quantity, {value} AS value, \
         count(DISTINCT {table}.hunt_id) AS hunt_count FROM {table} \
         WHERE {table}.hunt_id IN (SELECT hunt_sessions.id FROM hunt_sessions {}) \
         GROUP BY {table}.{column} ORDER BY {order} DESC LIMIT ?",
        conditions.where_clause()
    );
    let mut params = conditions.params;
    params.push(limit.into());
    let mut statement = c.prepare(&sql)?;
    let rows = statement.query_map(params_from_iter(params), |r| {
        Ok(RankedEntry { name: r.get(0)?, quantity: r.get(1)?, value: r.get(2)?, hunt_count: r.get(3)? })
    })?;
    Ok(rows.collect::<rusqlite::Result<_>>()?)
}

/// Quantidade (e valor) do nome em cada sessão filtrada, em ordem cronológica; sessões sem o
/// nome vêm com quantidade 0 e valor vazio.
fn entity_per_hunt(c: &Connection, kind: EntityKind, name: &str, filter: Option<&HuntFilter>) -> Result<Vec<EntityHuntRow>> {
    let (table, column) = repo::entry_table(kind.source());
    let conditions = hunt_filter_conditions(filter);
    let value = if kind.has_value() { format!("sum({table}.total_price)") } else { "NULL".to_owned() };
    let sql = format!(
        "SELECT hunt_sessions.id, hunt_sessions.session_id, hunt_sessions.start_datetime, \
         hunt_sessions.duration_seconds, coalesce(per_hunt.quantity, 0), per_hunt.value \
         FROM hunt_sessions LEFT OUTER JOIN (SELECT {table}.hunt_id AS hunt_id, \
         sum({table}.count) AS quantity, {value} AS value FROM {table} \
         WHERE lower({table}.{column}) = ? GROUP BY {table}.hunt_id) AS per_hunt \
         ON per_hunt.hunt_id = hunt_sessions.id {} ORDER BY {CHRONOLOGICAL}",
        conditions.where_clause()
    );
    let mut params: Vec<rusqlite::types::Value> = vec![py_strip(name).to_lowercase().into()];
    params.extend(conditions.params);
    let mut statement = c.prepare(&sql)?;
    let rows = statement.query_map(params_from_iter(params), |r| {
        Ok(EntityHuntRow {
            hunt_id: r.get(0)?,
            session_id: r.get(1)?,
            start_datetime: repo::datetime(r, 2)?,
            duration_seconds: r.get(3)?,
            quantity: r.get(4)?,
            value: r.get(5)?,
        })
    })?;
    Ok(rows.collect::<rusqlite::Result<_>>()?)
}

pub struct StatisticsService<'a> {
    database: &'a Database,
}

impl<'a> StatisticsService<'a> {
    pub fn new(database: &'a Database) -> Self {
        Self { database }
    }

    pub fn overview(&self, filter: Option<&HuntFilter>) -> Result<OverviewStats> {
        self.database.with(|c| overview(c, filter))
    }

    pub fn metric_breakdown(&self, filter: Option<&HuntFilter>) -> Result<Vec<MetricStats>> {
        self.database.with(|c| metric_breakdown(c, filter))
    }

    pub fn top(&self, kind: EntityKind, filter: Option<&HuntFilter>, limit: i64) -> Result<Vec<RankedEntry>> {
        self.database.with(|c| top_entries(c, kind, filter, limit))
    }

    pub fn entity_report(&self, kind: EntityKind, name: &str, filter: Option<&HuntFilter>) -> Result<EntityReport> {
        let rows = self.database.with(|c| entity_per_hunt(c, kind, name, filter))?;
        Ok(EntityReport { kind, name: py_strip(name).to_owned(), rows })
    }

    pub fn damage_by_element(&self, filter: Option<&HuntFilter>) -> Result<Vec<ElementDamage>> {
        let documents = self.database.with(|c| repo::raw_documents(c, filter))?;
        Ok(damage_by_element(documents.iter().map(String::as_str)))
    }
}
