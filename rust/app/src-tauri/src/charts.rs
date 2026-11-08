//! Dados dos gráficos (equivale a `app/ui/charts/charts.py` e `chart_points` do Dashboard): o
//! Rust calcula os valores, os textos das dicas, as marcas dos eixos e a média; a tela só
//! desenha. Uma série por gráfico, nomeada pelo título.

use pxg_core::format::{
    NumberFormat, PLACEHOLDER, format_compact, format_datetime_short, format_duration, format_money, format_number,
    format_text,
};
use pxg_core::hunts::categories::Category;
use pxg_core::hunts::model::HuntSummary;
use serde::Serialize;

/// Acima disso, linha em vez de barras.
pub const LINE_MODE_THRESHOLD: usize = 60;
pub const MAX_X_LABELS: usize = 8;
pub const RANKED_LABEL_LIMIT: usize = 22;

/// Como formatar o valor da dica e dos rótulos.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ValueFormat {
    Money,
    Number,
    Duration,
}

impl ValueFormat {
    pub fn format(self, value: Option<f64>, fmt: NumberFormat) -> String {
        match self {
            Self::Money => format_money(value, fmt),
            Self::Number => format_number(value, 0, fmt),
            Self::Duration => format_duration(value),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct Tick {
    pub value: f64,
    pub label: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ChartPoint {
    /// Id da sessão (clicar abre os detalhes) ou nome do item.
    pub key: Option<i64>,
    /// Rótulo do eixo ("26/09") ou o nome encurtado nas barras horizontais.
    pub label: String,
    pub value: Option<f64>,
    /// Valor formatado, em destaque na dica.
    pub value_text: String,
    /// Segunda linha da dica.
    pub title: String,
}

/// Uma métrica por sessão, em ordem cronológica (colunas; linha se houver muitas).
#[derive(Debug, Clone, Serialize)]
pub struct SeriesChart {
    pub title: String,
    pub subtitle: String,
    pub points: Vec<ChartPoint>,
    pub line: bool,
    pub low: f64,
    pub high: f64,
    pub average: Option<f64>,
    pub y_ticks: Vec<Tick>,
    /// Posição e rótulo das datas embaixo (no máximo 8).
    pub x_labels: Vec<(usize, String)>,
}

/// Barras horizontais ordenadas, com o valor na ponta.
#[derive(Debug, Clone, Serialize)]
pub struct RankedChart {
    pub title: String,
    pub points: Vec<ChartPoint>,
    /// Fim do eixo, com espaço para o rótulo na ponta da barra.
    pub high: f64,
    pub x_ticks: Vec<Tick>,
}

/// Marcas "redondas" (1, 2 ou 5 × 10ⁿ) cobrindo o intervalo, como o eixo do pyqtgraph.
pub fn nice_ticks(low: f64, high: f64, target: usize) -> Vec<f64> {
    let span = high - low;
    if !(span.is_finite() && span > 0.0) {
        return vec![low];
    }
    let raw = span / target.max(1) as f64;
    let magnitude = 10f64.powf(raw.log10().floor());
    let step = [1.0, 2.0, 5.0, 10.0].iter().map(|m| m * magnitude).find(|s| span / s <= (target + 1) as f64).unwrap_or(10.0 * magnitude);
    let mut ticks = Vec::new();
    let mut value = (low / step).ceil() * step;
    while value <= high + step * 1e-9 {
        ticks.push(if value.abs() < step * 1e-9 { 0.0 } else { value });
        value += step;
    }
    ticks
}

/// Marcas de duração em 30 min ou 1 h, dobrando até caberem ~6 (`DurationAxis`).
pub fn duration_ticks(low: f64, high: f64) -> Vec<f64> {
    let span = high - low;
    if !(span.is_finite() && span > 0.0) {
        return vec![low];
    }
    let mut major = if span > 4.0 * 3600.0 { 3600.0 } else { 1800.0 };
    while span / major > 6.0 {
        major *= 2.0;
    }
    let mut ticks = Vec::new();
    let mut value = (low / major).ceil() * major;
    while value <= high + 1e-9 {
        ticks.push(value);
        value += major;
    }
    ticks
}

/// `30min`, `1h`, `1h30`.
pub fn format_duration_tick(seconds: f64) -> String {
    let total_minutes = (seconds / 60.0).round() as i64;
    let (hours, minutes) = (total_minutes / 60, total_minutes % 60);
    if hours != 0 && minutes != 0 {
        format!("{hours}h{minutes:02}")
    } else if total_minutes == 0 {
        "0".into()
    } else if hours != 0 {
        format!("{hours}h")
    } else {
        format!("{minutes}min")
    }
}

fn axis_ticks(low: f64, high: f64, duration: bool, fmt: NumberFormat) -> Vec<Tick> {
    if duration {
        duration_ticks(low, high).into_iter().map(|v| Tick { value: v, label: format_duration_tick(v) }).collect()
    } else {
        nice_ticks(low, high, 5).into_iter().map(|v| Tick { value: v, label: format_compact(v, 1, fmt) }).collect()
    }
}

/// Sessões da mais antiga para a mais recente (sem data vão para o fim).
pub fn chronological(hunts: &[HuntSummary]) -> Vec<&HuntSummary> {
    let mut sorted: Vec<&HuntSummary> = hunts.iter().collect();
    sorted.sort_by_key(|h| (h.start_datetime.is_none(), h.start_datetime, h.id));
    sorted
}

/// Pontos de uma métrica; sem `noun`, cada sessão é nomeada pela categoria.
pub fn hunt_points(
    hunts: &[&HuntSummary],
    value: impl Fn(&HuntSummary) -> Option<f64>,
    format: ValueFormat,
    noun: Option<&str>,
    fmt: NumberFormat,
) -> Vec<ChartPoint> {
    hunts
        .iter()
        .map(|h| {
            let v = value(h);
            let name = noun.map_or_else(|| Category::from_value(Some(&h.category)).label().to_owned(), str::to_owned);
            ChartPoint {
                key: Some(h.id),
                label: h.start_datetime.map_or_else(|| PLACEHOLDER.to_owned(), |d| d.format("%d/%m").to_string()),
                value: v,
                value_text: format.format(v, fmt),
                title: format!(
                    "{name} {} · {}",
                    format_text(h.session_id.map(|id| id.to_string()).as_deref()),
                    format_datetime_short(h.start_datetime)
                ),
            }
        })
        .collect()
}

impl SeriesChart {
    pub fn new(title: &str, points: Vec<ChartPoint>, format: ValueFormat, fmt: NumberFormat) -> Self {
        let finite: Vec<f64> = points.iter().filter_map(|p| p.value.filter(|v| v.is_finite())).collect();
        let mut chart = Self {
            title: title.to_owned(),
            subtitle: "Sem dados para as Hunts filtradas".into(),
            line: points.len() > LINE_MODE_THRESHOLD,
            low: 0.0,
            high: 1.0,
            average: None,
            y_ticks: Vec::new(),
            x_labels: Vec::new(),
            points,
        };
        if finite.is_empty() {
            return chart;
        }
        let average = finite.iter().sum::<f64>() / finite.len() as f64;
        let (min, max) = finite.iter().fold((f64::INFINITY, f64::NEG_INFINITY), |(a, b), v| (a.min(*v), b.max(*v)));
        chart.subtitle = format!(
            "Média {}  ·  Mín. {}  ·  Máx. {}",
            format.format(Some(average), fmt),
            format.format(Some(min), fmt),
            format.format(Some(max), fmt)
        );
        let (low, high) = (min.min(0.0), max.max(0.0));
        let span = if high - low == 0.0 { 1.0 } else { high - low };
        chart.low = low - if low < 0.0 { span * 0.06 } else { 0.0 };
        chart.high = high + span * 0.08;
        chart.average = Some(average);
        chart.y_ticks = axis_ticks(chart.low, chart.high, format == ValueFormat::Duration, fmt);
        let step = chart.points.len().div_ceil(MAX_X_LABELS).max(1);
        chart.x_labels = (0..chart.points.len()).step_by(step).map(|i| (i, chart.points[i].label.clone())).collect();
        chart
    }
}

impl SeriesChart {
    /// Troca a média padrão por outra referência e o subtítulo (como `reference`/`subtitle` do
    /// `set_points`); sem dados, o gráfico continua vazio.
    pub fn with_reference(mut self, reference: Option<f64>, subtitle: String) -> Self {
        if self.average.is_some() {
            self.average = reference;
            self.subtitle = subtitle;
        }
        self
    }
}

fn shorten(text: &str, limit: usize) -> String {
    if text.chars().count() <= limit {
        text.to_owned()
    } else {
        format!("{}…", text.chars().take(limit - 1).collect::<String>())
    }
}

impl RankedChart {
    /// `entries` já ordenados; (nome, valor).
    pub fn new(title: &str, entries: &[(String, Option<f64>)], format: ValueFormat, fmt: NumberFormat) -> Self {
        let points: Vec<ChartPoint> = entries
            .iter()
            .map(|(name, value)| {
                let v = value.unwrap_or(0.0);
                ChartPoint {
                    key: None,
                    label: shorten(name, RANKED_LABEL_LIMIT),
                    value: Some(v),
                    value_text: format.format(Some(v), fmt),
                    title: name.clone(),
                }
            })
            .collect();
        let max = points.iter().filter_map(|p| p.value).fold(0.0, f64::max);
        let high = if max == 0.0 { 1.0 } else { max } * 1.22;
        Self { title: title.to_owned(), x_ticks: axis_ticks(0.0, high, false, fmt), points, high }
    }
}

/// As `limit` maiores entradas por valor, como `_ranked_points` dos detalhes.
pub fn top_entries<T>(
    entries: &[T],
    name: impl Fn(&T) -> String,
    value: impl Fn(&T) -> Option<f64>,
    limit: usize,
) -> Vec<(String, Option<f64>)> {
    let mut ranked: Vec<(String, Option<f64>)> = entries.iter().map(|e| (name(e), value(e))).collect();
    // Estável e decrescente, como `sorted(..., reverse=True)` do Python.
    ranked.sort_by(|a, b| b.1.unwrap_or(0.0).total_cmp(&a.1.unwrap_or(0.0)));
    ranked.truncate(limit);
    ranked
}

#[cfg(test)]
mod tests {
    use super::*;

    const FMT: NumberFormat = NumberFormat::PT_BR;

    #[test]
    fn duration_tick_labels() {
        assert_eq!(format_duration_tick(0.0), "0");
        assert_eq!(format_duration_tick(1800.0), "30min");
        assert_eq!(format_duration_tick(3600.0), "1h");
        assert_eq!(format_duration_tick(5400.0), "1h30");
    }

    #[test]
    fn duration_ticks_double_until_six() {
        assert_eq!(duration_ticks(0.0, 3.0 * 3600.0), vec![0.0, 1800.0, 3600.0, 5400.0, 7200.0, 9000.0, 10800.0]);
        assert_eq!(duration_ticks(0.0, 10.0 * 3600.0), vec![0.0, 7200.0, 14400.0, 21600.0, 28800.0, 36000.0]);
    }

    #[test]
    fn nice_ticks_are_round() {
        assert_eq!(nice_ticks(0.0, 1_080_000.0, 5), vec![0.0, 200_000.0, 400_000.0, 600_000.0, 800_000.0, 1_000_000.0]);
        assert_eq!(nice_ticks(-50.0, 120.0, 5), vec![-50.0, 0.0, 50.0, 100.0]);
    }

    #[test]
    fn series_summary_and_range() {
        let points = [100.0, 200.0, 300.0]
            .iter()
            .map(|v| ChartPoint { key: None, label: "x".into(), value: Some(*v), value_text: String::new(), title: String::new() })
            .collect();
        let chart = SeriesChart::new("Profit", points, ValueFormat::Money, FMT);
        assert_eq!(chart.subtitle, "Média 200  ·  Mín. 100  ·  Máx. 300");
        assert_eq!(chart.low, 0.0);
        assert!((chart.high - 324.0).abs() < 1e-9);
        assert!(!chart.line);
        assert_eq!(chart.x_labels.len(), 3);
    }

    #[test]
    fn series_without_data() {
        let points = vec![ChartPoint { key: None, label: "x".into(), value: None, value_text: String::new(), title: String::new() }];
        assert_eq!(SeriesChart::new("Profit", points, ValueFormat::Money, FMT).subtitle, "Sem dados para as Hunts filtradas");
    }

    #[test]
    fn ranked_keeps_order_and_shortens() {
        let entries = top_entries(&[("a", 1.0), ("um nome bem comprido demais para o eixo", 3.0), ("c", 2.0)], |e| e.0.to_owned(), |e| Some(e.1), 2);
        let chart = RankedChart::new("Drops", &entries, ValueFormat::Number, FMT);
        assert_eq!(chart.points[0].label, "um nome bem comprido …");
        assert_eq!(chart.points[1].label, "c");
        assert!((chart.high - 3.66).abs() < 1e-9);
    }
}
