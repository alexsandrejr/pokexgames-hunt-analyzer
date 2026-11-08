//! O que a seção Análise mostra (equivale a `app/ui/reports/`, `app/ui/items/` e
//! `app/ui/prices/`): o escopo das categorias, o relatório geral, o relatório de um item ou
//! inimigo e a lista de preços, já formatados.

use pxg_core::format::{
    NumberFormat, PLACEHOLDER, ValueKind, format_date, format_datetime_short, format_duration, format_duration_long,
    format_money, format_number, format_percent, format_text,
};
use pxg_core::hunts::categories::Category;
use pxg_core::hunts::statistics::{
    EntityHuntRow, EntityKind, EntityReport, MetricStats, OverviewStats, RankedEntry, rate_per_hour,
};
use pxg_core::parse::parse_user_number;
use pxg_core::prices::{PricedItem, item_key};
use serde::Serialize;

use crate::charts::{ChartPoint, SeriesChart, ValueFormat};
use crate::sessions::{Cell, ColumnView, SortKey, StatCardView, TableView, column, number_cell, row, text_cell};

pub const RANKING_LIMIT: i64 = 25;

// ------------------------------------------------------------------------------ escopo

/// Escopos do seletor de categorias (`SCOPES`): (rótulo, categorias); nenhuma = todas.
pub fn scopes() -> Vec<(String, Vec<Category>)> {
    let mut scopes = vec![
        ("Hunts".to_owned(), vec![Category::Hunt]),
        ("Todos os bosses".to_owned(), Category::bosses().collect()),
    ];
    scopes.extend(Category::bosses().map(|c| (format!("Bosses · {}", c.plural()), vec![c])));
    scopes.push(("Hunts e bosses".to_owned(), Vec::new()));
    scopes
}

/// O escopo pelo índice do seletor; fora da lista, "Hunts" (o padrão).
pub fn scope(index: usize) -> (String, Vec<Category>) {
    let mut all = scopes();
    if index < all.len() { all.swap_remove(index) } else { all.swap_remove(0) }
}

pub fn parse_kind(value: &str) -> Result<EntityKind, String> {
    match value {
        "drops" => Ok(EntityKind::Drops),
        "supplies" => Ok(EntityKind::Supplies),
        "enemies" => Ok(EntityKind::Enemies),
        other => Err(format!("Tipo desconhecido: {other}")),
    }
}

// ------------------------------------------------------------------------------ relatórios

fn format_metric(kind: ValueKind, value: Option<f64>, fmt: NumberFormat) -> String {
    match kind {
        ValueKind::Money => format_money(value, fmt),
        ValueKind::Number => format_number(value, 0, fmt),
        ValueKind::Duration => format_duration(value),
        ValueKind::Percent => format_percent(value, fmt),
        _ => value.map_or_else(|| PLACEHOLDER.to_owned(), |v| v.to_string()),
    }
}

fn metric_total(metric: &MetricStats, fmt: NumberFormat) -> String {
    let total = metric.total.map(|v| v as f64);
    if metric.kind == ValueKind::Duration {
        return format_duration_long(total, fmt);
    }
    format_metric(metric.kind, total, fmt)
}

fn metric_rate(metric: &MetricStats, value: Option<f64>, fmt: NumberFormat) -> String {
    match (value, metric.rate_unit) {
        (Some(v), Some(unit)) => format!("{} {}", format_metric(metric.kind, Some(v), fmt), unit.suffix()),
        _ => PLACEHOLDER.to_owned(),
    }
}

/// Página Relatórios: subtítulo, cards, métricas e os três rankings.
#[derive(Debug, Clone, Serialize)]
pub struct ReportView {
    pub subtitle: String,
    pub cards: Vec<StatCardView>,
    pub metrics: TableView,
    pub drops: TableView,
    pub supplies: TableView,
    pub enemies: TableView,
}

pub struct ReportInput<'a> {
    pub filter_active: bool,
    pub overview: &'a OverviewStats,
    pub metrics: &'a [MetricStats],
    pub drops: &'a [RankedEntry],
    pub supplies: &'a [RankedEntry],
    pub enemies: &'a [RankedEntry],
}

fn item_rank_table(entries: &[RankedEntry], fmt: NumberFormat) -> TableView {
    let rows = entries
        .iter()
        .enumerate()
        .map(|(i, e)| {
            let qty = Some(e.quantity as f64);
            let value = e.value.map(|v| v as f64);
            let hunts = Some(e.hunt_count as f64);
            let avg = e.average_per_hunt();
            row(i as i64, vec![
                text_cell(Some(&e.name)),
                number_cell(qty, format_number(qty, 0, fmt)),
                number_cell(value, format_money(value, fmt)),
                number_cell(hunts, format_number(hunts, 0, fmt)),
                number_cell(avg, format_number(avg, 0, fmt)),
            ])
        })
        .collect();
    TableView {
        columns: vec![
            column("Item", false, false),
            column("Quantidade", true, false),
            column("Valor total", true, false),
            column("Hunts", true, false),
            column("Média por Hunt", true, false),
        ],
        rows,
    }
}

fn enemy_rank_table(entries: &[RankedEntry], fmt: NumberFormat) -> TableView {
    let rows = entries
        .iter()
        .enumerate()
        .map(|(i, e)| {
            let qty = Some(e.quantity as f64);
            let hunts = Some(e.hunt_count as f64);
            let avg = e.average_per_hunt();
            row(i as i64, vec![
                text_cell(Some(&e.name)),
                number_cell(qty, format_number(qty, 0, fmt)),
                number_cell(hunts, format_number(hunts, 0, fmt)),
                number_cell(avg, format_number(avg, 0, fmt)),
            ])
        })
        .collect();
    TableView {
        columns: vec![
            column("Inimigo", false, false),
            column("Derrotados", true, false),
            column("Hunts", true, false),
            column("Média por Hunt", true, false),
        ],
        rows,
    }
}

fn metrics_table(metrics: &[MetricStats], fmt: NumberFormat) -> TableView {
    let rows = metrics
        .iter()
        .enumerate()
        .map(|(i, m)| {
            let value = |v: Option<f64>| Cell(format_metric(m.kind, v, fmt), None, None);
            row(i as i64, vec![
                Cell(m.label.to_owned(), None, None),
                Cell(metric_total(m, fmt), None, None),
                value(m.average),
                value(m.minimum.map(|v| v as f64)),
                value(m.maximum.map(|v| v as f64)),
                Cell(metric_rate(m, m.average_rate, fmt), None, None),
                Cell(metric_rate(m, m.rate_over_total_time, fmt), None, None),
            ])
        })
        .collect();
    // Todas pelo conteúdo: na janela mínima, a tabela rola em vez de cortar os números.
    TableView {
        columns: vec![
            column("Métrica", false, true),
            column("Total", true, true),
            column("Média por Hunt", true, true),
            column("Mínimo", true, true),
            column("Máximo", true, true),
            ColumnView {
                tooltip: Some("Média simples das taxas (/h ou /s) de cada Hunt"),
                ..column("Média das taxas", true, true)
            },
            ColumnView {
                tooltip: Some("Total dividido pelo tempo total (ponderado pela duração)"),
                ..column("Total ÷ tempo total", true, true)
            },
        ],
        rows,
    }
}

impl ReportView {
    pub fn new(input: ReportInput<'_>, fmt: NumberFormat) -> Self {
        let o = input.overview;
        let scope = if input.filter_active { "das Hunts filtradas" } else { "de todas as Hunts" };
        let period = if o.first_start.is_some() {
            format!(" · {} a {}", format_date(o.first_start), format_date(o.last_start))
        } else {
            String::new()
        };
        let cards = vec![
            StatCardView { title: "Hunts analisadas", value: format_number(o.hunt_count as f64, 0, fmt), hint: String::new() },
            StatCardView {
                title: "Tempo total",
                value: format_duration_long(o.total_duration_seconds as f64, fmt),
                hint: format!("Média por Hunt: {}", format_duration(o.average_duration_seconds())),
            },
            StatCardView {
                title: "Profit total",
                value: format_money(o.total_profit as f64, fmt),
                hint: format!("Média por Hunt: {}", format_money(o.average_profit, fmt)),
            },
            StatCardView {
                title: "Profit/h",
                value: format_money(o.profit_per_total_hour(), fmt),
                hint: format!("Média das Hunts: {}", format_money(o.average_profit_per_hour, fmt)),
            },
        ];
        Self {
            subtitle: format!("Estatísticas agregadas {scope}{period}"),
            cards,
            metrics: metrics_table(input.metrics, fmt),
            drops: item_rank_table(input.drops, fmt),
            supplies: item_rank_table(input.supplies, fmt),
            enemies: enemy_rank_table(input.enemies, fmt),
        }
    }
}

// ------------------------------------------------------------------------------ item ou inimigo

fn row_label(row: Option<&EntityHuntRow>) -> String {
    row.map_or_else(String::new, |r| {
        format!(
            "Hunt {} · {}",
            format_text(r.session_id.map(|v| v.to_string()).as_deref()),
            format_datetime_short(r.start_datetime)
        )
    })
}

/// Relatório de um item ou inimigo: um aviso (sem Hunts, nada encontrado) ou os resultados.
#[derive(Debug, Clone, Serialize)]
pub struct EntityReportView {
    /// Aviso no lugar dos resultados: (título, mensagem).
    pub empty: Option<(String, String)>,
    pub cards: Vec<StatCardView>,
    pub chart: Option<SeriesChart>,
    pub table_title: String,
    pub table: Option<TableView>,
}

fn entity_table(report: &EntityReport, fmt: NumberFormat) -> TableView {
    let has_value = report.kind.has_value();
    let mut columns = vec![
        column("Data", false, true),
        column("Sessão", true, false),
        column("Duração", true, false),
        column("Quantidade", true, false),
        column("Por hora", true, false),
    ];
    if has_value {
        columns.push(column("Valor", true, false));
    }
    let rows = report
        .present_rows()
        .map(|r| {
            let session = r.session_id.map(|v| v as f64);
            let duration = r.duration_seconds.map(|v| v as f64);
            let qty = Some(r.quantity as f64);
            let per_hour = rate_per_hour(Some(r.quantity), r.duration_seconds);
            let mut cells = vec![
                Cell(
                    format_datetime_short(r.start_datetime),
                    r.start_datetime.map(|d| SortKey::Number(d.and_utc().timestamp() as f64)),
                    None,
                ),
                number_cell(session, format_text(r.session_id.map(|v| v.to_string()).as_deref())),
                number_cell(duration, format_duration(duration)),
                number_cell(qty, format_number(qty, 0, fmt)),
                number_cell(per_hour, format_number(per_hour, 0, fmt)),
            ];
            if has_value {
                let value = r.value.map(|v| v as f64);
                cells.push(number_cell(value, format_money(value, fmt)));
            }
            row(r.hunt_id, cells)
        })
        .collect();
    TableView { columns, rows }
}

fn entity_cards(report: &EntityReport, fmt: NumberFormat) -> Vec<StatCardView> {
    let number = |v: Option<f64>| format_number(v, 0, fmt);
    let is_enemy = report.kind == EntityKind::Enemies;
    let in_present = "Nas Hunts em que apareceu".to_owned();
    let mut cards = vec![StatCardView {
        title: if is_enemy { "Total derrotado" } else { "Quantidade total" },
        value: number(Some(report.total_quantity() as f64)),
        hint: String::new(),
    }];
    if report.kind.has_value() {
        cards.push(StatCardView {
            title: "Valor total",
            value: format_money(report.total_value().map(|v| v as f64), fmt),
            hint: format!("{} por hora", format_money(report.value_per_hour(), fmt)),
        });
    }
    cards.push(StatCardView {
        title: "Hunts",
        value: format!("{} de {}", number(Some(report.present_count() as f64)), number(Some(report.hunt_count() as f64))),
        hint: format!("Presença: {}", format_percent(report.presence_ratio(), fmt)),
    });
    cards.push(StatCardView { title: "Média por Hunt", value: number(report.average_per_hunt()), hint: in_present.clone() });
    cards.push(StatCardView { title: "Média por hora", value: number(report.per_hour()), hint: in_present.clone() });
    if report.kind.has_value() {
        cards.push(StatCardView {
            title: "Valor médio por Hunt",
            value: format_money(report.average_value_per_hunt(), fmt),
            hint: in_present,
        });
    }
    let max = report.max_row();
    let min = report.min_row();
    cards.push(StatCardView {
        title: "Maior quantidade",
        value: number(max.map(|r| r.quantity as f64)),
        hint: row_label(max),
    });
    cards.push(StatCardView {
        title: "Menor quantidade",
        value: number(min.map(|r| r.quantity as f64)),
        hint: row_label(min),
    });
    cards
}

/// Mesma média dos cards (só as Hunts em que apareceu), com as ausências explicadas.
fn chart_subtitle(report: &EntityReport, fmt: NumberFormat) -> String {
    let number = |v: Option<f64>| format_number(v, 0, fmt);
    let mut text = format!(
        "Média quando aparece {}  ·  Máx. {}",
        number(report.average_per_hunt()),
        number(report.max_row().map(|r| r.quantity as f64))
    );
    let absent = report.hunt_count() - report.present_count();
    if absent > 0 {
        text.push_str(&format!("  ·  ausente em {absent} de {} Hunts (barras vazias)", report.hunt_count()));
    }
    text
}

impl EntityReportView {
    fn empty(title: &str, message: String) -> Self {
        Self { empty: Some((title.to_owned(), message)), cards: Vec::new(), chart: None, table_title: String::new(), table: None }
    }

    pub fn new(report: &EntityReport, fmt: NumberFormat) -> Self {
        if report.hunt_count() == 0 {
            return Self::empty("Sem Hunts", "Nenhuma Hunt corresponde aos filtros atuais.".to_owned());
        }
        if report.present_count() == 0 {
            return Self::empty(
                "Nada encontrado",
                format!(
                    "“{}” não aparece em nenhuma das {} Hunts filtradas. Confira o nome ou ajuste os filtros.",
                    report.name,
                    report.hunt_count()
                ),
            );
        }
        let points = report
            .rows
            .iter()
            .map(|r| {
                let value = Some(r.quantity as f64);
                ChartPoint {
                    key: Some(r.hunt_id),
                    label: r.start_datetime.map_or_else(|| PLACEHOLDER.to_owned(), |d| d.format("%d/%m").to_string()),
                    value,
                    value_text: format_number(value, 0, fmt),
                    title: row_label(Some(r)),
                }
            })
            .collect();
        let chart = SeriesChart::new(&format!("{} por Hunt", report.name), points, ValueFormat::Number, fmt)
            .with_reference(report.average_per_hunt(), chart_subtitle(report, fmt));
        let verb = if report.kind == EntityKind::Enemies { "foi derrotado" } else { "apareceu" };
        Self {
            empty: None,
            cards: entity_cards(report, fmt),
            chart: Some(chart),
            table_title: format!("Hunts em que {verb} ({})", report.present_count()),
            table: Some(entity_table(report, fmt)),
        }
    }
}

// ------------------------------------------------------------------------------ preços

/// Um item da página Preços, na mesma ordem das linhas da tabela (id = índice).
#[derive(Debug, Clone, Serialize)]
pub struct PriceItemView {
    pub name: String,
    pub has_custom_price: bool,
    /// Texto para o campo do diálogo: o preço personalizado, ou o do Analyzer.
    pub price_text: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct PricesView {
    pub table: TableView,
    pub items: Vec<PriceItemView>,
    pub custom_count: usize,
}

/// Sem separador de milhar, para ser lido igual em pt-BR e en-US (`str(int(price))`).
fn plain_price(price: f64) -> String {
    if price.fract() == 0.0 && price.abs() < 1e16 { format!("{}", price as i64) } else { format!("{price}") }
}

impl PricesView {
    pub fn new(items: &[PricedItem], fmt: NumberFormat) -> Self {
        let rows = items
            .iter()
            .enumerate()
            .map(|(i, item)| {
                let qty = Some(item.quantity as f64);
                let hunts = Some(item.hunt_count as f64);
                let mut custom = number_cell(item.custom_price, format_money(item.custom_price, fmt));
                custom.2 = item.custom_price.map(|_| "accent");
                row(i as i64, vec![
                    text_cell(Some(&item.name)),
                    text_cell(Some(item.sources())),
                    number_cell(item.analyzer_price, format_money(item.analyzer_price, fmt)),
                    custom,
                    number_cell(qty, format_number(qty, 0, fmt)),
                    number_cell(hunts, format_number(hunts, 0, fmt)),
                ])
            })
            .collect();
        let views = items
            .iter()
            .map(|item| {
                let price = if item.has_custom_price() { item.custom_price } else { item.analyzer_price };
                PriceItemView {
                    name: item.name.clone(),
                    has_custom_price: item.has_custom_price(),
                    price_text: price.map(plain_price).unwrap_or_default(),
                }
            })
            .collect();
        Self {
            table: TableView {
                columns: vec![
                    column("Item", false, false),
                    column("Aparece em", false, false),
                    ColumnView {
                        tooltip: Some("Preço unitário exportado pelo Analyzer na Hunt mais recente"),
                        ..column("Preço do Analyzer", true, false)
                    },
                    column("Preço personalizado", true, false),
                    column("Quantidade", true, false),
                    column("Hunts", true, false),
                ],
                rows,
            },
            items: views,
            custom_count: items.iter().filter(|i| i.has_custom_price()).count(),
        }
    }
}

/// Texto informativo do diálogo de preço e se dá para salvar (como `PriceDialog.validate`).
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct PriceCheck {
    pub text: String,
    pub error: bool,
    pub valid: bool,
}

/// O preço digitado, se for um número maior ou igual a zero.
pub fn parse_price(text: &str, fmt: NumberFormat) -> Option<f64> {
    parse_user_number(text, fmt).filter(|v| *v >= 0.0)
}

pub fn price_check(items: &[PricedItem], name: &str, price_text: &str, fmt: NumberFormat) -> PriceCheck {
    let name = name.trim();
    let price = parse_price(price_text, fmt);
    let key = item_key(name);
    let known = if name.is_empty() { None } else { items.iter().find(|i| item_key(&i.name) == key) };
    if !price_text.trim().is_empty() && price.is_none() {
        return PriceCheck { text: "Preço inválido: use um número maior ou igual a zero.".into(), error: true, valid: false };
    }
    let text = match known {
        Some(item) => format!(
            "Preço do Analyzer: {} · aparece em {} Hunt(s) como {}.",
            format_money(item.analyzer_price, fmt),
            item.hunt_count,
            item.sources().to_lowercase()
        ),
        None if !name.is_empty() => "Item ainda não visto nas Hunts: o preço valerá quando ele aparecer.".into(),
        None => String::new(),
    };
    PriceCheck { text, error: false, valid: !name.is_empty() && price.is_some() }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::NaiveDate;

    const FMT: NumberFormat = NumberFormat::PT_BR;

    #[test]
    fn scopes_follow_the_python_order() {
        let labels: Vec<String> = scopes().into_iter().map(|(label, _)| label).collect();
        assert_eq!(labels.first().map(String::as_str), Some("Hunts"));
        assert_eq!(labels[1], "Todos os bosses");
        assert_eq!(labels.last().map(String::as_str), Some("Hunts e bosses"));
        assert!(labels.iter().any(|l| l == "Bosses · Terrors"));
        assert_eq!(scope(99).1, vec![Category::Hunt]);
        assert!(scope(labels.len() - 1).1.is_empty());
    }

    fn entity_row(hunt_id: i64, quantity: i64, day: u32) -> EntityHuntRow {
        EntityHuntRow {
            hunt_id,
            session_id: Some(hunt_id * 10),
            start_datetime: NaiveDate::from_ymd_opt(2026, 9, day).and_then(|d| d.and_hms_opt(14, 0, 0)),
            duration_seconds: Some(3600),
            quantity,
            value: Some(quantity * 100),
        }
    }

    #[test]
    fn entity_report_without_presence_shows_a_message() {
        let report = EntityReport { kind: EntityKind::Drops, name: "Gold Nugget".into(), rows: vec![entity_row(1, 0, 1)] };
        let view = EntityReportView::new(&report, FMT);
        let (title, message) = view.empty.unwrap();
        assert_eq!(title, "Nada encontrado");
        assert!(message.starts_with("“Gold Nugget” não aparece em nenhuma das 1 Hunts"));
        let none = EntityReport { kind: EntityKind::Drops, name: "X".into(), rows: Vec::new() };
        assert_eq!(EntityReportView::new(&none, FMT).empty.unwrap().0, "Sem Hunts");
    }

    #[test]
    fn entity_report_uses_the_average_when_present() {
        let report = EntityReport {
            kind: EntityKind::Drops,
            name: "Gold Nugget".into(),
            rows: vec![entity_row(1, 10, 1), entity_row(2, 0, 2), entity_row(3, 30, 3)],
        };
        let view = EntityReportView::new(&report, FMT);
        let chart = view.chart.unwrap();
        assert_eq!(chart.title, "Gold Nugget por Hunt");
        assert_eq!(chart.average, Some(20.0));
        assert_eq!(chart.subtitle, "Média quando aparece 20  ·  Máx. 30  ·  ausente em 1 de 3 Hunts (barras vazias)");
        assert_eq!(view.table_title, "Hunts em que apareceu (2)");
        assert_eq!(view.table.unwrap().rows.len(), 2);
        let titles: Vec<&str> = view.cards.iter().map(|c| c.title).collect();
        assert_eq!(titles, [
            "Quantidade total",
            "Valor total",
            "Hunts",
            "Média por Hunt",
            "Média por hora",
            "Valor médio por Hunt",
            "Maior quantidade",
            "Menor quantidade"
        ]);
        assert_eq!(view.cards[2].value, "2 de 3");
        assert_eq!(view.cards[6].hint, "Hunt 30 · 03/09/2026 14:00");
    }

    #[test]
    fn enemy_report_has_no_value() {
        let report = EntityReport { kind: EntityKind::Enemies, name: "Rattata".into(), rows: vec![entity_row(1, 5, 1)] };
        let view = EntityReportView::new(&report, FMT);
        assert_eq!(view.cards[0].title, "Total derrotado");
        assert!(view.cards.iter().all(|c| c.title != "Valor total"));
        assert_eq!(view.table.unwrap().columns.len(), 5);
        assert_eq!(view.table_title, "Hunts em que foi derrotado (1)");
    }

    fn priced(name: &str, analyzer: Option<f64>, custom: Option<f64>) -> PricedItem {
        PricedItem {
            name: name.into(),
            in_drops: true,
            in_supplies: false,
            analyzer_price: analyzer,
            custom_price: custom,
            quantity: 3,
            hunt_count: 2,
        }
    }

    #[test]
    fn price_check_messages() {
        let items = vec![priced("Gold Nugget", Some(1500.0), None)];
        assert_eq!(price_check(&items, "", "", FMT), PriceCheck { text: String::new(), error: false, valid: false });
        let known = price_check(&items, "gold nugget", "1,2k", FMT);
        assert_eq!(known.text, "Preço do Analyzer: 1.500 · aparece em 2 Hunt(s) como drop.");
        assert!(known.valid);
        let unknown = price_check(&items, "Novo", "10", FMT);
        assert_eq!(unknown.text, "Item ainda não visto nas Hunts: o preço valerá quando ele aparecer.");
        let invalid = price_check(&items, "Novo", "-5", FMT);
        assert!(invalid.error && !invalid.valid);
        assert_eq!(invalid.text, "Preço inválido: use um número maior ou igual a zero.");
    }

    #[test]
    fn prices_view_marks_custom_prices() {
        let items = vec![priced("A", Some(1500.0), Some(2000.5)), priced("B", Some(800.0), None)];
        let view = PricesView::new(&items, FMT);
        assert_eq!(view.custom_count, 1);
        assert_eq!(view.items[0].price_text, "2000.5");
        assert_eq!(view.items[1].price_text, "800");
        assert_eq!(view.table.rows[0].colors[3], Some("accent"));
        assert_eq!(view.table.rows[1].colors[3], None);
    }
}
