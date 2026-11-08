//! SQL das sessões (equivale a `HuntRepository` em `app/database/repositories.py`).
//!
//! As funções recebem uma conexão ou transação; quem decide a transação é o serviço.

use std::collections::{BTreeMap, BTreeSet};

use chrono::NaiveDateTime;
use rusqlite::types::Value;
use rusqlite::{Connection, OptionalExtension, Row, params, params_from_iter};

use super::analyzer::{ParsedEnemy, ParsedSession};
use super::filters::{HuntFilter, ItemSource};
use super::model::{ChatRewardRow, EnemyRow, HuntDetails, HuntSummary, ItemRow};
use super::query::hunt_filter_conditions;
use crate::db::datetime::{from_db, to_db};
use crate::error::Result;

/// Colunas da seção `Session` em `hunt_sessions`, na ordem de [`ParsedSession`].
pub const SESSION_COLUMNS: [&str; 25] = [
    "session_id", "player", "start_datetime", "duration_seconds", "paused_seconds", "status",
    "session_type", "kills", "kills_per_hour", "rare_kills", "rare_kills_per_hour", "experience",
    "experience_per_hour", "profit", "profit_per_hour", "supplies", "supplies_per_hour",
    "raw_gains", "raw_gains_per_hour", "damage_dealt", "damage_dealt_per_second", "damage_taken",
    "damage_taken_per_second", "time_to_next_level", "time_to_next_level_seconds",
];

/// Colunas da listagem (evita trazer o `raw_json` de cada linha).
const SUMMARY_COLUMNS: &str = "id, session_id, player, start_datetime, duration_seconds, status, \
    kills, kills_per_hour, profit, profit_per_hour, supplies, supplies_per_hour, raw_gains, \
    raw_gains_per_hour, damage_dealt, damage_dealt_per_second, damage_taken, \
    damage_taken_per_second, experience, experience_per_hour, source_file, category";

/// Ordem cronológica, com as sessões sem início no fim (como o SQLAlchemy ordena).
pub const CHRONOLOGICAL: &str =
    "hunt_sessions.start_datetime IS NULL, hunt_sessions.start_datetime, hunt_sessions.id";

pub fn datetime(row: &Row<'_>, index: usize) -> rusqlite::Result<Option<NaiveDateTime>> {
    Ok(row.get::<_, Option<String>>(index)?.as_deref().and_then(from_db))
}

fn session_values(s: &ParsedSession) -> Vec<Value> {
    let int = |v: Option<i64>| v.map_or(Value::Null, Value::Integer);
    let real = |v: Option<f64>| v.map_or(Value::Null, Value::Real);
    let text = |v: &Option<String>| v.clone().map_or(Value::Null, Value::Text);
    vec![
        int(s.session_id), text(&s.player), s.start_datetime.map_or(Value::Null, |d| Value::Text(to_db(d))),
        int(s.duration_seconds), int(s.paused_seconds), text(&s.status), text(&s.session_type),
        int(s.kills), real(s.kills_per_hour), int(s.rare_kills), real(s.rare_kills_per_hour),
        int(s.experience), real(s.experience_per_hour), int(s.profit), real(s.profit_per_hour),
        int(s.supplies), real(s.supplies_per_hour), int(s.raw_gains), real(s.raw_gains_per_hour),
        int(s.damage_dealt), real(s.damage_dealt_per_second), int(s.damage_taken),
        real(s.damage_taken_per_second), text(&s.time_to_next_level), int(s.time_to_next_level_seconds),
    ]
}

fn session_from_row(r: &Row<'_>, start: usize) -> rusqlite::Result<ParsedSession> {
    let g = |i: usize| start + i;
    Ok(ParsedSession {
        session_id: r.get(g(0))?,
        player: r.get(g(1))?,
        start_datetime: datetime(r, g(2))?,
        duration_seconds: r.get(g(3))?,
        paused_seconds: r.get(g(4))?,
        status: r.get(g(5))?,
        session_type: r.get(g(6))?,
        kills: r.get(g(7))?,
        kills_per_hour: r.get(g(8))?,
        rare_kills: r.get(g(9))?,
        rare_kills_per_hour: r.get(g(10))?,
        experience: r.get(g(11))?,
        experience_per_hour: r.get(g(12))?,
        profit: r.get(g(13))?,
        profit_per_hour: r.get(g(14))?,
        supplies: r.get(g(15))?,
        supplies_per_hour: r.get(g(16))?,
        raw_gains: r.get(g(17))?,
        raw_gains_per_hour: r.get(g(18))?,
        damage_dealt: r.get(g(19))?,
        damage_dealt_per_second: r.get(g(20))?,
        damage_taken: r.get(g(21))?,
        damage_taken_per_second: r.get(g(22))?,
        time_to_next_level: r.get(g(23))?,
        time_to_next_level_seconds: r.get(g(24))?,
    })
}

/// Drop ou supply a gravar, com o preço do Analyzer preservado em `original_*`.
#[derive(Debug, Clone, PartialEq)]
pub struct NewItem {
    pub item: String,
    pub count: i64,
    pub unit_price: Option<f64>,
    pub total_price: Option<i64>,
    pub original_unit_price: Option<f64>,
    pub original_total_price: Option<i64>,
    pub player: Option<String>,
    pub ignored: Option<bool>,
}

/// Sessão a gravar.
#[derive(Debug, Clone, PartialEq)]
pub struct NewHunt {
    pub session: ParsedSession,
    pub category: String,
    pub source_file: Option<String>,
    pub content_hash: String,
    pub raw_json: String,
    pub created_at: NaiveDateTime,
    pub enemies: Vec<ParsedEnemy>,
    pub drops: Vec<NewItem>,
    pub supplies: Vec<NewItem>,
}

pub fn insert_hunt(c: &Connection, hunt: &NewHunt) -> Result<i64> {
    let columns = SESSION_COLUMNS.join(", ");
    let marks = vec!["?"; SESSION_COLUMNS.len() + 5].join(", ");
    let mut values = session_values(&hunt.session);
    values.extend([
        Value::Text(hunt.category.clone()),
        hunt.source_file.clone().map_or(Value::Null, Value::Text),
        Value::Text(hunt.content_hash.clone()),
        Value::Text(hunt.raw_json.clone()),
        Value::Text(to_db(hunt.created_at)),
    ]);
    c.execute(
        &format!(
            "INSERT INTO hunt_sessions ({columns}, category, source_file, content_hash, raw_json, \
             created_at) VALUES ({marks})"
        ),
        params_from_iter(values),
    )?;
    let hunt_id = c.last_insert_rowid();
    let mut enemy = c.prepare(
        "INSERT INTO enemies_defeated (hunt_id, enemy, player, count, rare, ignored) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
    )?;
    for e in &hunt.enemies {
        enemy.execute(params![hunt_id, e.enemy, e.player, e.count, e.rare, e.ignored])?;
    }
    for (source, items) in [(ItemSource::Drops, &hunt.drops), (ItemSource::Supplies, &hunt.supplies)] {
        for item in items {
            insert_item(c, source, hunt_id, item, None)?;
        }
    }
    Ok(hunt_id)
}

pub fn insert_item(
    c: &Connection,
    source: ItemSource,
    hunt_id: i64,
    item: &NewItem,
    chat_reward_id: Option<i64>,
) -> Result<i64> {
    let table = source.table();
    let (extra_column, extra_mark) =
        if source == ItemSource::Drops { (", chat_reward_id", ", ?10") } else { ("", "") };
    let sql = format!(
        "INSERT INTO {table} (hunt_id, item, count, unit_price, total_price, original_unit_price, \
         original_total_price, player, ignored{extra_column}) \
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9{extra_mark})"
    );
    let mut values: Vec<Value> = vec![
        hunt_id.into(),
        item.item.clone().into(),
        item.count.into(),
        item.unit_price.into(),
        item.total_price.into(),
        item.original_unit_price.into(),
        item.original_total_price.into(),
        item.player.clone().into(),
        item.ignored.into(),
    ];
    if source == ItemSource::Drops {
        values.push(chat_reward_id.into());
    }
    c.execute(&sql, params_from_iter(values))?;
    Ok(c.last_insert_rowid())
}

/// A sessão com inimigos, drops, supplies e mensagens do chat.
pub fn get_with_details(c: &Connection, hunt_id: i64) -> Result<Option<HuntDetails>> {
    let columns = SESSION_COLUMNS.join(", ");
    let found = c
        .query_row(
            &format!(
                "SELECT {columns}, id, category, source_file, content_hash, raw_json, created_at \
                 FROM hunt_sessions WHERE id = ?1"
            ),
            [hunt_id],
            |r| {
                let n = SESSION_COLUMNS.len();
                Ok(HuntDetails {
                    session: session_from_row(r, 0)?,
                    id: r.get(n)?,
                    category: r.get(n + 1)?,
                    source_file: r.get(n + 2)?,
                    content_hash: r.get(n + 3)?,
                    raw_json: r.get(n + 4)?,
                    created_at: datetime(r, n + 5)?,
                    enemies: Vec::new(),
                    drops: Vec::new(),
                    supplies: Vec::new(),
                    chat_rewards: Vec::new(),
                })
            },
        )
        .optional()?;
    let Some(mut hunt) = found else { return Ok(None) };
    let mut enemies = c.prepare(
        "SELECT id, enemy, player, count, rare, ignored FROM enemies_defeated WHERE hunt_id = ?1 ORDER BY id",
    )?;
    hunt.enemies = enemies
        .query_map([hunt_id], |r| {
            Ok(EnemyRow {
                id: r.get(0)?,
                enemy: r.get(1)?,
                player: r.get(2)?,
                count: r.get(3)?,
                rare: r.get(4)?,
                ignored: r.get(5)?,
            })
        })?
        .collect::<rusqlite::Result<_>>()?;
    hunt.drops = items(c, ItemSource::Drops, "hunt_id = ?1", hunt_id)?;
    hunt.supplies = items(c, ItemSource::Supplies, "hunt_id = ?1", hunt_id)?;
    let mut rewards = c.prepare("SELECT id, text, created_at FROM chat_rewards WHERE hunt_id = ?1 ORDER BY id")?;
    hunt.chat_rewards = rewards
        .query_map([hunt_id], |r| Ok(ChatRewardRow { id: r.get(0)?, text: r.get(1)?, created_at: datetime(r, 2)? }))?
        .collect::<rusqlite::Result<_>>()?;
    Ok(Some(hunt))
}

/// Drops ou supplies que atendem `condition` (com o parâmetro `?1`), na ordem dos ids.
pub fn items(c: &Connection, source: ItemSource, condition: &str, value: impl rusqlite::ToSql) -> Result<Vec<ItemRow>> {
    let chat = if source == ItemSource::Drops { "chat_reward_id" } else { "NULL" };
    let mut statement = c.prepare(&format!(
        "SELECT id, item, count, unit_price, total_price, original_unit_price, original_total_price, \
         player, ignored, {chat} FROM {} WHERE {condition} ORDER BY id",
        source.table()
    ))?;
    let rows = statement.query_map([value], |r| {
        Ok(ItemRow {
            id: r.get(0)?,
            item: r.get(1)?,
            count: r.get(2)?,
            unit_price: r.get(3)?,
            total_price: r.get(4)?,
            original_unit_price: r.get(5)?,
            original_total_price: r.get(6)?,
            player: r.get(7)?,
            ignored: r.get(8)?,
            chat_reward_id: r.get(9)?,
        })
    })?;
    Ok(rows.collect::<rusqlite::Result<_>>()?)
}

fn summary_from_row(r: &Row<'_>) -> rusqlite::Result<HuntSummary> {
    Ok(HuntSummary {
        id: r.get(0)?,
        session_id: r.get(1)?,
        player: r.get(2)?,
        start_datetime: datetime(r, 3)?,
        duration_seconds: r.get(4)?,
        status: r.get(5)?,
        kills: r.get(6)?,
        kills_per_hour: r.get(7)?,
        profit: r.get(8)?,
        profit_per_hour: r.get(9)?,
        supplies: r.get(10)?,
        supplies_per_hour: r.get(11)?,
        raw_gains: r.get(12)?,
        raw_gains_per_hour: r.get(13)?,
        damage_dealt: r.get(14)?,
        damage_dealt_per_second: r.get(15)?,
        damage_taken: r.get(16)?,
        damage_taken_per_second: r.get(17)?,
        experience: r.get(18)?,
        experience_per_hour: r.get(19)?,
        source_file: r.get(20)?,
        category: r.get(21)?,
    })
}

/// Linhas leves para a tabela de sessões, mais recentes primeiro.
pub fn list_summaries(c: &Connection, filter: Option<&HuntFilter>) -> Result<Vec<HuntSummary>> {
    let conditions = hunt_filter_conditions(filter);
    let mut statement = c.prepare(&format!(
        "SELECT {SUMMARY_COLUMNS} FROM hunt_sessions {} \
         ORDER BY hunt_sessions.start_datetime DESC, hunt_sessions.id DESC",
        conditions.where_clause()
    ))?;
    let rows = statement.query_map(params_from_iter(conditions.params), summary_from_row)?;
    Ok(rows.collect::<rusqlite::Result<_>>()?)
}

/// Resumo das sessões informadas, em ordem cronológica (usado na comparação).
pub fn list_summaries_by_ids(c: &Connection, hunt_ids: &[i64]) -> Result<Vec<HuntSummary>> {
    let marks = vec!["?"; hunt_ids.len()].join(", ");
    let mut statement = c.prepare(&format!(
        "SELECT {SUMMARY_COLUMNS} FROM hunt_sessions WHERE id IN ({marks}) ORDER BY {CHRONOLOGICAL}"
    ))?;
    let rows = statement.query_map(params_from_iter(hunt_ids), summary_from_row)?;
    Ok(rows.collect::<rusqlite::Result<_>>()?)
}

pub fn count(c: &Connection, filter: Option<&HuntFilter>) -> Result<i64> {
    let conditions = hunt_filter_conditions(filter);
    Ok(c.query_row(
        &format!("SELECT count(hunt_sessions.id) FROM hunt_sessions {}", conditions.where_clause()),
        params_from_iter(conditions.params),
        |r| r.get(0),
    )?)
}

/// Sessões já importadas que representam a mesma sessão.
///
/// É duplicada quando o conteúdo é idêntico OU quando `session_id + player + início`
/// coincidem. O `Session ID` sozinho não basta: não há garantia de que seja único.
pub fn find_duplicate_ids(
    c: &Connection,
    session_id: Option<i64>,
    player: Option<&str>,
    start: Option<NaiveDateTime>,
    content_hash: &str,
) -> Result<Vec<i64>> {
    let mut sql = "SELECT id FROM hunt_sessions WHERE content_hash = ?".to_owned();
    let mut values: Vec<Value> = vec![content_hash.to_owned().into()];
    if let (Some(session_id), Some(start)) = (session_id, start) {
        let player_sql = if player.is_some() { "player = ?" } else { "player IS NULL" };
        sql.push_str(&format!(" OR (session_id = ? AND {player_sql} AND start_datetime = ?)"));
        values.push(session_id.into());
        if let Some(player) = player {
            values.push(player.to_owned().into());
        }
        values.push(to_db(start).into());
    }
    sql.push_str(" ORDER BY id");
    let mut statement = c.prepare(&sql)?;
    let rows = statement.query_map(params_from_iter(values), |r| r.get(0))?;
    Ok(rows.collect::<rusqlite::Result<_>>()?)
}

fn id_list(ids: &[i64]) -> String {
    vec!["?"; ids.len()].join(", ")
}

pub fn set_category(c: &Connection, hunt_ids: &[i64], category: &str) -> Result<usize> {
    if hunt_ids.is_empty() {
        return Ok(0);
    }
    let mut values: Vec<Value> = vec![category.to_owned().into()];
    values.extend(hunt_ids.iter().map(|id| Value::Integer(*id)));
    Ok(c.execute(
        &format!("UPDATE hunt_sessions SET category = ? WHERE id IN ({})", id_list(hunt_ids)),
        params_from_iter(values),
    )?)
}

/// `{nome em minúsculas: categorias das sessões em que o inimigo apareceu}`.
pub fn enemy_categories(c: &Connection, keys: &BTreeSet<String>) -> Result<BTreeMap<String, BTreeSet<String>>> {
    let mut found: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    if keys.is_empty() {
        return Ok(found);
    }
    let marks = vec!["?"; keys.len()].join(", ");
    let mut statement = c.prepare(&format!(
        "SELECT DISTINCT lower(enemies_defeated.enemy), hunt_sessions.category FROM enemies_defeated \
         JOIN hunt_sessions ON hunt_sessions.id = enemies_defeated.hunt_id \
         WHERE lower(enemies_defeated.enemy) IN ({marks})"
    ))?;
    let rows = statement.query_map(params_from_iter(keys), |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))?;
    for row in rows {
        let (name, category) = row?;
        found.entry(name).or_default().insert(category);
    }
    Ok(found)
}

/// JSON original das sessões filtradas (para seções que não têm tabela própria).
pub fn raw_documents(c: &Connection, filter: Option<&HuntFilter>) -> Result<Vec<String>> {
    let conditions = hunt_filter_conditions(filter);
    let mut statement = c.prepare(&format!(
        "SELECT raw_json FROM hunt_sessions {}",
        conditions.where_clause()
    ))?;
    let rows = statement.query_map(params_from_iter(conditions.params), |r| r.get(0))?;
    Ok(rows.collect::<rusqlite::Result<_>>()?)
}

/// Apaga as sessões; inimigos, drops, supplies e mensagens saem pelas chaves estrangeiras.
pub fn delete_many(c: &Connection, hunt_ids: &[i64]) -> Result<usize> {
    if hunt_ids.is_empty() {
        return Ok(0);
    }
    Ok(c.execute(
        &format!("DELETE FROM hunt_sessions WHERE id IN ({})", id_list(hunt_ids)),
        params_from_iter(hunt_ids),
    )?)
}

pub fn distinct_players(c: &Connection) -> Result<Vec<String>> {
    let mut statement =
        c.prepare("SELECT DISTINCT player FROM hunt_sessions WHERE player IS NOT NULL ORDER BY player")?;
    let rows = statement.query_map([], |r| r.get(0))?;
    Ok(rows.collect::<rusqlite::Result<_>>()?)
}

/// Tabela e coluna do nome de inimigos (`None`) ou itens.
pub fn entry_table(source: Option<ItemSource>) -> (&'static str, &'static str) {
    match source {
        None => ("enemies_defeated", "enemy"),
        Some(source) => (source.table(), "item"),
    }
}

/// Nomes distintos de inimigos (`None`) ou itens, sem diferenciar maiúsculas na ordem.
pub fn distinct_names(c: &Connection, source: Option<ItemSource>) -> Result<Vec<String>> {
    let (table, column) = entry_table(source);
    let mut statement = c.prepare(&format!(
        "SELECT DISTINCT {table}.{column} FROM {table} ORDER BY lower({table}.{column})"
    ))?;
    let rows = statement.query_map([], |r| r.get(0))?;
    Ok(rows.collect::<rusqlite::Result<_>>()?)
}

// ------------------------------------------------- totais da sessão (preços e chat)

/// Totais que mudam quando o valor de um drop ou supply muda.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct HuntTotals {
    pub duration_seconds: Option<i64>,
    pub raw_gains: Option<i64>,
    pub raw_gains_per_hour: Option<f64>,
    pub profit: Option<i64>,
    pub profit_per_hour: Option<f64>,
    pub supplies: Option<i64>,
    pub supplies_per_hour: Option<f64>,
}

pub fn hunt_totals(c: &Connection, hunt_id: i64) -> Result<Option<HuntTotals>> {
    Ok(c.query_row(
        "SELECT duration_seconds, raw_gains, raw_gains_per_hour, profit, profit_per_hour, supplies, \
         supplies_per_hour FROM hunt_sessions WHERE id = ?1",
        [hunt_id],
        |r| {
            Ok(HuntTotals {
                duration_seconds: r.get(0)?,
                raw_gains: r.get(1)?,
                raw_gains_per_hour: r.get(2)?,
                profit: r.get(3)?,
                profit_per_hour: r.get(4)?,
                supplies: r.get(5)?,
                supplies_per_hour: r.get(6)?,
            })
        },
    )
    .optional()?)
}

pub fn save_hunt_totals(c: &Connection, hunt_id: i64, totals: &HuntTotals) -> Result<()> {
    c.execute(
        "UPDATE hunt_sessions SET raw_gains = ?2, raw_gains_per_hour = ?3, profit = ?4, \
         profit_per_hour = ?5, supplies = ?6, supplies_per_hour = ?7 WHERE id = ?1",
        params![hunt_id, totals.raw_gains, totals.raw_gains_per_hour, totals.profit,
            totals.profit_per_hour, totals.supplies, totals.supplies_per_hour],
    )?;
    Ok(())
}

pub fn set_item_price(c: &Connection, source: ItemSource, item_id: i64, unit_price: Option<f64>, total_price: Option<i64>) -> Result<()> {
    c.execute(
        &format!("UPDATE {} SET unit_price = ?2, total_price = ?3 WHERE id = ?1", source.table()),
        params![item_id, unit_price, total_price],
    )?;
    Ok(())
}
