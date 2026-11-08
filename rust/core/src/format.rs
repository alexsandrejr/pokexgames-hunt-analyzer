//! Formatação de valores para exibição (equivale a `app/utils/formatters.py`).
//!
//! O separador de milhar e decimal segue um [`NumberFormat`]: pt-BR (1.119.522 / 12,5, padrão)
//! ou en-US (1,119,522 / 12.5). Diferente da versão em Python, o formato é passado em cada
//! chamada em vez de ficar numa variável global, porque os comandos do Tauri rodam em várias
//! threads.

use chrono::NaiveDateTime;

pub const PLACEHOLDER: &str = "—";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NumberFormat {
    pub name: &'static str,
    pub thousands: char,
    pub decimal: char,
}

impl NumberFormat {
    pub const PT_BR: Self = Self { name: "pt-BR", thousands: '.', decimal: ',' };
    pub const EN_US: Self = Self { name: "en-US", thousands: ',', decimal: '.' };
    pub const ALL: [Self; 2] = [Self::PT_BR, Self::EN_US];

    /// Nomes desconhecidos viram pt-BR.
    pub fn from_name(name: &str) -> Self {
        Self::ALL.into_iter().find(|f| f.name == name).unwrap_or_default()
    }

    pub fn example(&self) -> String {
        let (t, d) = (self.thousands, self.decimal);
        format!("1{t}234{t}567{d}89")
    }
}

impl Default for NumberFormat {
    fn default() -> Self {
        Self::PT_BR
    }
}

fn finite(value: impl Into<Option<f64>>) -> Option<f64> {
    value.into().filter(|v| v.is_finite())
}

/// `1119522` → `"1.119.522"`; `12.5` com 1 casa → `"12,5"`. `None` ou não finito → `"—"`.
pub fn format_number(value: impl Into<Option<f64>>, decimals: usize, fmt: NumberFormat) -> String {
    let Some(number) = finite(value) else {
        return PLACEHOLDER.to_owned();
    };
    let text = format!("{number:.decimals$}");
    let (negative, digits) = match text.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, text.as_str()),
    };
    let (integer, fraction) = match digits.split_once('.') {
        Some((i, f)) => (i, Some(f)),
        None => (digits, None),
    };
    let mut out = String::with_capacity(text.len() + integer.len() / 3);
    // Evita "-0": um número que arredonda para zero sai sem sinal.
    if negative && digits.bytes().any(|b| matches!(b, b'1'..=b'9')) {
        out.push('-');
    }
    for (index, ch) in integer.chars().enumerate() {
        if index > 0 && (integer.len() - index) % 3 == 0 {
            out.push(fmt.thousands);
        }
        out.push(ch);
    }
    if let Some(fraction) = fraction {
        out.push(fmt.decimal);
        out.push_str(fraction);
    }
    out
}

/// Inteiro exato com separador de milhar, como o `f"{n:,}"` do Python (sem passar por `f64`,
/// que perderia os últimos dígitos acima de 2^53).
pub fn format_integer(value: i64, fmt: NumberFormat) -> String {
    let digits = value.unsigned_abs().to_string();
    let mut out = String::with_capacity(digits.len() + digits.len() / 3 + 1);
    if value < 0 {
        out.push('-');
    }
    for (index, ch) in digits.chars().enumerate() {
        if index > 0 && (digits.len() - index) % 3 == 0 {
            out.push(fmt.thousands);
        }
        out.push(ch);
    }
    out
}

/// Duração de um inteiro de segundos, exata para qualquer tamanho.
pub fn format_duration_integer(seconds: i64) -> String {
    if seconds < 0 {
        return PLACEHOLDER.to_owned();
    }
    let (hours, rest) = (seconds / 3600, seconds % 3600);
    format!("{hours:02}:{:02}:{:02}", rest / 60, rest % 60)
}

/// Sem separador de milhar nem casas fixas: `2.5` → `"2,5"`; `8.0` → `"8"`.
pub fn format_plain(value: f64, fmt: NumberFormat) -> String {
    let text = if value.is_finite() && value.fract() == 0.0 {
        format!("{}", value as i64)
    } else {
        crate::pyjson::python_float(value) // o `str(float)` do Python
    };
    text.replace('.', &fmt.decimal.to_string())
}

/// Valores em dinheiro do jogo são exibidos sem casas decimais.
pub fn format_money(value: impl Into<Option<f64>>, fmt: NumberFormat) -> String {
    format_number(value, 0, fmt)
}

const COMPACT_UNITS: [(f64, &str); 4] =
    [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")];

/// Grandes números de forma legível: `119470652` → `"119,5 M"`.
pub fn format_compact(value: impl Into<Option<f64>>, decimals: usize, fmt: NumberFormat) -> String {
    let Some(number) = finite(value) else {
        return PLACEHOLDER.to_owned();
    };
    for (threshold, suffix) in COMPACT_UNITS {
        if number.abs() >= threshold {
            return format!("{} {suffix}", format_number(number / threshold, decimals, fmt));
        }
    }
    format_number(number, 0, fmt)
}

/// `4310` → `"01:11:50"` (horas podem passar de 24).
pub fn format_duration(seconds: impl Into<Option<f64>>) -> String {
    match finite(seconds) {
        Some(number) if number >= 0.0 => {
            let total = round_half_even(number) as u64;
            let (hours, rest) = (total / 3600, total % 3600);
            format!("{hours:02}:{:02}:{:02}", rest / 60, rest % 60)
        }
        _ => PLACEHOLDER.to_owned(),
    }
}

/// Totais de tempo: `152280` → `"42h 18min"`.
pub fn format_duration_long(seconds: impl Into<Option<f64>>, fmt: NumberFormat) -> String {
    match finite(seconds) {
        Some(number) if number >= 0.0 => {
            let total_minutes = (number / 60.0).floor() as u64;
            let (hours, minutes) = (total_minutes / 60, total_minutes % 60);
            if hours > 0 {
                format!("{}h {minutes:02}min", format_number(hours as f64, 0, fmt))
            } else {
                format!("{minutes}min")
            }
        }
        _ => PLACEHOLDER.to_owned(),
    }
}

/// Fração 0–1 → `"12,5%"`.
pub fn format_percent(value: impl Into<Option<f64>>, fmt: NumberFormat) -> String {
    match finite(value) {
        Some(number) => format!("{}%", format_number(number * 100.0, 1, fmt)),
        None => PLACEHOLDER.to_owned(),
    }
}

pub fn format_datetime(value: Option<NaiveDateTime>) -> String {
    value.map_or_else(|| PLACEHOLDER.to_owned(), |v| v.format("%d/%m/%Y %H:%M:%S").to_string())
}

pub fn format_datetime_short(value: Option<NaiveDateTime>) -> String {
    value.map_or_else(|| PLACEHOLDER.to_owned(), |v| v.format("%d/%m/%Y %H:%M").to_string())
}

pub fn format_date(value: Option<NaiveDateTime>) -> String {
    value.map_or_else(|| PLACEHOLDER.to_owned(), |v| v.format("%d/%m/%Y").to_string())
}

pub fn format_bool(value: Option<bool>) -> String {
    match value {
        Some(true) => "Sim".to_owned(),
        Some(false) => "Não".to_owned(),
        None => PLACEHOLDER.to_owned(),
    }
}

pub fn format_text(value: Option<&str>) -> String {
    match value {
        Some(text) if !text.is_empty() => text.to_owned(),
        _ => PLACEHOLDER.to_owned(),
    }
}

/// Natureza de um valor: define a formatação na tela, no PDF e nas planilhas.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ValueKind {
    Text,
    /// Inteiro ou taxa exibida sem casas decimais.
    Number,
    Money,
    /// Segundos.
    Duration,
    Datetime,
    /// Fração 0–1.
    Percent,
}

/// Arredonda como o `round()` do Python: empates vão para o par.
pub fn round_half_even(value: f64) -> f64 {
    value.round_ties_even()
}

/// `round(value, places)` do Python: arredonda o valor binário exato, com empate para o par.
pub fn round_to(value: f64, places: usize) -> f64 {
    format!("{value:.places$}").parse().unwrap_or(value)
}

#[cfg(test)]
mod tests {
    use super::*;

    const BR: NumberFormat = NumberFormat::PT_BR;
    const US: NumberFormat = NumberFormat::EN_US;

    #[test]
    fn number() {
        assert_eq!(format_number(1119522.0, 0, BR), "1.119.522");
        assert_eq!(format_number(935099.4, 0, BR), "935.099");
        assert_eq!(format_number(12.5, 1, BR), "12,5");
        assert_eq!(format_number(-1500.0, 0, BR), "-1.500");
        assert_eq!(format_number(-0.2, 0, BR), "0");
        assert_eq!(format_number(0.0, 0, BR), "0");
        assert_eq!(format_number(None, 0, BR), PLACEHOLDER);
        assert_eq!(format_number(f64::NAN, 0, BR), PLACEHOLDER);
        assert_eq!(format_number(123.0, 0, BR), "123");
        assert_eq!(format_number(1000.0, 0, BR), "1.000");
    }

    #[test]
    fn number_follows_the_chosen_format() {
        assert_eq!(format_number(1119522.0, 0, US), "1,119,522");
        assert_eq!(format_number(12.5, 1, US), "12.5");
        assert_eq!(NumberFormat::from_name("en-US"), US);
        assert_eq!(NumberFormat::from_name("xx"), BR);
        assert_eq!(BR.example(), "1.234.567,89");
    }

    #[test]
    fn plain() {
        assert_eq!(format_plain(2.5, BR), "2,5");
        assert_eq!(format_plain(8.0, BR), "8");
        assert_eq!(format_plain(0.75, US), "0.75");
    }

    #[test]
    fn money_and_compact() {
        assert_eq!(format_money(1119522.0, BR), "1.119.522");
        assert_eq!(format_compact(119470652.0, 1, BR), "119,5 M");
        assert_eq!(format_compact(1_460_258.0, 1, BR), "1,5 M");
        assert_eq!(format_compact(2_500_000_000.0, 1, BR), "2,5 B");
        assert_eq!(format_compact(950.0, 1, BR), "950");
    }

    #[test]
    fn durations() {
        assert_eq!(format_duration(4310.0), "01:11:50");
        assert_eq!(format_duration(0.0), "00:00:00");
        assert_eq!(format_duration(90061.0), "25:01:01");
        assert_eq!(format_duration(None), PLACEHOLDER);
        assert_eq!(format_duration(-5.0), PLACEHOLDER);
        assert_eq!(format_duration_long((42 * 3600 + 18 * 60 + 30) as f64, BR), "42h 18min");
        assert_eq!(format_duration_long(540.0, BR), "9min");
        assert_eq!(format_duration_long((1500 * 3600) as f64, BR), "1.500h 00min");
    }

    #[test]
    fn dates_and_bools() {
        let moment = chrono::NaiveDate::from_ymd_opt(2026, 9, 26)
            .unwrap()
            .and_hms_opt(15, 24, 20)
            .unwrap();
        assert_eq!(format_date(Some(moment)), "26/09/2026");
        assert_eq!(format_datetime(Some(moment)), "26/09/2026 15:24:20");
        assert_eq!(format_date(None), PLACEHOLDER);
        assert_eq!(format_bool(Some(true)), "Sim");
        assert_eq!(format_bool(Some(false)), "Não");
        assert_eq!(format_bool(None), PLACEHOLDER);
    }

    #[test]
    fn percent_and_rounding() {
        assert_eq!(format_percent(0.125, BR), "12,5%");
        assert_eq!(round_to(75.0, 2), 75.0);
        assert_eq!(round_to(33.3333, 2), 33.33);
        assert_eq!(round_half_even(2.5), 2.0);
    }
}
