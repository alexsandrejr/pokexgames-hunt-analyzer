//! Comandos da seção Sessões: listas, filtros, importação, detalhes, recompensas do chat,
//! comparação e exportação (equivale às ações de `app/ui/hunts/` e `import_controller.py`).

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use pxg_core::export::documents::{comparison_document, entity_document, hunts_document, report_document};
use pxg_core::export::{
    ExportDocument, ExportFormat, document_html, export_document, export_target, pdf_landscape, suggested_filename,
    write_error,
};
use pxg_core::hunts::categories::{Category, category_dir};
use pxg_core::hunts::files::{ANALYZER_EXTENSIONS, collect_analyzer_files};
use pxg_core::hunts::filters::{DatePreset, HuntFilter, ItemSource, Operator, preset_range};
use pxg_core::hunts::service::HuntService;
use pxg_core::hunts::statistics::{EntityKind, StatisticsService};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, State};

use super::{Choice, CommandResult, message};
use crate::AppState;
use crate::sessions::{
    BossSummaryInput, BossSummaryView, ComparisonView, MIN_SESSIONS_FOR_CHARTS, RANKING_LIMIT, FilterBuild, FilterForm, HuntDetailsView, ImportOutcome, PANEL_METRICS, RewardLineView, TableView,
    chat_status, hunt_table, metric_key, paste_status, report_lines, summarize_results,
};

fn service(state: &AppState) -> HuntService<'_> {
    HuntService::new(&state.database)
}

fn current_filter(state: &AppState) -> HuntFilter {
    state.filter.lock().unwrap_or_else(|e| e.into_inner()).clone()
}

fn parse_category(value: Option<&str>) -> Option<Category> {
    value.and_then(|v| v.parse().ok())
}

// ------------------------------------------------------------------------------ listas

/// Quantas sessões há em cada página da sub-navegação (sem os filtros).
#[tauri::command]
pub fn session_counts(state: State<'_, AppState>) -> CommandResult<BTreeMap<String, i64>> {
    let service = service(&state);
    let mut counts = BTreeMap::new();
    counts.insert("all_sessions".to_owned(), service.count_hunts(None).map_err(message)?);
    for category in Category::ALL {
        let filter = HuntFilter::default().scoped(&[*category]);
        let key = if *category == Category::Hunt { "hunts".to_owned() } else { format!("boss:{}", category.as_str()) };
        counts.insert(key, service.count_hunts(Some(&filter)).map_err(message)?);
    }
    Ok(counts)
}

#[derive(Serialize)]
pub struct HuntList {
    table: TableView,
    /// Sessões da categoria no banco, sem os filtros.
    total_all: i64,
}

/// Sessões da categoria (todas, sem categoria) que passam nos filtros.
#[tauri::command]
pub fn hunt_list(state: State<'_, AppState>, category: Option<String>) -> CommandResult<HuntList> {
    let service = service(&state);
    let category = parse_category(category.as_deref());
    let scope: Vec<Category> = category.into_iter().collect();
    let hunts = service.list_hunts(Some(&current_filter(&state).scoped(&scope))).map_err(message)?;
    let total_all = service.count_hunts(Some(&HuntFilter::default().scoped(&scope))).map_err(message)?;
    Ok(HuntList { table: hunt_table(&hunts, category.is_none(), state.number_format()), total_all })
}

#[tauri::command]
pub fn hunts_delete(state: State<'_, AppState>, hunt_ids: Vec<i64>) -> CommandResult<usize> {
    service(&state).delete_hunts(&hunt_ids).map_err(message)
}

#[tauri::command]
pub fn hunts_move(state: State<'_, AppState>, hunt_ids: Vec<i64>, category: String) -> CommandResult<String> {
    let category: Category = category.parse().map_err(|e: pxg_core::UserError| e.0)?;
    let moved = service(&state).set_category(&hunt_ids, category).map_err(message)?;
    Ok(format!("{moved} sessão(ões) movida(s) para {}.", category.plural()))
}

#[derive(Serialize)]
pub struct CategoryChoice {
    value: &'static str,
    label: &'static str,
    plural: &'static str,
}

#[tauri::command]
pub fn session_categories() -> Vec<CategoryChoice> {
    Category::ALL.iter().map(|c| CategoryChoice { value: c.as_str(), label: c.label(), plural: c.plural() }).collect()
}

/// Para onde levar a tela depois de importar: a categoria com mais sessões novas.
#[derive(Serialize)]
pub struct ImportTarget {
    category: &'static str,
    hunt_ids: Vec<i64>,
    /// "Sessões importadas: 2 em Hunts, 1 em Terrors." quando foram para mais de uma.
    message: Option<String>,
}

#[tauri::command]
pub fn import_target(state: State<'_, AppState>, hunt_ids: Vec<i64>) -> CommandResult<ImportTarget> {
    let summaries = service(&state).get_summaries(&hunt_ids).map_err(message)?;
    let mut counts: Vec<(Category, usize)> = Vec::new();
    for summary in &summaries {
        let category = Category::from_value(Some(&summary.category));
        match counts.iter_mut().find(|(c, _)| *c == category) {
            Some((_, n)) => *n += 1,
            None => counts.push((category, 1)),
        }
    }
    // Como o Counter.most_common do Python: maior contagem; no empate, quem apareceu antes.
    counts.sort_by_key(|(_, n)| std::cmp::Reverse(*n));
    let target = counts.first().map_or(Category::Hunt, |(c, _)| *c);
    let ids = summaries.iter().filter(|s| Category::from_value(Some(&s.category)) == target).map(|s| s.id).collect();
    let message = (counts.len() > 1).then(|| {
        let parts: Vec<String> = counts.iter().map(|(c, n)| format!("{n} em {}", c.plural())).collect();
        format!("Sessões importadas: {}.", parts.join(", "))
    });
    Ok(ImportTarget { category: target.as_str(), hunt_ids: ids, message })
}

// ------------------------------------------------------------------------------ filtros

#[derive(Serialize)]
pub struct FilterSetup {
    presets: Vec<Choice>,
    operators: Vec<Choice>,
    item_sources: Vec<Choice>,
    /// (chave, rótulo, exemplo) das métricas do painel.
    metrics: Vec<(String, &'static str, &'static str)>,
    players: Vec<String>,
    enemies: Vec<String>,
    drop_items: Vec<String>,
    supply_items: Vec<String>,
    /// Resumo dos filtros ativos.
    parts: Vec<String>,
}

const PRESETS: [DatePreset; 7] = [
    DatePreset::All,
    DatePreset::Today,
    DatePreset::Last7Days,
    DatePreset::Last30Days,
    DatePreset::ThisMonth,
    DatePreset::LastMonth,
    DatePreset::Custom,
];

fn preset_value(preset: DatePreset) -> String {
    serde_json::to_value(preset).ok().and_then(|v| v.as_str().map(str::to_owned)).unwrap_or_default()
}

#[tauri::command]
pub fn filter_setup(state: State<'_, AppState>) -> CommandResult<FilterSetup> {
    let options = service(&state).filter_options().map_err(message)?;
    Ok(FilterSetup {
        presets: PRESETS.iter().map(|p| Choice::new(preset_value(*p), p.label())).collect(),
        operators: Operator::ALL.iter().map(|o| Choice::new(o.symbol(), o.symbol())).collect(),
        item_sources: [ItemSource::Drops, ItemSource::Supplies]
            .iter()
            .map(|s| Choice::new(if *s == ItemSource::Drops { "drops" } else { "supplies" }, format!("{}s", s.label())))
            .collect(),
        metrics: PANEL_METRICS.iter().map(|(m, example)| (metric_key(*m).to_owned(), m.label(), *example)).collect(),
        players: options.players,
        enemies: options.enemies,
        drop_items: options.drop_items,
        supply_items: options.supply_items,
        parts: current_filter(&state).describe(state.number_format()),
    })
}

/// Datas (`aaaa-mm-dd`) de um período pronto, para preencher os seletores.
#[tauri::command]
pub fn filter_preset_range(preset: DatePreset) -> (Option<String>, Option<String>) {
    let today = chrono::Local::now().date_naive();
    let (from, to) = preset_range(preset, today);
    let iso = |d: chrono::NaiveDate| d.format("%Y-%m-%d").to_string();
    (from.map(iso), to.map(iso))
}

#[derive(Serialize)]
pub struct FilterApplied {
    #[serde(flatten)]
    build: FilterBuild,
    parts: Vec<String>,
}

#[tauri::command]
pub fn filter_apply(state: State<'_, AppState>, form: FilterForm) -> CommandResult<FilterApplied> {
    let fmt = state.number_format();
    let options = service(&state).filter_options().map_err(message)?;
    let build = form.build(&options, chrono::Local::now().date_naive(), fmt);
    if let Some(filter) = &build.filter {
        *state.filter.lock().unwrap_or_else(|e| e.into_inner()) = filter.clone();
    }
    Ok(FilterApplied { build, parts: current_filter(&state).describe(fmt) })
}

#[tauri::command]
pub fn filter_clear(state: State<'_, AppState>) {
    *state.filter.lock().unwrap_or_else(|e| e.into_inner()) = HuntFilter::default();
}

// ------------------------------------------------------------------------------ importação

/// Arquivos `.json`/`.tsv` e pastas de um arrastar e soltar.
#[tauri::command]
pub fn dropped_paths(paths: Vec<PathBuf>) -> Vec<PathBuf> {
    paths
        .into_iter()
        .filter(|p| {
            p.is_dir()
                || (p.is_file()
                    && p.extension().is_some_and(|e| ANALYZER_EXTENSIONS.contains(&e.to_string_lossy().to_lowercase().as_str())))
        })
        .collect()
}

/// Expande pastas em arquivos, como `collect_analyzer_files`.
#[tauri::command]
pub fn collect_files(paths: Vec<PathBuf>) -> Vec<String> {
    collect_analyzer_files(&paths).iter().map(|p| p.display().to_string()).collect()
}

#[tauri::command]
pub fn import_file(
    state: State<'_, AppState>,
    path: PathBuf,
    allow_duplicate: bool,
    category: Option<String>,
) -> CommandResult<ImportOutcome> {
    let result = service(&state)
        .import_file(&path, allow_duplicate, parse_category(category.as_deref()))
        .map_err(message)?;
    Ok(ImportOutcome::from(&result))
}

#[tauri::command]
pub fn import_pasted(
    state: State<'_, AppState>,
    text: String,
    allow_duplicate: bool,
    category: Option<String>,
) -> CommandResult<ImportOutcome> {
    let result = service(&state)
        .import_pasted_text(&text, &state.paths.imports_dir, allow_duplicate, parse_category(category.as_deref()))
        .map_err(message)?;
    Ok(ImportOutcome::from(&result))
}

#[derive(Serialize)]
pub struct ImportReport {
    summary: String,
    lines: Vec<String>,
}

#[tauri::command]
pub fn import_report(results: Vec<ImportOutcome>, cancelled: bool) -> ImportReport {
    ImportReport { summary: summarize_results(&results, cancelled), lines: report_lines(&results) }
}

#[derive(Serialize)]
pub struct PasteCheck {
    message: String,
    color: &'static str,
    valid: bool,
}

#[tauri::command]
pub fn paste_check(state: State<'_, AppState>, text: String) -> PasteCheck {
    let (message, color, valid) = paste_status(&text, state.number_format());
    PasteCheck { message, color, valid }
}

/// Pasta onde o texto colado vira arquivo (bosses: a subpasta da categoria).
#[tauri::command]
pub fn paste_save_dir(state: State<'_, AppState>, category: Option<String>) -> String {
    let dir = &state.paths.imports_dir;
    match parse_category(category.as_deref()) {
        Some(category) => category_dir(dir, category),
        None => dir.clone(),
    }
    .display()
    .to_string()
}

/// Pasta inicial dos seletores de arquivo: a de imports, se existir.
#[tauri::command]
pub fn import_start_dir(state: State<'_, AppState>) -> String {
    let imports = &state.paths.imports_dir;
    if imports.exists() { imports.display().to_string() } else { crate::home().display().to_string() }
}

// ------------------------------------------------------------------------------ detalhes e chat

#[tauri::command]
pub fn hunt_details(state: State<'_, AppState>, hunt_id: i64) -> CommandResult<Option<HuntDetailsView>> {
    let details = service(&state).get_hunt_details(hunt_id).map_err(message)?;
    Ok(details.map(|d| HuntDetailsView::new(&d, state.number_format())))
}

#[derive(Serialize)]
pub struct ChatPreview {
    lines: Vec<RewardLineView>,
    status: String,
    color: &'static str,
}

#[tauri::command]
pub fn chat_preview(state: State<'_, AppState>, hunt_id: i64, text: String) -> CommandResult<ChatPreview> {
    let fmt = state.number_format();
    let preview = service(&state).preview_chat_rewards(Some(hunt_id), &text).map_err(message)?;
    let (status, color) = chat_status(&text, &preview, fmt);
    Ok(ChatPreview { lines: preview.lines.iter().map(|l| RewardLineView::new(l, fmt)).collect(), status, color })
}

/// Preço e nome de um item depois que a pessoa corrige o nome na prévia.
#[tauri::command]
pub fn chat_quote(state: State<'_, AppState>, chat_name: String, item: String, count: i64) -> CommandResult<RewardLineView> {
    let name = item.split_whitespace().collect::<Vec<_>>().join(" ");
    let name = if name.is_empty() { chat_name.clone() } else { name };
    let line = service(&state).quote_reward_item(&chat_name, &name, count).map_err(message)?;
    Ok(RewardLineView::new(&line, state.number_format()))
}

/// Status da prévia depois de editar nomes (as linhas mudaram, as mensagens não).
#[tauri::command]
pub fn chat_status_for(
    state: State<'_, AppState>,
    hunt_id: i64,
    text: String,
    lines: Vec<RewardLineView>,
) -> CommandResult<(String, &'static str)> {
    let mut preview = service(&state).preview_chat_rewards(Some(hunt_id), &text).map_err(message)?;
    preview.lines = lines.iter().map(RewardLineView::to_line).collect();
    Ok(chat_status(&text, &preview, state.number_format()))
}

#[tauri::command]
pub fn chat_add(state: State<'_, AppState>, hunt_id: i64, text: String, lines: Vec<RewardLineView>) -> CommandResult<usize> {
    let lines: Vec<_> = lines.iter().map(RewardLineView::to_line).collect();
    service(&state).add_chat_rewards(hunt_id, &text, Some(&lines)).map_err(message)
}

#[tauri::command]
pub fn chat_remove(state: State<'_, AppState>, hunt_id: i64) -> CommandResult<usize> {
    service(&state).remove_chat_rewards(hunt_id).map_err(message)
}

#[tauri::command]
pub fn hunts_comparison(state: State<'_, AppState>, hunt_ids: Vec<i64>) -> CommandResult<ComparisonView> {
    let hunts = service(&state).get_summaries(&hunt_ids).map_err(message)?;
    Ok(ComparisonView::new(&hunts, state.number_format()))
}

// ------------------------------------------------------------------------------ exportação

/// O que exportar; o documento é montado aqui, com os dados atuais.
#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ExportRequest {
    /// As sessões visíveis na tabela, na ordem exibida.
    Hunts { hunt_ids: Vec<i64>, category: Option<String> },
    Comparison { hunt_ids: Vec<i64> },
    /// Página Relatórios, no escopo escolhido.
    Report { scope: usize },
    /// Relatório de um item ou inimigo.
    Entity { entity: String, name: String, scope: usize },
}

fn build_document(state: &AppState, request: &ExportRequest) -> CommandResult<ExportDocument> {
    let service = service(state);
    match request {
        ExportRequest::Hunts { hunt_ids, category } => {
            let summaries = service.get_summaries(hunt_ids).map_err(message)?;
            let ordered: Vec<_> =
                hunt_ids.iter().filter_map(|id| summaries.iter().find(|s| s.id == *id).cloned()).collect();
            let title = parse_category(category.as_deref()).map_or("Sessões", |c| c.plural());
            Ok(hunts_document(&ordered, &current_filter(state).describe(state.number_format()), title))
        }
        ExportRequest::Comparison { hunt_ids } => {
            Ok(comparison_document(&service.get_summaries(hunt_ids).map_err(message)?))
        }
        ExportRequest::Report { scope } => {
            let filter = super::analysis::scoped_filter(state, *scope);
            let statistics = StatisticsService::new(&state.database);
            let top = |kind| statistics.top(kind, Some(&filter), crate::analysis::RANKING_LIMIT).map_err(message);
            Ok(report_document(
                &statistics.overview(Some(&filter)).map_err(message)?,
                &statistics.metric_breakdown(Some(&filter)).map_err(message)?,
                &top(EntityKind::Drops)?,
                &top(EntityKind::Supplies)?,
                &top(EntityKind::Enemies)?,
                &super::analysis::scope_description(state, *scope),
            ))
        }
        ExportRequest::Entity { entity, name, scope } => {
            let filter = super::analysis::scoped_filter(state, *scope);
            let report = StatisticsService::new(&state.database)
                .entity_report(crate::analysis::parse_kind(entity)?, name.trim(), Some(&filter))
                .map_err(message)?;
            Ok(entity_document(&report, &super::analysis::scope_description(state, *scope)))
        }
    }
}

fn parse_format(value: &str) -> CommandResult<ExportFormat> {
    ExportFormat::ALL.into_iter().find(|f| f.extension() == value).ok_or_else(|| format!("Formato desconhecido: {value}"))
}

#[derive(Serialize)]
pub struct ExportFormatChoice {
    value: &'static str,
    label: String,
    description: &'static str,
}

#[tauri::command]
pub fn export_formats() -> Vec<ExportFormatChoice> {
    ExportFormat::ALL
        .iter()
        .map(|f| ExportFormatChoice {
            value: f.extension(),
            label: format!("{} (.{})", f.label(), f.extension()),
            description: f.description(),
        })
        .collect()
}

fn documents_dir() -> PathBuf {
    let documents = crate::home().join("Documents");
    if documents.is_dir() { documents } else { crate::home() }
}

/// Caminho sugerido: a última pasta usada (ou Documentos) e o nome do documento.
#[tauri::command]
pub fn export_default_path(state: State<'_, AppState>, request: ExportRequest, format: String) -> CommandResult<String> {
    let format = parse_format(&format)?;
    let document = build_document(&state, &request)?;
    let directory = state.last_export_dir.lock().unwrap_or_else(|e| e.into_inner()).clone().unwrap_or_else(documents_dir);
    Ok(directory.join(suggested_filename(&document.title, format, None)).display().to_string())
}

/// Grava o arquivo e devolve o caminho gravado (com a extensão, se faltava).
/// O PDF é impresso pelo WebView2 (`crate::pdf`); os outros formatos são gravados pelo núcleo.
#[tauri::command]
pub async fn export_run(
    app: AppHandle,
    state: State<'_, AppState>,
    request: ExportRequest,
    format: String,
    path: PathBuf,
) -> CommandResult<String> {
    let format = parse_format(&format)?;
    let document = build_document(&state, &request)?;
    let saved = if format == ExportFormat::Pdf {
        let target = export_target(&path, format);
        // Confere a permissão antes, para dar a mesma mensagem dos outros formatos.
        if let Some(parent) = target.parent() {
            std::fs::create_dir_all(parent).map_err(|e| message(write_error(&target, &e)))?;
        }
        std::fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(&target)
            .map_err(|e| message(write_error(&target, &e)))?;
        let html = document_html(&document, state.number_format());
        crate::pdf::print_html(&app, &html, pdf_landscape(&document), &target).await?;
        target
    } else {
        export_document(&document, &path, format, state.number_format()).map_err(message)?
    };
    *state.last_export_dir.lock().unwrap_or_else(|e| e.into_inner()) = saved.parent().map(Path::to_path_buf);
    Ok(saved.display().to_string())
}


// ------------------------------------------------------------------------------ resumo de boss

/// Resumo de um tipo de boss sobre as sessões filtradas.
#[tauri::command]
pub fn boss_summary(state: State<'_, AppState>, category: String) -> CommandResult<BossSummaryView> {
    let category: Category = category.parse().map_err(|e: pxg_core::UserError| e.0)?;
    let user_filter = current_filter(&state);
    let filter = user_filter.scoped(&[category]);
    let statistics = StatisticsService::new(&state.database);
    let stats = statistics.overview(Some(&filter)).map_err(message)?;
    let (enemies, drops, elements) = if stats.hunt_count > 0 {
        (
            statistics.top(EntityKind::Enemies, Some(&filter), RANKING_LIMIT).map_err(message)?,
            statistics.top(EntityKind::Drops, Some(&filter), RANKING_LIMIT).map_err(message)?,
            statistics.damage_by_element(Some(&filter)).map_err(message)?,
        )
    } else {
        Default::default()
    };
    let hunts = if stats.hunt_count >= MIN_SESSIONS_FOR_CHARTS {
        service(&state).list_hunts(Some(&filter)).map_err(message)?
    } else {
        Vec::new()
    };
    Ok(BossSummaryView::new(
        BossSummaryInput {
            plural: category.plural(),
            filter_active: !user_filter.is_empty(),
            stats: &stats,
            enemies: &enemies,
            drops: &drops,
            elements: &elements,
            hunts: &hunts,
        },
        state.number_format(),
    ))
}
