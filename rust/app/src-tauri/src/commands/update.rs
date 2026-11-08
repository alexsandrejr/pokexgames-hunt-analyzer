//! Verificação e instalação de versões novas (equivale a `app/ui/update/update_controller.py`
//! e `update_dialog.py`). A rede e o disco rodam fora da thread da interface; o progresso do
//! download chega à tela pelo evento `update-progress`.

use std::path::{Path, PathBuf};
use std::sync::atomic::Ordering;

use pxg_core::format::format_number;
use pxg_core::update::{ReleaseInfo, UpdateError, UpdateService, can_install_itself, ensure_writable, start_installer};
use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, State};

use super::CommandResult;
use crate::AppState;

const MEGABYTE: u64 = 1024 * 1024;

/// Pasta do programa instalado, se ele puder se atualizar sozinho (só o `.exe` de release).
fn install_dir() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    can_install_itself(crate::installed(), &exe).then(|| exe.parent().map(Path::to_path_buf)).flatten()
}

#[derive(Debug, Clone, Serialize)]
pub struct ReleaseView {
    version: String,
    current: &'static str,
    /// Novidades em Markdown; vazio vira "Esta versão não traz uma lista de novidades."
    notes: String,
    page_url: String,
    can_install: bool,
    hint: &'static str,
}

fn hint(install_dir: Option<&Path>, release: &ReleaseInfo) -> &'static str {
    if install_dir.is_none() {
        "A instalação automática só funciona no programa em .exe."
    } else if !release.installable() {
        "Este release não tem o pacote esperado. Baixe a versão pela página do GitHub."
    } else {
        "O app baixa a versão nova, fecha e abre de novo já atualizado. Seus dados continuam no mesmo lugar, e o banco ganha um backup antes de qualquer mudança de versão."
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct UpdateCheck {
    /// Texto ao lado de "Verificar agora".
    status: String,
    release: Option<ReleaseView>,
}

/// Consulta o GitHub. A tela decide o que mostrar numa verificação silenciosa (ao abrir).
#[tauri::command]
pub async fn update_check(app: AppHandle) -> CommandResult<UpdateCheck> {
    let updates_dir = app.state::<AppState>().paths.updates_dir();
    let result = tauri::async_runtime::spawn_blocking(move || UpdateService::new(updates_dir).check())
        .await
        .map_err(|e| format!("Falha inesperada na verificação: {e}"))?;
    let release = result.map_err(|e| e.to_string())?;
    let state = app.state::<AppState>();
    *state.update_release.lock().unwrap_or_else(|e| e.into_inner()) = release.clone();
    Ok(match release {
        None => UpdateCheck {
            status: format!("Você já está na versão mais recente ({}).", pxg_core::APP_VERSION),
            release: None,
        },
        Some(release) => {
            let dir = install_dir();
            UpdateCheck {
                status: format!("Versão {} disponível.", release.version),
                release: Some(ReleaseView {
                    version: release.version.clone(),
                    current: pxg_core::APP_VERSION,
                    notes: release.notes.clone(),
                    page_url: release.page_url.clone(),
                    can_install: dir.is_some() && release.installable(),
                    hint: hint(dir.as_deref(), &release),
                }),
            }
        }
    })
}

#[derive(Debug, Clone, Serialize)]
struct Progress {
    /// 0 a 1.
    fraction: f64,
    text: String,
}

fn progress_text(received: u64, total: u64, app: &AppHandle) -> String {
    if received >= total {
        return "Preparando a instalação…".to_owned();
    }
    let fmt = app.state::<AppState>().number_format();
    format!(
        "Baixando… {} de {} MB",
        format_number((received / MEGABYTE) as f64, 0, fmt),
        format_number((total / MEGABYTE) as f64, 0, fmt)
    )
}

/// Resultado do download: a pasta extraída ou o cancelamento (a tela só fecha o diálogo).
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum DownloadOutcome {
    Ready { new_root: String },
    Cancelled,
}

/// Baixa e extrai a versão oferecida na última verificação.
#[tauri::command]
pub async fn update_download(app: AppHandle) -> CommandResult<DownloadOutcome> {
    let dir = install_dir().ok_or("A instalação automática só funciona no programa em .exe.")?;
    ensure_writable(&dir).map_err(|e| e.to_string())?;
    let state = app.state::<AppState>();
    let release = state.update_release.lock().unwrap_or_else(|e| e.into_inner()).clone().ok_or("Verifique de novo.")?;
    let cancel = state.update_cancel.clone();
    cancel.store(false, Ordering::SeqCst);
    let updates_dir = state.paths.updates_dir();
    let handle = app.clone();
    let result = tauri::async_runtime::spawn_blocking(move || {
        let service = UpdateService::new(updates_dir);
        let report = |received: u64, total: u64| {
            let fraction = if total > 0 { received as f64 / total as f64 } else { 0.0 };
            let _ = handle.emit("update-progress", Progress { fraction, text: progress_text(received, total, &handle) });
        };
        let archive = service.download(&release, Some(&report), Some(&cancel))?;
        report(release.asset_size, release.asset_size);
        service.extract(&archive, &release.version)
    })
    .await
    .map_err(|e| format!("Falha inesperada na atualização: {e}"))?;
    match result {
        Ok(root) => Ok(DownloadOutcome::Ready { new_root: root.display().to_string() }),
        Err(UpdateError::Cancelled) => Ok(DownloadOutcome::Cancelled),
        Err(error) => {
            log::warn!("Atualização não concluída: {error}");
            Err(error.to_string())
        }
    }
}

/// Pede o cancelamento; o download confirma devolvendo `Cancelled`.
#[tauri::command]
pub fn update_cancel(state: State<'_, AppState>) {
    state.update_cancel.store(true, Ordering::SeqCst);
}

/// Abre o instalador da versão nova e fecha o app para ele trocar os arquivos.
#[tauri::command]
pub fn update_install(app: AppHandle, new_root: PathBuf) -> CommandResult<()> {
    let dir = install_dir().ok_or("A instalação automática só funciona no programa em .exe.")?;
    start_installer(&new_root, &dir, std::process::id()).map_err(|e| {
        log::error!("{e}");
        e.to_string()
    })?;
    log::info!("Instalador da atualização aberto; encerrando");
    app.exit(0);
    Ok(())
}

/// Se a verificação ao abrir está ligada (ela espera a janela abrir, como o Python).
#[tauri::command]
pub fn update_check_on_start(state: State<'_, AppState>) -> bool {
    // Só no .exe (como o Python), e o teste do build não vai à internet.
    !state.smoke_test && crate::installed() && state.settings.lock().unwrap_or_else(|e| e.into_inner()).check_updates
}
