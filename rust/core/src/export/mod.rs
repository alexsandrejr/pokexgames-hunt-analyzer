//! Exportação de tabelas para CSV, Excel (.xlsx), JSON e o HTML do PDF (equivale a
//! `app/services/export_service.py`).
//!
//! Um [`ExportDocument`] reúne uma ou mais [`ExportTable`]. Os valores das linhas são **brutos**
//! (números, datas, segundos); cada coluna informa seu [`ValueKind`], que decide a formatação:
//!
//! * CSV: separador e decimal do formato numérico — pt-BR: `;` e vírgula (abre direto no Excel
//!   em português); en-US: `,` e ponto;
//! * Excel: números com formatação de milhar, datas e durações `[h]:mm:ss`;
//! * PDF: valores formatados como na interface. No Python, o Qt desenha o PDF a partir de
//!   [`document_html`]; no Tauri, o WebView imprime o mesmo HTML (fase 4);
//! * JSON: valores brutos (durações em segundos, datas em ISO 8601).

pub mod documents;

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use chrono::{Local, NaiveDateTime, Timelike};
use regex::Regex;
use serde_json::{Map, Number, Value as Json, json};

use crate::error::{Error, Result};
use crate::format::{
    NumberFormat, PLACEHOLDER, ValueKind, format_datetime, format_duration, format_duration_integer,
    format_integer, format_money,
    format_number, format_percent, round_to,
};
use crate::pyjson::{dumps_pretty, python_float};

pub const APP_NAME: &str = "PokeXGames Hunt Analyzer";
const DECIMALS: usize = 2;

/// Valor bruto de uma célula, com os tipos que o Python distingue.
#[derive(Debug, Clone, PartialEq)]
pub enum CellValue {
    Null,
    Int(i64),
    Float(f64),
    Text(String),
    DateTime(NaiveDateTime),
    Bool(bool),
}

impl From<Option<i64>> for CellValue {
    fn from(value: Option<i64>) -> Self {
        value.map_or(Self::Null, Self::Int)
    }
}

impl From<Option<f64>> for CellValue {
    fn from(value: Option<f64>) -> Self {
        value.map_or(Self::Null, Self::Float)
    }
}

impl From<Option<NaiveDateTime>> for CellValue {
    fn from(value: Option<NaiveDateTime>) -> Self {
        value.map_or(Self::Null, Self::DateTime)
    }
}

impl From<Option<String>> for CellValue {
    fn from(value: Option<String>) -> Self {
        value.map_or(Self::Null, Self::Text)
    }
}

impl From<&str> for CellValue {
    fn from(value: &str) -> Self {
        Self::Text(value.to_owned())
    }
}

impl From<i64> for CellValue {
    fn from(value: i64) -> Self {
        Self::Int(value)
    }
}

impl CellValue {
    fn number(&self) -> Option<f64> {
        match self {
            Self::Int(v) => Some(*v as f64),
            Self::Float(v) if v.is_finite() => Some(*v),
            _ => None,
        }
    }

    /// `str(value)` do Python.
    fn python_str(&self) -> String {
        match self {
            Self::Null => "None".to_owned(),
            Self::Int(v) => v.to_string(),
            Self::Float(v) => python_float(*v),
            Self::Text(t) => t.clone(),
            Self::DateTime(d) => python_isoformat(*d, ' '),
            Self::Bool(true) => "True".to_owned(),
            Self::Bool(false) => "False".to_owned(),
        }
    }
}

/// `datetime.isoformat(sep)` do Python: microssegundos só quando existem.
fn python_isoformat(moment: NaiveDateTime, separator: char) -> String {
    let base = moment.format(&format!("%Y-%m-%d{separator}%H:%M:%S")).to_string();
    match moment.nanosecond() / 1000 {
        0 => base,
        micro => format!("{base}.{micro:06}"),
    }
}

/// Texto na tela e no PDF (equivale a `format_value` de `formatters.py`).
pub fn format_value(kind: ValueKind, value: &CellValue, fmt: NumberFormat) -> String {
    // Inteiros são formatados de forma exata, como no Python.
    match (kind, value) {
        (ValueKind::Money | ValueKind::Number, CellValue::Int(v)) => return format_integer(*v, fmt),
        (ValueKind::Duration, CellValue::Int(v)) => return format_duration_integer(*v),
        _ => {}
    }
    match kind {
        ValueKind::Money => format_money(value.number(), fmt),
        ValueKind::Number => format_number(value.number(), 0, fmt),
        ValueKind::Duration => format_duration(value.number()),
        ValueKind::Datetime => match value {
            CellValue::DateTime(d) => format_datetime(Some(*d)),
            other => format_text(other),
        },
        ValueKind::Percent => format_percent(value.number(), fmt),
        ValueKind::Text => format_text(value),
    }
}

fn format_text(value: &CellValue) -> String {
    match value {
        CellValue::Null => PLACEHOLDER.to_owned(),
        CellValue::Text(t) if t.is_empty() => PLACEHOLDER.to_owned(),
        other => other.python_str(),
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ExportFormat {
    Csv,
    Xlsx,
    Pdf,
    Json,
}

impl ExportFormat {
    pub const ALL: [Self; 4] = [Self::Csv, Self::Xlsx, Self::Pdf, Self::Json];

    pub fn label(self) -> &'static str {
        match self {
            Self::Csv => "CSV",
            Self::Xlsx => "Excel",
            Self::Pdf => "PDF",
            Self::Json => "JSON",
        }
    }

    pub fn extension(self) -> &'static str {
        match self {
            Self::Csv => "csv",
            Self::Xlsx => "xlsx",
            Self::Pdf => "pdf",
            Self::Json => "json",
        }
    }

    pub fn description(self) -> &'static str {
        match self {
            Self::Csv => "CSV",
            Self::Xlsx => "Planilha do Excel",
            Self::Pdf => "Documento PDF",
            Self::Json => "JSON",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ExportColumn {
    pub header: String,
    /// `None`: o tipo vem da linha (`ExportTable::row_kinds`), em tabelas transpostas.
    pub kind: Option<ValueKind>,
}

impl ExportColumn {
    pub fn new(header: &str, kind: Option<ValueKind>) -> Self {
        Self { header: header.to_owned(), kind }
    }

    pub fn text(header: &str) -> Self {
        Self::new(header, Some(ValueKind::Text))
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ExportTable {
    pub title: String,
    pub columns: Vec<ExportColumn>,
    pub rows: Vec<Vec<CellValue>>,
    /// Tabelas transpostas (ex.: comparação): tipo de cada linha, nas colunas sem tipo.
    pub row_kinds: Option<Vec<ValueKind>>,
}

impl ExportTable {
    pub fn cell_kind(&self, row: usize, column: usize) -> ValueKind {
        match self.columns[column].kind {
            Some(kind) => kind,
            None => self.row_kinds.as_ref().map_or(ValueKind::Text, |kinds| kinds[row]),
        }
    }

    pub fn display_rows(&self, fmt: NumberFormat) -> Vec<Vec<String>> {
        self.rows
            .iter()
            .enumerate()
            .map(|(r, row)| row.iter().enumerate().map(|(c, v)| format_value(self.cell_kind(r, c), v, fmt)).collect())
            .collect()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ExportDocument {
    pub title: String,
    pub tables: Vec<ExportTable>,
    pub subtitle: String,
    pub generated_at: NaiveDateTime,
}

impl ExportDocument {
    pub fn new(title: &str, tables: Vec<ExportTable>, subtitle: String) -> Self {
        Self { title: title.to_owned(), tables, subtitle, generated_at: Local::now().naive_local() }
    }
}

/// Caminho com a extensão do formato, acrescentada se faltar.
pub fn export_target(path: &Path, format: ExportFormat) -> PathBuf {
    let extension = format!(".{}", format.extension());
    let has_extension = path
        .extension()
        .is_some_and(|e| format!(".{}", e.to_string_lossy().to_lowercase()) == extension);
    if has_extension {
        path.to_path_buf()
    } else {
        path.with_file_name(format!("{}{extension}", path.file_name().map(|n| n.to_string_lossy()).unwrap_or_default()))
    }
}

/// Erro de gravação com a mensagem mostrada ao usuário.
pub fn write_error(target: &Path, error: &std::io::Error) -> Error {
    if error.kind() == std::io::ErrorKind::PermissionDenied {
        Error::user(format!("Sem permissão para gravar {}. O arquivo está aberto em outro programa?", target.display()))
    } else {
        Error::user(format!("Não foi possível gravar {}: {error}", target.display()))
    }
}

/// Grava o documento; devolve o caminho gravado (com a extensão, se faltava).
///
/// O PDF não passa por aqui: a janela do aplicativo o imprime a partir de [`document_html`].
pub fn export_document(document: &ExportDocument, path: &Path, format: ExportFormat, fmt: NumberFormat) -> Result<PathBuf> {
    let target = export_target(path, format);
    let written = (|| -> std::io::Result<()> {
        if let Some(parent) = target.parent() {
            std::fs::create_dir_all(parent)?;
        }
        match format {
            ExportFormat::Csv => std::fs::write(&target, csv_bytes(document, fmt)),
            ExportFormat::Json => std::fs::write(&target, text_file(&json_text(document))),
            ExportFormat::Xlsx => write_xlsx(document, &target, fmt).map_err(std::io::Error::other),
            ExportFormat::Pdf => Err(std::io::Error::other(
                "o PDF é impresso pela janela do aplicativo a partir de document_html",
            )),
        }
    })();
    written.map(|()| target.clone()).map_err(|e| write_error(&target, &e))
}

static NON_WORD: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[^\w]+").expect("regex válida"));

/// `relatorio_de_hunts_2026-11-07_12-30.csv`.
pub fn suggested_filename(title: &str, format: ExportFormat, moment: Option<NaiveDateTime>) -> String {
    let slug = NON_WORD.replace_all(&title.to_lowercase(), "_").trim_matches('_').to_owned();
    let slug = if slug.is_empty() { "export".to_owned() } else { slug };
    let stamp = moment.unwrap_or_else(|| Local::now().naive_local()).format("%Y-%m-%d_%H-%M");
    format!("{slug}_{stamp}.{}", format.extension())
}

// ----------------------------------------------------------------------- CSV

fn csv_value(kind: ValueKind, value: &CellValue, fmt: NumberFormat) -> String {
    if *value == CellValue::Null {
        return String::new();
    }
    if kind == ValueKind::Duration {
        return match value {
            CellValue::Int(v) => format_duration_integer(*v),
            other => format_duration(other.number()),
        };
    }
    match value {
        CellValue::DateTime(d) => format_datetime(Some(*d)),
        CellValue::Bool(true) => "Sim".to_owned(),
        CellValue::Bool(false) => "Não".to_owned(),
        CellValue::Float(v) => {
            let text = format!("{:.DECIMALS$}", round_to(*v, DECIMALS));
            let text = text.trim_end_matches('0').trim_end_matches('.');
            text.replace('.', &fmt.decimal.to_string())
        }
        other => other.python_str(),
    }
}

/// Como o `csv.writer` do Python: aspas só quando o campo exige, e `\r\n` no fim da linha.
fn csv_row(fields: &[String], delimiter: char) -> String {
    if fields.len() == 1 && fields[0].is_empty() {
        return "\"\"\r\n".to_owned();
    }
    let quoted: Vec<String> = fields
        .iter()
        .map(|f| {
            if f.contains([delimiter, '"', '\r', '\n']) {
                format!("\"{}\"", f.replace('"', "\"\""))
            } else {
                f.clone()
            }
        })
        .collect();
    quoted.join(&delimiter.to_string()) + "\r\n"
}

/// O arquivo CSV com BOM (UTF-8), como o Python grava.
pub fn csv_bytes(document: &ExportDocument, fmt: NumberFormat) -> Vec<u8> {
    // Com vírgula decimal, o separador de campos precisa ser ";".
    let delimiter = if fmt.decimal == ',' { ';' } else { ',' };
    let several = document.tables.len() > 1;
    let mut out = String::from("\u{feff}");
    for (index, table) in document.tables.iter().enumerate() {
        if several {
            if index > 0 {
                out.push_str("\r\n");
            }
            out.push_str(&csv_row(std::slice::from_ref(&table.title), delimiter));
        }
        let headers: Vec<String> = table.columns.iter().map(|c| c.header.clone()).collect();
        out.push_str(&csv_row(&headers, delimiter));
        for (r, row) in table.rows.iter().enumerate() {
            let fields: Vec<String> = row.iter().enumerate().map(|(c, v)| csv_value(table.cell_kind(r, c), v, fmt)).collect();
            out.push_str(&csv_row(&fields, delimiter));
        }
    }
    out.into_bytes()
}

// ---------------------------------------------------------------------- JSON

/// Texto gravado como o `write_text` do Python: no Windows, `\n` vira `\r\n`.
fn text_file(text: &str) -> String {
    if cfg!(windows) { text.replace('\n', "\r\n") } else { text.to_owned() }
}

fn json_value(value: &CellValue) -> Json {
    match value {
        CellValue::Null => Json::Null,
        CellValue::Int(v) => json!(v),
        CellValue::Float(v) => Number::from_f64(round_to(*v, DECIMALS)).map_or(Json::Null, Json::Number),
        CellValue::Text(t) => json!(t),
        CellValue::DateTime(d) => json!(python_isoformat(*d, 'T')),
        CellValue::Bool(b) => json!(b),
    }
}

fn json_key(column: &ExportColumn) -> String {
    if column.kind == Some(ValueKind::Duration) { format!("{} (s)", column.header) } else { column.header.clone() }
}

/// O arquivo JSON, igual ao do Python (`json.dumps(..., indent=2, ensure_ascii=False)`).
pub fn json_text(document: &ExportDocument) -> String {
    let tables: Vec<Json> = document
        .tables
        .iter()
        .map(|table| {
            let rows: Vec<Json> = table
                .rows
                .iter()
                .map(|row| {
                    let mut object = Map::new();
                    for (column, value) in table.columns.iter().zip(row) {
                        object.insert(json_key(column), json_value(value));
                    }
                    Json::Object(object)
                })
                .collect();
            json!({"title": table.title, "rows": rows})
        })
        .collect();
    let payload = json!({
        "title": document.title,
        "subtitle": document.subtitle,
        "generated_at": document.generated_at.format("%Y-%m-%dT%H:%M:%S").to_string(),
        "generator": APP_NAME,
        "tables": tables,
    });
    dumps_pretty(&payload, 2)
}

// --------------------------------------------------------------------- Excel

fn xlsx_format(kind: ValueKind) -> Option<&'static str> {
    match kind {
        ValueKind::Money | ValueKind::Number => Some("#,##0"),
        ValueKind::Duration => Some("[h]:mm:ss"),
        ValueKind::Datetime => Some("dd/mm/yyyy hh:mm"),
        ValueKind::Percent => Some("0.0%"),
        ValueKind::Text => None,
    }
}

static SHEET_FORBIDDEN: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[\[\]:*?/\\]").expect("regex válida"));

fn sheet_title(title: &str, used: &mut HashSet<String>) -> String {
    let cleaned = SHEET_FORBIDDEN.replace_all(title, " ");
    let base: String = crate::text::py_strip(&cleaned).chars().take(31).collect();
    let base = if base.is_empty() { "Tabela".to_owned() } else { base };
    let (mut name, mut counter) = (base.clone(), 2);
    while used.contains(&name) {
        let suffix = format!(" ({counter})");
        name = base.chars().take(31 - suffix.chars().count()).collect::<String>() + &suffix;
        counter += 1;
    }
    used.insert(name.clone());
    name
}

fn write_xlsx(document: &ExportDocument, path: &Path, fmt: NumberFormat) -> std::result::Result<(), rust_xlsxwriter::XlsxError> {
    use rust_xlsxwriter::{DocProperties, Format, FormatAlign, FormatPattern, Workbook};

    let mut workbook = Workbook::new();
    workbook.set_properties(&DocProperties::new().set_title(&document.title).set_author(APP_NAME));
    let header = Format::new()
        .set_bold()
        .set_font_color("FFFFFF")
        .set_background_color("2A3140")
        .set_pattern(FormatPattern::Solid)
        .set_align(FormatAlign::VerticalCenter);
    let mut used = HashSet::new();
    for table in &document.tables {
        let sheet = workbook.add_worksheet();
        sheet.set_name(sheet_title(&table.title, &mut used))?;
        for (c, column) in table.columns.iter().enumerate() {
            sheet.write_string_with_format(0, c as u16, &column.header, &header)?;
        }
        let displays = table.display_rows(fmt);
        let mut widths: Vec<usize> = table.columns.iter().map(|c| c.header.chars().count()).collect();
        for (r, row) in table.rows.iter().enumerate() {
            let line = r as u32 + 1;
            for (c, value) in row.iter().enumerate() {
                let kind = table.cell_kind(r, c);
                let col = c as u16;
                widths[c] = widths[c].max(displays[r][c].chars().count());
                let format = xlsx_format(kind).map(|f| Format::new().set_num_format(f));
                let number = |v: f64| if kind == ValueKind::Duration { v / 86400.0 } else { v };
                match (value, &format) {
                    (CellValue::Null, _) => {}
                    (CellValue::Int(v), Some(f)) => { sheet.write_number_with_format(line, col, number(*v as f64), f)?; }
                    (CellValue::Int(v), None) => { sheet.write_number(line, col, number(*v as f64))?; }
                    (CellValue::Float(v), Some(f)) => { sheet.write_number_with_format(line, col, number(*v), f)?; }
                    (CellValue::Float(v), None) => { sheet.write_number(line, col, number(*v))?; }
                    (CellValue::Text(t), Some(f)) => { sheet.write_string_with_format(line, col, t, f)?; }
                    (CellValue::Text(t), None) => { sheet.write_string(line, col, t)?; }
                    (CellValue::Bool(b), Some(f)) => { sheet.write_boolean_with_format(line, col, *b, f)?; }
                    (CellValue::Bool(b), None) => { sheet.write_boolean(line, col, *b)?; }
                    (CellValue::DateTime(d), f) => {
                        let f = f.clone().unwrap_or_else(|| Format::new().set_num_format("yyyy-mm-dd h:mm:ss"));
                        sheet.write_datetime_with_format(line, col, d, &f)?;
                    }
                }
            }
        }
        for (c, width) in widths.iter().enumerate() {
            // O openpyxl grava a largura pura; o rust_xlsxwriter soma 5/7 de margem.
            sheet.set_column_width(c as u16, (*width + 3).min(50) as f64 - 5.0 / 7.0)?;
        }
        sheet.set_freeze_panes(1, 0)?;
    }
    workbook.save(path)
}

// ----------------------------------------------------------------------- PDF

fn is_numeric(kind: ValueKind) -> bool {
    matches!(kind, ValueKind::Number | ValueKind::Money | ValueKind::Duration | ValueKind::Percent)
}

/// `html.escape` do Python (com aspas).
fn escape(text: &str) -> String {
    text.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&#x27;")
}

/// HTML simples (tema claro, próprio para impressão) de onde sai o PDF.
pub fn document_html(document: &ExportDocument, fmt: NumberFormat) -> String {
    let mut parts = vec![
        "<html><body style='font-family: Segoe UI, Arial; color: #111827;'>".to_owned(),
        format!("<h2 style='margin-bottom: 0'>{}</h2>", escape(&document.title)),
        format!(
            "<p style='color: #6b7280; margin-top: 2px'>{}{}Gerado em {} · {}</p>",
            escape(&document.subtitle),
            if document.subtitle.is_empty() { "" } else { " · " },
            format_datetime(Some(document.generated_at)),
            escape(APP_NAME)
        ),
    ];
    for table in &document.tables {
        parts.push(format!("<h3 style='margin-top: 14px'>{}</h3>", escape(&table.title)));
        parts.push(
            "<table width='100%' cellspacing='0' cellpadding='4' style='border-collapse: collapse; font-size: 8pt;'>"
                .to_owned(),
        );
        parts.push("<tr style='background-color: #e5e7eb;'>".to_owned());
        for column in &table.columns {
            let align = if column.kind.is_none_or(is_numeric) { "right" } else { "left" };
            parts.push(format!("<th align='{align}'>{}</th>", escape(&column.header)));
        }
        parts.push("</tr>".to_owned());
        for (r, row) in table.display_rows(fmt).iter().enumerate() {
            let shade = if r % 2 == 1 { " style='background-color: #f5f6f8;'" } else { "" };
            parts.push(format!("<tr{shade}>"));
            for (c, text) in row.iter().enumerate() {
                let right = table.columns[c].kind.is_none() || is_numeric(table.cell_kind(r, c));
                let align = if right { "right" } else { "left" };
                parts.push(format!("<td align='{align}'>{}</td>", escape(text)));
            }
            parts.push("</tr>".to_owned());
        }
        if table.rows.is_empty() {
            parts.push(format!(
                "<tr><td colspan='{}' style='color: #6b7280;'>Sem registros.</td></tr>",
                table.columns.len()
            ));
        }
        parts.push("</table>".to_owned());
    }
    parts.push("</body></html>".to_owned());
    parts.concat()
}

/// O PDF fica em paisagem quando alguma tabela tem mais de 7 colunas.
pub fn pdf_landscape(document: &ExportDocument) -> bool {
    document.tables.iter().map(|t| t.columns.len()).max().unwrap_or(0) > 7
}
