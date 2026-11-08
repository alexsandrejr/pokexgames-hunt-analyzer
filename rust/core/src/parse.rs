//! Conversões seguras de valores (equivale a `app/utils/validators.py`).
//!
//! As funções de JSON toleram `null`, tipos inesperados e textos malformados, devolvendo
//! `None` em vez de falhar: um campo estranho não pode quebrar a importação inteira.

use std::sync::LazyLock;

use chrono::{NaiveDate, NaiveDateTime};
use regex::Regex;
use serde_json::Value;

use crate::format::{NumberFormat, round_half_even};
use crate::text::py_strip;

/// Formatos de data e hora de início da sessão exportados pelo Analyzer.
pub const ANALYZER_DATETIME_FORMATS: [&str; 5] = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
];

const TRUE_STRINGS: [&str; 6] = ["true", "1", "yes", "sim", "y", "s"];
const FALSE_STRINGS: [&str; 6] = ["false", "0", "no", "nao", "não", "n"];

/// Texto como o `float()` do Python lê: aceita `_` entre dígitos e recusa o que não é finito.
pub fn text_to_float(text: &str) -> Option<f64> {
    let text = py_strip(text);
    if text.is_empty() {
        return None;
    }
    let cleaned;
    let text = if text.contains('_') {
        let bytes = text.as_bytes();
        let valid = bytes.iter().enumerate().all(|(i, &b)| {
            b != b'_'
                || (i > 0
                    && bytes[i - 1].is_ascii_digit()
                    && bytes.get(i + 1).is_some_and(u8::is_ascii_digit))
        });
        if !valid {
            return None;
        }
        cleaned = text.replace('_', "");
        cleaned.as_str()
    } else {
        text
    };
    text.parse::<f64>().ok().filter(|n| n.is_finite())
}

/// Converte para número finito; valores inválidos viram `None`.
pub fn to_float(value: &Value) -> Option<f64> {
    match value {
        Value::Number(n) => n.as_f64().filter(|v| v.is_finite()),
        Value::String(s) => text_to_float(&s.replace(' ', "")),
        _ => None,
    }
}

/// Converte para inteiro, arredondando decimais; inválidos viram `None`.
///
/// Fora dos 64 bits também vira `None`. O Python aceitaria o número e falharia ao gravar,
/// porque o SQLite só guarda inteiros de 64 bits.
pub fn to_int(value: &Value) -> Option<i64> {
    if let Value::Number(n) = value {
        if let Some(i) = n.as_i64() {
            return Some(i);
        }
    }
    to_float(value).and_then(round_to_i64)
}

/// `numerator / denominator` entre inteiros do Python: o quociente exato, arredondado uma única
/// vez para o `f64` mais próximo (empate para o par). Converter antes para `f64` arredondaria
/// duas vezes quando o numerador passa de 2^53.
pub fn int_true_div(numerator: i128, denominator: i128) -> f64 {
    assert!(denominator != 0, "divisão por zero");
    if numerator == 0 {
        return 0.0;
    }
    let negative = (numerator < 0) != (denominator < 0);
    let (n, d) = (numerator.unsigned_abs(), denominator.unsigned_abs());
    let bits = |x: u128| 128 - x.leading_zeros() as i32;
    // Desloca para o quociente ter 56 ou 57 bits: 53 do resultado, mais os de arredondamento.
    let shift = 56 - (bits(n) - bits(d));
    let (scaled_n, scaled_d) = if shift >= 0 { (n << shift, d) } else { (n, d << -shift) };
    let quotient = scaled_n / scaled_d;
    let sticky = scaled_n % scaled_d != 0;
    let extra = bits(quotient) - 53;
    let mut mantissa = quotient >> extra;
    let rest = quotient & ((1u128 << extra) - 1);
    let half = 1u128 << (extra - 1);
    if rest > half || (rest == half && (sticky || mantissa & 1 == 1)) {
        mantissa += 1;
    }
    let value = mantissa as f64 * 2f64.powi(extra - shift);
    if negative { -value } else { value }
}

/// `int(round(value))` do Python, ou `None` se o resultado não couber em 64 bits.
pub fn round_to_i64(value: f64) -> Option<i64> {
    const LIMIT: f64 = 9_223_372_036_854_775_808.0; // 2^63
    let rounded = round_half_even(value);
    (-LIMIT..LIMIT).contains(&rounded).then_some(rounded as i64)
}

/// Converte flags como `true`/`false`/`1`/`0`; o resto vira `None`.
pub fn to_bool(value: &Value) -> Option<bool> {
    match value {
        Value::Bool(b) => Some(*b),
        Value::Number(n) => n.as_f64().map(|v| v != 0.0),
        Value::String(s) => {
            let text = py_strip(s).to_lowercase();
            if TRUE_STRINGS.contains(&text.as_str()) {
                Some(true)
            } else if FALSE_STRINGS.contains(&text.as_str()) {
                Some(false)
            } else {
                None
            }
        }
        _ => None,
    }
}

/// Converte para texto sem espaços nas pontas; vazio vira `None`.
pub fn to_str(value: &Value) -> Option<String> {
    match value {
        Value::String(s) => Some(py_strip(s)).filter(|t| !t.is_empty()).map(str::to_owned),
        Value::Number(n) => Some(crate::pyjson::python_number(n)),
        Value::Bool(true) => Some("True".to_owned()),
        Value::Bool(false) => Some("False".to_owned()),
        _ => None,
    }
}

/// Data e hora de início da sessão, nos formatos conhecidos ou em ISO 8601.
pub fn parse_datetime(value: &Value) -> Option<NaiveDateTime> {
    let text = to_str(value)?;
    ANALYZER_DATETIME_FORMATS
        .iter()
        .find_map(|fmt| NaiveDateTime::parse_from_str(&text, fmt).ok())
        .or_else(|| parse_iso_datetime(&text))
}

/// O que o `datetime.fromisoformat` aceita nos casos práticos (sem fuso horário).
fn parse_iso_datetime(text: &str) -> Option<NaiveDateTime> {
    ["%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%d %H:%M:%S%.f", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]
        .iter()
        .find_map(|fmt| NaiveDateTime::parse_from_str(text, fmt).ok())
        .or_else(|| {
            NaiveDate::parse_from_str(text, "%Y-%m-%d").ok().and_then(|d| d.and_hms_opt(0, 0, 0))
        })
}

/// Converte `"HH:MM:SS"` (ou `"MM:SS"`) em segundos. Horas acima de 24 são aceitas.
pub fn parse_duration(text: &str) -> Option<i64> {
    let text = py_strip(text);
    let parts: Vec<&str> = text.split(':').map(py_strip).collect();
    if !(2..=3).contains(&parts.len())
        || !parts.iter().all(|p| !p.is_empty() && p.bytes().all(|b| b.is_ascii_digit()))
    {
        return None;
    }
    let mut numbers: Vec<i64> = parts.iter().map(|p| p.parse().ok()).collect::<Option<_>>()?;
    if numbers.len() == 2 {
        numbers.insert(0, 0);
    }
    let (hours, minutes, seconds) = (numbers[0], numbers[1], numbers[2]);
    if minutes >= 60 || seconds >= 60 {
        return None;
    }
    Some(hours * 3600 + minutes * 60 + seconds)
}

const SUFFIX_MULTIPLIERS: [(&str, f64); 3] = [("kkk", 1e9), ("kk", 1e6), ("k", 1e3)];

/// Número digitado pelo usuário, no formato ativo e na notação do jogo.
///
/// pt-BR: `"1.000.000"`, `"12,5"`; en-US: `"1,000,000"`, `"12.5"`. Em ambos: `"800k"`,
/// `"1,2kk"`, `"1.5kk"`, `"2kkk"`. Texto vazio ou inválido → `None`.
pub fn parse_user_number(text: &str, fmt: NumberFormat) -> Option<f64> {
    let mut cleaned = py_strip(text).to_lowercase().replace(' ', "");
    if cleaned.is_empty() {
        return None;
    }
    let mut multiplier = 1.0;
    for (suffix, factor) in SUFFIX_MULTIPLIERS {
        if let Some(rest) = cleaned.strip_suffix(suffix) {
            cleaned = rest.to_owned();
            multiplier = factor;
            break;
        }
    }
    if is_grouped(&cleaned, fmt.thousands) {
        cleaned = cleaned.replace(fmt.thousands, "");
    } else if cleaned.matches(',').count() == 1 && !cleaned.contains('.') {
        cleaned = cleaned.replace(',', ".");
    }
    text_to_float(&cleaned).map(|n| n * multiplier)
}

/// `-?\d{1,3}(<milhar>\d{3})+`, o número inteiro com separador de milhar.
fn is_grouped(text: &str, thousands: char) -> bool {
    let text = text.strip_prefix('-').unwrap_or(text);
    let mut groups = text.split(thousands);
    let Some(first) = groups.next() else { return false };
    let digits = |s: &str| s.bytes().all(|b| b.is_ascii_digit());
    let mut rest = groups.peekable();
    (1..=3).contains(&first.len())
        && digits(first)
        && rest.peek().is_some()
        && rest.all(|g| g.len() == 3 && digits(g))
}

static DURATION_WORDS: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:(\d+)\s*h)?\s*(?:(\d+)\s*(?:min|m)?)?$").expect("regex válida")
});

/// Duração digitada pelo usuário, em segundos.
///
/// `"1:30"` (h:mm), `"1:30:00"`, `"90"` (minutos), `"1h30"`, `"2h"`, `"45min"`.
pub fn parse_user_duration(text: &str) -> Option<i64> {
    let cleaned = py_strip(text).to_lowercase();
    if cleaned.is_empty() {
        return None;
    }
    if cleaned.contains(':') {
        let mut parts: Vec<&str> = cleaned.split(':').collect();
        if parts.len() == 2 {
            parts.push("0");
        }
        return parse_duration(&parts.join(":"));
    }
    let captures = DURATION_WORDS.captures(&cleaned)?;
    let group = |i| captures.get(i).map(|m| m.as_str().parse::<i64>());
    let (hours, minutes) = (group(1), group(2));
    if hours.is_none() && minutes.is_none() {
        return None;
    }
    let hours = hours.transpose().ok()?.unwrap_or(0);
    let minutes = minutes.transpose().ok()?.unwrap_or(0);
    if hours > 0 && minutes >= 60 {
        return None;
    }
    Some(hours * 3600 + minutes * 60)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const BR: NumberFormat = NumberFormat::PT_BR;
    const US: NumberFormat = NumberFormat::EN_US;

    fn close(actual: Option<f64>, expected: f64) -> bool {
        actual.is_some_and(|a| (a - expected).abs() < 1e-7)
    }

    #[test]
    fn user_numbers() {
        let cases = [
            ("800000", 800_000.0), ("1.000.000", 1_000_000.0), ("12,5", 12.5), ("1.5", 1.5),
            ("800k", 800_000.0), ("800K", 800_000.0), ("1,2kk", 1_200_000.0),
            ("1.5kk", 1_500_000.0), ("2kkk", 2_000_000_000.0), (" 250 ", 250.0),
            ("-500", -500.0), ("-1.000", -1000.0),
        ];
        for (text, expected) in cases {
            assert!(close(parse_user_number(text, BR), expected), "{text}");
        }
        for text in ["", "  ", "abc", "1,2,3", "k"] {
            assert_eq!(parse_user_number(text, BR), None, "{text}");
        }
    }

    #[test]
    fn user_numbers_follow_the_format() {
        assert_eq!(parse_user_number("1.200", BR), Some(1200.0));
        assert_eq!(parse_user_number("1,200", BR), Some(1.2));
        assert_eq!(parse_user_number("1,200", US), Some(1200.0));
        assert_eq!(parse_user_number("1.200", US), Some(1.2));
        assert_eq!(parse_user_number("1,000,000", US), Some(1_000_000.0));
        assert_eq!(parse_user_number("1.5kk", US), Some(1_500_000.0));
        assert_eq!(parse_user_number("800k", US), Some(800_000.0));
    }

    #[test]
    fn user_durations() {
        let cases = [
            ("1:30", 5400), ("01:11:50", 4310), ("90", 5400), ("1h30", 5400),
            ("1h 30min", 5400), ("2h", 7200), ("45min", 2700), ("45m", 2700), ("0:45", 2700),
        ];
        for (text, expected) in cases {
            assert_eq!(parse_user_duration(text), Some(expected), "{text}");
        }
        for text in ["", "abc", "1:75", "1h90"] {
            assert_eq!(parse_user_duration(text), None, "{text}");
        }
    }

    #[test]
    fn json_values() {
        assert_eq!(to_int(&json!(5)), Some(5));
        assert_eq!(to_int(&json!(5.6)), Some(6));
        assert_eq!(to_int(&json!("42")), Some(42));
        assert_eq!(to_int(&json!(" 7.0 ")), Some(7));
        assert_eq!(to_int(&json!("abc")), None);
        assert_eq!(to_int(&json!(null)), None);
        assert_eq!(to_int(&json!(true)), None);
        assert_eq!(to_int(&json!([1])), None);
        assert_eq!(to_float(&json!("1.5")), Some(1.5));
        assert_eq!(to_float(&json!("inf")), None);
        assert_eq!(to_float(&json!({})), None);
        assert_eq!(to_bool(&json!(false)), Some(false));
        assert_eq!(to_bool(&json!("true")), Some(true));
        assert_eq!(to_bool(&json!(0)), Some(false));
        assert_eq!(to_bool(&json!(null)), None);
        assert_eq!(to_bool(&json!("maybe")), None);
        assert_eq!(to_str(&json!("  x ")).as_deref(), Some("x"));
        assert_eq!(to_str(&json!("   ")), None);
        assert_eq!(to_str(&json!(10)).as_deref(), Some("10"));
        assert_eq!(to_str(&json!({"a": 1})), None);
    }

    #[test]
    fn datetimes_and_durations() {
        let moment = NaiveDate::from_ymd_opt(2026, 9, 26).unwrap().and_hms_opt(15, 24, 20);
        assert_eq!(parse_datetime(&json!("2026-09-26 15:24:20")), moment);
        assert_eq!(parse_datetime(&json!("26/09/2026 15:24:20")), moment);
        assert_eq!(parse_datetime(&json!("ontem")), None);
        assert_eq!(parse_datetime(&json!(null)), None);
        assert_eq!(parse_duration("01:11:50"), Some(4310));
        assert_eq!(parse_duration("11:50"), Some(710));
        assert_eq!(parse_duration("25:00:00"), Some(90000));
        assert_eq!(parse_duration("01:61:00"), None);
        assert_eq!(parse_duration("1h"), None);
    }

    #[test]
    fn integer_division_like_python() {
        // Valores de referência calculados pelo Python: `total * unidade / duração`.
        let cases: [(i128, i128, i128, &str); 9] = [
            (6892825199626, 3600, 7, "3544881531236228.5"),
            (1119522, 3600, 4310, "935099.5823665893"),
            (-4032727713265456, 3600, 3601, "-4031607822203732.5"),
            (9223372036854775807, 3600, 1, "3.3204139332677193e+22"),
            (-9223372036854775808, 3600, 7, "-4.743448476096742e+21"),
            (1, 1, 3, "0.3333333333333333"),
            (2, 1, 3, "0.6666666666666666"),
            (5, 3600, 9999999, "0.001800000180000018"),
            (123456789012345678, 3600, 86399, "5144092413621042.0"),
        ];
        for (total, unit, duration, expected) in cases {
            let value = int_true_div(total * unit, duration);
            assert_eq!(crate::pyjson::python_float(value), expected, "{total}");
        }
    }

    #[test]
    fn python_float_rules() {
        assert_eq!(text_to_float("1_000"), Some(1000.0));
        assert_eq!(text_to_float("1__0"), None);
        assert_eq!(text_to_float("nan"), None);
        assert_eq!(text_to_float("1e3"), Some(1000.0));
    }
}
