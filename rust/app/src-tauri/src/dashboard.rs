//! O que a página Início mostra (equivale a `app/ui/dashboard/dashboard_widget.py`): cards das
//! sessões filtradas no escopo escolhido, o resumo por categoria e a evolução por sessão.

use pxg_core::format::{NumberFormat, format_date, format_duration, format_duration_long, format_money, format_number};
use pxg_core::hunts::categories::Category;
use pxg_core::hunts::model::HuntSummary;
use pxg_core::hunts::statistics::OverviewStats;
use serde::Serialize;

use crate::charts::{SeriesChart, ValueFormat, chronological, hunt_points};
use crate::sessions::StatCardView;

pub const MIN_HUNTS_FOR_CHARTS: i64 = 2;

/// O seletor começa em "Hunts e bosses" (o último escopo), para o dinheiro dos bosses entrar.
pub fn default_scope() -> usize {
    crate::analysis::scopes().len() - 1
}

type ChartSpec = (&'static str, ValueFormat, fn(&HuntSummary) -> Option<f64>);

const DASHBOARD_CHARTS: [ChartSpec; 8] = [
    ("Profit/h por sessão", ValueFormat::Money, |h| h.profit_per_hour),
    ("Kills/h por sessão", ValueFormat::Number, |h| h.kills_per_hour),
    ("Profit por sessão", ValueFormat::Money, |h| h.profit.map(|v| v as f64)),
    ("Supplies/h por sessão", ValueFormat::Money, |h| h.supplies_per_hour),
    ("Damage dealt por segundo", ValueFormat::Number, |h| h.damage_dealt_per_second),
    ("Damage taken por segundo", ValueFormat::Number, |h| h.damage_taken_per_second),
    ("Kills por sessão", ValueFormat::Number, |h| h.kills.map(|v| v as f64)),
    ("Duração das sessões", ValueFormat::Duration, |h| h.duration_seconds.map(|v| v as f64)),
];

/// (singular, plural) das sessões do escopo: "Hunt"/"Hunts" ou "sessão"/"sessões".
pub fn scope_nouns(categories: &[Category]) -> (&'static str, &'static str) {
    if categories == [Category::Hunt] { ("Hunt", "Hunts") } else { ("sessão", "sessões") }
}

fn capitalize(text: &str) -> String {
    let mut chars = text.chars();
    chars.next().map_or_else(String::new, |first| first.to_uppercase().chain(chars).collect())
}

#[derive(Debug, Clone, Serialize)]
pub struct DashboardView {
    pub subtitle: String,
    /// Os 4 cards em destaque e, depois, os 4 menores; vazio quando não há sessões.
    pub main_cards: Vec<StatCardView>,
    pub small_cards: Vec<StatCardView>,
    /// Aviso quando não há sessões ou há menos de 2 (sem gráficos).
    pub hint: Option<String>,
    /// Só as categorias com sessões, e só quando há mais de uma.
    pub categories: Vec<StatCardView>,
    pub charts_title: String,
    pub charts_hint: String,
    pub charts: Vec<SeriesChart>,
}

pub struct DashboardInput<'a> {
    pub scope_label: &'a str,
    pub categories: &'a [Category],
    pub filter_active: bool,
    pub stats: &'a OverviewStats,
    /// Visão geral de cada categoria, com o filtro do usuário.
    pub per_category: &'a [(Category, OverviewStats)],
    pub hunts: &'a [HuntSummary],
}

fn cards(stats: &OverviewStats, singular: &str, plural: &str, fmt: NumberFormat) -> (Vec<StatCardView>, Vec<StatCardView>) {
    let money = |v: Option<f64>| format_money(v, fmt);
    let number = |v: Option<f64>| format_number(v, 0, fmt);
    let per = format!("Média por {singular}");
    let main = vec![
        StatCardView {
            title: "Profit",
            value: money(Some(stats.total_profit as f64)),
            hint: format!("{per}: {}", money(stats.average_profit)),
        },
        StatCardView {
            title: "Profit/h médio",
            value: money(stats.average_profit_per_hour),
            hint: format!("Total ÷ tempo total: {}", money(stats.profit_per_total_hour())),
        },
        StatCardView {
            title: "Kills/h médio",
            value: number(stats.average_kills_per_hour),
            hint: format!("Total ÷ tempo total: {}", number(stats.kills_per_total_hour())),
        },
        StatCardView {
            title: "Tempo total",
            value: format_duration_long(stats.total_duration_seconds as f64, fmt),
            hint: format!("{per}: {}", format_duration(stats.average_duration_seconds())),
        },
    ];
    let small = vec![
        StatCardView {
            title: if plural == "Hunts" { "Hunts analisadas" } else { "Sessões analisadas" },
            value: number(Some(stats.hunt_count as f64)),
            hint: format!("Última: {}", format_date(stats.last_start)),
        },
        StatCardView {
            title: "Kills",
            value: number(Some(stats.total_kills as f64)),
            hint: format!("{per}: {}", number(stats.average_kills())),
        },
        StatCardView {
            title: "Supplies",
            value: money(Some(stats.total_supplies as f64)),
            hint: format!("Por hora: {}", money(stats.supplies_per_total_hour())),
        },
        StatCardView {
            title: "Raw Gains",
            value: money(Some(stats.total_raw_gains as f64)),
            hint: format!("Por hora: {}", money(stats.raw_gains_per_total_hour())),
        },
    ];
    (main, small)
}

fn category_cards(per_category: &[(Category, OverviewStats)], fmt: NumberFormat) -> Vec<StatCardView> {
    let cards: Vec<StatCardView> = per_category
        .iter()
        .filter(|(_, stats)| stats.hunt_count > 0)
        .map(|(category, stats)| StatCardView {
            title: category.plural(),
            value: format_money(stats.total_profit as f64, fmt),
            hint: format!(
                "{} sessão(ões) · {} kills · {}\nProfit/h: {}",
                format_number(stats.hunt_count as f64, 0, fmt),
                format_number(stats.total_kills as f64, 0, fmt),
                format_duration_long(stats.total_duration_seconds as f64, fmt),
                format_money(stats.profit_per_total_hour(), fmt)
            ),
        })
        .collect();
    // Uma categoria só já é o que os cards de cima mostram.
    if cards.len() > 1 { cards } else { Vec::new() }
}

impl DashboardView {
    pub fn new(input: DashboardInput<'_>, fmt: NumberFormat) -> Self {
        let (singular, plural) = scope_nouns(input.categories);
        let stats = input.stats;
        let scope = format!("{}{}", input.scope_label, if input.filter_active { " (filtradas)" } else { "" });
        let period = if stats.first_start.is_some() {
            format!(" · {} a {}", format_date(stats.first_start), format_date(stats.last_start))
        } else {
            String::new()
        };
        let enough = stats.hunt_count >= MIN_HUNTS_FOR_CHARTS;
        let hint = if stats.hunt_count == 0 {
            Some(if input.filter_active {
                format!("Nenhuma {singular} corresponde aos filtros.")
            } else {
                format!(
                    "Nenhuma {singular} nesta categoria ainda. Clique em Importar, na barra lateral, ou arraste arquivos .json/.tsv para a janela."
                )
            })
        } else if !enough {
            Some(format!("Os gráficos aparecem a partir de 2 {plural}."))
        } else {
            None
        };
        let (main_cards, small_cards) =
            if stats.hunt_count > 0 { cards(stats, singular, plural, fmt) } else { (Vec::new(), Vec::new()) };
        let charts = if enough {
            let sessions = chronological(input.hunts);
            DASHBOARD_CHARTS
                .iter()
                .map(|(title, format, value)| {
                    SeriesChart::new(title, hunt_points(&sessions, value, *format, None, fmt), *format, fmt)
                })
                .collect()
        } else {
            Vec::new()
        };
        Self {
            subtitle: format!("Visão geral: {scope}{period}"),
            main_cards,
            small_cards,
            hint,
            categories: category_cards(input.per_category, fmt),
            charts_title: format!("Evolução por {singular}"),
            charts_hint: format!(
                "{} em ordem cronológica. A linha horizontal marca a média. Clique em uma barra para abrir a {singular}.",
                capitalize(plural)
            ),
            charts,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const FMT: NumberFormat = NumberFormat::PT_BR;

    fn stats(hunt_count: i64) -> OverviewStats {
        OverviewStats { hunt_count, total_profit: 1000 * hunt_count, ..OverviewStats::default() }
    }

    fn input<'a>(
        categories: &'a [Category],
        stats: &'a OverviewStats,
        per_category: &'a [(Category, OverviewStats)],
    ) -> DashboardInput<'a> {
        DashboardInput { scope_label: "Hunts", categories, filter_active: false, stats, per_category, hunts: &[] }
    }

    #[test]
    fn nouns_follow_the_scope() {
        assert_eq!(scope_nouns(&[Category::Hunt]), ("Hunt", "Hunts"));
        assert_eq!(scope_nouns(&[]), ("sessão", "sessões"));
        assert_eq!(default_scope(), crate::analysis::scopes().len() - 1);
    }

    #[test]
    fn empty_scope_shows_the_import_hint() {
        let s = stats(0);
        let view = DashboardView::new(input(&[Category::Hunt], &s, &[]), FMT);
        assert!(view.main_cards.is_empty());
        assert_eq!(view.subtitle, "Visão geral: Hunts");
        assert!(view.hint.unwrap().starts_with("Nenhuma Hunt nesta categoria ainda."));
    }

    #[test]
    fn one_session_has_cards_but_no_charts() {
        let s = stats(1);
        let view = DashboardView::new(input(&[], &s, &[]), FMT);
        assert_eq!(view.main_cards.len(), 4);
        assert_eq!(view.small_cards[0].title, "Sessões analisadas");
        assert_eq!(view.hint.as_deref(), Some("Os gráficos aparecem a partir de 2 sessões."));
        assert_eq!(view.charts_hint.split(' ').next(), Some("Sessões"));
    }

    #[test]
    fn categories_only_with_more_than_one() {
        let s = stats(3);
        let one = [(Category::Hunt, stats(3)), (Category::Rift, stats(0))];
        assert!(DashboardView::new(input(&[], &s, &one), FMT).categories.is_empty());
        let two = [(Category::Hunt, stats(2)), (Category::Rift, stats(1))];
        let view = DashboardView::new(input(&[], &s, &two), FMT);
        assert_eq!(view.categories.len(), 2);
        assert_eq!(view.categories[1].title, Category::Rift.plural());
        assert!(view.categories[0].hint.starts_with("2 sessão(ões) · 0 kills"));
    }
}
