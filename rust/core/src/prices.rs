//! Tabela global de preços personalizados dos itens (equivale a `app/services/price_service.py`
//! e ao `PriceRepository`).
//!
//! Um preço personalizado substitui o preço unitário do Analyzer em todos os drops e supplies
//! com aquele nome (sem diferenciar maiúsculas), nas sessões já importadas e nas futuras. O
//! preço do Analyzer fica em `original_*` e volta a valer quando o personalizado é removido.
//!
//! Os totais da sessão acompanham a diferença no valor do item:
//!
//! * drop: `Raw gains` e `Profit` sobem ou descem junto;
//! * supply: `Supplies` acompanha e `Profit` vai no sentido contrário.
//!
//! As taxas por hora mudam na mesma proporção. Entradas ignoradas pelo Analyzer mudam de
//! preço, mas não alteram os totais.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

use chrono::Local;
use rusqlite::{Connection, OptionalExtension, params, params_from_iter};
use serde::Serialize;

use crate::db::Database;
use crate::db::datetime::to_db;
use crate::error::{Error, Result};
use crate::hunts::filters::ItemSource;
use crate::hunts::repository::{self as hunts_repo, CHRONOLOGICAL, HuntTotals, NewHunt, NewItem};
use crate::parse::{int_true_div, round_to_i64};
use crate::text::{py_strip, sort_casefold};

/// Linha da tela de preços: um item e onde ele aparece.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PricedItem {
    pub name: String,
    pub in_drops: bool,
    pub in_supplies: bool,
    /// Preço do Analyzer na sessão mais recente.
    pub analyzer_price: Option<f64>,
    pub custom_price: Option<f64>,
    pub quantity: i64,
    pub hunt_count: usize,
}

impl PricedItem {
    pub fn sources(&self) -> &'static str {
        match (self.in_drops, self.in_supplies) {
            (true, true) => "Drop e Supply",
            (true, false) => "Drop",
            (false, true) => "Supply",
            (false, false) => "—",
        }
    }

    pub fn has_custom_price(&self) -> bool {
        self.custom_price.is_some()
    }
}

/// Nome sem espaços nas pontas e em minúsculas, usado para casar itens.
pub fn item_key(name: &str) -> String {
    py_strip(name).to_lowercase()
}

pub fn validate_price(unit_price: f64) -> Result<f64> {
    if !unit_price.is_finite() || unit_price < 0.0 {
        return Err(Error::user("O preço precisa ser um número maior ou igual a zero."));
    }
    Ok(unit_price)
}

/// Taxa por hora de um total; `None` quando não há tempo para dividir.
pub fn rate_per_hour(total: i64, duration_seconds: Option<i64>) -> Option<f64> {
    let duration = duration_seconds.filter(|d| *d > 0)?;
    Some(int_true_div(i128::from(total) * 3600, i128::from(duration)))
}

/// Soma `change` ao total e o equivalente à taxa por hora (se existirem).
fn shift(total: &mut Option<i64>, rate: &mut Option<f64>, change: i64, duration: Option<i64>) {
    let Some(value) = total else { return };
    *value += change;
    if let (Some(rate), Some(rate_change)) = (rate.as_mut(), rate_per_hour(change, duration)) {
        *rate += rate_change;
    }
}

/// Ajusta os totais quando o valor de uma entrada muda em `delta` (também usado para somar ou
/// tirar drops inteiros, como os do chat).
pub fn shift_hunt_totals(totals: &mut HuntTotals, source: ItemSource, ignored: Option<bool>, delta: i64) {
    if delta == 0 || ignored == Some(true) {
        return;
    }
    let duration = totals.duration_seconds;
    match source {
        ItemSource::Drops => {
            shift(&mut totals.raw_gains, &mut totals.raw_gains_per_hour, delta, duration);
            shift(&mut totals.profit, &mut totals.profit_per_hour, delta, duration);
        }
        ItemSource::Supplies => {
            shift(&mut totals.supplies, &mut totals.supplies_per_hour, delta, duration);
            shift(&mut totals.profit, &mut totals.profit_per_hour, -delta, duration);
        }
    }
}

/// Preço e total depois de aplicar `unit_price` (`None` = preço do Analyzer).
pub fn repriced(
    count: i64,
    unit_price: Option<f64>,
    original_unit_price: Option<f64>,
    original_total_price: Option<i64>,
) -> (Option<f64>, Option<i64>) {
    match unit_price {
        None => (original_unit_price, original_total_price),
        Some(price) => (Some(price), round_to_i64(price * count as f64)),
    }
}

fn totals_of(hunt: &NewHunt) -> HuntTotals {
    let s = &hunt.session;
    HuntTotals {
        duration_seconds: s.duration_seconds,
        raw_gains: s.raw_gains,
        raw_gains_per_hour: s.raw_gains_per_hour,
        profit: s.profit,
        profit_per_hour: s.profit_per_hour,
        supplies: s.supplies,
        supplies_per_hour: s.supplies_per_hour,
    }
}

/// Aplica a tabela de preços a uma sessão que ainda vai ser gravada.
pub fn apply_custom_prices(hunt: &mut NewHunt, prices: &HashMap<String, f64>) {
    if prices.is_empty() {
        return;
    }
    let mut totals = totals_of(hunt);
    let mut reprice = |item: &mut NewItem, source| {
        if let Some(price) = prices.get(&item_key(&item.item)) {
            let old = item.total_price;
            (item.unit_price, item.total_price) =
                repriced(item.count, Some(*price), item.original_unit_price, item.original_total_price);
            let delta = item.total_price.unwrap_or(0) - old.unwrap_or(0);
            shift_hunt_totals(&mut totals, source, item.ignored, delta);
        }
    };
    for item in &mut hunt.drops {
        reprice(item, ItemSource::Drops);
    }
    for item in &mut hunt.supplies {
        reprice(item, ItemSource::Supplies);
    }
    let s = &mut hunt.session;
    s.raw_gains = totals.raw_gains;
    s.raw_gains_per_hour = totals.raw_gains_per_hour;
    s.profit = totals.profit;
    s.profit_per_hour = totals.profit_per_hour;
    s.supplies = totals.supplies;
    s.supplies_per_hour = totals.supplies_per_hour;
}

// --------------------------------------------------------------------- SQL

/// `{nome em minúsculas: preço}`.
pub fn price_map(c: &Connection) -> Result<HashMap<String, f64>> {
    let mut statement = c.prepare("SELECT key, unit_price FROM item_prices")?;
    let rows = statement.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?;
    Ok(rows.collect::<rusqlite::Result<_>>()?)
}

/// `(chave, nome exibido, preço)` de todos os preços, em ordem de chave.
pub fn all_prices(c: &Connection) -> Result<Vec<(String, String, f64)>> {
    let mut statement = c.prepare("SELECT key, item, unit_price FROM item_prices ORDER BY key")?;
    let rows = statement.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?;
    Ok(rows.collect::<rusqlite::Result<_>>()?)
}

/// `{nome em minúsculas: preço do Analyzer na sessão mais recente}`; o de drops vence.
pub fn latest_analyzer_prices(c: &Connection, keys: &BTreeSet<String>) -> Result<HashMap<String, f64>> {
    let mut prices = HashMap::new();
    if keys.is_empty() {
        return Ok(prices);
    }
    let marks = vec!["?"; keys.len()].join(", ");
    for source in [ItemSource::Supplies, ItemSource::Drops] {
        let table = source.table();
        let mut statement = c.prepare(&format!(
            "SELECT lower({table}.item), {table}.original_unit_price FROM {table} \
             JOIN hunt_sessions ON hunt_sessions.id = {table}.hunt_id \
             WHERE lower({table}.item) IN ({marks}) AND {table}.original_unit_price IS NOT NULL \
             ORDER BY {CHRONOLOGICAL}"
        ))?;
        let rows = statement.query_map(params_from_iter(keys), |r| Ok((r.get::<_, String>(0)?, r.get::<_, f64>(1)?)))?;
        for row in rows {
            let (key, price) = row?;
            prices.insert(key, price); // a mais recente vence
        }
    }
    Ok(prices)
}

pub struct PriceService<'a> {
    database: &'a Database,
}

impl<'a> PriceService<'a> {
    pub fn new(database: &'a Database) -> Self {
        Self { database }
    }

    /// Todos os itens já vistos em drops e supplies, mais os que só têm preço definido.
    pub fn list_items(&self) -> Result<Vec<PricedItem>> {
        self.database.with(|c| {
            let custom_rows = all_prices(c)?; // em ordem de chave, como no Python
            let custom: HashMap<String, (String, f64)> =
                custom_rows.iter().map(|(k, item, price)| (k.clone(), (item.clone(), *price))).collect();
            let mut order: Vec<String> = Vec::new();
            let mut names: HashMap<String, String> = HashMap::new();
            let mut in_drops = HashSet::new();
            let mut in_supplies = HashSet::new();
            let mut analyzer: HashMap<String, Option<f64>> = HashMap::new();
            let mut quantity: HashMap<String, i64> = HashMap::new();
            let mut hunts: HashMap<String, HashSet<i64>> = HashMap::new();
            for source in [ItemSource::Drops, ItemSource::Supplies] {
                let table = source.table();
                let mut statement = c.prepare(&format!(
                    "SELECT {table}.item, {table}.count, {table}.hunt_id, {table}.original_unit_price \
                     FROM {table} JOIN hunt_sessions ON hunt_sessions.id = {table}.hunt_id \
                     ORDER BY {CHRONOLOGICAL}"
                ))?;
                let rows = statement.query_map([], |r| {
                    Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?, r.get::<_, i64>(2)?, r.get::<_, Option<f64>>(3)?))
                })?;
                for row in rows {
                    let (item, count, hunt_id, price) = row?;
                    let key = item_key(&item);
                    if !names.contains_key(&key) {
                        order.push(key.clone());
                        names.insert(key.clone(), item);
                    }
                    if source == ItemSource::Drops { in_drops.insert(key.clone()) } else { in_supplies.insert(key.clone()) };
                    if price.is_some() || !analyzer.contains_key(&key) {
                        analyzer.insert(key.clone(), price); // a mais recente vence
                    }
                    *quantity.entry(key.clone()).or_default() += count;
                    hunts.entry(key).or_default().insert(hunt_id);
                }
            }
            for (key, item, _) in &custom_rows {
                if !names.contains_key(key) {
                    order.push(key.clone());
                    names.insert(key.clone(), item.clone());
                }
            }
            let mut items: Vec<PricedItem> = order
                .into_iter()
                .map(|key| PricedItem {
                    name: names[&key].clone(),
                    in_drops: in_drops.contains(&key),
                    in_supplies: in_supplies.contains(&key),
                    analyzer_price: analyzer.get(&key).copied().flatten(),
                    custom_price: custom.get(&key).map(|(_, price)| *price),
                    quantity: quantity.get(&key).copied().unwrap_or(0),
                    hunt_count: hunts.get(&key).map_or(0, HashSet::len),
                })
                .collect();
            sort_casefold(&mut items, |item| &item.name);
            Ok(items)
        })
    }

    pub fn custom_prices(&self) -> Result<HashMap<String, f64>> {
        self.database.with(price_map)
    }

    /// Define o preço do item e recalcula as sessões; devolve quantas sessões mudaram.
    pub fn set_price(&self, name: &str, unit_price: f64) -> Result<usize> {
        let name = py_strip(name);
        if name.is_empty() {
            return Err(Error::user("Informe o nome do item."));
        }
        let unit_price = validate_price(unit_price)?;
        let key = item_key(name);
        let now = to_db(Local::now().naive_local());
        self.database.transaction(|tx| {
            let exists: Option<i64> = tx
                .query_row("SELECT id FROM item_prices WHERE key = ?1", [&key], |r| r.get(0))
                .optional()?;
            match exists {
                Some(id) => tx.execute(
                    "UPDATE item_prices SET unit_price = ?2, updated_at = ?3 WHERE id = ?1",
                    params![id, unit_price, now],
                )?,
                None => tx.execute(
                    "INSERT INTO item_prices (key, item, unit_price, updated_at) VALUES (?1, ?2, ?3, ?4)",
                    params![key, name, unit_price, now],
                )?,
            };
            reprice_all(tx, &key, Some(unit_price))
        })
    }

    /// Remove o preço personalizado e volta ao preço do Analyzer em todas as sessões.
    pub fn clear_price(&self, name: &str) -> Result<usize> {
        let key = item_key(name);
        self.database.transaction(|tx| {
            if tx.execute("DELETE FROM item_prices WHERE key = ?1", [&key])? == 0 {
                return Ok(0);
            }
            reprice_all(tx, &key, None)
        })
    }
}

/// Drop ou supply afetado por uma mudança de preço.
struct PricedEntry {
    id: i64,
    hunt_id: i64,
    count: i64,
    total_price: Option<i64>,
    original_unit_price: Option<f64>,
    original_total_price: Option<i64>,
    ignored: Option<bool>,
}

/// Aplica o preço a todos os drops e supplies do item e ajusta as sessões, na ordem do Python
/// (drops e depois supplies, cada um na ordem dos ids). Devolve quantas sessões mudaram.
fn reprice_all(c: &Connection, key: &str, unit_price: Option<f64>) -> Result<usize> {
    let mut totals: BTreeMap<i64, HuntTotals> = BTreeMap::new();
    let mut touched = HashSet::new();
    for source in [ItemSource::Drops, ItemSource::Supplies] {
        let mut statement = c.prepare(&format!(
            "SELECT id, hunt_id, count, total_price, original_unit_price, original_total_price, ignored \
             FROM {} WHERE lower(item) = ?1 ORDER BY id",
            source.table()
        ))?;
        let rows: Vec<PricedEntry> = statement
            .query_map([key], |r| {
                Ok(PricedEntry {
                    id: r.get(0)?,
                    hunt_id: r.get(1)?,
                    count: r.get(2)?,
                    total_price: r.get(3)?,
                    original_unit_price: r.get(4)?,
                    original_total_price: r.get(5)?,
                    ignored: r.get(6)?,
                })
            })?
            .collect::<rusqlite::Result<_>>()?;
        for entry in rows {
            let (hunt_id, old_total, ignored) = (entry.hunt_id, entry.total_price, entry.ignored);
            let (new_unit, new_total) =
                repriced(entry.count, unit_price, entry.original_unit_price, entry.original_total_price);
            hunts_repo::set_item_price(c, source, entry.id, new_unit, new_total)?;
            touched.insert(hunt_id);
            if let std::collections::btree_map::Entry::Vacant(slot) = totals.entry(hunt_id) {
                if let Some(found) = hunts_repo::hunt_totals(c, hunt_id)? {
                    slot.insert(found);
                }
            }
            if let Some(hunt) = totals.get_mut(&hunt_id) {
                shift_hunt_totals(hunt, source, ignored, new_total.unwrap_or(0) - old_total.unwrap_or(0));
            }
        }
    }
    for (hunt_id, hunt) in &totals {
        hunts_repo::save_hunt_totals(c, *hunt_id, hunt)?;
    }
    Ok(touched.len())
}
