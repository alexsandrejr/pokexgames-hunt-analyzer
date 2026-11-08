//! Comandos da página Início (equivale a `app/ui/dashboard/dashboard_widget.py`).

use pxg_core::hunts::categories::Category;
use pxg_core::hunts::service::HuntService;
use pxg_core::hunts::statistics::StatisticsService;
use tauri::State;

use super::{CommandResult, message};
use crate::AppState;
use crate::analysis::scope;
use crate::dashboard::{DashboardInput, DashboardView, MIN_HUNTS_FOR_CHARTS};

/// Índice do escopo com que a página abre ("Hunts e bosses").
#[tauri::command]
pub fn dashboard_default_scope() -> usize {
    crate::dashboard::default_scope()
}

#[tauri::command]
pub fn dashboard(state: State<'_, AppState>, scope_index: usize) -> CommandResult<DashboardView> {
    let user_filter = state.filter.lock().unwrap_or_else(|e| e.into_inner()).clone();
    let (label, categories) = scope(scope_index);
    let filter = user_filter.scoped(&categories);
    let statistics = StatisticsService::new(&state.database);
    let stats = statistics.overview(Some(&filter)).map_err(message)?;
    // O resumo por categoria não depende do seletor, só dos filtros.
    let mut per_category = Vec::new();
    for category in Category::ALL {
        let overview = statistics.overview(Some(&user_filter.scoped(&[*category]))).map_err(message)?;
        per_category.push((*category, overview));
    }
    let hunts = if stats.hunt_count >= MIN_HUNTS_FOR_CHARTS {
        HuntService::new(&state.database).list_hunts(Some(&filter)).map_err(message)?
    } else {
        Vec::new()
    };
    Ok(DashboardView::new(
        DashboardInput {
            scope_label: &label,
            categories: &categories,
            filter_active: !user_filter.is_empty(),
            stats: &stats,
            per_category: &per_category,
            hunts: &hunts,
        },
        state.number_format(),
    ))
}
