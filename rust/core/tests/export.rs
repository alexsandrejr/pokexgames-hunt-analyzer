//! Porta de `tests/test_export.py` e do teste de CSV de `tests/test_settings.py`. O PDF é
//! impresso pela janela (fase 4); aqui se confere o HTML de onde ele sai.

mod common;

use std::collections::HashMap;
use std::path::Path;

use calamine::{Data, Reader, Xlsx, open_workbook};
use chrono::NaiveDate;
use common::{sample_hunt_path, sample_text};
use pxg_core::Database;
use pxg_core::export::documents::{comparison_table, entity_document, hunts_document, report_document};
use pxg_core::export::{ExportDocument, ExportFormat, csv_bytes, document_html, export_document, suggested_filename};
use pxg_core::format::NumberFormat;
use pxg_core::hunts::model::HuntSummary;
use pxg_core::hunts::service::HuntService;
use pxg_core::hunts::statistics::{EntityKind, StatisticsService};
use serde_json::{Value, json};

const BR: NumberFormat = NumberFormat::PT_BR;

struct Fixture {
    database: Database,
    hunts: Vec<HuntSummary>,
    dir: tempfile::TempDir,
}

impl Fixture {
    fn new() -> Self {
        let database = Database::in_memory().unwrap();
        let service = HuntService::new(&database);
        service.import_file(&sample_hunt_path(), false, None).unwrap();
        let second = sample_text(&[("Session ID", json!(1081)), ("Start", json!("2026-09-27 10:00:00")),
            ("Duration seconds", json!(90061)), ("Profit", json!(-5000))]);
        service.import_text(&second, "", false, None).unwrap();
        let ids: Vec<i64> = service.list_hunts(None).unwrap().iter().map(|h| h.id).collect();
        let hunts = service.get_summaries(&ids).unwrap();
        Self { database, hunts, dir: tempfile::tempdir().unwrap() }
    }

    fn stats(&self) -> StatisticsService<'_> {
        StatisticsService::new(&self.database)
    }

    fn report(&self) -> ExportDocument {
        let s = self.stats();
        report_document(
            &s.overview(None).unwrap(), &s.metric_breakdown(None).unwrap(),
            &s.top(EntityKind::Drops, None, 20).unwrap(), &s.top(EntityKind::Supplies, None, 20).unwrap(),
            &s.top(EntityKind::Enemies, None, 20).unwrap(), &[],
        )
    }

    fn path(&self, name: &str) -> std::path::PathBuf {
        self.dir.path().join(name)
    }
}

/// Lê um CSV simples (sem aspas) gravado com BOM e `\r\n`.
fn read_csv(path: &Path, delimiter: char) -> Vec<Vec<String>> {
    let text = std::fs::read_to_string(path).unwrap();
    let text = text.strip_prefix('\u{feff}').unwrap();
    text.split("\r\n").filter(|l| !l.is_empty()).map(|l| l.split(delimiter).map(str::to_owned).collect()).collect()
}

#[test]
fn csv() {
    let f = Fixture::new();
    let document = hunts_document(&f.hunts, &["Player: Royal".to_owned()], "Hunts");
    let path = export_document(&document, &f.path("hunts"), ExportFormat::Csv, BR).unwrap();
    assert_eq!(path.extension().unwrap(), "csv");
    let rows = read_csv(&path, ';');
    assert_eq!(rows.len(), 3);
    let record: HashMap<&str, &str> = rows[0].iter().map(String::as_str).zip(rows[1].iter().map(String::as_str)).collect();
    assert_eq!(record["Data"], "26/09/2026 15:24:20");
    assert_eq!(record["Duração"], "01:11:50");
    assert_eq!(record["Profit"], "1119522");
    assert_eq!(record["Profit/h"], "935099"); // inteiro no JSON de origem
    assert_eq!(record["Arquivo"], "sample_hunt.json");
    let second: HashMap<&str, &str> = rows[0].iter().map(String::as_str).zip(rows[2].iter().map(String::as_str)).collect();
    assert_eq!(second["Duração"], "25:01:01");
}

#[test]
fn csv_decimal_comma_and_sections() {
    let f = Fixture::new();
    let path = export_document(&f.report(), &f.path("r.csv"), ExportFormat::Csv, BR).unwrap();
    let text = std::fs::read_to_string(path).unwrap().replace("\r\n", "\n");
    assert!(text.starts_with("\u{feff}Resumo\n"));
    assert!(text.contains("\n\nMétricas\n"));
    assert!(text.contains("\n\nInimigos\n"));
    assert!(regex::Regex::new(r"Profit;\d+;\d+(,\d+)?;").unwrap().is_match(&text)); // decimais com vírgula
}

#[test]
fn csv_follows_the_number_format() {
    let f = Fixture::new();
    let document = hunts_document(&f.hunts[..1], &[], "Hunts");
    let pt = String::from_utf8(csv_bytes(&document, BR)).unwrap();
    let en = String::from_utf8(csv_bytes(&document, NumberFormat::EN_US)).unwrap();
    let rows = |text: &str, d: char| -> Vec<Vec<String>> {
        text.trim_start_matches('\u{feff}').split("\r\n").filter(|l| !l.is_empty()).map(|l| l.split(d).map(str::to_owned).collect()).collect()
    };
    let (pt, en) = (rows(&pt, ';'), rows(&en, ','));
    let column = pt[0].iter().position(|h| h == "Profit/h").unwrap();
    assert_eq!(pt[1][column], "935099");
    assert_eq!(en[1][column], "935099");
    assert_eq!(en[0].len(), pt[0].len());
    let kills = pt[0].iter().position(|h| h == "Kills/h").unwrap();
    assert_eq!((pt[1][kills].as_str(), en[1][kills].as_str()), ("307", "307"));
}

#[test]
fn csv_quotes_fields_like_python() {
    let mut document = hunts_document(&[], &[], "Hunts");
    document.tables[0].columns[0].header = "Data; com \"aspas\"".to_owned();
    let text = String::from_utf8(csv_bytes(&document, BR)).unwrap();
    assert!(text.starts_with("\u{feff}\"Data; com \"\"aspas\"\"\";Sessão;"));
}

#[test]
fn json() {
    let f = Fixture::new();
    let path = export_document(&hunts_document(&f.hunts, &[], "Hunts"), &f.path("h.json"), ExportFormat::Json, BR).unwrap();
    let payload: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    assert_eq!(payload["title"], json!("Hunts"));
    let row = &payload["tables"][0]["rows"][0];
    assert_eq!(row["Profit"], json!(1119522));
    assert_eq!(row["Duração (s)"], json!(4310));
    assert_eq!(row["Data"], json!("2026-09-26T15:24:20"));
    assert_eq!(payload["tables"][0]["rows"][1]["Profit"], json!(-5000));
}

#[test]
fn xlsx() {
    let f = Fixture::new();
    let mut document = f.report();
    document.tables.insert(0, hunts_document(&f.hunts, &[], "Hunts").tables.remove(0));
    let path = export_document(&document, &f.path("r.xlsx"), ExportFormat::Xlsx, BR).unwrap();
    let mut workbook: Xlsx<_> = open_workbook(&path).unwrap();
    assert_eq!(workbook.sheet_names(), ["Hunts", "Resumo", "Métricas", "Drops", "Supplies", "Inimigos"]);
    let sheet = workbook.worksheet_range("Hunts").unwrap();
    let headers: Vec<String> = sheet.rows().next().unwrap().iter().map(|c| c.to_string()).collect();
    let column = |name: &str| headers.iter().position(|h| h == name).unwrap();
    assert_eq!(sheet.get((1, column("Profit"))), Some(&Data::Float(1119522.)));
    match sheet.get((1, column("Duração"))) {
        Some(Data::DateTime(d)) => assert!((d.as_f64() - 4310. / 86400.).abs() < 1e-12), // duração real no Excel
        other => panic!("esperava uma duração, veio {other:?}"),
    }
    match sheet.get((1, 0)) {
        Some(Data::DateTime(d)) => {
            let moment = NaiveDate::from_ymd_opt(2026, 9, 26).unwrap().and_hms_opt(15, 24, 20).unwrap();
            // O Excel conta os dias a partir de 30/12/1899.
            let origin = NaiveDate::from_ymd_opt(1899, 12, 30).unwrap().and_hms_opt(0, 0, 0).unwrap();
            let serial = (moment - origin).num_seconds() as f64 / 86400.;
            assert!((d.as_f64() - serial).abs() < 1e-9);
        }
        other => panic!("esperava uma data, veio {other:?}"),
    }
    let metrics = workbook.worksheet_range("Métricas").unwrap();
    assert_eq!(metrics.get((1, 0)), Some(&Data::String("Duração".into())));
    assert!(matches!(metrics.get((1, 1)), Some(Data::DateTime(_)))); // tipo vem da linha
    assert_eq!(metrics.get((3, 7)), Some(&Data::String("/h".into()))); // coluna de texto não herda o tipo
}

#[test]
fn pdf_html() {
    let f = Fixture::new();
    let document = pxg_core::export::documents::comparison_document(&f.hunts);
    let html = document_html(&document, BR);
    assert!(html.starts_with("<html><body"));
    assert!(html.contains("<h2 style='margin-bottom: 0'>Comparação de Hunts</h2>"));
    assert!(html.contains("<td align='right'>1.119.522</td>"));
    assert!(!pxg_core::export::pdf_landscape(&document)); // 3 colunas: retrato
    assert!(export_document(&document, &f.path("c.pdf"), ExportFormat::Pdf, BR).is_err()); // a janela imprime
}

#[test]
fn comparison() {
    let f = Fixture::new();
    let table = comparison_table(&f.hunts);
    assert_eq!(table.columns[0].header, "Métrica");
    assert!(table.columns[1].header.starts_with("Hunt 1080 · 26/09/2026"));
    let display: HashMap<String, Vec<String>> = table.display_rows(BR).into_iter().map(|row| (row[0].clone(), row[1..].to_vec())).collect();
    assert_eq!(display["Duração"], ["01:11:50", "25:01:01"]);
    assert_eq!(display["Profit"], ["1.119.522", "-5.000"]);
    assert_eq!(display["Player"], ["Royalzxd", "Royalzxd"]);
}

#[test]
fn entity() {
    let f = Fixture::new();
    let report = f.stats().entity_report(EntityKind::Drops, "metal scraps", None).unwrap();
    let document = entity_document(&report, &["Player: Royal".to_owned()]);
    assert_eq!(document.title, "Drop: metal scraps");
    let summary: HashMap<String, String> = document.tables[0].display_rows(BR).into_iter().map(|r| (r[0].clone(), r[1].clone())).collect();
    assert_eq!(summary["Quantidade total"], "388");
    assert_eq!(summary["Valor total"], "776.000");
    assert_eq!(summary["Presença"], "100,0%");
    let enemy = entity_document(&f.stats().entity_report(EntityKind::Enemies, "Mecha Charizard", None).unwrap(), &[]);
    assert!(!enemy.tables[1].columns.iter().any(|c| c.header == "Valor"));
    for format in [ExportFormat::Csv, ExportFormat::Json, ExportFormat::Xlsx] {
        assert!(export_document(&document, &f.path(&format!("e.{}", format.extension())), format, BR).unwrap().exists());
    }
}

#[test]
fn empty_tables_export() {
    let f = Fixture::new();
    let document = hunts_document(&[], &[], "Hunts");
    for format in [ExportFormat::Csv, ExportFormat::Json, ExportFormat::Xlsx] {
        assert!(export_document(&document, &f.path(&format!("v.{}", format.extension())), format, BR).unwrap().exists());
    }
    assert!(document_html(&document, BR).contains("Sem registros."));
}

#[test]
fn write_error_is_reported() {
    let f = Fixture::new();
    let blocker = f.path("arquivo");
    std::fs::write(&blocker, "x").unwrap();
    let result = export_document(&hunts_document(&f.hunts, &[], "Hunts"), &blocker.join("sub").join("h.csv"), ExportFormat::Csv, BR);
    assert!(matches!(result, Err(pxg_core::Error::User(_))));
}

#[test]
fn suggested_filenames() {
    let moment = NaiveDate::from_ymd_opt(2026, 9, 26).unwrap().and_hms_opt(15, 30, 0);
    assert_eq!(suggested_filename("Relatório de Hunts", ExportFormat::Xlsx, moment), "relatório_de_hunts_2026-09-26_15-30.xlsx");
    assert_eq!(suggested_filename("Drop: nightmare ore", ExportFormat::Csv, moment), "drop_nightmare_ore_2026-09-26_15-30.csv");
}
