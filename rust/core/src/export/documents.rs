//! Montagem das tabelas exportáveis e da comparação exibida na tela (equivale a
//! `app/services/export_documents.py`).

use super::{CellValue, ExportColumn, ExportDocument, ExportTable};
use crate::format::{ValueKind as K, format_datetime_short};
use crate::hunts::model::HuntSummary;
use crate::hunts::statistics::{EntityReport, MetricStats, OverviewStats, RankedEntry};

fn filter_subtitle(filter_description: &[String]) -> String {
    if filter_description.is_empty() {
        "Sem filtros (todas as Hunts)".to_owned()
    } else {
        format!("Filtros: {}", filter_description.join(" · "))
    }
}

/// Valor de uma coluna da listagem, pelo nome do atributo do Python.
fn summary_value(hunt: &HuntSummary, attribute: &str) -> CellValue {
    match attribute {
        "start_datetime" => hunt.start_datetime.into(),
        "session_id" => hunt.session_id.into(),
        "player" => hunt.player.clone().into(),
        "duration_seconds" => hunt.duration_seconds.into(),
        "kills" => hunt.kills.into(),
        "kills_per_hour" => hunt.kills_per_hour.into(),
        "profit" => hunt.profit.into(),
        "profit_per_hour" => hunt.profit_per_hour.into(),
        "supplies" => hunt.supplies.into(),
        "supplies_per_hour" => hunt.supplies_per_hour.into(),
        "raw_gains" => hunt.raw_gains.into(),
        "raw_gains_per_hour" => hunt.raw_gains_per_hour.into(),
        "experience" => hunt.experience.into(),
        "damage_dealt" => hunt.damage_dealt.into(),
        "damage_dealt_per_second" => hunt.damage_dealt_per_second.into(),
        "damage_taken" => hunt.damage_taken.into(),
        "damage_taken_per_second" => hunt.damage_taken_per_second.into(),
        "source_file" => hunt.source_file.clone().into(),
        other => panic!("atributo desconhecido: {other}"),
    }
}

/// (cabeçalho, atributo, formato) das colunas exportadas da listagem.
pub const HUNT_EXPORT_COLUMNS: [(&str, &str, K); 18] = [
    ("Data", "start_datetime", K::Datetime),
    ("Sessão", "session_id", K::Text),
    ("Player", "player", K::Text),
    ("Duração", "duration_seconds", K::Duration),
    ("Kills", "kills", K::Number),
    ("Kills/h", "kills_per_hour", K::Number),
    ("Profit", "profit", K::Money),
    ("Profit/h", "profit_per_hour", K::Money),
    ("Supplies", "supplies", K::Money),
    ("Supplies/h", "supplies_per_hour", K::Money),
    ("Raw gains", "raw_gains", K::Money),
    ("Raw gains/h", "raw_gains_per_hour", K::Money),
    ("Experience", "experience", K::Number),
    ("Damage dealt", "damage_dealt", K::Number),
    ("Damage dealt/s", "damage_dealt_per_second", K::Number),
    ("Damage taken", "damage_taken", K::Number),
    ("Damage taken/s", "damage_taken_per_second", K::Number),
    ("Arquivo", "source_file", K::Text),
];

pub fn hunts_document(hunts: &[HuntSummary], filter_description: &[String], title: &str) -> ExportDocument {
    let table = ExportTable {
        title: title.to_owned(),
        columns: HUNT_EXPORT_COLUMNS.iter().map(|(h, _, k)| ExportColumn::new(h, Some(*k))).collect(),
        rows: hunts
            .iter()
            .map(|hunt| HUNT_EXPORT_COLUMNS.iter().map(|(_, attr, _)| summary_value(hunt, attr)).collect())
            .collect(),
        row_kinds: None,
    };
    let subtitle = format!("{} {title} · {}", hunts.len(), filter_subtitle(filter_description));
    ExportDocument::new(title, vec![table], subtitle)
}

/// (rótulo, atributo, formato) das linhas da comparação. A data já identifica cada coluna.
pub const COMPARISON_ROWS: [(&str, &str, K); 14] = [
    ("Player", "player", K::Text),
    ("Duração", "duration_seconds", K::Duration),
    ("Kills", "kills", K::Number),
    ("Kills/h", "kills_per_hour", K::Number),
    ("Profit", "profit", K::Money),
    ("Profit/h", "profit_per_hour", K::Money),
    ("Supplies", "supplies", K::Money),
    ("Supplies/h", "supplies_per_hour", K::Money),
    ("Raw gains", "raw_gains", K::Money),
    ("Raw gains/h", "raw_gains_per_hour", K::Money),
    ("Damage dealt", "damage_dealt", K::Number),
    ("Damage dealt/s", "damage_dealt_per_second", K::Number),
    ("Damage taken", "damage_taken", K::Number),
    ("Damage taken/s", "damage_taken_per_second", K::Number),
];

pub fn hunt_label(hunt: &HuntSummary) -> String {
    let session = hunt.session_id.map_or_else(|| crate::format::PLACEHOLDER.to_owned(), |id| id.to_string());
    format!("Hunt {session} · {}", format_datetime_short(hunt.start_datetime))
}

/// Métricas nas linhas, sessões nas colunas (lado a lado, sem ranking).
pub fn comparison_table(hunts: &[HuntSummary]) -> ExportTable {
    let mut columns = vec![ExportColumn::text("Métrica")];
    columns.extend(hunts.iter().map(|h| ExportColumn::new(&hunt_label(h), None)));
    ExportTable {
        title: "Comparação de Hunts".to_owned(),
        columns,
        rows: COMPARISON_ROWS
            .iter()
            .map(|(label, attr, _)| {
                std::iter::once(CellValue::from(*label)).chain(hunts.iter().map(|h| summary_value(h, attr))).collect()
            })
            .collect(),
        row_kinds: Some(COMPARISON_ROWS.iter().map(|(_, _, k)| *k).collect()),
    }
}

pub fn comparison_document(hunts: &[HuntSummary]) -> ExportDocument {
    ExportDocument::new("Comparação de Hunts", vec![comparison_table(hunts)], format!("{} Hunts lado a lado", hunts.len()))
}

fn ranking(title: &str, entries: &[RankedEntry], with_value: bool) -> ExportTable {
    let mut columns = vec![ExportColumn::text("Nome"), ExportColumn::new("Quantidade", Some(K::Number))];
    if with_value {
        columns.push(ExportColumn::new("Valor total", Some(K::Money)));
    }
    columns.extend([ExportColumn::new("Hunts", Some(K::Number)), ExportColumn::new("Média por Hunt", Some(K::Number))]);
    let rows = entries
        .iter()
        .map(|e| {
            let mut row = vec![CellValue::from(e.name.as_str()), e.quantity.into()];
            if with_value {
                row.push(e.value.into());
            }
            row.extend([e.hunt_count.into(), e.average_per_hunt().into()]);
            row
        })
        .collect();
    ExportTable { title: title.to_owned(), columns, rows, row_kinds: None }
}

pub fn report_document(
    overview: &OverviewStats,
    metrics: &[MetricStats],
    drops: &[RankedEntry],
    supplies: &[RankedEntry],
    enemies: &[RankedEntry],
    filter_description: &[String],
) -> ExportDocument {
    let summary = ExportTable {
        title: "Resumo".to_owned(),
        columns: vec![ExportColumn::text("Indicador"), ExportColumn::new("Valor", None)],
        rows: vec![
            vec!["Hunts analisadas".into(), overview.hunt_count.into()],
            vec!["Primeira Hunt".into(), overview.first_start.into()],
            vec!["Última Hunt".into(), overview.last_start.into()],
            vec!["Tempo total".into(), overview.total_duration_seconds.into()],
            vec!["Profit total".into(), overview.total_profit.into()],
            vec!["Profit/h (média das Hunts)".into(), overview.average_profit_per_hour.into()],
            vec!["Profit/h (total ÷ tempo total)".into(), overview.profit_per_total_hour().into()],
        ],
        row_kinds: Some(vec![K::Number, K::Datetime, K::Datetime, K::Duration, K::Money, K::Money, K::Money]),
    };
    let metric_columns = ["Total", "Média por Hunt", "Mínimo", "Máximo", "Média das taxas", "Total ÷ tempo total"];
    let mut columns = vec![ExportColumn::text("Métrica")];
    columns.extend(metric_columns.iter().map(|h| ExportColumn::new(h, None)));
    columns.push(ExportColumn::text("Unidade da taxa"));
    let metrics_table = ExportTable {
        title: "Métricas".to_owned(),
        columns,
        rows: metrics
            .iter()
            .map(|m| {
                vec![
                    m.label.into(),
                    m.total.into(),
                    m.average.into(),
                    m.minimum.into(),
                    m.maximum.into(),
                    m.average_rate.into(),
                    m.rate_over_total_time.into(),
                    m.rate_unit.map_or("", |u| u.suffix()).into(),
                ]
            })
            .collect(),
        row_kinds: Some(metrics.iter().map(|m| m.kind).collect()),
    };
    let tables = vec![
        summary,
        metrics_table,
        ranking("Drops", drops, true),
        ranking("Supplies", supplies, true),
        ranking("Inimigos", enemies, false),
    ];
    ExportDocument::new("Relatório de Hunts", tables, filter_subtitle(filter_description))
}

pub fn entity_document(report: &EntityReport, filter_description: &[String]) -> ExportDocument {
    let has_value = report.kind.has_value();
    let mut summary_rows: Vec<(&str, CellValue, K)> = vec![
        ("Quantidade total", report.total_quantity().into(), K::Number),
        ("Hunts em que apareceu", (report.present_count() as i64).into(), K::Number),
        ("Hunts analisadas", (report.hunt_count() as i64).into(), K::Number),
        ("Presença", report.presence_ratio().into(), K::Percent),
        ("Média por Hunt (quando aparece)", report.average_per_hunt().into(), K::Number),
        ("Média por hora (quando aparece)", report.per_hour().into(), K::Number),
        ("Maior quantidade em uma Hunt", report.max_row().map(|r| r.quantity).into(), K::Number),
        ("Menor quantidade em uma Hunt", report.min_row().map(|r| r.quantity).into(), K::Number),
    ];
    if has_value {
        summary_rows.splice(1..1, [
            ("Valor total", report.total_value().into(), K::Money),
            ("Valor médio por Hunt", report.average_value_per_hunt().into(), K::Money),
        ]);
    }
    let summary = ExportTable {
        title: "Resumo".to_owned(),
        columns: vec![ExportColumn::text("Indicador"), ExportColumn::new("Valor", None)],
        row_kinds: Some(summary_rows.iter().map(|(_, _, k)| *k).collect()),
        rows: summary_rows.into_iter().map(|(label, value, _)| vec![label.into(), value]).collect(),
    };
    let mut columns = vec![
        ExportColumn::new("Data", Some(K::Datetime)),
        ExportColumn::text("Sessão"),
        ExportColumn::new("Duração", Some(K::Duration)),
        ExportColumn::new("Quantidade", Some(K::Number)),
    ];
    if has_value {
        columns.push(ExportColumn::new("Valor", Some(K::Money)));
    }
    let rows = report
        .rows
        .iter()
        .map(|r| {
            let mut row = vec![r.start_datetime.into(), r.session_id.into(), r.duration_seconds.into(), r.quantity.into()];
            if has_value {
                row.push(r.value.into());
            }
            row
        })
        .collect();
    let per_hunt = ExportTable { title: "Por Hunt".to_owned(), columns, rows, row_kinds: None };
    let title = format!("{}: {}", report.kind.label(), report.name);
    ExportDocument::new(&title, vec![summary, per_hunt], filter_subtitle(filter_description))
}
