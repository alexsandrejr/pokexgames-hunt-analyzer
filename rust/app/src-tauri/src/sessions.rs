//! O que a seção Sessões mostra (equivale a `app/ui/hunts/`, `app/ui/filters/filter_panel.py` e
//! `app/ui/import_controller.py`): tabelas já formatadas, o formulário de filtros e o resumo
//! das importações.

use chrono::NaiveDate;
use pxg_core::format::{
    NumberFormat, format_bool, format_date, format_datetime, format_datetime_short, format_duration,
    format_duration_long, format_money, format_number, format_percent, format_text,
};
use pxg_core::hunts::advanced_search::parse_advanced_query;
use pxg_core::hunts::categories::Category;
use pxg_core::hunts::filters::{
    DatePreset, HuntFilter, ItemCondition, ItemSource, Metric, MetricCondition, Operator, QuantityCondition, preset_range,
};
use pxg_core::hunts::model::{
    ChatRewardPreview, FilterOptions, HuntDetails, HuntSummary, ImportResult, ImportStatus, ItemRow, RewardLine,
};
use pxg_core::hunts::statistics::{ElementDamage, OverviewStats, RankedEntry, rate_per_second};
use pxg_core::parse::{parse_user_duration, parse_user_number};
use pxg_core::text::py_strip;
use serde::{Deserialize, Serialize};

use crate::charts::{RankedChart, SeriesChart, ValueFormat, chronological, hunt_points, top_entries};

// ------------------------------------------------------------------------------ tabelas

/// Coluna de uma tabela montada no Rust (como `Column` do RecordTable).
#[derive(Debug, Clone, Serialize)]
pub struct ColumnView {
    pub title: &'static str,
    pub numeric: bool,
    pub fit: bool,
    pub centered: bool,
    pub tooltip: Option<&'static str>,
}

/// Valor de ordenação: número, texto (já sem diferenciar maiúsculas) ou vazio.
#[derive(Debug, Clone, Serialize)]
#[serde(untagged)]
pub enum SortKey {
    Number(f64),
    Text(String),
}

#[derive(Debug, Clone, Serialize)]
pub struct RowView {
    pub id: i64,
    pub cells: Vec<String>,
    /// `None` fica depois dos demais na ordem crescente, como no Qt.
    pub sort: Vec<Option<SortKey>>,
    /// "positive" ou "negative" (lucro e prejuízo), por coluna.
    pub colors: Vec<Option<&'static str>>,
}

#[derive(Debug, Clone, Serialize)]
pub struct TableView {
    pub columns: Vec<ColumnView>,
    pub rows: Vec<RowView>,
}

/// Uma célula: texto exibido, chave de ordenação e cor.
pub(crate) struct Cell(pub String, pub Option<SortKey>, pub Option<&'static str>);

pub(crate) fn text_cell(value: Option<&str>) -> Cell {
    let text = format_text(value);
    let key = value.map(|v| SortKey::Text(pxg_core::text::casefold(v)));
    Cell(text, key, None)
}

pub(crate) fn number_cell(value: Option<f64>, text: String) -> Cell {
    Cell(text, value.map(SortKey::Number), None)
}

fn profit_color(value: Option<f64>) -> Option<&'static str> {
    match value {
        Some(v) if v > 0.0 => Some("positive"),
        Some(v) if v < 0.0 => Some("negative"),
        _ => None,
    }
}

pub(crate) fn column(title: &'static str, numeric: bool, fit: bool) -> ColumnView {
    ColumnView { title, numeric, fit, centered: false, tooltip: None }
}

pub(crate) fn row(id: i64, cells: Vec<Cell>) -> RowView {
    let mut row = RowView { id, cells: Vec::new(), sort: Vec::new(), colors: Vec::new() };
    for Cell(text, key, color) in cells {
        row.cells.push(text);
        row.sort.push(key);
        row.colors.push(color);
    }
    row
}

/// Colunas da lista de sessões (`HUNT_COLUMNS`); "Todas" ganha Categoria e perde Supplies/h.
pub fn hunt_table(hunts: &[HuntSummary], all_categories: bool, fmt: NumberFormat) -> TableView {
    let mut columns = vec![column("Data", false, true)];
    if all_categories {
        columns.push(column("Categoria", false, true));
    }
    columns.extend([
        column("Sessão", true, false),
        column("Player", false, false),
        column("Duração", true, false),
        column("Kills", true, false),
        column("Kills/h", true, false),
        column("Profit", true, false),
        column("Profit/h", true, false),
        column("Supplies", true, false),
    ]);
    if !all_categories {
        columns.push(column("Supplies/h", true, false));
    }
    columns.push(column("Raw Gains", true, false));

    let rows = hunts
        .iter()
        .map(|h| {
            let money = |v: Option<f64>| number_cell(v, format_money(v, fmt));
            let number = |v: Option<f64>| number_cell(v, format_number(v, 0, fmt));
            let profit = h.profit.map(|v| v as f64);
            let mut cells = vec![Cell(
                format_datetime_short(h.start_datetime),
                h.start_datetime.map(|d| SortKey::Number(d.and_utc().timestamp() as f64)),
                None,
            )];
            if all_categories {
                let label = Category::from_value(Some(&h.category)).label();
                cells.push(Cell(label.into(), Some(SortKey::Text(label.to_lowercase())), None));
            }
            cells.extend([
                number_cell(h.session_id.map(|v| v as f64), format_text(h.session_id.map(|v| v.to_string()).as_deref())),
                text_cell(h.player.as_deref()),
                number_cell(h.duration_seconds.map(|v| v as f64), format_duration(h.duration_seconds.map(|v| v as f64))),
                number(h.kills.map(|v| v as f64)),
                number(h.kills_per_hour),
                Cell(format_money(profit, fmt), profit.map(SortKey::Number), profit_color(profit)),
                Cell(format_money(h.profit_per_hour, fmt), h.profit_per_hour.map(SortKey::Number), profit_color(h.profit_per_hour)),
                money(h.supplies.map(|v| v as f64)),
            ]);
            if !all_categories {
                cells.push(money(h.supplies_per_hour));
            }
            cells.push(money(h.raw_gains.map(|v| v as f64)));
            row(h.id, cells)
        })
        .collect();
    TableView { columns, rows }
}

// ------------------------------------------------------------------------------ detalhes

#[derive(Debug, Clone, Serialize)]
pub struct StatCardView {
    pub title: &'static str,
    pub value: String,
    pub hint: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct FieldGroupView {
    pub title: &'static str,
    pub fields: Vec<(&'static str, String)>,
}

/// Uma aba de lista dos detalhes: o resumo em partes (rótulo, valor em negrito) e a tabela.
#[derive(Debug, Clone, Serialize)]
pub struct ListTabView {
    pub summary: Vec<(String, String)>,
    pub table: TableView,
    /// Coluna em que a tabela começa ordenada (do maior para o menor).
    pub sort_column: usize,
    pub empty_message: &'static str,
}

#[derive(Debug, Clone, Serialize)]
pub struct HuntDetailsView {
    pub id: i64,
    pub title: String,
    pub subtitle: String,
    pub cards: Vec<StatCardView>,
    pub groups: Vec<FieldGroupView>,
    pub enemies: ListTabView,
    pub drops: ListTabView,
    pub supplies: ListTabView,
    pub json: String,
    /// Mensagens das recompensas do chat gravadas, para a dica de "Remover do chat".
    pub chat_messages: Vec<String>,
    /// Aba Gráficos: só as listas com 2 itens ou mais (uma barra só não é um gráfico).
    pub charts: Vec<RankedChart>,
}

fn int_text(value: Option<i64>, fmt: NumberFormat) -> String {
    format_number(value.map(|v| v as f64), 0, fmt)
}

fn money_i(value: Option<i64>, fmt: NumberFormat) -> String {
    format_money(value.map(|v| v as f64), fmt)
}

fn item_table(items: &[ItemRow], drops: bool, fmt: NumberFormat) -> TableView {
    let mut columns = vec![
        column("Item", false, false),
        column("Count", true, false),
        column("Unit price", true, false),
        column("Total price", true, false),
        ColumnView {
            tooltip: Some("Preço unitário exportado pelo Analyzer (antes dos preços personalizados)"),
            ..column("Analyzer price", true, false)
        },
        column("Player", false, false),
        ColumnView { centered: true, ..column("Ignored", false, false) },
    ];
    if drops {
        columns.push(ColumnView {
            centered: true,
            tooltip: Some("Chat: item de uma mensagem \"Você recebeu:\", fora do JSON do Analyzer"),
            ..column("Origem", false, false)
        });
    }
    let rows = items
        .iter()
        .map(|item| {
            let mut cells = vec![
                text_cell(Some(&item.item)),
                number_cell(Some(item.count as f64), format_number(item.count as f64, 0, fmt)),
                number_cell(item.unit_price, format_money(item.unit_price, fmt)),
                number_cell(item.total_price.map(|v| v as f64), money_i(item.total_price, fmt)),
                number_cell(item.original_unit_price, format_money(item.original_unit_price, fmt)),
                text_cell(item.player.as_deref()),
                bool_cell(item.ignored),
            ];
            if drops {
                let origin = if item.from_chat() { "Chat" } else { "Analyzer" };
                cells.push(Cell(origin.into(), Some(SortKey::Text(origin.to_lowercase())), None));
            }
            row(item.id, cells)
        })
        .collect();
    TableView { columns, rows }
}

fn bool_cell(value: Option<bool>) -> Cell {
    Cell(format_bool(value), value.map(|v| SortKey::Number(if v { 1.0 } else { 0.0 })), None)
}

fn total_price(items: &[ItemRow]) -> f64 {
    items.iter().map(|i| i.total_price.unwrap_or(0) as f64).sum()
}

impl HuntDetailsView {
    pub fn new(hunt: &HuntDetails, fmt: NumberFormat) -> Self {
        let s = &hunt.session;
        let category = Category::from_value(Some(&hunt.category));
        let duration = format_duration(s.duration_seconds.map(|v| v as f64));
        let session_id = format_text(s.session_id.map(|v| v.to_string()).as_deref());
        let cards = vec![
            StatCardView { title: "Duração", value: duration.clone(), hint: String::new() },
            StatCardView {
                title: "Kills",
                value: int_text(s.kills, fmt),
                hint: format!("{} por hora", format_number(s.kills_per_hour, 0, fmt)),
            },
            StatCardView {
                title: "Profit",
                value: money_i(s.profit, fmt),
                hint: format!("{} por hora", format_money(s.profit_per_hour, fmt)),
            },
            StatCardView {
                title: "Raw gains",
                value: money_i(s.raw_gains, fmt),
                hint: format!("Supplies: {}", money_i(s.supplies, fmt)),
            },
        ];
        let chat_drops: Vec<&ItemRow> = hunt.drops.iter().filter(|d| d.from_chat()).collect();
        let mut import_fields = vec![
            ("Arquivo", format_text(hunt.source_file.as_deref())),
            ("Importada em", format_datetime(hunt.created_at)),
            ("ID interno", hunt.id.to_string()),
        ];
        if !chat_drops.is_empty() {
            let value: f64 = chat_drops.iter().map(|d| d.total_price.unwrap_or(0) as f64).sum();
            import_fields.push((
                "Drops do chat",
                format!("{} itens · {}", format_number(chat_drops.len() as f64, 0, fmt), format_money(value, fmt)),
            ));
        }
        let groups = vec![
            FieldGroupView {
                title: "Sessão",
                fields: vec![
                    ("Categoria", category.plural().into()),
                    ("Player", format_text(s.player.as_deref())),
                    ("Session ID", session_id.clone()),
                    ("Data", format_datetime(s.start_datetime)),
                    ("Status", format_text(s.status.as_deref())),
                    ("Session Type", format_text(s.session_type.as_deref())),
                    ("Duração", duration.clone()),
                    ("Paused seconds", int_text(s.paused_seconds, fmt)),
                    ("Tempo p/ próximo nível", format_text(s.time_to_next_level.as_deref())),
                ],
            },
            FieldGroupView {
                title: "Kills e experiência",
                fields: vec![
                    ("Kills", int_text(s.kills, fmt)),
                    ("Kills/h", format_number(s.kills_per_hour, 0, fmt)),
                    ("Rare kills", int_text(s.rare_kills, fmt)),
                    ("Rare kills/h", format_number(s.rare_kills_per_hour, 1, fmt)),
                    ("Experience", int_text(s.experience, fmt)),
                    ("Experience/h", format_number(s.experience_per_hour, 0, fmt)),
                ],
            },
            FieldGroupView {
                title: "Economia",
                fields: vec![
                    ("Profit", money_i(s.profit, fmt)),
                    ("Profit/h", format_money(s.profit_per_hour, fmt)),
                    ("Supplies", money_i(s.supplies, fmt)),
                    ("Supplies/h", format_money(s.supplies_per_hour, fmt)),
                    ("Raw gains", money_i(s.raw_gains, fmt)),
                    ("Raw gains/h", format_money(s.raw_gains_per_hour, fmt)),
                ],
            },
            FieldGroupView {
                title: "Dano",
                fields: vec![
                    ("Damage dealt", int_text(s.damage_dealt, fmt)),
                    ("Damage dealt/s", format_number(s.damage_dealt_per_second, 0, fmt)),
                    ("Damage taken", int_text(s.damage_taken, fmt)),
                    ("Damage taken/s", format_number(s.damage_taken_per_second, 0, fmt)),
                ],
            },
            FieldGroupView { title: "Importação", fields: import_fields },
        ];

        let enemy_total: i64 = hunt.enemies.iter().map(|e| e.count).sum();
        let enemies = ListTabView {
            summary: vec![
                ("Inimigos derrotados".into(), format_number(enemy_total as f64, 0, fmt)),
                ("Tipos".into(), format_number(hunt.enemies.len() as f64, 0, fmt)),
            ],
            table: TableView {
                columns: vec![
                    column("Enemy", false, false),
                    column("Count", true, false),
                    column("Player", false, false),
                    ColumnView { centered: true, ..column("Rare", false, false) },
                    ColumnView { centered: true, ..column("Ignored", false, false) },
                ],
                rows: hunt
                    .enemies
                    .iter()
                    .map(|e| {
                        row(e.id, vec![
                            text_cell(Some(&e.enemy)),
                            number_cell(Some(e.count as f64), format_number(e.count as f64, 0, fmt)),
                            text_cell(e.player.as_deref()),
                            bool_cell(e.rare),
                            bool_cell(e.ignored),
                        ])
                    })
                    .collect(),
            },
            sort_column: 1,
            empty_message: "Nenhum inimigo registrado nesta Hunt.",
        };

        let drop_quantity: i64 = hunt.drops.iter().map(|d| d.count).sum();
        let mut drop_summary = vec![
            ("Valor total dos drops".into(), format_money(total_price(&hunt.drops), fmt)),
            ("Quantidade de itens".into(), format_number(drop_quantity as f64, 0, fmt)),
            ("Tipos".into(), format_number(hunt.drops.len() as f64, 0, fmt)),
        ];
        if !chat_drops.is_empty() {
            let value: f64 = chat_drops.iter().map(|d| d.total_price.unwrap_or(0) as f64).sum();
            drop_summary.push((
                "Do chat".into(),
                format!("{} ({})", format_number(chat_drops.len() as f64, 0, fmt), format_money(value, fmt)),
            ));
        }
        let supply_quantity: i64 = hunt.supplies.iter().map(|d| d.count).sum();

        Self {
            id: hunt.id,
            title: format!("{} {session_id}", category.label()),
            subtitle: format!("{} · {} · {duration}", format_text(s.player.as_deref()), format_datetime(s.start_datetime)),
            cards,
            groups,
            enemies,
            drops: ListTabView {
                summary: drop_summary,
                table: item_table(&hunt.drops, true, fmt),
                sort_column: 3,
                empty_message: "Nenhum drop registrado nesta Hunt.",
            },
            supplies: ListTabView {
                summary: vec![
                    ("Custo total dos supplies".into(), format_money(total_price(&hunt.supplies), fmt)),
                    ("Quantidade".into(), format_number(supply_quantity as f64, 0, fmt)),
                ],
                table: item_table(&hunt.supplies, false, fmt),
                sort_column: 3,
                empty_message: "Nenhum supply registrado nesta Hunt.",
            },
            json: pretty_json(&hunt.raw_json),
            charts: detail_charts(hunt, fmt),
            chat_messages: hunt.chat_rewards.iter().flat_map(|r| r.messages().into_iter().map(str::to_owned)).collect(),
        }
    }
}

pub const CHART_TOP_N: usize = 15;

fn detail_charts(hunt: &HuntDetails, fmt: NumberFormat) -> Vec<RankedChart> {
    let mut charts = Vec::new();
    if hunt.enemies.len() >= 2 {
        let entries = top_entries(&hunt.enemies, |e| e.enemy.clone(), |e| Some(e.count as f64), CHART_TOP_N);
        charts.push(RankedChart::new(&format!("Inimigos derrotados (top {CHART_TOP_N})"), &entries, ValueFormat::Number, fmt));
    }
    let price = |i: &ItemRow| i.total_price.map(|v| v as f64);
    if hunt.drops.len() >= 2 {
        let entries = top_entries(&hunt.drops, |i| i.item.clone(), price, CHART_TOP_N);
        charts.push(RankedChart::new(&format!("Drops por valor total (top {CHART_TOP_N})"), &entries, ValueFormat::Money, fmt));
    }
    if hunt.supplies.len() >= 2 {
        let entries = top_entries(&hunt.supplies, |i| i.item.clone(), price, CHART_TOP_N);
        charts.push(RankedChart::new("Supplies por custo total", &entries, ValueFormat::Money, fmt));
    }
    charts
}

/// Reindenta o JSON mantendo a ordem das chaves; texto inválido volta como está.
pub fn pretty_json(text: &str) -> String {
    match serde_json::from_str::<serde_json::Value>(text) {
        Ok(value) => pxg_core::pyjson::dumps_pretty(&value, 4),
        Err(_) => text.to_owned(),
    }
}

// ------------------------------------------------------------------------------ recompensas do chat

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RewardLineView {
    pub chat_name: String,
    pub item: String,
    pub count: i64,
    pub unit_price: Option<f64>,
    pub known: bool,
    pub count_text: String,
    pub price_text: String,
    pub total_text: String,
}

impl RewardLineView {
    pub fn new(line: &RewardLine, fmt: NumberFormat) -> Self {
        Self {
            chat_name: line.chat_name.clone(),
            item: line.item.clone(),
            count: line.count,
            unit_price: line.unit_price,
            known: line.known,
            count_text: format_number(line.count as f64, 0, fmt),
            price_text: format_money(line.unit_price, fmt),
            total_text: format_money(line.total_price().map(|v| v as f64), fmt),
        }
    }

    pub fn to_line(&self) -> RewardLine {
        RewardLine {
            chat_name: self.chat_name.clone(),
            item: self.item.clone(),
            count: self.count,
            unit_price: self.unit_price,
            known: self.known,
        }
    }
}

/// Mensagem embaixo da prévia, com a cor: "muted", "negative", "positive" ou "warning".
pub fn chat_status(text: &str, preview: &ChatRewardPreview, fmt: NumberFormat) -> (String, &'static str) {
    if py_strip(text).is_empty() {
        return ("Nenhuma mensagem colada.".into(), "muted");
    }
    if preview.messages.is_empty() {
        return ("Nenhuma mensagem \"Você recebeu:\" encontrada no texto.".into(), "negative");
    }
    if preview.lines.is_empty() {
        return ("As mensagens não têm itens reconhecíveis.".into(), "negative");
    }
    let value: f64 = preview.lines.iter().map(|l| l.total_price().unwrap_or(0) as f64).sum();
    let mut parts = vec![format!(
        "✓ {} mensagem(ns), {} item(ns) · valor {}",
        preview.messages.len(),
        preview.lines.len(),
        format_money(value, fmt)
    )];
    let unpriced = preview.lines.iter().filter(|l| l.unit_price.is_none()).count();
    if unpriced > 0 {
        parts.push(format!("{unpriced} item(ns) sem preço (entram com valor 0; defina na página Preços)"));
    }
    let unknown = preview.lines.iter().filter(|l| !l.known).count();
    if unknown > 0 {
        parts.push(format!("{unknown} nome(s) novo(s), em destaque: confira antes de adicionar"));
    }
    let mut color = "positive";
    if !preview.invalid.is_empty() {
        parts.push(format!("ignorado(s), sem quantidade: {}", preview.invalid.join(", ")));
        color = "warning";
    }
    if !preview.repeated.is_empty() {
        parts.push(format!(
            "⚠ {} mensagem(ns) já adicionada(s) a esta sessão: adicionar de novo soma os itens outra vez",
            preview.repeated.len()
        ));
        color = "warning";
    }
    (parts.join("\n"), color)
}

// ------------------------------------------------------------------------------ comparação

#[derive(Debug, Clone, Serialize)]
pub struct ComparisonView {
    pub title: String,
    pub subtitle: String,
    /// "Hunt 123" e a data, uma coluna por sessão.
    pub headers: Vec<(String, String)>,
    pub rows: Vec<Vec<String>>,
}

impl ComparisonView {
    pub fn new(hunts: &[HuntSummary], fmt: NumberFormat) -> Self {
        let table = pxg_core::export::documents::comparison_table(hunts);
        Self {
            title: format!("Comparação de {} Hunts", hunts.len()),
            subtitle: format!("{} Hunts em ordem cronológica", hunts.len()),
            headers: hunts
                .iter()
                .map(|h| {
                    (
                        format!("Hunt {}", format_text(h.session_id.map(|v| v.to_string()).as_deref())),
                        format_datetime_short(h.start_datetime),
                    )
                })
                .collect(),
            rows: table.display_rows(fmt),
        }
    }
}

// ------------------------------------------------------------------------------ resumo de boss

pub const RANKING_LIMIT: i64 = 25;
pub const MIN_SESSIONS_FOR_CHARTS: i64 = 2;

/// Resumo de um tipo de boss (`BossSummaryView`): cards, tabelas e gráficos das sessões filtradas.
#[derive(Debug, Clone, Serialize)]
pub struct BossSummaryView {
    pub cards: Vec<StatCardView>,
    pub has_sessions: bool,
    /// Aviso quando não há sessões ou há menos de 2 (sem gráficos).
    pub hint: Option<String>,
    pub enemies: TableView,
    pub drops: TableView,
    pub elements: TableView,
    pub charts: Vec<SeriesChart>,
}

fn ranked_rows(entries: &[RankedEntry], with_value: bool, fmt: NumberFormat) -> Vec<RowView> {
    entries
        .iter()
        .enumerate()
        .map(|(i, e)| {
            let qty = Some(e.quantity as f64);
            let sessions = Some(e.hunt_count as f64);
            let mut cells = vec![text_cell(Some(&e.name)), number_cell(qty, format_number(qty, 0, fmt))];
            if with_value {
                let value = e.value.map(|v| v as f64);
                cells.push(number_cell(value, format_money(value, fmt)));
                cells.push(number_cell(sessions, format_number(sessions, 0, fmt)));
            } else {
                cells.push(number_cell(sessions, format_number(sessions, 0, fmt)));
                let avg = e.average_per_hunt();
                cells.push(number_cell(avg, format_number(avg, 0, fmt)));
            }
            row(i as i64, cells)
        })
        .collect()
}

fn element_rows(entries: &[ElementDamage], fmt: NumberFormat) -> Vec<RowView> {
    entries
        .iter()
        .enumerate()
        .map(|(i, e)| {
            row(i as i64, vec![
                text_cell(Some(&e.element)),
                number_cell(Some(e.dealt as f64), format_number(e.dealt as f64, 0, fmt)),
                number_cell(e.dealt_share, format_percent(e.dealt_share, fmt)),
                number_cell(Some(e.taken as f64), format_number(e.taken as f64, 0, fmt)),
                number_cell(e.taken_share, format_percent(e.taken_share, fmt)),
            ])
        })
        .collect()
}

pub fn boss_cards(stats: &OverviewStats, fmt: NumberFormat) -> Vec<StatCardView> {
    let money = |v: Option<f64>| format_money(v, fmt);
    let number = |v: Option<f64>| format_number(v, 0, fmt);
    let taken = rate_per_second(Some(stats.total_damage_taken), Some(stats.total_duration_seconds));
    vec![
        StatCardView {
            title: "Sessões",
            value: number(Some(stats.hunt_count as f64)),
            hint: format!("Última: {}", format_date(stats.last_start)),
        },
        StatCardView {
            title: "Kills",
            value: number(Some(stats.total_kills as f64)),
            hint: format!("Média por sessão: {}", number(stats.average_kills())),
        },
        StatCardView {
            title: "Tempo total",
            value: format_duration_long(stats.total_duration_seconds as f64, fmt),
            hint: format!("Por kill: {}", format_duration(stats.duration_per_kill())),
        },
        StatCardView {
            title: "Profit",
            value: money(Some(stats.total_profit as f64)),
            hint: format!("Por kill: {}", money(stats.profit_per_kill())),
        },
        StatCardView {
            title: "Profit/h",
            value: money(stats.profit_per_total_hour()),
            hint: format!("Média das sessões: {}", money(stats.average_profit_per_hour)),
        },
        StatCardView {
            title: "Supplies",
            value: money(Some(stats.total_supplies as f64)),
            hint: format!("Por kill: {}", money(stats.supplies_per_kill())),
        },
        StatCardView {
            title: "Experience",
            value: number(Some(stats.total_experience as f64)),
            hint: format!("Por kill: {}", number(stats.experience_per_kill())),
        },
        StatCardView {
            title: "Damage dealt/s",
            value: number(stats.average_damage_dealt_per_second),
            hint: format!("Damage taken/s: {}", number(taken)),
        },
    ]
}

pub struct BossSummaryInput<'a> {
    pub plural: &'a str,
    pub filter_active: bool,
    pub stats: &'a OverviewStats,
    pub enemies: &'a [RankedEntry],
    pub drops: &'a [RankedEntry],
    pub elements: &'a [ElementDamage],
    pub hunts: &'a [HuntSummary],
}

type SeriesSpec = (&'static str, ValueFormat, fn(&HuntSummary) -> Option<f64>);

const BOSS_CHARTS: [SeriesSpec; 4] = [
    ("Profit por sessão", ValueFormat::Money, |h| h.profit.map(|v| v as f64)),
    ("Profit/h por sessão", ValueFormat::Money, |h| h.profit_per_hour),
    ("Duração das sessões", ValueFormat::Duration, |h| h.duration_seconds.map(|v| v as f64)),
    ("Damage dealt por segundo", ValueFormat::Number, |h| h.damage_dealt_per_second),
];

impl BossSummaryView {
    pub fn new(input: BossSummaryInput<'_>, fmt: NumberFormat) -> Self {
        let has_sessions = input.stats.hunt_count > 0;
        let enough = input.stats.hunt_count >= MIN_SESSIONS_FOR_CHARTS;
        let hint = if !has_sessions {
            Some(if input.filter_active {
                "Nenhuma sessão corresponde aos filtros.".to_owned()
            } else {
                format!(
                    "Nenhuma sessão de {} ainda. Clique em Importar com este tipo aberto, ou mova uma sessão com “Mover”.",
                    input.plural
                )
            })
        } else if !enough {
            Some("Os gráficos aparecem a partir de 2 sessões.".to_owned())
        } else {
            None
        };
        let charts = if enough {
            let sessions = chronological(input.hunts);
            BOSS_CHARTS
                .iter()
                .map(|(title, format, value)| {
                    SeriesChart::new(title, hunt_points(&sessions, value, *format, Some("Sessão"), fmt), *format, fmt)
                })
                .collect()
        } else {
            Vec::new()
        };
        Self {
            cards: boss_cards(input.stats, fmt),
            has_sessions,
            hint,
            enemies: TableView {
                columns: vec![
                    column("Boss / inimigo", false, false),
                    column("Derrotados", true, false),
                    column("Sessões", true, false),
                    column("Média por sessão", true, false),
                ],
                rows: ranked_rows(input.enemies, false, fmt),
            },
            drops: TableView {
                columns: vec![
                    column("Item", false, false),
                    column("Quantidade", true, false),
                    column("Valor total", true, false),
                    column("Sessões", true, false),
                ],
                rows: ranked_rows(input.drops, true, fmt),
            },
            elements: TableView {
                columns: vec![
                    column("Elemento", false, false),
                    column("Causado", true, false),
                    column("% causado", true, false),
                    column("Recebido", true, false),
                    column("% recebido", true, false),
                ],
                rows: element_rows(input.elements, fmt),
            },
            charts,
        }
    }
}

// ------------------------------------------------------------------------------ filtros

#[derive(Debug, Clone, Default, Deserialize)]
pub struct MetricInput {
    pub operator: Option<Operator>,
    pub value: String,
}

/// Campos do painel de filtros como foram preenchidos.
#[derive(Debug, Clone, Deserialize)]
pub struct FilterForm {
    pub preset: DatePreset,
    /// `aaaa-mm-dd`, do seletor de data.
    pub date_from: String,
    pub date_to: String,
    pub player: String,
    pub enemy: String,
    pub enemy_operator: Operator,
    pub enemy_quantity: String,
    pub item_source: ItemSource,
    pub item: String,
    pub item_operator: Operator,
    pub item_quantity: String,
    /// Na ordem do painel: Profit, Profit/h, Kills, Kills/h e Duração.
    pub metrics: Vec<(Metric, MetricInput)>,
    pub advanced: String,
}

/// Métricas oferecidas no painel, na ordem exibida, com o exemplo do campo.
pub const PANEL_METRICS: [(Metric, &str); 5] = [
    (Metric::Profit, "ex.: 1kk"),
    (Metric::ProfitPerHour, "ex.: 800k"),
    (Metric::Kills, "ex.: 300"),
    (Metric::KillsPerHour, "ex.: 250"),
    (Metric::Duration, "ex.: 1:30 ou 90"),
];

/// Resultado da montagem: o filtro ou os erros, e os campos a marcar como inválidos.
#[derive(Debug, Clone, Default, Serialize)]
pub struct FilterBuild {
    #[serde(skip)]
    pub filter: Option<HuntFilter>,
    pub errors: Vec<String>,
    /// "enemy_quantity", "item_quantity", "advanced" ou a métrica.
    pub invalid: Vec<String>,
}

fn parse_date(text: &str) -> Option<NaiveDate> {
    NaiveDate::parse_from_str(py_strip(text), "%Y-%m-%d").ok()
}

fn quantity_condition(
    name: &str,
    operator: Operator,
    text: &str,
    label: &str,
    field: &str,
    fmt: NumberFormat,
    build: &mut FilterBuild,
) -> Option<QuantityCondition> {
    let name = py_strip(name);
    let text = py_strip(text);
    let quantity = if text.is_empty() { None } else { parse_user_number(text, fmt) };
    let invalid = !text.is_empty() && (quantity.is_none() || name.is_empty());
    if invalid {
        build.invalid.push(field.into());
        build.errors.push(if name.is_empty() {
            format!("Escolha um {label} para usar a quantidade.")
        } else {
            format!("Quantidade inválida para {label}.")
        });
        return None;
    }
    if name.is_empty() {
        return None;
    }
    Some(match quantity {
        Some(q) => QuantityCondition::with(name, operator, q),
        None => QuantityCondition::present(name),
    })
}

impl FilterForm {
    /// Monta o filtro como `FilterPanel.build_filter`; `today` decide os períodos prontos.
    pub fn build(&self, options: &FilterOptions, today: NaiveDate, fmt: NumberFormat) -> FilterBuild {
        let mut build = FilterBuild::default();
        let (date_from, date_to) = if self.preset == DatePreset::Custom {
            (parse_date(&self.date_from), parse_date(&self.date_to))
        } else {
            preset_range(self.preset, today)
        };
        if let (Some(from), Some(to)) = (date_from, date_to)
            && from > to
        {
            build.errors.push("A data inicial é posterior à final.".into());
        }
        let enemy =
            quantity_condition(&self.enemy, self.enemy_operator, &self.enemy_quantity, "inimigo", "enemy_quantity", fmt, &mut build);
        let item = quantity_condition(&self.item, self.item_operator, &self.item_quantity, "item", "item_quantity", fmt, &mut build);
        let mut metrics = Vec::new();
        for (metric, input) in &self.metrics {
            let text = py_strip(&input.value);
            if text.is_empty() {
                continue;
            }
            let value = if metric.is_duration() { parse_user_duration(text).map(|v| v as f64) } else { parse_user_number(text, fmt) };
            match value {
                Some(value) => {
                    metrics.push(MetricCondition { metric: *metric, operator: input.operator.unwrap_or(Operator::Ge), value })
                }
                None => {
                    build.invalid.push(metric_key(*metric).into());
                    build.errors.push(format!("Valor inválido em {}.", metric.label()));
                }
            }
        }
        let advanced = parse_advanced_query(&self.advanced, options, fmt);
        if !advanced.ok() {
            build.invalid.push("advanced".into());
        }
        build.errors.extend(advanced.errors.iter().cloned());
        if build.errors.is_empty() {
            let player = py_strip(&self.player);
            build.filter = Some(advanced.merged_into(&HuntFilter {
                date_from,
                date_to,
                player: (!player.is_empty()).then(|| player.to_owned()),
                enemies: enemy.into_iter().collect(),
                items: item.into_iter().map(|condition| ItemCondition { condition, source: self.item_source }).collect(),
                metrics,
                categories: Vec::new(),
            }));
        }
        build
    }
}

pub fn metric_key(metric: Metric) -> &'static str {
    match metric {
        Metric::Profit => "profit",
        Metric::ProfitPerHour => "profit_per_hour",
        Metric::Kills => "kills",
        Metric::KillsPerHour => "kills_per_hour",
        Metric::Duration => "duration",
        Metric::Supplies => "supplies",
        Metric::SuppliesPerHour => "supplies_per_hour",
        Metric::RawGains => "raw_gains",
        Metric::RawGainsPerHour => "raw_gains_per_hour",
    }
}

// ------------------------------------------------------------------------------ importação

/// Resultado de uma importação como a tela precisa (e devolve para o resumo).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImportOutcome {
    pub status: String,
    pub source_name: String,
    pub message: String,
    pub hunt_id: Option<i64>,
    pub warnings: Vec<String>,
    pub detail: Option<String>,
    pub saved_path: Option<String>,
    pub category: Option<String>,
}

impl From<&ImportResult> for ImportOutcome {
    fn from(result: &ImportResult) -> Self {
        Self {
            status: match result.status {
                ImportStatus::Imported => "imported",
                ImportStatus::Duplicate => "duplicate",
                ImportStatus::Error => "error",
            }
            .into(),
            source_name: result.source_name(),
            message: result.message.clone(),
            hunt_id: result.hunt_id,
            warnings: result.warnings.clone(),
            detail: result.detail.clone(),
            saved_path: result.saved_path.as_ref().map(|p| p.display().to_string()),
            category: result.category.map(|c| c.as_str().to_owned()),
        }
    }
}

pub const MAX_REPORT_LINES: usize = 15;

/// Uma linha para cada erro, aviso e duplicata, limitadas a poucas linhas (`report_lines`).
pub fn report_lines(results: &[ImportOutcome]) -> Vec<String> {
    let mut lines: Vec<String> =
        results.iter().filter(|r| r.status == "error").map(|r| format!("• {}: {}", r.source_name, r.message)).collect();
    lines.extend(
        results
            .iter()
            .filter(|r| r.status == "imported")
            .flat_map(|r| r.warnings.iter().map(move |w| format!("• {}: {w}", r.source_name))),
    );
    lines.extend(
        results.iter().filter(|r| r.status == "duplicate").map(|r| format!("• {}: já importada (ignorada)", r.source_name)),
    );
    if lines.len() > MAX_REPORT_LINES {
        let hidden = lines.len() - MAX_REPORT_LINES;
        lines.truncate(MAX_REPORT_LINES);
        lines.push(format!("… e mais {hidden}."));
    }
    lines
}

/// Resumo da barra de status (`summarize_results`).
pub fn summarize_results(results: &[ImportOutcome], cancelled: bool) -> String {
    let count = |status: &str| results.iter().filter(|r| r.status == status).count();
    if let [result] = results
        && !cancelled
    {
        if result.status == "duplicate" {
            return format!("Importação cancelada: {} já estava importada.", result.source_name);
        }
        if let Some(saved) = &result.saved_path {
            return format!("{} JSON salvo em {saved}", result.message);
        }
        return format!("{} ({})", result.message, result.source_name);
    }
    let mut parts = vec![format!("{} importada(s)", count("imported"))];
    if count("duplicate") > 0 {
        parts.push(format!("{} duplicada(s) ignorada(s)", count("duplicate")));
    }
    if count("error") > 0 {
        parts.push(format!("{} com erro", count("error")));
    }
    let prefix = if cancelled { "Importação cancelada" } else { "Importação concluída" };
    format!("{prefix}: {}.", parts.join(", "))
}

/// Mensagem de validação do texto colado e se ele pode ser importado.
pub fn paste_status(text: &str, fmt: NumberFormat) -> (String, &'static str, bool) {
    let text = py_strip(text);
    if text.is_empty() {
        return ("Nenhum conteúdo colado.".into(), "muted", false);
    }
    match pxg_core::hunts::analyzer::parse_analyzer_text(text, None) {
        Err(error) => (error.message, "negative", false),
        Ok(parsed) => {
            let s = &parsed.session;
            let kind = if pxg_core::hunts::tsv::looks_like_tsv(text) { "TSV" } else { "JSON" };
            (
                format!(
                    "✓ {kind} válido — Hunt {} · {} · {} · {} · Profit {}",
                    format_text(s.session_id.map(|v| v.to_string()).as_deref()),
                    format_text(s.player.as_deref()),
                    format_datetime(s.start_datetime),
                    format_duration(s.duration_seconds.map(|v| v as f64)),
                    money_i(s.profit, fmt)
                ),
                "positive",
                true,
            )
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const FMT: NumberFormat = NumberFormat::PT_BR;

    fn outcome(status: &str, name: &str) -> ImportOutcome {
        ImportOutcome {
            status: status.into(),
            source_name: name.into(),
            message: "Hunt importada com sucesso.".into(),
            hunt_id: None,
            warnings: vec![],
            detail: None,
            saved_path: None,
            category: None,
        }
    }

    #[test]
    fn summary_matches_python_texts() {
        assert_eq!(summarize_results(&[outcome("imported", "a.json")], false), "Hunt importada com sucesso. (a.json)");
        assert_eq!(
            summarize_results(&[outcome("duplicate", "a.json")], false),
            "Importação cancelada: a.json já estava importada."
        );
        let many = [outcome("imported", "a"), outcome("duplicate", "b"), outcome("error", "c")];
        assert_eq!(
            summarize_results(&many, false),
            "Importação concluída: 1 importada(s), 1 duplicada(s) ignorada(s), 1 com erro."
        );
        assert_eq!(summarize_results(&many[..1], true), "Importação cancelada: 1 importada(s).");
        assert_eq!(report_lines(&many), vec!["• c: Hunt importada com sucesso.", "• b: já importada (ignorada)"]);
    }

    #[test]
    fn report_is_limited() {
        let many: Vec<ImportOutcome> = (0..20).map(|i| outcome("duplicate", &format!("{i}"))).collect();
        let lines = report_lines(&many);
        assert_eq!(lines.len(), MAX_REPORT_LINES + 1);
        assert_eq!(lines.last().unwrap(), "… e mais 5.");
    }

    fn form() -> FilterForm {
        FilterForm {
            preset: DatePreset::All,
            date_from: String::new(),
            date_to: String::new(),
            player: String::new(),
            enemy: String::new(),
            enemy_operator: Operator::Ge,
            enemy_quantity: String::new(),
            item_source: ItemSource::Drops,
            item: String::new(),
            item_operator: Operator::Ge,
            item_quantity: String::new(),
            metrics: PANEL_METRICS.iter().map(|(m, _)| (*m, MetricInput::default())).collect(),
            advanced: String::new(),
        }
    }

    #[test]
    fn empty_form_builds_empty_filter() {
        let build = form().build(&FilterOptions::default(), NaiveDate::from_ymd_opt(2026, 11, 7).unwrap(), FMT);
        assert!(build.errors.is_empty());
        assert!(build.filter.unwrap().is_empty());
    }

    #[test]
    fn form_reports_errors_in_python_order() {
        let mut f = form();
        f.preset = DatePreset::Custom;
        f.date_from = "2026-11-08".into();
        f.date_to = "2026-11-01".into();
        f.enemy_quantity = "5".into();
        f.item = "Nightmare Ore".into();
        f.item_quantity = "abc".into();
        f.metrics[0].1.value = "x".into();
        let build = f.build(&FilterOptions::default(), NaiveDate::from_ymd_opt(2026, 11, 7).unwrap(), FMT);
        assert!(build.filter.is_none());
        assert_eq!(
            build.errors,
            vec![
                "A data inicial é posterior à final.",
                "Escolha um inimigo para usar a quantidade.",
                "Quantidade inválida para item.",
                "Valor inválido em Profit.",
            ]
        );
        assert_eq!(build.invalid, vec!["enemy_quantity", "item_quantity", "profit"]);
    }

    #[test]
    fn form_builds_conditions() {
        let mut f = form();
        f.preset = DatePreset::Last7Days;
        f.player = " Ash ".into();
        f.item = "Nightmare Ore".into();
        f.item_quantity = "50".into();
        f.metrics[1].1 = MetricInput { operator: Some(Operator::Gt), value: "800k".into() };
        f.metrics[4].1.value = "1:30".into();
        let filter = f.build(&FilterOptions::default(), NaiveDate::from_ymd_opt(2026, 11, 7).unwrap(), FMT).filter.unwrap();
        assert_eq!(filter.date_from, NaiveDate::from_ymd_opt(2026, 11, 1));
        assert_eq!(filter.player.as_deref(), Some("Ash"));
        assert_eq!(filter.items[0].condition.quantity, Some(50.0));
        assert_eq!(filter.metrics[0].value, 800_000.0);
        assert_eq!(filter.metrics[1].value, 5400.0);
    }

    #[test]
    fn paste_status_validates() {
        assert_eq!(paste_status("  ", FMT).0, "Nenhum conteúdo colado.");
        let (message, color, ok) = paste_status("{", FMT);
        assert_eq!((message.as_str(), color, ok), ("JSON inválido.", "negative", false));
    }
}
