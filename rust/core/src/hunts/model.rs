//! Objetos trocados entre o serviço de sessões e a interface (equivale a `app/services/dto.py`
//! e às linhas de `HuntSession`, `Drop`, `Supply`, `EnemyDefeated` e `ChatReward`).

use std::path::PathBuf;

use chrono::NaiveDateTime;
use serde::Serialize;

use super::analyzer::ParsedSession;
use super::categories::Category;
use crate::format::round_half_even;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ImportStatus {
    Imported,
    Duplicate,
    Error,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ImportResult {
    pub status: ImportStatus,
    pub source: String,
    pub message: String,
    pub hunt_id: Option<i64>,
    pub duplicate_of: Vec<i64>,
    pub warnings: Vec<String>,
    pub detail: Option<String>,
    /// Arquivo criado a partir de um texto colado.
    pub saved_path: Option<PathBuf>,
    /// Categoria em que a sessão foi gravada.
    pub category: Option<Category>,
}

impl ImportResult {
    pub fn new(status: ImportStatus, source: &str, message: &str) -> Self {
        Self {
            status,
            source: source.to_owned(),
            message: message.to_owned(),
            hunt_id: None,
            duplicate_of: Vec::new(),
            warnings: Vec::new(),
            detail: None,
            saved_path: None,
            category: None,
        }
    }

    /// Nome do arquivo de origem, sem a pasta.
    pub fn source_name(&self) -> String {
        std::path::Path::new(&self.source)
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_default()
    }
}

/// Linha da listagem de sessões (sem JSON e sem listas relacionadas).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct HuntSummary {
    pub id: i64,
    pub session_id: Option<i64>,
    pub player: Option<String>,
    pub start_datetime: Option<NaiveDateTime>,
    pub duration_seconds: Option<i64>,
    pub status: Option<String>,
    pub kills: Option<i64>,
    pub kills_per_hour: Option<f64>,
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
    pub experience: Option<i64>,
    pub experience_per_hour: Option<f64>,
    pub source_file: Option<String>,
    pub category: String,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct EnemyRow {
    pub id: i64,
    pub enemy: String,
    pub player: Option<String>,
    pub count: i64,
    pub rare: Option<bool>,
    pub ignored: Option<bool>,
}

/// Drop ou supply gravado.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ItemRow {
    pub id: i64,
    pub item: String,
    pub count: i64,
    /// Preço em vigor: o do Analyzer ou o da tabela de preços personalizados.
    pub unit_price: Option<f64>,
    pub total_price: Option<i64>,
    /// Preço exportado pelo Analyzer, restaurado quando o personalizado é removido.
    pub original_unit_price: Option<f64>,
    pub original_total_price: Option<i64>,
    pub player: Option<String>,
    pub ignored: Option<bool>,
    /// Preenchido nos drops vindos de uma mensagem do chat; sempre `None` em supplies.
    pub chat_reward_id: Option<i64>,
}

impl ItemRow {
    pub fn from_chat(&self) -> bool {
        self.chat_reward_id.is_some()
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ChatRewardRow {
    pub id: i64,
    /// Uma mensagem por linha, como foram coladas.
    pub text: String,
    pub created_at: Option<NaiveDateTime>,
}

impl ChatRewardRow {
    pub fn messages(&self) -> Vec<&str> {
        self.text.lines().filter(|line| !crate::text::py_strip(line).is_empty()).collect()
    }
}

/// Sessão completa: colunas, listas e JSON original.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct HuntDetails {
    pub id: i64,
    pub session: ParsedSessionView,
    pub category: String,
    pub source_file: Option<String>,
    pub content_hash: String,
    pub raw_json: String,
    pub created_at: Option<NaiveDateTime>,
    pub enemies: Vec<EnemyRow>,
    pub drops: Vec<ItemRow>,
    pub supplies: Vec<ItemRow>,
    pub chat_rewards: Vec<ChatRewardRow>,
}

/// As colunas da seção `Session`, como gravadas.
pub type ParsedSessionView = ParsedSession;

impl serde::Serialize for ParsedSession {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        use serde::ser::SerializeStruct;
        let mut s = serializer.serialize_struct("ParsedSession", 25)?;
        s.serialize_field("session_id", &self.session_id)?;
        s.serialize_field("player", &self.player)?;
        s.serialize_field("start_datetime", &self.start_datetime)?;
        s.serialize_field("duration_seconds", &self.duration_seconds)?;
        s.serialize_field("paused_seconds", &self.paused_seconds)?;
        s.serialize_field("status", &self.status)?;
        s.serialize_field("session_type", &self.session_type)?;
        s.serialize_field("kills", &self.kills)?;
        s.serialize_field("kills_per_hour", &self.kills_per_hour)?;
        s.serialize_field("rare_kills", &self.rare_kills)?;
        s.serialize_field("rare_kills_per_hour", &self.rare_kills_per_hour)?;
        s.serialize_field("experience", &self.experience)?;
        s.serialize_field("experience_per_hour", &self.experience_per_hour)?;
        s.serialize_field("profit", &self.profit)?;
        s.serialize_field("profit_per_hour", &self.profit_per_hour)?;
        s.serialize_field("supplies", &self.supplies)?;
        s.serialize_field("supplies_per_hour", &self.supplies_per_hour)?;
        s.serialize_field("raw_gains", &self.raw_gains)?;
        s.serialize_field("raw_gains_per_hour", &self.raw_gains_per_hour)?;
        s.serialize_field("damage_dealt", &self.damage_dealt)?;
        s.serialize_field("damage_dealt_per_second", &self.damage_dealt_per_second)?;
        s.serialize_field("damage_taken", &self.damage_taken)?;
        s.serialize_field("damage_taken_per_second", &self.damage_taken_per_second)?;
        s.serialize_field("time_to_next_level", &self.time_to_next_level)?;
        s.serialize_field("time_to_next_level_seconds", &self.time_to_next_level_seconds)?;
        s.end()
    }
}

/// Valores conhecidos no banco, oferecidos nas listas do painel de filtros.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct FilterOptions {
    pub players: Vec<String>,
    pub enemies: Vec<String>,
    pub drop_items: Vec<String>,
    pub supply_items: Vec<String>,
}

/// Item de uma mensagem do chat, com o nome no banco e o preço que vai valer.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct RewardLine {
    /// Como veio no chat.
    pub chat_name: String,
    /// Nome gravado no drop.
    pub item: String,
    pub count: i64,
    /// Preço personalizado ou o do Analyzer; `None` se desconhecido.
    pub unit_price: Option<f64>,
    /// O nome já existe em drops, supplies ou preços.
    pub known: bool,
}

impl RewardLine {
    pub fn total_price(&self) -> Option<i64> {
        self.unit_price.map(|price| round_half_even(price * self.count as f64) as i64)
    }
}

/// Resultado da leitura das mensagens "Você recebeu:" antes de gravar.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct ChatRewardPreview {
    pub lines: Vec<RewardLine>,
    pub messages: Vec<String>,
    /// Trechos sem quantidade.
    pub invalid: Vec<String>,
    /// Mensagens já adicionadas a esta sessão.
    pub repeated: Vec<String>,
}
