//! Conversão do TSV do Analyzer (texto separado por tabulações) para o documento JSON
//! (equivale a `app/services/tsv_importer.py`).
//!
//! O Analyzer também exporta a sessão como tabelas em texto, uma por seção, separadas por uma
//! linha em branco: título, cabeçalho e linhas. Títulos, cabeçalhos e campos em português são
//! traduzidos para as chaves do JSON (`Saques` → `Drops`, `Contagem` → `Count`...); nomes já em
//! inglês passam direto. O resultado tem a mesma estrutura do JSON e segue pelo mesmo leitor.

use serde_json::{Map, Number, Value};

use crate::parse::to_bool;
use crate::text::{py_lstrip, py_strip};

pub const FIELD_COLUMN: &str = "Field";
pub const VALUE_COLUMN: &str = "Value";

fn section_name(title: &str) -> &str {
    match title {
        "Sessão" => "Session",
        "Experiência" => "Experience",
        "Saques" => "Drops",
        "Suprimentos" => "Supplies",
        "Inimigos Derrotados" => "Enemies Defeated",
        "Dano" => "Damage",
        other => other,
    }
}

fn column_name(name: &str) -> &str {
    match name {
        "Campo" => FIELD_COLUMN,
        "Valor" => VALUE_COLUMN,
        "Jogador" => "Player",
        "Item" => "Item",
        "Contagem" => "Count",
        "Preço unitário" => "Unit price",
        "Preço total" => "Total price",
        "Ignoradas" | "Ignorado" => "Ignored",
        "Inimigo" => "Enemy",
        "Raro" => "Rare",
        "Elemento" => "Element",
        "Experiência" => "Experience",
        "Dano recebido" => "Damage taken",
        "Dano causado" => "Damage dealt",
        other => other,
    }
}

fn session_field_name(name: &str) -> &str {
    match name {
        "Tipo de sessão" => "Session type",
        "ID da sessão" => "Session ID",
        "Status" => "Status",
        "Começar" | "Início" => "Start",
        "Duração" => "Duration",
        "Duração em segundos" => "Duration seconds",
        "Tempo pausado em segundos" => "Paused seconds",
        "Experiência" => "Experience",
        "Experiência por hora" => "Experience per hour",
        "Tempo até o próximo nível" => "Time to next level",
        "Tempo em segundos até o próximo nível" => "Time to next level seconds",
        "Ganho bruto" => "Raw gains",
        "Ganho bruto por hora" => "Raw gains per hour",
        "Suprimentos" => "Supplies",
        "Suprimentos por hora" => "Supplies per hour",
        "Lucro" => "Profit",
        "Lucro por hora" => "Profit per hour",
        "Eliminações" => "Kills",
        "Eliminações por hora" => "Kills per hour",
        "Raros derrotados" => "Rare kills",
        "Raros derrotados por hora" => "Rare kills per hour",
        "Dano recebido" => "Damage taken",
        "Dano recebido por segundo" => "Damage taken per second",
        "Dano causado" => "Damage dealt",
        "Dano causado por segundo" => "Damage dealt per second",
        other => other,
    }
}

/// Colunas "Sim"/"Não" que viram true/false no documento.
const BOOLEAN_COLUMNS: [&str; 2] = ["Rare", "Ignored"];

/// O texto não tem nenhuma seção reconhecível do TSV do Analyzer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TsvFormatError(pub String);

/// TSV: tem tabulações e não começa como JSON (`{` ou `[`).
pub fn looks_like_tsv(text: &str) -> bool {
    let stripped = py_lstrip(text);
    stripped.contains('\t') && !stripped.starts_with(['{', '['])
}

/// Converte o TSV no objeto equivalente ao JSON do Analyzer.
///
/// Seções com cabeçalho `Campo`/`Valor` viram objetos; as demais, listas de objetos (uma por
/// linha). Células ausentes no fim da linha viram `null`.
pub fn tsv_to_document(text: &str) -> Result<Map<String, Value>, TsvFormatError> {
    let mut document = Map::new();
    for block in blocks(text) {
        if block.len() < 2 || block[0].contains('\t') {
            continue; // sem título ou sem cabeçalho
        }
        let section = section_name(py_strip(block[0])).to_owned();
        let header: Vec<String> = cells(block[1]).into_iter().map(|n| column_name(&n).to_owned()).collect();
        let rows = &block[2..];
        let value = if header.len() >= 2 && header[0] == FIELD_COLUMN && header[1] == VALUE_COLUMN {
            Value::Object(field_values(rows, &section))
        } else {
            Value::Array(rows.iter().map(|row| Value::Object(row_object(&header, row))).collect())
        };
        document.insert(section, value);
    }
    if document.is_empty() {
        return Err(TsvFormatError(
            "Nenhuma seção (título + cabeçalho) foi encontrada no texto.".to_owned(),
        ));
    }
    Ok(document)
}

/// Grupos de linhas separados por linhas em branco (como o `splitlines` do Python).
fn blocks(text: &str) -> Vec<Vec<&str>> {
    let mut blocks = Vec::new();
    let mut current = Vec::new();
    for line in python_lines(text).into_iter().chain(std::iter::once("")) {
        if !py_strip(line).is_empty() {
            current.push(line);
        } else if !current.is_empty() {
            blocks.push(std::mem::take(&mut current));
        }
    }
    blocks
}

/// `str.splitlines()`: separa em `\n`, `\r\n`, `\r` e nos demais fins de linha do Unicode.
fn python_lines(text: &str) -> Vec<&str> {
    let mut lines = Vec::new();
    let mut start = 0;
    let mut chars = text.char_indices().peekable();
    while let Some((index, ch)) = chars.next() {
        let breaks = matches!(
            ch,
            '\n' | '\r' | '\u{0b}' | '\u{0c}' | '\u{1c}' | '\u{1d}' | '\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}'
        );
        if breaks {
            lines.push(&text[start..index]);
            let mut end = index + ch.len_utf8();
            if ch == '\r' && chars.peek().is_some_and(|(_, next)| *next == '\n') {
                chars.next();
                end += 1;
            }
            start = end;
        }
    }
    if start < text.len() {
        lines.push(&text[start..]);
    }
    lines
}

fn cells(line: &str) -> Vec<String> {
    line.split('\t').map(|cell| py_strip(cell).to_owned()).collect()
}

fn field_values(rows: &[&str], section: &str) -> Map<String, Value> {
    let mut values = Map::new();
    for row in rows {
        let mut row_cells = cells(row);
        row_cells.push(String::new());
        let (field, value) = (&row_cells[0], &row_cells[1]);
        if !field.is_empty() {
            let name = if section == "Session" { session_field_name(field) } else { field };
            values.insert(name.to_owned(), convert(value));
        }
    }
    values
}

fn row_object(header: &[String], row: &str) -> Map<String, Value> {
    let mut row_cells = cells(row);
    if row_cells.len() < header.len() {
        row_cells.resize(header.len(), String::new());
    }
    header
        .iter()
        .zip(row_cells)
        .map(|(column, cell)| {
            let value = if BOOLEAN_COLUMNS.contains(&column.as_str()) {
                to_bool(&Value::String(cell)).map_or(Value::Null, Value::Bool)
            } else {
                convert(&cell)
            };
            (column.clone(), value)
        })
        .collect()
}

fn ascii_digits(text: &str) -> bool {
    !text.is_empty() && text.bytes().all(|b| b.is_ascii_digit())
}

/// Números viram inteiro ou número com casas, vazio vira `null`; o resto fica como texto.
fn convert(value: &str) -> Value {
    if value.is_empty() {
        return Value::Null;
    }
    let unsigned = value.strip_prefix('-').unwrap_or(value);
    if ascii_digits(unsigned) {
        // `int()` do Python: sem limite de tamanho, sem zeros à esquerda e sem "-0".
        let digits = unsigned.trim_start_matches('0');
        let text = match (value.starts_with('-'), digits.is_empty()) {
            (_, true) => "0".to_owned(),
            (true, false) => format!("-{digits}"),
            (false, false) => digits.to_owned(),
        };
        return serde_json::from_str::<Number>(&text).map_or(Value::String(value.to_owned()), Value::Number);
    }
    if let Some((whole, fraction)) = unsigned.split_once('.') {
        if ascii_digits(whole) && ascii_digits(fraction) {
            if let Some(number) = value.parse::<f64>().ok().and_then(Number::from_f64) {
                return Value::Number(number);
            }
        }
    }
    Value::String(value.to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pyjson::dumps_canonical;

    #[test]
    fn detects_tsv() {
        assert!(looks_like_tsv("Sessão\nCampo\tValor"));
        assert!(!looks_like_tsv("  {\"a\":\t1}"));
        assert!(!looks_like_tsv("sem tabulação"));
    }

    #[test]
    fn converts_sections_and_values() {
        let text = "Sessão\r\nCampo\tValor\r\nID da sessão\t198\r\nInício\t2026-09-26 15:24:20\r\n\
            Lucro por hora\t935099.58\r\nVazio\t\r\n\r\nSaques\r\nJogador\tItem\tContagem\tIgnoradas\r\n\
            Avg\tpot of lava\t368\tNão\r\nAvg\t007 item\t-0\r\n";
        let document = tsv_to_document(text).unwrap();
        assert_eq!(
            dumps_canonical(&Value::Object(document)),
            r#"{"Drops":[{"Count":368,"Ignored":false,"Item":"pot of lava","Player":"Avg"},{"Count":0,"Ignored":null,"Item":"007 item","Player":"Avg"}],"Session":{"Profit per hour":935099.58,"Session ID":198,"Start":"2026-09-26 15:24:20","Vazio":null}}"#
        );
    }

    #[test]
    fn text_without_sections_is_an_error() {
        assert!(tsv_to_document("a\tb\nc\td").is_err());
    }
}
