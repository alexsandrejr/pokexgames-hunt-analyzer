//! Preferências do usuário em `settings.json` (equivale a `app/services/settings_service.py`).
//!
//! O arquivo é lido de forma tolerante: ausente, corrompido ou com valores inválidos, os
//! padrões são usados e o aplicativo abre normalmente. O formato é o mesmo da versão em Python.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::error::Result;
use crate::format::NumberFormat;

/// (valor gravado, nome na tela).
pub const THEMES: [(&str, &str); 2] = [("dark", "Escuro"), ("light", "Claro")];
pub const MIN_BACKUPS_TO_KEEP: i64 = 1;
pub const MAX_BACKUPS_TO_KEEP: i64 = 100;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AppSettings {
    pub theme: String,
    pub number_format: String,
    /// `None`: banco padrão (ver [`crate::config`]).
    pub database_path: Option<String>,
    pub auto_backup: bool,
    pub backups_to_keep: i64,
    /// Verificar no GitHub ao abrir o executável.
    pub check_updates: bool,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            theme: "dark".to_owned(),
            number_format: "pt-BR".to_owned(),
            database_path: None,
            auto_backup: true,
            backups_to_keep: 10,
            check_updates: true,
        }
    }
}

impl AppSettings {
    pub fn number_format(&self) -> NumberFormat {
        NumberFormat::from_name(&self.number_format)
    }

    /// Lê um objeto JSON campo a campo, trocando o que for inválido pelo padrão.
    fn from_json(data: &Map<String, Value>) -> Self {
        let default = Self::default();
        let text = |key| data.get(key).and_then(Value::as_str);
        let flag = |key, fallback| data.get(key).and_then(Value::as_bool).unwrap_or(fallback);
        Self {
            theme: text("theme")
                .filter(|t| THEMES.iter().any(|(value, _)| value == t))
                .map_or(default.theme, str::to_owned),
            number_format: text("number_format")
                .filter(|n| NumberFormat::ALL.iter().any(|f| f.name == *n))
                .map_or(default.number_format, str::to_owned),
            database_path: text("database_path")
                .map(crate::text::py_strip)
                .filter(|p| !p.is_empty())
                .map(str::to_owned),
            auto_backup: flag("auto_backup", default.auto_backup),
            // `as_i64` recusa true/false e números com casas, como o Python.
            backups_to_keep: data
                .get("backups_to_keep")
                .and_then(Value::as_i64)
                .filter(|k| (MIN_BACKUPS_TO_KEEP..=MAX_BACKUPS_TO_KEEP).contains(k))
                .unwrap_or(default.backups_to_keep),
            check_updates: flag("check_updates", default.check_updates),
        }
    }

    /// Troca valores inválidos pelos padrões.
    pub fn validated(&self) -> Self {
        match serde_json::to_value(self) {
            Ok(Value::Object(map)) => Self::from_json(&map),
            _ => Self::default(),
        }
    }
}

pub struct SettingsStore {
    path: PathBuf,
}

impl SettingsStore {
    pub fn new(path: PathBuf) -> Self {
        Self { path }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn load(&self) -> AppSettings {
        let Ok(text) = std::fs::read_to_string(&self.path) else {
            return AppSettings::default();
        };
        match serde_json::from_str::<Value>(&text) {
            Ok(Value::Object(map)) => AppSettings::from_json(&map),
            _ => AppSettings::default(),
        }
    }

    pub fn save(&self, settings: &AppSettings) -> Result<()> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let temporary = self.path.with_extension("tmp");
        let text = serde_json::to_string_pretty(&settings.validated())
            .expect("configurações sempre viram JSON");
        std::fs::write(&temporary, text)?;
        // Troca atômica: nunca deixa o arquivo pela metade.
        std::fs::rename(&temporary, &self.path)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn store() -> (tempfile::TempDir, SettingsStore) {
        let dir = tempfile::tempdir().unwrap();
        let store = SettingsStore::new(dir.path().join("data").join("settings.json"));
        (dir, store)
    }

    #[test]
    fn missing_file_gives_defaults() {
        let (_dir, store) = store();
        assert_eq!(store.load(), AppSettings::default());
    }

    #[test]
    fn round_trip() {
        let (_dir, store) = store();
        let settings = AppSettings {
            theme: "light".into(),
            number_format: "en-US".into(),
            database_path: Some("D:/pxg/hunts.db".into()),
            auto_backup: false,
            backups_to_keep: 25,
            check_updates: true,
        };
        store.save(&settings).unwrap();
        assert_eq!(store.load(), settings);
        assert!(!store.path().with_extension("tmp").exists());
    }

    #[test]
    fn corrupted_or_invalid_values_fall_back_to_defaults() {
        let (_dir, store) = store();
        std::fs::create_dir_all(store.path().parent().unwrap()).unwrap();
        for content in ["{ quebrado", "[1, 2]", "null"] {
            std::fs::write(store.path(), content).unwrap();
            assert_eq!(store.load(), AppSettings::default(), "{content}");
        }
        let invalid = r#"{"theme": "neon", "number_format": "xx", "database_path": "   ",
            "auto_backup": "sim", "backups_to_keep": 0, "campo_futuro": 1}"#;
        std::fs::write(store.path(), invalid).unwrap();
        assert_eq!(store.load(), AppSettings::default());
        std::fs::write(store.path(), r#"{"backups_to_keep": true}"#).unwrap();
        assert_eq!(store.load().backups_to_keep, 10);
    }

    #[test]
    fn same_file_format_as_python() {
        let (_dir, store) = store();
        store.save(&AppSettings::default()).unwrap();
        let expected = "{\n  \"theme\": \"dark\",\n  \"number_format\": \"pt-BR\",\n  \
            \"database_path\": null,\n  \"auto_backup\": true,\n  \"backups_to_keep\": 10,\n  \
            \"check_updates\": true\n}";
        assert_eq!(std::fs::read_to_string(store.path()).unwrap(), expected);
    }
}
