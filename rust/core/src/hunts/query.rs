//! Tradução de [`HuntFilter`] em condições SQL sobre `hunt_sessions` (equivale a
//! `app/database/query_filters.py`).
//!
//! O SQL reproduz o que o SQLAlchemy gera, inclusive o `lower()` do SQLite no filtro de player
//! e no nome de inimigos e itens.

use rusqlite::types::Value;

use super::filters::{HuntFilter, MetricCondition, Operator, QuantityCondition};
use crate::db::datetime::to_db;
use crate::format::round_half_even;
use crate::text::py_strip;

/// Condições combinadas com E, com os parâmetros na ordem dos `?`.
#[derive(Debug, Clone, Default)]
pub struct Conditions {
    pub sql: Vec<String>,
    pub params: Vec<Value>,
}

impl Conditions {
    /// `WHERE ...` ou texto vazio.
    pub fn where_clause(&self) -> String {
        if self.sql.is_empty() { String::new() } else { format!("WHERE {}", self.sql.join(" AND ")) }
    }

    /// `AND ...` para juntar a outra condição, ou texto vazio.
    pub fn and_clause(&self) -> String {
        if self.sql.is_empty() { String::new() } else { format!("AND {}", self.sql.join(" AND ")) }
    }

    fn push(&mut self, sql: String, params: impl IntoIterator<Item = Value>) {
        self.sql.push(sql);
        self.params.extend(params);
    }
}

pub fn hunt_filter_conditions(filter: Option<&HuntFilter>) -> Conditions {
    let mut conditions = Conditions::default();
    let Some(filter) = filter else { return conditions };
    if !filter.categories.is_empty() {
        let marks = vec!["?"; filter.categories.len()].join(", ");
        conditions.push(
            format!("hunt_sessions.category IN ({marks})"),
            filter.categories.iter().map(|c| Value::Text(c.as_str().to_owned())),
        );
    }
    if let Some(from) = filter.date_from {
        let start = to_db(from.and_hms_opt(0, 0, 0).expect("meia-noite"));
        conditions.push("hunt_sessions.start_datetime >= ?".to_owned(), [Value::Text(start)]);
    }
    if let Some(to) = filter.date_to {
        let end = to_db((to + chrono::Duration::days(1)).and_hms_opt(0, 0, 0).expect("meia-noite"));
        conditions.push("hunt_sessions.start_datetime < ?".to_owned(), [Value::Text(end)]);
    }
    if let Some(player) = filter.player.as_deref().filter(|p| !p.is_empty()) {
        let pattern = format!("%{}%", escape_like(py_strip(player)));
        conditions.push(
            "lower(hunt_sessions.player) LIKE lower(?) ESCAPE '\\'".to_owned(),
            [Value::Text(pattern)],
        );
    }
    for condition in &filter.enemies {
        let (sql, params) = quantity_condition("enemies_defeated", "enemy", condition);
        conditions.push(sql, params);
    }
    for condition in &filter.items {
        let (sql, params) = quantity_condition(condition.source.table(), "item", &condition.condition);
        conditions.push(sql, params);
    }
    for condition in &filter.metrics {
        let (sql, params) = metric_condition(condition);
        conditions.push(sql, params);
    }
    conditions
}

fn escape_like(text: &str) -> String {
    text.replace('\\', "\\\\").replace('%', "\\%").replace('_', "\\_")
}

fn metric_condition(condition: &MetricCondition) -> (String, Vec<Value>) {
    let column = format!("hunt_sessions.{}", condition.metric.column());
    if condition.operator == Operator::Eq && condition.metric.is_rate() {
        // O `round()` do Python é a param (empate para o par); o do SQLite, a coluna.
        let value = round_half_even(condition.value) as i64;
        return (format!("round({column}) = ?"), vec![Value::Integer(value)]);
    }
    (format!("{column} {} ?", condition.operator.symbol()), vec![Value::Real(condition.value)])
}

fn quantity_condition(table: &str, column: &str, condition: &QuantityCondition) -> (String, Vec<Value>) {
    let name = Value::Text(py_strip(&condition.name).to_lowercase());
    let matches = format!("entry.hunt_id = hunt_sessions.id AND lower(entry.{column}) = ?");
    match condition.comparison() {
        None => (format!("EXISTS (SELECT 1 FROM {table} AS entry WHERE {matches})"), vec![name]),
        Some((operator, quantity)) => (
            format!(
                "(SELECT coalesce(sum(entry.count), 0) FROM {table} AS entry WHERE {matches}) {} ?",
                operator.symbol()
            ),
            vec![name, Value::Real(quantity)],
        ),
    }
}
