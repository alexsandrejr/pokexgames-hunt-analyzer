"""Montagem das tabelas exportáveis (e da comparação exibida na tela)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.services.dto import HuntSummary, RankedEntry
from app.services.entity_report import EntityReport
from app.services.export_service import ExportColumn, ExportDocument, ExportTable
from app.services.statistics_service import MetricStats, OverviewStats
from app.utils.formatters import ValueKind, format_datetime_short, format_text

K = ValueKind


def _filter_subtitle(filter_description: Sequence[str]) -> str:
    return ("Filtros: " + " · ".join(filter_description)) if filter_description \
        else "Sem filtros (todas as Hunts)"


# --------------------------------------------------------------------- Hunts

HUNT_EXPORT_COLUMNS: tuple[tuple[str, str, ValueKind], ...] = (
    ("Data", "start_datetime", K.DATETIME),
    ("Sessão", "session_id", K.TEXT),
    ("Player", "player", K.TEXT),
    ("Duração", "duration_seconds", K.DURATION),
    ("Kills", "kills", K.NUMBER),
    ("Kills/h", "kills_per_hour", K.NUMBER),
    ("Profit", "profit", K.MONEY),
    ("Profit/h", "profit_per_hour", K.MONEY),
    ("Supplies", "supplies", K.MONEY),
    ("Supplies/h", "supplies_per_hour", K.MONEY),
    ("Raw gains", "raw_gains", K.MONEY),
    ("Raw gains/h", "raw_gains_per_hour", K.MONEY),
    ("Experience", "experience", K.NUMBER),
    ("Damage dealt", "damage_dealt", K.NUMBER),
    ("Damage dealt/s", "damage_dealt_per_second", K.NUMBER),
    ("Damage taken", "damage_taken", K.NUMBER),
    ("Damage taken/s", "damage_taken_per_second", K.NUMBER),
    ("Arquivo", "source_file", K.TEXT),
)


def hunts_document(hunts: Sequence[HuntSummary],
                   filter_description: Sequence[str] = (), title: str = "Hunts") -> ExportDocument:
    table = ExportTable(
        title,
        [ExportColumn(header, kind) for header, _attr, kind in HUNT_EXPORT_COLUMNS],
        [[getattr(hunt, attr) for _header, attr, _kind in HUNT_EXPORT_COLUMNS]
         for hunt in hunts],
    )
    return ExportDocument(title, [table],
                          f"{len(hunts)} {title} · {_filter_subtitle(filter_description)}")


# ---------------------------------------------------------------- Comparação

@dataclass(frozen=True)
class ComparisonRow:
    label: str
    attribute: str
    kind: ValueKind


# A data já identifica cada coluna (cabeçalho), então não se repete como linha.
COMPARISON_ROWS: tuple[ComparisonRow, ...] = (
    ComparisonRow("Player", "player", K.TEXT),
    ComparisonRow("Duração", "duration_seconds", K.DURATION),
    ComparisonRow("Kills", "kills", K.NUMBER),
    ComparisonRow("Kills/h", "kills_per_hour", K.NUMBER),
    ComparisonRow("Profit", "profit", K.MONEY),
    ComparisonRow("Profit/h", "profit_per_hour", K.MONEY),
    ComparisonRow("Supplies", "supplies", K.MONEY),
    ComparisonRow("Supplies/h", "supplies_per_hour", K.MONEY),
    ComparisonRow("Raw gains", "raw_gains", K.MONEY),
    ComparisonRow("Raw gains/h", "raw_gains_per_hour", K.MONEY),
    ComparisonRow("Damage dealt", "damage_dealt", K.NUMBER),
    ComparisonRow("Damage dealt/s", "damage_dealt_per_second", K.NUMBER),
    ComparisonRow("Damage taken", "damage_taken", K.NUMBER),
    ComparisonRow("Damage taken/s", "damage_taken_per_second", K.NUMBER),
)


def hunt_label(hunt: HuntSummary) -> str:
    return f"Hunt {format_text(hunt.session_id)} · {format_datetime_short(hunt.start_datetime)}"


def comparison_table(hunts: Sequence[HuntSummary]) -> ExportTable:
    """Métricas nas linhas, Hunts nas colunas (lado a lado, sem ranking)."""
    return ExportTable(
        "Comparação de Hunts",
        [ExportColumn("Métrica")] + [ExportColumn(hunt_label(h), None) for h in hunts],
        [[row.label] + [getattr(h, row.attribute) for h in hunts] for row in COMPARISON_ROWS],
        row_kinds=[row.kind for row in COMPARISON_ROWS],
    )


def comparison_document(hunts: Sequence[HuntSummary]) -> ExportDocument:
    return ExportDocument("Comparação de Hunts", [comparison_table(hunts)],
                          f"{len(hunts)} Hunts lado a lado")


# ---------------------------------------------------------------- Relatórios

def report_document(overview: OverviewStats, metrics: Sequence[MetricStats],
                    drops: Sequence[RankedEntry], supplies: Sequence[RankedEntry],
                    enemies: Sequence[RankedEntry],
                    filter_description: Sequence[str] = ()) -> ExportDocument:
    summary = ExportTable("Resumo", [ExportColumn("Indicador"), ExportColumn("Valor", None)], [
        ["Hunts analisadas", overview.hunt_count],
        ["Primeira Hunt", overview.first_start],
        ["Última Hunt", overview.last_start],
        ["Tempo total", overview.total_duration_seconds],
        ["Profit total", overview.total_profit],
        ["Profit/h (média das Hunts)", overview.average_profit_per_hour],
        ["Profit/h (total ÷ tempo total)", overview.profit_per_total_hour],
    ], row_kinds=[K.NUMBER, K.DATETIME, K.DATETIME, K.DURATION, K.MONEY, K.MONEY, K.MONEY])

    metric_columns = [ExportColumn("Métrica"), ExportColumn("Total", None),
                      ExportColumn("Média por Hunt", None), ExportColumn("Mínimo", None),
                      ExportColumn("Máximo", None), ExportColumn("Média das taxas", None),
                      ExportColumn("Total ÷ tempo total", None), ExportColumn("Unidade da taxa")]
    metric_rows = [[m.label, m.total, m.average, m.minimum, m.maximum, m.average_rate,
                    m.rate_over_total_time, m.rate_unit.value if m.rate_unit else ""]
                   for m in metrics]
    metrics_table = ExportTable("Métricas", metric_columns, metric_rows,
                                row_kinds=[m.kind for m in metrics])

    def ranking(title: str, entries: Sequence[RankedEntry], with_value: bool) -> ExportTable:
        columns = [ExportColumn("Nome"), ExportColumn("Quantidade", K.NUMBER)]
        if with_value:
            columns.append(ExportColumn("Valor total", K.MONEY))
        columns += [ExportColumn("Hunts", K.NUMBER), ExportColumn("Média por Hunt", K.NUMBER)]
        rows = [[e.name, e.quantity, *([e.value] if with_value else []), e.hunt_count,
                 e.average_per_hunt] for e in entries]
        return ExportTable(title, columns, rows)

    tables = [summary, metrics_table, ranking("Drops", drops, True),
              ranking("Supplies", supplies, True), ranking("Inimigos", enemies, False)]
    return ExportDocument("Relatório de Hunts", tables, _filter_subtitle(filter_description))


# ------------------------------------------------------------ Item / inimigo

def entity_document(report: EntityReport,
                    filter_description: Sequence[str] = ()) -> ExportDocument:
    has_value = report.kind.has_value
    summary_rows: list[tuple[str, object, ValueKind]] = [
        ("Quantidade total", report.total_quantity, K.NUMBER),
        ("Hunts em que apareceu", report.present_count, K.NUMBER),
        ("Hunts analisadas", report.hunt_count, K.NUMBER),
        ("Presença", report.presence_ratio, K.PERCENT),
        ("Média por Hunt (quando aparece)", report.average_per_hunt, K.NUMBER),
        ("Média por hora (quando aparece)", report.per_hour, K.NUMBER),
        ("Maior quantidade em uma Hunt", report.max_row.quantity if report.max_row else None,
         K.NUMBER),
        ("Menor quantidade em uma Hunt", report.min_row.quantity if report.min_row else None,
         K.NUMBER),
    ]
    if has_value:
        summary_rows[1:1] = [("Valor total", report.total_value, K.MONEY),
                             ("Valor médio por Hunt", report.average_value_per_hunt, K.MONEY)]
    summary = ExportTable("Resumo", [ExportColumn("Indicador"), ExportColumn("Valor", None)],
                          [[label, value] for label, value, _kind in summary_rows],
                          row_kinds=[kind for _label, _value, kind in summary_rows])

    columns = [ExportColumn("Data", K.DATETIME), ExportColumn("Sessão"),
               ExportColumn("Duração", K.DURATION), ExportColumn("Quantidade", K.NUMBER)]
    if has_value:
        columns.append(ExportColumn("Valor", K.MONEY))
    rows = [[r.start_datetime, r.session_id, r.duration_seconds, r.quantity,
             *([r.value] if has_value else [])] for r in report.rows]
    per_hunt = ExportTable("Por Hunt", columns, rows)

    title = f"{report.kind.label}: {report.name}"
    return ExportDocument(title, [summary, per_hunt], _filter_subtitle(filter_description))
