//! Comandos da página Configurações (equivale a `app/ui/settings/settings_widget.py`):
//! aparência, banco de dados e backups. A atualização fica em `commands::update`.

use std::path::{Path, PathBuf};

use pxg_core::backup::{BackupInfo, BackupKind, inspect_backup};
use pxg_core::config::database_path_from_env;
use pxg_core::format::{NumberFormat, format_datetime, format_number};
use pxg_core::hunts::filters::HuntFilter;
use pxg_core::hunts::service::HuntService;
use pxg_core::settings::{AppSettings, MAX_BACKUPS_TO_KEEP, MIN_BACKUPS_TO_KEEP, THEMES};
use serde::Serialize;
use tauri::{AppHandle, State};

use super::{Choice, CommandResult, message};
use crate::AppState;
use crate::sessions::{Cell, SortKey, TableView, column, row};

pub fn format_size(size_bytes: Option<u64>, fmt: NumberFormat) -> String {
    match size_bytes {
        None => pxg_core::format::PLACEHOLDER.to_owned(),
        Some(size) if size >= 1024 * 1024 => format!("{} MB", format_number(size as f64 / (1024.0 * 1024.0), 1, fmt)),
        Some(size) => format!("{} KB", format_number(size as f64 / 1024.0, 1, fmt)),
    }
}

fn backups_table(backups: &[BackupInfo], fmt: NumberFormat) -> TableView {
    let rows = backups
        .iter()
        .enumerate()
        .map(|(i, b)| {
            let name = b.path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
            row(i as i64, vec![
                Cell(format_datetime(Some(b.created_at)), None, None),
                Cell(b.kind.label().to_owned(), None, None),
                Cell(format_size(Some(b.size_bytes), fmt), Some(SortKey::Number(b.size_bytes as f64)), None),
                Cell(name, None, None),
            ])
        })
        .collect();
    TableView {
        columns: vec![
            column("Data", false, false),
            column("Tipo", false, false),
            column("Tamanho", true, false),
            column("Arquivo", false, false),
        ],
        rows,
    }
}

#[derive(Serialize)]
pub struct SettingsView {
    version: &'static str,
    theme: String,
    themes: Vec<Choice>,
    number_format: String,
    number_formats: Vec<Choice>,
    check_updates: bool,
    auto_backup: bool,
    backups_to_keep: i64,
    min_backups: i64,
    max_backups: i64,
    database_path: String,
    database_size: String,
    hunt_count: String,
    /// O banco vem de `PXG_HUNTS_DB`: não dá para trocar por aqui.
    env_locked: bool,
    /// Há um banco escolhido nas configurações (o botão "Voltar ao banco padrão" vale).
    custom_database: bool,
    backups: TableView,
    /// Caminho de cada backup, na ordem das linhas.
    backup_paths: Vec<String>,
    backups_hint: String,
}

fn settings(state: &AppState) -> AppSettings {
    state.settings.lock().unwrap_or_else(|e| e.into_inner()).clone()
}

/// Grava uma mudança nas configurações (como `_save_settings`).
fn save_settings(state: &AppState, change: impl FnOnce(&mut AppSettings)) -> CommandResult<()> {
    let mut settings = state.settings.lock().unwrap_or_else(|e| e.into_inner());
    change(&mut settings);
    state.store.save(&settings).map_err(message)
}

#[tauri::command]
pub fn settings_view(state: State<'_, AppState>) -> CommandResult<SettingsView> {
    let fmt = state.number_format();
    let s = settings(&state);
    let backups = state.backups();
    let list = backups.list_backups().map_err(message)?;
    let count = HuntService::new(&state.database).count_hunts(None).map_err(message)?;
    Ok(SettingsView {
        version: pxg_core::APP_VERSION,
        theme: s.theme.clone(),
        themes: THEMES.iter().map(|(value, label)| Choice::new(*value, *label)).collect(),
        number_format: s.number_format.clone(),
        number_formats: NumberFormat::ALL
            .iter()
            .map(|f| Choice::new(f.name, format!("{}  ({})", f.example(), f.name)))
            .collect(),
        check_updates: s.check_updates,
        auto_backup: s.auto_backup,
        backups_to_keep: s.backups_to_keep,
        min_backups: MIN_BACKUPS_TO_KEEP,
        max_backups: MAX_BACKUPS_TO_KEEP,
        database_path: state.database_path.display().to_string(),
        database_size: format_size(std::fs::metadata(&state.database_path).ok().map(|m| m.len()), fmt),
        hunt_count: format_number(count as f64, 0, fmt),
        env_locked: database_path_from_env().is_some(),
        custom_database: s.database_path.is_some(),
        backups: backups_table(&list, fmt),
        backup_paths: list.iter().map(|b| b.path.display().to_string()).collect(),
        backups_hint: format!(
            "Pasta: {}. Antes de restaurar, o banco atual é sempre salvo como backup “Antes de restaurar”. Backups manuais nunca são apagados automaticamente.",
            backups.backups_dir().display()
        ),
    })
}

#[tauri::command]
pub fn settings_set_theme(state: State<'_, AppState>, theme: String) -> CommandResult<()> {
    if !THEMES.iter().any(|(value, _)| *value == theme) {
        return Err(format!("Tema desconhecido: {theme}"));
    }
    save_settings(&state, |s| s.theme = theme)
}

#[tauri::command]
pub fn settings_set_number_format(state: State<'_, AppState>, name: String) -> CommandResult<()> {
    if !NumberFormat::ALL.iter().any(|f| f.name == name) {
        return Err(format!("Formato desconhecido: {name}"));
    }
    save_settings(&state, |s| s.number_format = name)
}

#[tauri::command]
pub fn settings_set_check_updates(state: State<'_, AppState>, enabled: bool) -> CommandResult<()> {
    save_settings(&state, |s| s.check_updates = enabled)
}

#[tauri::command]
pub fn settings_set_backup_options(state: State<'_, AppState>, auto_backup: bool, keep: i64) -> CommandResult<()> {
    let keep = keep.clamp(MIN_BACKUPS_TO_KEEP, MAX_BACKUPS_TO_KEEP);
    save_settings(&state, |s| {
        s.auto_backup = auto_backup;
        s.backups_to_keep = keep;
    })
}

/// Grava o novo banco (`None` = padrão) e devolve o aviso de reinício. A troca vale ao reabrir.
#[tauri::command]
pub fn database_set_path(state: State<'_, AppState>, path: Option<PathBuf>) -> CommandResult<String> {
    if let Some(path) = &path {
        if path.exists() {
            inspect_backup(path).map_err(message)?;
        }
    }
    let default = state.paths.default_db_path();
    let resolved = path.as_deref().map(|p| std::path::absolute(p).unwrap_or_else(|_| p.to_path_buf()));
    let is_default = match &resolved {
        None => true,
        Some(p) => same_path(p, &default),
    };
    save_settings(&state, |s| {
        s.database_path = if is_default { None } else { resolved.as_ref().map(|p| p.display().to_string()) }
    })?;
    let target = if is_default { default } else { resolved.unwrap_or_default() };
    let action = if target.exists() { "aberto" } else { "criado" };
    Ok(format!("O banco {} será {action} quando o aplicativo for reiniciado.", target.display()))
}

fn same_path(a: &Path, b: &Path) -> bool {
    match (std::fs::canonicalize(a), std::fs::canonicalize(b)) {
        (Ok(a), Ok(b)) => a == b,
        _ => a == b,
    }
}

/// Faz um backup manual (na pasta de backups ou no destino) e devolve a mensagem de status.
#[tauri::command]
pub fn backup_now(state: State<'_, AppState>, destination: Option<PathBuf>) -> CommandResult<String> {
    let path = state.backups().create_backup(BackupKind::Manual, destination.as_deref()).map_err(message)?;
    Ok(format!("Backup salvo em {}", path.display()))
}

/// Caminho sugerido para "Salvar cópia em…".
#[tauri::command]
pub fn backup_copy_default_path() -> String {
    let today = chrono::Local::now().format("%Y-%m-%d");
    crate::home().join(format!("hunts_copia_{today}.db")).display().to_string()
}

#[tauri::command]
pub fn backups_dir(state: State<'_, AppState>) -> String {
    let dir = state.backups().backups_dir().to_path_buf();
    if dir.exists() { dir } else { crate::home() }.display().to_string()
}

/// Confere o backup antes da pergunta: devolve o texto da confirmação.
#[tauri::command]
pub fn backup_inspect(state: State<'_, AppState>, path: PathBuf) -> CommandResult<String> {
    let fmt = state.number_format();
    let count = inspect_backup(&path).map_err(message)?;
    let current = HuntService::new(&state.database).count_hunts(None).map_err(message)?;
    let name = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
    Ok(format!(
        "Restaurar “{name}” ({} Hunts)?\n\nO banco atual ({} Hunts) será substituído. Antes disso, uma cópia dele será salva na pasta de backups.",
        format_number(count as f64, 0, fmt),
        format_number(current as f64, 0, fmt)
    ))
}

/// Restaura o backup, limpa os filtros e devolve a mensagem de status.
#[tauri::command]
pub fn backup_restore(state: State<'_, AppState>, path: PathBuf) -> CommandResult<String> {
    let fmt = state.number_format();
    let count = inspect_backup(&path).map_err(message)?;
    let safety = state.backups().restore(&path).map_err(message)?;
    *state.filter.lock().unwrap_or_else(|e| e.into_inner()) = HuntFilter::default();
    let name = safety.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
    Ok(format!(
        "Backup restaurado ({} Hunts). O banco anterior foi salvo em {name}.",
        format_number(count as f64, 0, fmt)
    ))
}

/// Abre uma pasta (criando-a, se for a de backups) ou um endereço no programa padrão.
#[tauri::command]
pub fn open_path(target: String, create: bool) -> CommandResult<()> {
    if create {
        std::fs::create_dir_all(&target).map_err(|e| e.to_string())?;
    }
    std::process::Command::new("explorer.exe").arg(&target).spawn().map(|_| ()).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn app_restart(app: AppHandle) {
    app.restart();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sizes_like_python() {
        let fmt = NumberFormat::PT_BR;
        assert_eq!(format_size(None, fmt), "—");
        assert_eq!(format_size(Some(1536), fmt), "1,5 KB");
        assert_eq!(format_size(Some(3 * 1024 * 1024 + 512 * 1024), fmt), "3,5 MB");
    }
}
