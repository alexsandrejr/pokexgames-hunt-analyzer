//! Leitura, validação e extração dos arquivos do Analyzer do PokeXGames (equivale a
//! `app/services/json_importer.py`).
//!
//! O TSV também é aceito: [`parse_analyzer_text`] detecta o formato e converte o TSV no JSON
//! equivalente antes de extrair. Este módulo não conhece o banco: ele transforma o texto num
//! [`ParsedHunt`], e quem grava é o serviço de sessões.

use std::path::Path;

use chrono::NaiveDateTime;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

use super::tsv::{looks_like_tsv, tsv_to_document};
use crate::parse::{int_true_div, parse_datetime, parse_duration, round_to_i64, to_bool, to_float, to_int, to_str};
use crate::pyjson::{dumps_canonical, dumps_pretty};

pub const SECONDS_PER_HOUR: i64 = 3600;

/// Tipo do erro de importação; cada um tem a mensagem padrão para o usuário.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ImportErrorKind {
    FileRead,
    InvalidJson,
    InvalidTsv,
    InvalidSession,
}

/// Erro de importação com mensagem pronta para exibir e o detalhe técnico.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AnalyzerImportError {
    pub kind: ImportErrorKind,
    pub message: String,
    pub detail: Option<String>,
}

impl AnalyzerImportError {
    pub fn new(kind: ImportErrorKind, detail: impl Into<String>) -> Self {
        let message = match kind {
            ImportErrorKind::FileRead => "Não foi possível ler o arquivo.",
            ImportErrorKind::InvalidJson => "JSON inválido.",
            ImportErrorKind::InvalidTsv => "TSV inválido.",
            ImportErrorKind::InvalidSession => "O arquivo não possui uma sessão válida do Analyzer.",
        };
        Self { kind, message: message.to_owned(), detail: Some(detail.into()) }
    }
}

impl std::fmt::Display for AnalyzerImportError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AnalyzerImportError {}

/// Campos da seção `Session`, com os nomes das colunas de `hunt_sessions`.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ParsedSession {
    pub session_id: Option<i64>,
    pub player: Option<String>,
    pub start_datetime: Option<NaiveDateTime>,
    pub duration_seconds: Option<i64>,
    pub paused_seconds: Option<i64>,
    pub status: Option<String>,
    pub session_type: Option<String>,
    pub kills: Option<i64>,
    pub kills_per_hour: Option<f64>,
    pub rare_kills: Option<i64>,
    pub rare_kills_per_hour: Option<f64>,
    pub experience: Option<i64>,
    pub experience_per_hour: Option<f64>,
    pub profit: Option<i64>,
    pub profit_per_hour: Option<f64>,
    pub supplies: Option<i64>,
    pub supplies_per_hour: Option<f64>,
    pub raw_gains: Option<i64>,
    pub raw_gains_per_hour: Option<f64>,
    pub damage_dealt: Option<i64>,
    pub damage_dealt_per_second: Option<f64>,
    pub damage_taken: Option<i64>,
    pub damage_taken_per_second: Option<f64>,
    pub time_to_next_level: Option<String>,
    pub time_to_next_level_seconds: Option<i64>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ParsedEnemy {
    pub enemy: String,
    pub count: i64,
    pub player: Option<String>,
    pub rare: Option<bool>,
    pub ignored: Option<bool>,
}

/// Entrada de `Drops` ou `Supplies`.
#[derive(Debug, Clone, PartialEq)]
pub struct ParsedItem {
    pub item: String,
    pub count: i64,
    pub unit_price: Option<f64>,
    pub total_price: Option<i64>,
    pub player: Option<String>,
    pub ignored: Option<bool>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ParsedHunt {
    pub session: ParsedSession,
    pub enemies: Vec<ParsedEnemy>,
    pub drops: Vec<ParsedItem>,
    pub supplies: Vec<ParsedItem>,
    pub raw_json: String,
    pub content_hash: String,
    pub source_file: Option<String>,
    pub warnings: Vec<String>,
}

/// Pelo menos uma destas chaves precisa existir para considerar a sessão válida.
pub const REQUIRED_SESSION_KEYS: [&str; 4] = ["Session ID", "Start", "Duration seconds", "Duration"];

/// Lê o arquivo como texto UTF-8, tolerando BOM.
///
/// Como o modo texto do Python, troca `\r\n` e `\r` por `\n`: o `raw_json` guardado é o mesmo
/// nas duas versões (o hash não muda, porque é calculado do conteúdo já lido).
pub fn read_analyzer_file(path: &Path) -> Result<String, AnalyzerImportError> {
    let bytes = std::fs::read(path)
        .map_err(|e| AnalyzerImportError::new(ImportErrorKind::FileRead, e.to_string()))?;
    let bytes = bytes.strip_prefix(b"\xef\xbb\xbf").unwrap_or(&bytes);
    let text = String::from_utf8(bytes.to_vec()).map_err(|e| {
        AnalyzerImportError::new(ImportErrorKind::InvalidJson, format!("Codificação inválida: {e}"))
    })?;
    Ok(text.replace("\r\n", "\n").replace('\r', "\n"))
}

pub fn load_json(text: &str) -> Result<Value, AnalyzerImportError> {
    serde_json::from_str(text)
        .map_err(|e| AnalyzerImportError::new(ImportErrorKind::InvalidJson, e.to_string()))
}

/// SHA-256 do JSON canônico (ignora espaços e ordem das chaves), igual ao do Python.
pub fn compute_content_hash(data: &Value) -> String {
    let digest = Sha256::digest(dumps_canonical(data).as_bytes());
    digest.iter().map(|b| format!("{b:02x}")).collect()
}

/// Garante que o documento tem uma seção `Session` utilizável.
pub fn validate_analyzer_document(data: &Value) -> Result<&Map<String, Value>, AnalyzerImportError> {
    let invalid = |detail: &str| AnalyzerImportError::new(ImportErrorKind::InvalidSession, detail);
    let Some(root) = data.as_object() else {
        return Err(invalid("A raiz do JSON não é um objeto."));
    };
    let Some(session) = root.get("Session").and_then(Value::as_object).filter(|s| !s.is_empty()) else {
        return Err(invalid("Seção 'Session' ausente ou vazia."));
    };
    if !REQUIRED_SESSION_KEYS.iter().any(|key| session.get(*key).is_some_and(|v| !v.is_null())) {
        return Err(invalid("A seção 'Session' não contém identificação, início ou duração."));
    }
    Ok(session)
}

/// Valida e extrai uma sessão do texto do Analyzer, em JSON ou TSV.
///
/// O TSV é convertido e guardado como JSON (`raw_json`), com todas as seções.
pub fn parse_analyzer_text(text: &str, source_file: Option<String>) -> Result<ParsedHunt, AnalyzerImportError> {
    if !looks_like_tsv(text) {
        return parse_analyzer_json(text, source_file);
    }
    let document = tsv_to_document(text)
        .map_err(|e| AnalyzerImportError::new(ImportErrorKind::InvalidTsv, e.0))?;
    let data = Value::Object(document);
    let raw_json = dumps_pretty(&data, 2);
    parse_document(&data, raw_json, source_file)
}

/// Valida e extrai uma sessão do texto JSON do Analyzer.
pub fn parse_analyzer_json(text: &str, source_file: Option<String>) -> Result<ParsedHunt, AnalyzerImportError> {
    parse_document(&load_json(text)?, text.to_owned(), source_file)
}

fn parse_document(data: &Value, raw_json: String, source_file: Option<String>) -> Result<ParsedHunt, AnalyzerImportError> {
    let session_data = validate_analyzer_document(data)?;
    let mut warnings = Vec::new();
    let mut session = parse_session(session_data);
    let enemies = parse_entries(data, "Enemies Defeated", parse_enemy, &mut warnings);
    let drops = parse_entries(data, "Drops", parse_item, &mut warnings);
    let supplies = parse_entries(data, "Supplies", parse_item, &mut warnings);
    if session.player.is_none() {
        let players = enemies
            .iter()
            .map(|e| &e.player)
            .chain(drops.iter().map(|d| &d.player))
            .chain(supplies.iter().map(|s| &s.player));
        session.player = infer_player(players);
    }
    Ok(ParsedHunt {
        session,
        enemies,
        drops,
        supplies,
        raw_json,
        content_hash: compute_content_hash(data),
        source_file,
        warnings,
    })
}

fn parse_session(data: &Map<String, Value>) -> ParsedSession {
    let get = |key: &str| data.get(key).unwrap_or(&Value::Null);
    let int = |key| to_int(get(key));
    let float = |key| to_float(get(key));
    let text = |key| to_str(get(key));
    let mut session = ParsedSession {
        session_id: int("Session ID"),
        player: text("Player"),
        start_datetime: parse_datetime(get("Start")),
        duration_seconds: int("Duration seconds"),
        paused_seconds: int("Paused seconds"),
        status: text("Status"),
        session_type: text("Session type"),
        kills: int("Kills"),
        kills_per_hour: float("Kills per hour"),
        rare_kills: int("Rare kills"),
        rare_kills_per_hour: float("Rare kills per hour"),
        experience: int("Experience"),
        experience_per_hour: float("Experience per hour"),
        profit: int("Profit"),
        profit_per_hour: float("Profit per hour"),
        supplies: int("Supplies"),
        supplies_per_hour: float("Supplies per hour"),
        raw_gains: int("Raw gains"),
        raw_gains_per_hour: float("Raw gains per hour"),
        damage_dealt: int("Damage dealt"),
        damage_dealt_per_second: float("Damage dealt per second"),
        damage_taken: int("Damage taken"),
        damage_taken_per_second: float("Damage taken per second"),
        time_to_next_level: text("Time to next level"),
        time_to_next_level_seconds: int("Time to next level seconds"),
    };
    if session.duration_seconds.is_none() {
        session.duration_seconds = to_str(get("Duration")).and_then(|d| parse_duration(&d));
    }
    // Taxas ausentes são derivadas do total: (taxa, total, segundos da unidade).
    if let Some(duration) = session.duration_seconds.filter(|d| *d > 0) {
        let duration = i128::from(duration);
        let s = &mut session;
        let rates: [(&mut Option<f64>, Option<i64>, i64); 8] = [
            (&mut s.kills_per_hour, s.kills, SECONDS_PER_HOUR),
            (&mut s.rare_kills_per_hour, s.rare_kills, SECONDS_PER_HOUR),
            (&mut s.experience_per_hour, s.experience, SECONDS_PER_HOUR),
            (&mut s.profit_per_hour, s.profit, SECONDS_PER_HOUR),
            (&mut s.supplies_per_hour, s.supplies, SECONDS_PER_HOUR),
            (&mut s.raw_gains_per_hour, s.raw_gains, SECONDS_PER_HOUR),
            (&mut s.damage_dealt_per_second, s.damage_dealt, 1),
            (&mut s.damage_taken_per_second, s.damage_taken, 1),
        ];
        for (rate, total, unit) in rates {
            if rate.is_none() {
                if let Some(total) = total {
                    *rate = Some(int_true_div(i128::from(total) * i128::from(unit), duration));
                }
            }
        }
    }
    session
}

fn parse_entries<T>(
    data: &Value,
    key: &str,
    parse_entry: fn(&Map<String, Value>) -> Option<T>,
    warnings: &mut Vec<String>,
) -> Vec<T> {
    let raw = data.get(key).unwrap_or(&Value::Null);
    if raw.is_null() {
        return Vec::new();
    }
    let Some(raw_entries) = raw.as_array() else {
        warnings.push(format!("'{key}' não é uma lista e foi ignorado."));
        return Vec::new();
    };
    let mut entries = Vec::new();
    let mut skipped = 0;
    for raw in raw_entries {
        match raw.as_object().and_then(parse_entry) {
            Some(entry) => entries.push(entry),
            None => skipped += 1,
        }
    }
    if skipped > 0 {
        warnings.push(format!("{skipped} registro(s) inválido(s) em '{key}' foram ignorados."));
    }
    entries
}

fn field<'a>(raw: &'a Map<String, Value>, key: &str) -> &'a Value {
    raw.get(key).unwrap_or(&Value::Null)
}

fn parse_enemy(raw: &Map<String, Value>) -> Option<ParsedEnemy> {
    Some(ParsedEnemy {
        enemy: to_str(field(raw, "Enemy"))?,
        count: to_int(field(raw, "Count")).unwrap_or(0),
        player: to_str(field(raw, "Player")),
        rare: to_bool(field(raw, "Rare")),
        ignored: to_bool(field(raw, "Ignored")),
    })
}

fn parse_item(raw: &Map<String, Value>) -> Option<ParsedItem> {
    let item = to_str(field(raw, "Item"))?;
    let count = to_int(field(raw, "Count")).unwrap_or(0);
    let unit_price = to_float(field(raw, "Unit price"));
    let total_price = to_int(field(raw, "Total price"))
        .or_else(|| unit_price.and_then(|price| round_to_i64(price * count as f64)));
    Some(ParsedItem {
        item,
        count,
        unit_price,
        total_price,
        player: to_str(field(raw, "Player")),
        ignored: to_bool(field(raw, "Ignored")),
    })
}

/// A seção Session não traz o player; ele vem das listas. Com mais de um player, os nomes
/// são unidos em ordem de aparição.
fn infer_player<'a>(players: impl Iterator<Item = &'a Option<String>>) -> Option<String> {
    let mut seen: Vec<&str> = Vec::new();
    for player in players.flatten() {
        if !player.is_empty() && !seen.contains(&player.as_str()) {
            seen.push(player);
        }
    }
    if seen.is_empty() { None } else { Some(seen.join(", ")) }
}
