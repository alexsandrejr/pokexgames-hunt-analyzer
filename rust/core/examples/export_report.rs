//! Os mesmos documentos de `rust/tools/export_report.py`, gravados numa pasta.
//!
//! ```text
//! cargo run -q -p pxg-core --example export_report -- <cópia.db> <pasta>
//! ```

use std::path::Path;

use chrono::NaiveDate;
use pxg_core::Database;
use pxg_core::export::documents::{comparison_document, entity_document, hunts_document, report_document};
use pxg_core::export::{ExportDocument, ExportFormat, document_html, export_document};
use pxg_core::format::NumberFormat;
use pxg_core::hunts::filters::{HuntFilter, Metric, MetricCondition, Operator};
use pxg_core::hunts::service::HuntService;
use pxg_core::hunts::statistics::{EntityKind, StatisticsService};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let database = Database::open(Path::new(&args[0]))?;
    let folder = Path::new(&args[1]);
    std::fs::create_dir_all(folder)?;
    let (hunts, stats) = (HuntService::new(&database), StatisticsService::new(&database));
    let br = NumberFormat::PT_BR;
    let filtered = HuntFilter {
        metrics: vec![MetricCondition { metric: Metric::Duration, operator: Operator::Ge, value: 600. }],
        ..Default::default()
    };
    let description = filtered.describe(br);
    let ids: Vec<i64> = hunts.list_hunts(None)?.iter().map(|h| h.id).collect();
    let mut docs: Vec<(String, ExportDocument)> = vec![
        ("sessoes".into(), hunts_document(&hunts.list_hunts(None)?, &[], "Hunts")),
        ("sessoes_filtradas".into(), hunts_document(&hunts.list_hunts(Some(&filtered))?, &description, "Rifts")),
        ("comparacao".into(), comparison_document(&hunts.get_summaries(&ids[..ids.len().min(3)])?)),
        ("relatorio".into(), report_document(
            &stats.overview(None)?, &stats.metric_breakdown(None)?, &stats.top(EntityKind::Drops, None, 20)?,
            &stats.top(EntityKind::Supplies, None, 20)?, &stats.top(EntityKind::Enemies, None, 20)?, &description,
        )),
    ];
    for (kind, key) in [(EntityKind::Drops, "drops"), (EntityKind::Supplies, "supplies"), (EntityKind::Enemies, "enemies")] {
        if let Some(top) = stats.top(kind, None, 1)?.first() {
            docs.push((format!("item_{key}"), entity_document(&stats.entity_report(kind, &top.name, None)?, &[])));
        }
    }
    let moment = NaiveDate::from_ymd_opt(2026, 1, 1).unwrap().and_hms_opt(12, 0, 0).unwrap();
    for (name, document) in &mut docs {
        document.generated_at = moment;
        for fmt in [NumberFormat::PT_BR, NumberFormat::EN_US] {
            export_document(document, &folder.join(format!("{name}_{}.csv", fmt.name)), ExportFormat::Csv, fmt)?;
            std::fs::write(folder.join(format!("{name}_{}.html", fmt.name)), document_html(document, fmt))?;
        }
        export_document(document, &folder.join(format!("{name}.json")), ExportFormat::Json, br)?;
        export_document(document, &folder.join(format!("{name}.xlsx")), ExportFormat::Xlsx, br)?;
    }
    Ok(())
}
