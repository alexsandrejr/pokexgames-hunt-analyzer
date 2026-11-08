//! Critérios de filtro de sessões, independentes de banco e de interface (equivale a
//! `app/services/filters.py`).
//!
//! Um [`HuntFilter`] combina todos os critérios com **E**. `categories` não é um critério do
//! painel de filtros: é o escopo da página (Hunts, uma aba de Bosses...). O SQL fica em
//! [`super::query`].

use chrono::{Datelike, Duration, NaiveDate};
use serde::{Deserialize, Serialize};

use super::categories::Category;
use crate::format::{NumberFormat, format_date, format_duration, format_number};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Operator {
    #[serde(rename = ">")]
    Gt,
    #[serde(rename = ">=")]
    Ge,
    #[serde(rename = "=")]
    Eq,
    #[serde(rename = "<=")]
    Le,
    #[serde(rename = "<")]
    Lt,
}

impl Operator {
    pub const ALL: [Self; 5] = [Self::Gt, Self::Ge, Self::Eq, Self::Le, Self::Lt];

    pub fn symbol(self) -> &'static str {
        match self {
            Self::Gt => ">",
            Self::Ge => ">=",
            Self::Eq => "=",
            Self::Le => "<=",
            Self::Lt => "<",
        }
    }
}

/// Métricas numéricas filtráveis; a coluna é a de `hunt_sessions`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Metric {
    Profit,
    ProfitPerHour,
    Kills,
    KillsPerHour,
    Duration,
    Supplies,
    SuppliesPerHour,
    RawGains,
    RawGainsPerHour,
}

impl Metric {
    pub const ALL: [Self; 9] = [
        Self::Profit, Self::ProfitPerHour, Self::Kills, Self::KillsPerHour, Self::Duration,
        Self::Supplies, Self::SuppliesPerHour, Self::RawGains, Self::RawGainsPerHour,
    ];

    pub fn column(self) -> &'static str {
        match self {
            Self::Profit => "profit",
            Self::ProfitPerHour => "profit_per_hour",
            Self::Kills => "kills",
            Self::KillsPerHour => "kills_per_hour",
            Self::Duration => "duration_seconds",
            Self::Supplies => "supplies",
            Self::SuppliesPerHour => "supplies_per_hour",
            Self::RawGains => "raw_gains",
            Self::RawGainsPerHour => "raw_gains_per_hour",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Profit => "Profit",
            Self::ProfitPerHour => "Profit/h",
            Self::Kills => "Kills",
            Self::KillsPerHour => "Kills/h",
            Self::Duration => "Duração",
            Self::Supplies => "Supplies",
            Self::SuppliesPerHour => "Supplies/h",
            Self::RawGains => "Raw gains",
            Self::RawGainsPerHour => "Raw gains/h",
        }
    }

    pub fn is_duration(self) -> bool {
        self == Self::Duration
    }

    /// Taxas são decimais (935099.58...): no "=", compara-se o valor arredondado exibido.
    pub fn is_rate(self) -> bool {
        matches!(self, Self::ProfitPerHour | Self::KillsPerHour | Self::SuppliesPerHour | Self::RawGainsPerHour)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ItemSource {
    Drops,
    Supplies,
}

impl ItemSource {
    /// Tabela das entradas.
    pub fn table(self) -> &'static str {
        match self {
            Self::Drops => "drops",
            Self::Supplies => "supplies",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Drops => "Drop",
            Self::Supplies => "Supply",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct MetricCondition {
    pub metric: Metric,
    pub operator: Operator,
    /// Duração em segundos.
    pub value: f64,
}

impl MetricCondition {
    pub fn describe(&self, fmt: NumberFormat) -> String {
        let value = if self.metric.is_duration() {
            format_duration(self.value)
        } else {
            format_number(self.value, 0, fmt)
        };
        format!("{} {} {value}", self.metric.label(), self.operator.symbol())
    }
}

/// Presença de um inimigo ou item na sessão, opcionalmente com quantidade.
///
/// Sem `operator`/`quantity`: basta aparecer. Com quantidade, a soma na sessão é comparada
/// (sessões em que o nome não aparece contam como 0).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct QuantityCondition {
    pub name: String,
    pub operator: Option<Operator>,
    pub quantity: Option<f64>,
}

impl QuantityCondition {
    pub fn present(name: &str) -> Self {
        Self { name: name.to_owned(), operator: None, quantity: None }
    }

    pub fn with(name: &str, operator: Operator, quantity: f64) -> Self {
        Self { name: name.to_owned(), operator: Some(operator), quantity: Some(quantity) }
    }

    pub fn comparison(&self) -> Option<(Operator, f64)> {
        self.operator.zip(self.quantity)
    }

    fn describe(&self, prefix: &str, fmt: NumberFormat) -> String {
        match self.comparison() {
            Some((operator, quantity)) => format!(
                "{prefix}: {} {} {}",
                self.name,
                operator.symbol(),
                format_number(quantity, 0, fmt)
            ),
            None => format!("{prefix}: {}", self.name),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ItemCondition {
    #[serde(flatten)]
    pub condition: QuantityCondition,
    pub source: ItemSource,
}

impl ItemCondition {
    pub fn drop(condition: QuantityCondition) -> Self {
        Self { condition, source: ItemSource::Drops }
    }

    pub fn describe(&self, fmt: NumberFormat) -> String {
        self.condition.describe(self.source.label(), fmt)
    }
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct HuntFilter {
    pub date_from: Option<NaiveDate>,
    pub date_to: Option<NaiveDate>,
    /// Contém, sem diferenciar maiúsculas.
    pub player: Option<String>,
    pub enemies: Vec<QuantityCondition>,
    pub items: Vec<ItemCondition>,
    pub metrics: Vec<MetricCondition>,
    /// Vazio: todas as categorias. Fica fora de `describe`/`is_empty` (é o escopo da página).
    pub categories: Vec<Category>,
}

impl HuntFilter {
    pub fn is_empty(&self) -> bool {
        self.describe(NumberFormat::PT_BR).is_empty()
    }

    /// O mesmo filtro restrito às categorias informadas (nenhuma: todas).
    pub fn scoped(&self, categories: &[Category]) -> Self {
        Self { categories: categories.to_vec(), ..self.clone() }
    }

    /// Descrição legível de cada critério ativo (usada nos resumos da interface).
    pub fn describe(&self, fmt: NumberFormat) -> Vec<String> {
        let date = |d: NaiveDate| format_date(d.and_hms_opt(0, 0, 0));
        let mut parts = Vec::new();
        match (self.date_from, self.date_to) {
            (Some(from), Some(to)) => parts.push(format!("Data: {} a {}", date(from), date(to))),
            (Some(from), None) => parts.push(format!("Data: a partir de {}", date(from))),
            (None, Some(to)) => parts.push(format!("Data: até {}", date(to))),
            (None, None) => {}
        }
        if let Some(player) = self.player.as_deref().filter(|p| !p.is_empty()) {
            parts.push(format!("Player: {player}"));
        }
        parts.extend(self.enemies.iter().map(|c| c.describe("Inimigo", fmt)));
        parts.extend(self.items.iter().map(|c| c.describe(fmt)));
        parts.extend(self.metrics.iter().map(|c| c.describe(fmt)));
        parts
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DatePreset {
    All,
    Today,
    Last7Days,
    Last30Days,
    ThisMonth,
    LastMonth,
    Custom,
}

impl DatePreset {
    pub fn label(self) -> &'static str {
        match self {
            Self::All => "Todo o período",
            Self::Today => "Hoje",
            Self::Last7Days => "Últimos 7 dias",
            Self::Last30Days => "Últimos 30 dias",
            Self::ThisMonth => "Este mês",
            Self::LastMonth => "Mês passado",
            Self::Custom => "Personalizado",
        }
    }
}

/// Intervalo (inclusivo) de um período pré-definido.
pub fn preset_range(preset: DatePreset, today: NaiveDate) -> (Option<NaiveDate>, Option<NaiveDate>) {
    let first_of_month = today.with_day(1).expect("dia 1 existe");
    match preset {
        DatePreset::Today => (Some(today), Some(today)),
        DatePreset::Last7Days => (Some(today - Duration::days(6)), Some(today)),
        DatePreset::Last30Days => (Some(today - Duration::days(29)), Some(today)),
        DatePreset::ThisMonth => (Some(first_of_month), Some(today)),
        DatePreset::LastMonth => {
            let last = first_of_month - Duration::days(1);
            (Some(last.with_day(1).expect("dia 1 existe")), Some(last))
        }
        DatePreset::All | DatePreset::Custom => (None, None),
    }
}
