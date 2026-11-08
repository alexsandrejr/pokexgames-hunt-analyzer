//! Caminhos dos dados (equivale a `app/config.py`).
//!
//! Três modos de execução:
//!
//! * **Desenvolvimento:** dados na pasta `data` do projeto.
//! * **Executável:** dados em `%LOCALAPPDATA%/PokeXGames Hunt Analyzer`, gravável e separado
//!   por usuário. É a mesma pasta da versão em Python, então o banco continua o mesmo.
//! * **Portátil:** se existir uma pasta `data` ao lado do `.exe`, os dados ficam nela.
//!
//! Os ícones e as telas vão dentro do `.exe` pelo Tauri, por isso não há pasta de recursos.

use std::path::{Path, PathBuf};

pub const APP_DIR_NAME: &str = "PokeXGames Hunt Analyzer";
/// Permite apontar para outro banco sem alterar código (útil em desenvolvimento).
pub const DB_PATH_ENV_VAR: &str = "PXG_HUNTS_DB";
pub const BACKUPS_DIR_NAME: &str = "backups";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AppPaths {
    /// Gravável: banco, configurações, backups e logs.
    pub data_dir: PathBuf,
    /// Pasta inicial dos diálogos e destino dos JSONs colados.
    pub imports_dir: PathBuf,
    pub portable: bool,
}

impl AppPaths {
    pub fn logs_dir(&self) -> PathBuf {
        self.data_dir.join("logs")
    }

    /// Downloads de versões novas, apagados na abertura seguinte.
    pub fn updates_dir(&self) -> PathBuf {
        self.data_dir.join("updates")
    }

    pub fn default_db_path(&self) -> PathBuf {
        self.data_dir.join("hunts.db")
    }

    pub fn settings_path(&self) -> PathBuf {
        self.data_dir.join("settings.json")
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RunMode {
    Development { project_root: PathBuf },
    Executable { exe: PathBuf, local_app_data: Option<PathBuf>, home: PathBuf },
}

/// Decide os caminhos para o modo de execução (função pura, testável).
pub fn resolve_paths(mode: &RunMode) -> AppPaths {
    match mode {
        RunMode::Development { project_root } => AppPaths {
            data_dir: project_root.join("data"),
            imports_dir: project_root.join("imports"),
            portable: false,
        },
        RunMode::Executable { exe, local_app_data, home } => {
            let exe_dir = exe.parent().unwrap_or(Path::new("."));
            let portable_data = exe_dir.join("data");
            if portable_data.is_dir() {
                return AppPaths {
                    imports_dir: portable_data.join("imports"),
                    data_dir: portable_data,
                    portable: true,
                };
            }
            let base = local_app_data.clone().unwrap_or_else(|| home.join("AppData").join("Local"));
            let data_dir = base.join(APP_DIR_NAME);
            AppPaths { imports_dir: data_dir.join("imports"), data_dir, portable: false }
        }
    }
}

/// `~` no começo vira a pasta do usuário, e o caminho fica absoluto.
fn expand(path: &str, home: &Path) -> PathBuf {
    let expanded = match path.strip_prefix('~') {
        Some(rest) if rest.is_empty() || rest.starts_with(['/', '\\']) => {
            home.join(rest.trim_start_matches(['/', '\\']))
        }
        _ => PathBuf::from(path),
    };
    std::path::absolute(&expanded).unwrap_or(expanded)
}

/// Banco em uso: variável de ambiente > configuração salva > banco padrão.
pub fn get_database_path(
    from_env: Option<&str>,
    configured: Option<&str>,
    paths: &AppPaths,
    home: &Path,
) -> PathBuf {
    match from_env.filter(|v| !v.is_empty()).or(configured) {
        Some(path) => expand(path, home),
        None => paths.default_db_path(),
    }
}

/// Valor de `PXG_HUNTS_DB`, se definido.
pub fn database_path_from_env() -> Option<String> {
    std::env::var(DB_PATH_ENV_VAR).ok()
}

pub fn backups_dir_for(database_path: &Path) -> PathBuf {
    database_path.parent().unwrap_or(Path::new(".")).join(BACKUPS_DIR_NAME)
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Fixture {
        _dir: tempfile::TempDir,
        root: PathBuf,
        exe: PathBuf,
    }

    fn fixture() -> Fixture {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().to_path_buf();
        let exe = root.join("app").join("PokeXGames Hunt Analyzer.exe");
        std::fs::create_dir(exe.parent().unwrap()).unwrap();
        Fixture { _dir: dir, root, exe }
    }

    #[test]
    fn development_uses_project_folders() {
        let f = fixture();
        let paths = resolve_paths(&RunMode::Development { project_root: f.root.clone() });
        assert_eq!(paths.data_dir, f.root.join("data"));
        assert_eq!(paths.imports_dir, f.root.join("imports"));
        assert!(!paths.portable);
    }

    #[test]
    fn executable_uses_local_app_data() {
        let f = fixture();
        let mode = RunMode::Executable {
            exe: f.exe.clone(),
            local_app_data: Some(f.root.join("Local")),
            home: f.root.join("home"),
        };
        let paths = resolve_paths(&mode);
        assert_eq!(paths.data_dir, f.root.join("Local").join(APP_DIR_NAME));
        assert_eq!(paths.imports_dir, f.root.join("Local").join(APP_DIR_NAME).join("imports"));
        assert!(!paths.portable);
    }

    #[test]
    fn executable_without_local_app_data() {
        let f = fixture();
        let home = f.root.join("home");
        let mode = RunMode::Executable { exe: f.exe.clone(), local_app_data: None, home: home.clone() };
        assert_eq!(resolve_paths(&mode).data_dir, home.join("AppData").join("Local").join(APP_DIR_NAME));
    }

    #[test]
    fn portable_mode_when_data_folder_is_next_to_exe() {
        let f = fixture();
        std::fs::create_dir(f.exe.parent().unwrap().join("data")).unwrap();
        let mode = RunMode::Executable {
            exe: f.exe.clone(),
            local_app_data: Some(f.root.join("Local")),
            home: f.root.join("home"),
        };
        let paths = resolve_paths(&mode);
        assert!(paths.portable);
        assert_eq!(paths.data_dir, f.exe.parent().unwrap().join("data"));
    }

    #[test]
    fn database_path_priority() {
        let f = fixture();
        let home = f.root.join("home");
        let paths = resolve_paths(&RunMode::Development { project_root: f.root.clone() });
        let env = f.root.join("env.db");
        let saved = f.root.join("saved.db");
        let env_text = env.to_str().unwrap();
        let saved_text = saved.to_str().unwrap();
        assert_eq!(get_database_path(Some(env_text), Some(saved_text), &paths, &home), env);
        assert_eq!(get_database_path(None, Some(saved_text), &paths, &home), saved);
        assert_eq!(get_database_path(None, None, &paths, &home), f.root.join("data").join("hunts.db"));
        assert_eq!(get_database_path(Some("~/pxg.db"), None, &paths, &home), home.join("pxg.db"));
        assert_eq!(backups_dir_for(&saved), f.root.join("backups"));
    }
}
