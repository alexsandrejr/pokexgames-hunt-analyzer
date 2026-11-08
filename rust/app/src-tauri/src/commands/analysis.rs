//! Comandos da seção Análise: Relatórios, Itens, Inimigos e Preços (equivale a
//! `app/ui/reports/`, `app/ui/items/` e `app/ui/prices/`).

use pxg_core::format::format_money;
use pxg_core::hunts::filters::HuntFilter;
use pxg_core::hunts::service::HuntService;
use pxg_core::hunts::statistics::{EntityKind, StatisticsService};
use pxg_core::prices::PriceService;
use tauri::State;

use super::{CommandResult, message};
use crate::AppState;
use crate::analysis::{
    EntityReportView, PriceCheck, PricesView, RANKING_LIMIT, ReportInput, ReportView, parse_kind, parse_price,
    price_check, scope, scopes,
};

fn current_filter(state: &AppState) -> HuntFilter {
    state.filter.lock().unwrap_or_else(|e| e.into_inner()).clone()
}

/// Filtro do painel restrito ao escopo escolhido na página.
pub fn scoped_filter(state: &AppState, scope_index: usize) -> HuntFilter {
    current_filter(state).scoped(&scope(scope_index).1)
}

/// Descrição do escopo e dos filtros, para o cabeçalho dos documentos exportados.
pub fn scope_description(state: &AppState, scope_index: usize) -> Vec<String> {
    let mut parts = vec![format!("Categoria: {}", scope(scope_index).0)];
    parts.extend(current_filter(state).describe(state.number_format()));
    parts
}

/// Rótulos do seletor de categorias, na ordem dos índices.
#[tauri::command]
pub fn analysis_scopes() -> Vec<String> {
    scopes().into_iter().map(|(label, _)| label).collect()
}

#[tauri::command]
pub fn analysis_report(state: State<'_, AppState>, scope: usize) -> CommandResult<ReportView> {
    let filter = scoped_filter(&state, scope);
    let statistics = StatisticsService::new(&state.database);
    let overview = statistics.overview(Some(&filter)).map_err(message)?;
    let metrics = statistics.metric_breakdown(Some(&filter)).map_err(message)?;
    let top = |kind| statistics.top(kind, Some(&filter), RANKING_LIMIT).map_err(message);
    let (drops, supplies, enemies) = (top(EntityKind::Drops)?, top(EntityKind::Supplies)?, top(EntityKind::Enemies)?);
    Ok(ReportView::new(
        ReportInput {
            filter_active: !filter.is_empty(),
            overview: &overview,
            metrics: &metrics,
            drops: &drops,
            supplies: &supplies,
            enemies: &enemies,
        },
        state.number_format(),
    ))
}

/// Nomes conhecidos de um tipo (para a lista de sugestões do seletor).
#[tauri::command]
pub fn entity_names(state: State<'_, AppState>, kind: String) -> CommandResult<Vec<String>> {
    let options = HuntService::new(&state.database).filter_options().map_err(message)?;
    Ok(match parse_kind(&kind)? {
        EntityKind::Drops => options.drop_items,
        EntityKind::Supplies => options.supply_items,
        EntityKind::Enemies => options.enemies,
    })
}

#[tauri::command]
pub fn entity_report(
    state: State<'_, AppState>,
    kind: String,
    name: String,
    scope: usize,
) -> CommandResult<EntityReportView> {
    let filter = scoped_filter(&state, scope);
    let report = StatisticsService::new(&state.database)
        .entity_report(parse_kind(&kind)?, name.trim(), Some(&filter))
        .map_err(message)?;
    Ok(EntityReportView::new(&report, state.number_format()))
}

// ------------------------------------------------------------------------------ preços

#[tauri::command]
pub fn price_list(state: State<'_, AppState>) -> CommandResult<PricesView> {
    let items = PriceService::new(&state.database).list_items().map_err(message)?;
    Ok(PricesView::new(&items, state.number_format()))
}

#[tauri::command]
pub fn price_check_input(state: State<'_, AppState>, name: String, price: String) -> CommandResult<PriceCheck> {
    let items = PriceService::new(&state.database).list_items().map_err(message)?;
    Ok(price_check(&items, &name, &price, state.number_format()))
}

/// Grava o preço e devolve a mensagem da barra de status.
#[tauri::command]
pub fn price_set(state: State<'_, AppState>, name: String, price: String) -> CommandResult<String> {
    let fmt = state.number_format();
    let name = name.trim();
    let price = parse_price(&price, fmt).ok_or("Preço inválido: use um número maior ou igual a zero.")?;
    if name.is_empty() {
        return Err("Informe o item.".into());
    }
    let hunts = PriceService::new(&state.database).set_price(name, price).map_err(message)?;
    Ok(format!("Preço de {name} definido em {}; {hunts} Hunt(s) recalculada(s).", format_money(price, fmt)))
}

#[tauri::command]
pub fn price_clear(state: State<'_, AppState>, names: Vec<String>) -> CommandResult<String> {
    let service = PriceService::new(&state.database);
    let mut hunts = 0;
    for name in &names {
        hunts += service.clear_price(name).map_err(message)?;
    }
    Ok(format!("Preço do Analyzer restaurado em {} item(ns); {hunts} Hunt(s) recalculada(s).", names.len()))
}
