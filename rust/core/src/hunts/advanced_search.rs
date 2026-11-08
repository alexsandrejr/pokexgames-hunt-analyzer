//! Pesquisa avançada em texto: `nightmare ore > 50 e nightmare gem > 1000; kills/h >= 300`
//! (equivale a `app/services/advanced_search.py`).
//!
//! * Condições separadas por `e`, `and`, `;` ou `&`; todas combinadas com E.
//! * Cada condição: `[prefixo:] nome [operador valor]`.
//! * Operadores: `>`, `>=`, `=`, `<=`, `<` (também `≥` e `≤`).
//! * Métricas (exigem operador): `profit`, `profit/h`, `kills`, `kills/h`, `duração`,
//!   `supplies`, `supplies/h`, `raw gains`, `raw gains/h`.
//! * Sem prefixo, o nome é procurado nos drops, depois nos inimigos e nos supplies conhecidos.
//!   Prefixos forçam o tipo: `drop:`, `supply:`, `inimigo:`.
//! * Sem operador, basta o item ou inimigo aparecer na sessão.

use std::sync::LazyLock;

use regex::Regex;

use super::filters::{HuntFilter, ItemCondition, ItemSource, Metric, MetricCondition, Operator, QuantityCondition};
use super::model::FilterOptions;
use crate::format::NumberFormat;
use crate::parse::{parse_user_duration, parse_user_number};
use crate::text::{py_split, py_strip};

static SEPARATORS: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)\s+(?:e|and)\s+|;|&&?").expect("regex válida"));
static CONDITION: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:(?P<prefix>[^\W\d_]+)\s*:\s*)?(?P<name>.+?)(?:\s*(?P<op>>=|<=|≥|≤|=|>|<)\s*(?P<value>.*))?$")
        .expect("regex válida")
});

fn operator(symbol: &str) -> Option<Operator> {
    match symbol {
        ">" => Some(Operator::Gt),
        ">=" | "≥" => Some(Operator::Ge),
        "=" => Some(Operator::Eq),
        "<=" | "≤" => Some(Operator::Le),
        "<" => Some(Operator::Lt),
        _ => None,
    }
}

fn metric_alias(name: &str) -> Option<Metric> {
    Some(match name {
        "profit" | "lucro" => Metric::Profit,
        "profit/h" | "lucro/h" => Metric::ProfitPerHour,
        "kills" => Metric::Kills,
        "kills/h" | "k/h" => Metric::KillsPerHour,
        "duração" | "duracao" | "duration" | "tempo" => Metric::Duration,
        "supplies" => Metric::Supplies,
        "supplies/h" => Metric::SuppliesPerHour,
        "raw gains" => Metric::RawGains,
        "raw gains/h" => Metric::RawGainsPerHour,
        _ => return None,
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Kind {
    Drop,
    Supply,
    Enemy,
}

fn prefix_kind(prefix: &str) -> Option<Kind> {
    match prefix {
        "drop" | "drops" | "item" => Some(Kind::Drop),
        "supply" => Some(Kind::Supply),
        "inimigo" | "enemy" | "pokemon" | "pokémon" => Some(Kind::Enemy),
        _ => None,
    }
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct AdvancedQuery {
    pub enemies: Vec<QuantityCondition>,
    pub items: Vec<ItemCondition>,
    pub metrics: Vec<MetricCondition>,
    pub errors: Vec<String>,
}

impl AdvancedQuery {
    pub fn ok(&self) -> bool {
        self.errors.is_empty()
    }

    /// Soma estas condições às do filtro (tudo continua combinado com E). Como no Python, o
    /// escopo de categorias não é copiado: quem chama aplica o da página.
    pub fn merged_into(&self, filter: &HuntFilter) -> HuntFilter {
        HuntFilter {
            date_from: filter.date_from,
            date_to: filter.date_to,
            player: filter.player.clone(),
            enemies: filter.enemies.iter().chain(&self.enemies).cloned().collect(),
            items: filter.items.iter().chain(&self.items).cloned().collect(),
            metrics: filter.metrics.iter().chain(&self.metrics).cloned().collect(),
            categories: Vec::new(),
        }
    }
}

pub fn parse_advanced_query(text: &str, options: &FilterOptions, fmt: NumberFormat) -> AdvancedQuery {
    let mut query = AdvancedQuery::default();
    for part in SEPARATORS.split(text) {
        let part = py_strip(part);
        if !part.is_empty() {
            parse_condition(part, options, fmt, &mut query);
        }
    }
    query
}

fn parse_condition(text: &str, options: &FilterOptions, fmt: NumberFormat, query: &mut AdvancedQuery) {
    let mut captures = CONDITION.captures(text);
    let mut prefix = captures
        .as_ref()
        .and_then(|c| c.name("prefix"))
        .map(|m| m.as_str().to_lowercase())
        .unwrap_or_default();
    let replaced;
    if captures.is_none() || (!prefix.is_empty() && prefix_kind(&prefix).is_none()) {
        // Um "prefixo" desconhecido provavelmente faz parte do nome.
        captures = if captures.is_some() {
            replaced = text.replacen(':', " ", 1);
            CONDITION.captures(&replaced)
        } else {
            None
        };
        prefix.clear();
    }
    let Some(captures) = captures else {
        query.errors.push(format!("Não entendi “{text}”."));
        return;
    };
    let name = py_split(&captures["name"]).collect::<Vec<_>>().join(" ");
    let symbol = captures.name("op").map(|m| m.as_str());
    let value_text = captures.name("value").map_or("", |m| py_strip(m.as_str()));
    let op = symbol.and_then(operator);
    if symbol.is_some() && value_text.is_empty() {
        query.errors.push(format!("Falta o valor em “{text}”."));
        return;
    }
    let metric = if prefix.is_empty() { metric_alias(&name.to_lowercase()) } else { None };
    if let Some(metric) = metric {
        add_metric(metric, op, value_text, text, fmt, query);
        return;
    }
    let mut quantity = None;
    if op.is_some() {
        quantity = parse_user_number(value_text, fmt);
        if quantity.is_none() {
            query.errors.push(format!("Quantidade inválida em “{text}”."));
            return;
        }
    }
    let Some((kind, canonical)) = resolve_name(&name, prefix_kind(&prefix), options) else {
        query.errors.push(format!(
            "“{name}” não foi encontrado nos drops, inimigos ou supplies importados. \
             Use drop:, supply: ou inimigo: para forçar o tipo."
        ));
        return;
    };
    let condition = QuantityCondition { name: canonical, operator: op, quantity };
    match kind {
        Kind::Enemy => query.enemies.push(condition),
        Kind::Supply => query.items.push(ItemCondition { condition, source: ItemSource::Supplies }),
        Kind::Drop => query.items.push(ItemCondition { condition, source: ItemSource::Drops }),
    }
}

fn add_metric(metric: Metric, op: Option<Operator>, value_text: &str, text: &str, fmt: NumberFormat, query: &mut AdvancedQuery) {
    let Some(operator) = op else {
        query.errors.push(format!(
            "Informe operador e valor para {} (ex.: {} > 100).",
            metric.label(),
            metric.label().to_lowercase()
        ));
        return;
    };
    let value = if metric.is_duration() {
        parse_user_duration(value_text).map(|v| v as f64)
    } else {
        parse_user_number(value_text, fmt)
    };
    match value {
        Some(value) => query.metrics.push(MetricCondition { metric, operator, value }),
        None => query.errors.push(format!("Valor inválido em “{text}”.")),
    }
}

/// Descobre se o nome é drop, inimigo ou supply (nessa ordem de preferência).
fn resolve_name(name: &str, forced: Option<Kind>, options: &FilterOptions) -> Option<(Kind, String)> {
    let list = |kind| match kind {
        Kind::Drop => &options.drop_items,
        Kind::Enemy => &options.enemies,
        Kind::Supply => &options.supply_items,
    };
    let lowered = name.to_lowercase();
    let kinds = match forced {
        Some(kind) => vec![kind],
        None => vec![Kind::Drop, Kind::Enemy, Kind::Supply],
    };
    for kind in kinds {
        if let Some(known) = list(kind).iter().find(|k| k.to_lowercase() == lowered) {
            return Some((kind, known.clone()));
        }
    }
    // Tipo explícito: aceita mesmo sem registros (o resultado pode ser vazio).
    forced.map(|kind| (kind, name.to_owned()))
}
