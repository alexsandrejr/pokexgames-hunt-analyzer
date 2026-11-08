//! Montagem do aplicativo (equivale a `app/application.py`): caminhos, configurações, banco,
//! backups e a janela. As regras ficam no `pxg-core`; aqui só há a ligação com as telas.

mod analysis;
mod charts;
mod commands;
mod dashboard;
mod forms;
mod install;
mod pdf;
mod sessions;
mod view;

use std::path::{Path, PathBuf};
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex};

use pxg_core::Database;
use pxg_core::backup::BackupService;
use pxg_core::config::{AppPaths, RunMode, backups_dir_for, database_path_from_env, get_database_path, resolve_paths};
use pxg_core::dps::transfer::{DpsBundle, ImportItem};
use pxg_core::format::NumberFormat;
use pxg_core::hunts::filters::HuntFilter;
use pxg_core::settings::{AppSettings, SettingsStore};
use pxg_core::update;

/// Estado compartilhado pelos comandos.
pub struct AppState {
    pub database: Database,
    pub database_path: PathBuf,
    pub paths: AppPaths,
    pub store: SettingsStore,
    pub settings: Mutex<AppSettings>,
    /// Arquivo de cadastros do DPS lido e o plano, até a pessoa confirmar a importação.
    pub pending_import: Mutex<Option<(DpsBundle, Vec<ImportItem>)>>,
    /// Filtro do painel, o mesmo em todas as páginas que o mostram.
    pub filter: Mutex<HuntFilter>,
    /// Última pasta usada ao exportar, sugerida na próxima vez.
    pub last_export_dir: Mutex<Option<PathBuf>>,
    /// Versão oferecida na última verificação de atualização.
    pub update_release: Mutex<Option<update::ReleaseInfo>>,
    /// Pedido de cancelamento do download da atualização.
    pub update_cancel: Arc<AtomicBool>,
    /// `--smoke-test`: as telas visitam todas as páginas e o programa fecha (usado pelo build).
    pub smoke_test: bool,
}

impl AppState {
    pub fn number_format(&self) -> NumberFormat {
        self.settings.lock().unwrap_or_else(|e| e.into_inner()).number_format()
    }

    pub fn backups(&self) -> BackupService<'_> {
        BackupService::new(&self.database, backups_dir_for(&self.database_path))
    }
}

/// Executável instalado: o binário de release com o nome original.
pub(crate) fn installed() -> bool {
    !cfg!(debug_assertions)
}

pub(crate) fn home() -> PathBuf {
    std::env::var_os("USERPROFILE").or_else(|| std::env::var_os("HOME")).map(PathBuf::from).unwrap_or_default()
}

/// Em desenvolvimento, os dados ficam em `rust/data`, longe do banco real do dono (`data/`).
fn run_mode() -> RunMode {
    if installed() {
        RunMode::Executable {
            exe: std::env::current_exe().unwrap_or_default(),
            local_app_data: std::env::var_os("LOCALAPPDATA").map(PathBuf::from),
            home: home(),
        }
    } else {
        let rust_root = Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("..");
        RunMode::Development { project_root: std::path::absolute(&rust_root).unwrap_or(rust_root) }
    }
}

pub fn run() -> i32 {
    let arguments: Vec<String> = std::env::args().collect();
    // Um contexto só: ele embute as telas no executável.
    let mut context = Some(tauri::generate_context!());
    let paths = resolve_paths(&run_mode());
    let store = SettingsStore::new(paths.settings_path());
    let settings = store.load();
    let log_file = pxg_core::logging::setup_logging(&paths.logs_dir());
    install_panic_hook();
    log::info!(
        "Iniciando {} {} (executável: {}, dados: {}{})",
        pxg_core::update::APP_NAME,
        pxg_core::APP_VERSION,
        installed(),
        paths.data_dir.display(),
        if paths.portable { ", portátil" } else { "" }
    );
    if log_file.is_none() {
        eprintln!("Log em arquivo indisponível em {}", paths.logs_dir().display());
    }
    if let Some(code) = install::run_install(&arguments, installed(), settings.theme.clone(), &mut context) {
        return code;
    }
    let Some(context) = context else { return 1 };
    if installed() {
        if let Ok(exe) = std::env::current_exe() {
            update::clean_leftovers(&paths.updates_dir(), exe.parent().unwrap_or(Path::new(".")));
        }
    }
    let database_path = get_database_path(
        database_path_from_env().as_deref(),
        settings.database_path.as_deref(),
        &paths,
        &home(),
    );
    let database = match pxg_core::db::open_and_migrate(&database_path) {
        Ok(database) => database,
        Err(error) => {
            // Como o Python: banco de versão mais nova só com a mensagem; o resto, com o caminho.
            log::error!("Falha ao abrir o banco {}: {error}", database_path.display());
            let text = match error {
                pxg_core::Error::SchemaTooNew { .. } => error.to_string(),
                _ => format!("Não foi possível abrir o banco de dados:\n{}\n\n{error}", database_path.display()),
            };
            install::native_error(&text);
            return 1;
        }
    };
    log::info!("Banco: {} (versão {})", database_path.display(), database.schema_version().unwrap_or_default());
    let smoke_test = arguments.iter().any(|a| a == install::SMOKE_TEST_ARG);
    let state = AppState {
        database,
        database_path,
        paths,
        store,
        settings: Mutex::new(settings),
        pending_import: Mutex::new(None),
        filter: Mutex::new(HuntFilter::default()),
        last_export_dir: Mutex::new(None),
        update_release: Mutex::new(None),
        update_cancel: Arc::new(AtomicBool::new(false)),
        smoke_test,
    };
    if state.settings.lock().map(|s| s.auto_backup).unwrap_or(false) {
        let keep = state.settings.lock().map(|s| s.backups_to_keep).unwrap_or(10).max(1) as usize;
        if let Err(error) = state.backups().automatic_backup_if_due(keep, None) {
            log::warn!("Backup automático não realizado: {error}");
        }
    }
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(state)
        .setup(move |app| {
            let config = app.config().app.windows.iter().find(|w| w.label == "main").cloned().ok_or("Janela principal ausente")?;
            // No teste do build, a janela não aparece.
            tauri::WebviewWindowBuilder::from_config(app.handle(), &config)?.visible(!smoke_test).build()?;
            if smoke_test {
                commands::smoke_test_deadline(app.handle().clone());
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::app_info,
            commands::log_frontend_error,
            commands::smoke_test_done,
            commands::dps::dps_options,
            commands::dps::dps_bosses,
            commands::dps::dps_ranking,
            commands::dps::dps_remember_boss,
            commands::dps::dps_set_source,
            commands::dps::dps_set_dummy,
            commands::dps::dps_remove_from_boss,
            commands::dps::dps_set_boss_pokemons,
            commands::dps::dps_pokemon_choices,
            commands::dps::dps_boss_form,
            commands::dps::dps_save_boss,
            commands::dps::dps_delete_boss,
            commands::dps::dps_pokemons,
            commands::dps::dps_pokemon_form,
            commands::dps::dps_damage_texts,
            commands::dps::dps_save_pokemon,
            commands::dps::dps_duplicate_pokemon,
            commands::dps::dps_delete_pokemon,
            commands::dps::dps_tests_form,
            commands::dps::dps_save_tests,
            commands::dps::dps_test_average,
            commands::dps::dps_settings_form,
            commands::dps::dps_save_settings,
            commands::dps::dps_export_path,
            commands::dps::dps_export,
            commands::dps::dps_import_plan,
            commands::dps::dps_import_apply,
            commands::sessions::session_counts,
            commands::sessions::hunt_list,
            commands::sessions::hunts_delete,
            commands::sessions::hunts_move,
            commands::sessions::session_categories,
            commands::sessions::import_target,
            commands::sessions::filter_setup,
            commands::sessions::filter_preset_range,
            commands::sessions::filter_apply,
            commands::sessions::filter_clear,
            commands::sessions::dropped_paths,
            commands::sessions::collect_files,
            commands::sessions::import_file,
            commands::sessions::import_pasted,
            commands::sessions::import_report,
            commands::sessions::paste_check,
            commands::sessions::paste_save_dir,
            commands::sessions::import_start_dir,
            commands::sessions::hunt_details,
            commands::sessions::chat_preview,
            commands::sessions::chat_quote,
            commands::sessions::chat_status_for,
            commands::sessions::chat_add,
            commands::sessions::chat_remove,
            commands::sessions::hunts_comparison,
            commands::sessions::export_formats,
            commands::sessions::export_default_path,
            commands::sessions::export_run,
            commands::sessions::boss_summary,
            commands::analysis::analysis_scopes,
            commands::analysis::analysis_report,
            commands::analysis::entity_names,
            commands::analysis::entity_report,
            commands::analysis::price_list,
            commands::analysis::price_check_input,
            commands::analysis::price_set,
            commands::analysis::price_clear,
            commands::dashboard::dashboard_default_scope,
            commands::dashboard::dashboard,
            commands::settings::settings_view,
            commands::settings::settings_set_theme,
            commands::settings::settings_set_number_format,
            commands::settings::settings_set_check_updates,
            commands::settings::settings_set_backup_options,
            commands::settings::database_set_path,
            commands::settings::backup_now,
            commands::settings::backup_copy_default_path,
            commands::settings::backups_dir,
            commands::settings::backup_inspect,
            commands::settings::backup_restore,
            commands::settings::open_path,
            commands::settings::app_restart,
            commands::update::update_check,
            commands::update::update_download,
            commands::update::update_cancel,
            commands::update::update_install,
            commands::update::update_check_on_start,
        ])
        .build(context)
        .map(|app| {
            let code = app.run_return(|_, _| {});
            log::info!("Encerrado com código {code}");
            code
        })
        .unwrap_or_else(|error| {
            log::error!("Falha ao abrir a janela: {error}");
            eprintln!("Falha ao abrir a janela: {error}");
            1
        })
}

/// Pânicos vão para o log, com o local; sem console, seria a única pista.
fn install_panic_hook() {
    let default = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        log::error!("Erro não tratado: {info}
{}", std::backtrace::Backtrace::force_capture());
        default(info);
    }));
}
