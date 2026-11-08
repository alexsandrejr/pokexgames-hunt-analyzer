//! Regras de negócio das sessões: importação, consulta, exclusão e recompensas do chat
//! (equivale a `app/services/hunt_service.py`).
//!
//! Toda sessão importada recebe uma categoria. Como o arquivo do Analyzer não a informa, ela é
//! decidida nesta ordem:
//!
//! 1. a pasta do arquivo (`imports/terrors/x.json` → Terror);
//! 2. a categoria pedida na importação (a aba de Bosses aberta);
//! 3. os inimigos da sessão, se todos já apareceram só numa mesma categoria de boss;
//! 4. Hunt.

use std::collections::{BTreeSet, HashMap};
use std::path::{Path, PathBuf};

use chrono::Local;

use super::analyzer::{AnalyzerImportError, ParsedHunt, ParsedItem, parse_analyzer_text, read_analyzer_file};
use super::categories::{Category, category_dir, category_from_folder};
use super::chat_rewards::{parse_chat_rewards, resolve_item_name};
use super::files::{suggested_filename, write_new_json_file};
use super::filters::{HuntFilter, ItemSource};
use super::model::{ChatRewardPreview, FilterOptions, HuntDetails, HuntSummary, ImportResult, ImportStatus, RewardLine};
use super::repository::{self as repo, NewHunt, NewItem};
use crate::db::Database;
use crate::db::datetime::to_db;
use crate::error::{Error, Result};
use crate::prices::{self, item_key, shift_hunt_totals};
use crate::parse::round_to_i64;
use crate::text::{py_split, py_strip};

pub const DUPLICATE_MESSAGE: &str = "Esta Hunt já foi importada.";
pub const IMPORTED_MESSAGE: &str = "Hunt importada com sucesso.";
pub const PASTED_SOURCE: &str = "Texto colado";

fn error_result(source: &str, error: AnalyzerImportError) -> ImportResult {
    ImportResult { detail: error.detail, ..ImportResult::new(ImportStatus::Error, source, &error.message) }
}

fn item_fields(item: &ParsedItem) -> NewItem {
    NewItem {
        item: item.item.clone(),
        count: item.count,
        unit_price: item.unit_price,
        total_price: item.total_price,
        original_unit_price: item.unit_price,
        original_total_price: item.total_price,
        player: item.player.clone(),
        ignored: item.ignored,
    }
}

fn total(unit_price: Option<f64>, count: i64) -> Option<i64> {
    unit_price.and_then(|price| round_to_i64(price * count as f64))
}

fn collapse(text: &str) -> String {
    py_split(text).collect::<Vec<_>>().join(" ")
}

pub struct HuntService<'a> {
    database: &'a Database,
}

impl<'a> HuntService<'a> {
    pub fn new(database: &'a Database) -> Self {
        Self { database }
    }

    // ------------------------------------------------------------ importação

    /// Importa um JSON ou TSV do Analyzer a partir de um arquivo.
    ///
    /// Erros de conteúdo não viram `Err`: o resultado informa o status (importada, duplicada ou
    /// erro) com a mensagem para o usuário. `Err` fica para falhas do banco.
    pub fn import_file(&self, path: &Path, allow_duplicate: bool, category: Option<Category>) -> Result<ImportResult> {
        let source = path.to_string_lossy().into_owned();
        match read_analyzer_file(path) {
            Ok(text) => self.import_text(&text, &source, allow_duplicate, category),
            Err(error) => Ok(error_result(&source, error)),
        }
    }

    pub fn import_text(&self, text: &str, source: &str, allow_duplicate: bool, category: Option<Category>) -> Result<ImportResult> {
        let name = Path::new(source).file_name().map(|n| n.to_string_lossy().into_owned()).filter(|n| !n.is_empty());
        let parsed = match parse_analyzer_text(text, name) {
            Ok(parsed) => parsed,
            Err(error) => return Ok(error_result(source, error)),
        };
        let category = category_from_folder(Path::new(source)).or(category);
        self.store(parsed, source, allow_duplicate, None, category)
    }

    /// Importa um JSON ou TSV colado e o salva como arquivo `.json`.
    ///
    /// Hunts vão para `save_dir`; bosses, para a subpasta da categoria. O arquivo só é criado se
    /// a sessão for de fato gravada: texto inválido ou duplicidade não confirmada não deixam
    /// arquivos para trás. Um TSV é salvo já convertido para JSON.
    pub fn import_pasted_text(&self, text: &str, save_dir: &Path, allow_duplicate: bool, category: Option<Category>) -> Result<ImportResult> {
        match parse_analyzer_text(py_strip(text), None) {
            Ok(parsed) => self.store(parsed, PASTED_SOURCE, allow_duplicate, Some(save_dir), category),
            Err(error) => Ok(error_result(PASTED_SOURCE, error)),
        }
    }

    fn store(
        &self,
        mut parsed: ParsedHunt,
        source: &str,
        allow_duplicate: bool,
        save_dir: Option<&Path>,
        category: Option<Category>,
    ) -> Result<ImportResult> {
        let mut saved_path: Option<PathBuf> = None;
        let result = self.database.transaction(|tx| {
            let category = match category {
                Some(category) => category,
                None => known_boss_category(tx, &parsed)?.unwrap_or(Category::Hunt),
            };
            let s = &parsed.session;
            let duplicates = repo::find_duplicate_ids(
                tx, s.session_id, s.player.as_deref(), s.start_datetime, &parsed.content_hash,
            )?;
            if !duplicates.is_empty() && !allow_duplicate {
                return Ok(ImportResult {
                    duplicate_of: duplicates,
                    warnings: parsed.warnings.clone(),
                    ..ImportResult::new(ImportStatus::Duplicate, source, DUPLICATE_MESSAGE)
                });
            }
            let mut source = source.to_owned();
            if let Some(save_dir) = save_dir {
                let path = write_new_json_file(
                    &category_dir(save_dir, category),
                    &suggested_filename(&parsed.session, None),
                    &parsed.raw_json,
                )?;
                parsed.source_file = path.file_name().map(|n| n.to_string_lossy().into_owned());
                source = path.to_string_lossy().into_owned();
                saved_path = Some(path);
            }
            let mut hunt = NewHunt {
                session: parsed.session.clone(),
                category: category.as_str().to_owned(),
                source_file: parsed.source_file.clone(),
                content_hash: parsed.content_hash.clone(),
                raw_json: parsed.raw_json.clone(),
                created_at: Local::now().naive_local(),
                enemies: parsed.enemies.clone(),
                drops: parsed.drops.iter().map(item_fields).collect(),
                supplies: parsed.supplies.iter().map(item_fields).collect(),
            };
            prices::apply_custom_prices(&mut hunt, &prices::price_map(tx)?);
            let hunt_id = repo::insert_hunt(tx, &hunt)?;
            let message = if category.is_boss() {
                format!("Sessão importada em {}.", category.plural())
            } else {
                IMPORTED_MESSAGE.to_owned()
            };
            Ok(ImportResult {
                hunt_id: Some(hunt_id),
                duplicate_of: duplicates,
                warnings: parsed.warnings.clone(),
                saved_path: saved_path.clone(),
                category: Some(category),
                ..ImportResult::new(ImportStatus::Imported, &source, &message)
            })
        });
        if result.is_err() {
            if let Some(path) = &saved_path {
                let _ = std::fs::remove_file(path);
            }
        }
        result
    }

    // -------------------------------------------------------------- consultas

    pub fn list_hunts(&self, filter: Option<&HuntFilter>) -> Result<Vec<HuntSummary>> {
        self.database.with(|c| repo::list_summaries(c, filter))
    }

    /// Resumos das sessões informadas, da mais antiga para a mais recente.
    pub fn get_summaries(&self, hunt_ids: &[i64]) -> Result<Vec<HuntSummary>> {
        self.database.with(|c| repo::list_summaries_by_ids(c, hunt_ids))
    }

    /// Sessão completa, com inimigos, drops, supplies e JSON original.
    pub fn get_hunt_details(&self, hunt_id: i64) -> Result<Option<HuntDetails>> {
        self.database.with(|c| repo::get_with_details(c, hunt_id))
    }

    pub fn count_hunts(&self, filter: Option<&HuntFilter>) -> Result<i64> {
        self.database.with(|c| repo::count(c, filter))
    }

    pub fn filter_options(&self) -> Result<FilterOptions> {
        self.database.with(|c| {
            Ok(FilterOptions {
                players: repo::distinct_players(c)?,
                enemies: repo::distinct_names(c, None)?,
                drop_items: repo::distinct_names(c, Some(ItemSource::Drops))?,
                supply_items: repo::distinct_names(c, Some(ItemSource::Supplies))?,
            })
        })
    }

    pub fn delete_hunts(&self, hunt_ids: &[i64]) -> Result<usize> {
        self.database.transaction(|tx| repo::delete_many(tx, hunt_ids))
    }

    /// Move as sessões para outra categoria (ex.: um boss importado como Hunt).
    pub fn set_category(&self, hunt_ids: &[i64], category: Category) -> Result<usize> {
        self.database.transaction(|tx| repo::set_category(tx, hunt_ids, category.as_str()))
    }

    // ---------------------------------------------------- recompensas do chat

    /// Lê as mensagens "Você recebeu:" sem gravar: nomes no banco, preços e repetições.
    ///
    /// Um item que aparece em mais de uma mensagem vira uma linha só, somada.
    pub fn preview_chat_rewards(&self, hunt_id: Option<i64>, text: &str) -> Result<ChatRewardPreview> {
        let parsed = parse_chat_rewards(text);
        self.database.with(|c| {
            let known = known_item_names(c)?;
            let mut order: Vec<String> = Vec::new();
            let mut merged: HashMap<String, RewardLine> = HashMap::new();
            for entry in &parsed.items {
                let (name, is_known) = resolve_item_name(&entry.name, entry.count, &known);
                let key = item_key(&name);
                match merged.get_mut(&key) {
                    Some(line) => line.count += entry.count,
                    None => {
                        order.push(key.clone());
                        merged.insert(key, RewardLine {
                            chat_name: entry.name.clone(),
                            item: name,
                            count: entry.count,
                            unit_price: None,
                            known: is_known,
                        });
                    }
                }
            }
            let prices = reward_prices(c, &order.iter().cloned().collect())?;
            let lines = order
                .iter()
                .map(|key| RewardLine { unit_price: prices.get(key).copied(), ..merged[key].clone() })
                .collect();
            let mut repeated = Vec::new();
            if let Some(hunt) = hunt_id.map(|id| repo::get_with_details(c, id)).transpose()?.flatten() {
                let added: Vec<String> = hunt
                    .chat_rewards
                    .iter()
                    .flat_map(|r| r.messages().into_iter().map(str::to_owned).collect::<Vec<_>>())
                    .collect();
                repeated = parsed.messages.iter().filter(|m| added.contains(m)).cloned().collect();
            }
            Ok(ChatRewardPreview { lines, messages: parsed.messages.clone(), invalid: parsed.invalid.clone(), repeated })
        })
    }

    /// Linha com o nome escolhido pelo usuário (e o preço desse nome).
    pub fn quote_reward_item(&self, chat_name: &str, item: &str, count: i64) -> Result<RewardLine> {
        let item = collapse(item);
        let key = item_key(&item);
        self.database.with(|c| {
            let known = known_item_names(c)?.contains_key(&key);
            let price = reward_prices(c, &BTreeSet::from([key.clone()]))?.get(&key).copied();
            Ok(RewardLine { chat_name: chat_name.to_owned(), item: item.clone(), count, unit_price: price, known })
        })
    }

    /// Soma os itens das mensagens à sessão como drops; devolve quantos drops criou.
    ///
    /// `lines` são as linhas da prévia, com os nomes que o usuário corrigiu; sem elas, os nomes
    /// vêm de [`Self::preview_chat_rewards`]. O preço é o de agora: o personalizado do item ou o
    /// do Analyzer na sessão mais recente (que volta a valer se o personalizado for removido).
    /// Raw gains e Profit sobem junto.
    pub fn add_chat_rewards(&self, hunt_id: i64, text: &str, lines: Option<&[RewardLine]>) -> Result<usize> {
        let messages = parse_chat_rewards(text).messages;
        let preview_lines;
        let lines = match lines {
            Some(lines) => lines,
            None => {
                preview_lines = self.preview_chat_rewards(Some(hunt_id), text)?.lines;
                &preview_lines
            }
        };
        let mut order: Vec<String> = Vec::new();
        let mut counts: HashMap<String, (String, i64)> = HashMap::new();
        for line in lines {
            let name = collapse(&line.item);
            if !name.is_empty() && line.count > 0 {
                let key = item_key(&name);
                let entry = counts.entry(key.clone()).or_insert_with(|| {
                    order.push(key);
                    (name, 0)
                });
                entry.1 += line.count;
            }
        }
        if messages.is_empty() || counts.is_empty() {
            return Err(Error::user("Nenhum item de mensagem \"Você recebeu:\" para adicionar."));
        }
        self.database.transaction(|tx| {
            let hunt = repo::get_with_details(tx, hunt_id)?
                .ok_or_else(|| Error::user("A sessão não existe mais no banco de dados."))?;
            let analyzer = prices::latest_analyzer_prices(tx, &order.iter().cloned().collect())?;
            let custom = prices::price_map(tx)?;
            tx.execute(
                "INSERT INTO chat_rewards (hunt_id, text, created_at) VALUES (?1, ?2, ?3)",
                rusqlite::params![hunt_id, messages.join("\n"), to_db(Local::now().naive_local())],
            )?;
            let reward_id = tx.last_insert_rowid();
            let mut totals = repo::hunt_totals(tx, hunt_id)?.expect("a sessão acabou de ser lida");
            for key in &order {
                let (name, count) = &counts[key];
                let original = analyzer.get(key).copied();
                let price = custom.get(key).copied().or(original);
                let drop = NewItem {
                    item: name.clone(),
                    count: *count,
                    unit_price: price,
                    total_price: total(price, *count),
                    original_unit_price: original,
                    original_total_price: total(original, *count),
                    player: hunt.session.player.clone(),
                    ignored: None,
                };
                repo::insert_item(tx, ItemSource::Drops, hunt_id, &drop, Some(reward_id))?;
                shift_hunt_totals(&mut totals, ItemSource::Drops, None, drop.total_price.unwrap_or(0));
            }
            repo::save_hunt_totals(tx, hunt_id, &totals)?;
            Ok(order.len())
        })
    }

    /// Tira da sessão todos os drops vindos do chat; devolve quantos removeu.
    pub fn remove_chat_rewards(&self, hunt_id: i64) -> Result<usize> {
        self.database.transaction(|tx| {
            let Some(hunt) = repo::get_with_details(tx, hunt_id)? else { return Ok(0) };
            let mut totals = repo::hunt_totals(tx, hunt_id)?.expect("a sessão acabou de ser lida");
            let chat_drops: Vec<_> = hunt.drops.iter().filter(|d| d.from_chat()).collect();
            for drop in &chat_drops {
                shift_hunt_totals(&mut totals, ItemSource::Drops, drop.ignored, -drop.total_price.unwrap_or(0));
                tx.execute("DELETE FROM drops WHERE id = ?1", [drop.id])?;
            }
            tx.execute("DELETE FROM chat_rewards WHERE hunt_id = ?1", [hunt_id])?;
            repo::save_hunt_totals(tx, hunt_id, &totals)?;
            Ok(chat_drops.len())
        })
    }
}

/// Categoria de boss em que todos os inimigos da sessão já apareceram (e só nela).
///
/// Depois que um boss é importado na aba certa uma vez, as próximas sessões dele vão para lá
/// sozinhas, mesmo importadas fora da aba.
fn known_boss_category(c: &rusqlite::Connection, parsed: &ParsedHunt) -> Result<Option<Category>> {
    let names: BTreeSet<String> = parsed.enemies.iter().map(|e| py_strip(&e.enemy).to_lowercase()).collect();
    if names.is_empty() {
        return Ok(None);
    }
    let seen = repo::enemy_categories(c, &names)?;
    let mut categories = BTreeSet::new();
    for name in &names {
        match seen.get(name) {
            Some(found) if !found.contains(Category::Hunt.as_str()) => categories.extend(found.iter().cloned()),
            _ => return Ok(None),
        }
    }
    if categories.len() != 1 {
        return Ok(None);
    }
    let category = Category::from_value(categories.first().map(String::as_str));
    Ok(category.is_boss().then_some(category))
}

/// `{nome em minúsculas: nome exibido}` de drops, supplies e preços personalizados.
fn known_item_names(c: &rusqlite::Connection) -> Result<HashMap<String, String>> {
    let mut names: HashMap<String, String> =
        prices::all_prices(c)?.into_iter().map(|(key, item, _)| (key, item)).collect();
    for source in [ItemSource::Supplies, ItemSource::Drops] {
        // Drops por último: têm prioridade.
        for name in repo::distinct_names(c, Some(source))? {
            names.insert(item_key(&name), name);
        }
    }
    Ok(names)
}

/// Preço que um drop do chat recebe: o personalizado ou o último do Analyzer.
fn reward_prices(c: &rusqlite::Connection, keys: &BTreeSet<String>) -> Result<HashMap<String, f64>> {
    let mut found = prices::latest_analyzer_prices(c, keys)?;
    for (key, price) in prices::price_map(c)? {
        if keys.contains(&key) {
            found.insert(key, price);
        }
    }
    Ok(found)
}
