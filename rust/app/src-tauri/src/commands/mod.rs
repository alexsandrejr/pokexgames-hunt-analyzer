//! Comandos chamados pelas telas. Os erros voltam como texto pronto para mostrar.

pub mod analysis;
pub mod dashboard;
pub mod dps;
pub mod sessions;
pub mod settings;
pub mod update;

use serde::Serialize;
use std::time::Duration;

use tauri::{AppHandle, State};

use crate::AppState;

pub type CommandResult<T> = Result<T, String>;

pub fn message(error: pxg_core::Error) -> String {
    error.to_string()
}

/// Opção de um seletor: o valor gravado e o texto exibido.
#[derive(Serialize)]
pub struct Choice {
    pub value: String,
    pub label: String,
}

impl Choice {
    pub fn new(value: impl Into<String>, label: impl Into<String>) -> Self {
        Self { value: value.into(), label: label.into() }
    }
}

#[derive(Serialize)]
pub struct AppInfo {
    version: &'static str,
    theme: String,
    number_format: String,
    database_path: String,
    data_dir: String,
    portable: bool,
    smoke_test: bool,
}

#[tauri::command]
pub fn app_info(state: State<'_, AppState>) -> AppInfo {
    let settings = state.settings.lock().unwrap_or_else(|e| e.into_inner()).clone();
    AppInfo {
        version: pxg_core::APP_VERSION,
        theme: settings.theme,
        number_format: settings.number_format,
        database_path: state.database_path.display().to_string(),
        data_dir: state.paths.data_dir.display().to_string(),
        portable: state.paths.portable,
        smoke_test: state.smoke_test,
    }
}

/// Erro de JavaScript não tratado nas telas: vai para o log, como os do Python.
#[tauri::command]
pub fn log_frontend_error(message: String) {
    log::error!("Erro não tratado nas telas: {message}");
}

/// Tempo máximo do `--smoke-test`; depois disso, as telas travaram em algum ponto.
const SMOKE_TEST_TIMEOUT: Duration = Duration::from_secs(180);

/// Encerra com código 1 se as telas não terminarem o teste a tempo.
pub fn smoke_test_deadline(app: AppHandle) {
    std::thread::spawn(move || {
        std::thread::sleep(SMOKE_TEST_TIMEOUT);
        log::error!("Smoke test não terminou em {} s", SMOKE_TEST_TIMEOUT.as_secs());
        app.exit(1);
    });
}

/// Fim do `--smoke-test`: código 0 se nenhuma página falhou, 1 caso contrário.
#[tauri::command]
pub fn smoke_test_done(app: AppHandle, state: State<'_, AppState>, pages: Vec<String>, errors: Vec<String>) {
    if !state.smoke_test {
        return;
    }
    if errors.is_empty() {
        log::info!("Smoke test concluído: {} páginas ({})", pages.len(), pages.join(", "));
        app.exit(0);
    } else {
        for error in &errors {
            log::error!("Smoke test: {error}");
        }
        log::error!("Smoke test falhou");
        app.exit(1);
    }
}
