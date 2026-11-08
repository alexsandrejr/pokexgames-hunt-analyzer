//! JSON escrito exatamente como o `json.dumps` do Python.
//!
//! O `content_hash` das sessões é o SHA-256 de
//! `json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, e a detecção
//! de duplicidade compara com os hashes que o app Python já gravou. Por isso os bytes precisam
//! ser os mesmos: números com casas como o `repr` do Python (`1.0`, `1e+16`, `1.5e-05`),
//! inteiros de qualquer tamanho e o mesmo escape de textos.
//!
//! Requer o recurso `arbitrary_precision` do `serde_json`, que guarda o número como veio no
//! arquivo (o Python distingue `1` de `1.0` e não tem limite para inteiros).

use serde_json::{Number, Value};

/// `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
pub fn dumps_canonical(value: &Value) -> String {
    let mut out = String::new();
    write_value(&mut out, value, None, 0, true);
    out
}

/// `json.dumps(value, ensure_ascii=False, indent=indent)`, na ordem original das chaves.
pub fn dumps_pretty(value: &Value, indent: usize) -> String {
    let mut out = String::new();
    write_value(&mut out, value, Some(indent), 0, false);
    out
}

fn write_value(out: &mut String, value: &Value, indent: Option<usize>, level: usize, sort: bool) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Number(number) => out.push_str(&python_number(number)),
        Value::String(text) => write_string(out, text),
        Value::Array(items) => {
            if items.is_empty() {
                out.push_str("[]");
                return;
            }
            out.push('[');
            for (index, item) in items.iter().enumerate() {
                separator(out, index, indent, level + 1);
                write_value(out, item, indent, level + 1, sort);
            }
            close(out, indent, level, ']');
        }
        Value::Object(map) => {
            if map.is_empty() {
                out.push_str("{}");
                return;
            }
            let mut entries: Vec<(&String, &Value)> = map.iter().collect();
            if sort {
                // A ordem dos bytes em UTF-8 é a ordem dos pontos de código, como no Python.
                entries.sort_by(|a, b| a.0.cmp(b.0));
            }
            out.push('{');
            for (index, (key, item)) in entries.into_iter().enumerate() {
                separator(out, index, indent, level + 1);
                write_string(out, key);
                out.push(':');
                if indent.is_some() {
                    out.push(' ');
                }
                write_value(out, item, indent, level + 1, sort);
            }
            close(out, indent, level, '}');
        }
    }
}

fn separator(out: &mut String, index: usize, indent: Option<usize>, level: usize) {
    if index > 0 {
        out.push(',');
    }
    if let Some(width) = indent {
        out.push('\n');
        out.push_str(&" ".repeat(width * level));
    }
}

fn close(out: &mut String, indent: Option<usize>, level: usize, bracket: char) {
    if let Some(width) = indent {
        out.push('\n');
        out.push_str(&" ".repeat(width * level));
    }
    out.push(bracket);
}

/// Escape do `json.dumps(..., ensure_ascii=False)`.
fn write_string(out: &mut String, text: &str) {
    out.push('"');
    for ch in text.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}

/// Número como o Python o escreve depois de ler o JSON: `int` ou `float`.
pub fn python_number(number: &Number) -> String {
    let text = number.to_string();
    if text.contains(['.', 'e', 'E']) {
        let value: f64 = text.parse().unwrap_or(f64::NAN);
        return python_float(value);
    }
    // Inteiro: o Python o guarda sem limite e escreve sem zeros à esquerda nem "-0".
    let (negative, digits) = match text.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, text.as_str()),
    };
    let digits = digits.trim_start_matches('0');
    match (negative, digits.is_empty()) {
        (_, true) => "0".to_owned(),
        (true, false) => format!("-{digits}"),
        (false, false) => digits.to_owned(),
    }
}

/// `repr(float)` do Python, e `Infinity`/`NaN` como o `json.dumps`.
pub fn python_float(value: f64) -> String {
    if value.is_nan() {
        return "NaN".to_owned();
    }
    if value.is_infinite() {
        return if value > 0.0 { "Infinity" } else { "-Infinity" }.to_owned();
    }
    if value == 0.0 {
        return if value.is_sign_negative() { "-0.0" } else { "0.0" }.to_owned();
    }
    // `{:e}` dá a menor quantidade de dígitos que volta ao mesmo número. Quando há duas opções
    // com essa quantidade (`…914.2` e `…914.3` para `…914.25`), o Python escolhe a mais próxima
    // do valor exato, com empate para o par; por isso os dígitos vêm do arredondamento exato.
    let shortest = format!("{value:e}");
    let digit_count = shortest.split_once('e').expect("formato científico").0.chars().filter(char::is_ascii_digit).count();
    let exact = format!("{value:.*e}", digit_count - 1);
    let scientific = if exact.parse::<f64>() == Ok(value) { exact } else { shortest };
    let (mantissa, exponent) = scientific.split_once('e').expect("formato científico");
    let exponent: i32 = exponent.parse().expect("expoente");
    let (sign, mantissa) = match mantissa.strip_prefix('-') {
        Some(rest) => ("-", rest),
        None => ("", mantissa),
    };
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    if !(-4..16).contains(&exponent) {
        let (first, rest) = digits.split_at(1);
        let fraction = if rest.is_empty() { String::new() } else { format!(".{rest}") };
        let exp_sign = if exponent < 0 { '-' } else { '+' };
        return format!("{sign}{first}{fraction}e{exp_sign}{:02}", exponent.abs());
    }
    if exponent < 0 {
        let zeros = "0".repeat((-exponent - 1) as usize);
        return format!("{sign}0.{zeros}{digits}");
    }
    let point = exponent as usize + 1;
    if digits.len() <= point {
        format!("{sign}{digits}{}.0", "0".repeat(point - digits.len()))
    } else {
        format!("{sign}{}.{}", &digits[..point], &digits[point..])
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    #[allow(clippy::excessive_precision)] // os valores de empate são exatos de propósito
    fn floats_like_python_repr() {
        let cases = [
            (1.0, "1.0"), (0.1, "0.1"), (1.5, "1.5"), (-2.5, "-2.5"), (1e16, "1e+16"),
            (1e15, "1000000000000000.0"), (123456789012345680.0, "1.2345678901234568e+17"),
            (0.0001, "0.0001"), (0.00001, "1e-05"), (1.5e-5, "1.5e-05"), (1e100, "1e+100"),
            (935099.58, "935099.58"), (307.4, "307.4"), (-0.0, "-0.0"), (0.0, "0.0"),
            (2.0 / 3.0, "0.6666666666666666"), (1e-320, "1e-320"),
            // Duas opções igualmente curtas: o Python fica com a mais próxima, empate para o par.
            (-1692015283119914.25, "-1692015283119914.2"), (280366018351980.125, "280366018351980.12"),
        ];
        for (value, expected) in cases {
            assert_eq!(python_float(value), expected, "{value:e}");
        }
    }

    #[test]
    fn numbers_keep_int_and_float_apart() {
        let data: Value = serde_json::from_str(
            r#"[1, 1.0, -0, 100000000000000000000000, 1E2, 2.50, 1e400]"#,
        )
        .unwrap();
        assert_eq!(dumps_canonical(&data), "[1,1.0,0,100000000000000000000000,100.0,2.5,Infinity]");
    }

    #[test]
    fn canonical_sorts_keys_and_escapes_like_python() {
        let data = json!({"b": "ç\"\\\n\u{1f}é", "a": [true, null, {"z": 1, "Z": 2}], "": {}});
        assert_eq!(
            dumps_canonical(&data),
            r#"{"":{},"a":[true,null,{"Z":2,"z":1}],"b":"ç\"\\\n\u001fé"}"#
        );
    }

    #[test]
    fn pretty_like_python_indent() {
        let data = json!({"Session": {"Kills": 1, "Lista": []}, "Drops": [1, 2.5]});
        let expected = "{\n  \"Session\": {\n    \"Kills\": 1,\n    \"Lista\": []\n  },\n  \
            \"Drops\": [\n    1,\n    2.5\n  ]\n}";
        assert_eq!(dumps_pretty(&data, 2), expected);
    }
}
