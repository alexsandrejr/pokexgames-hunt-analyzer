//! Log em arquivo (equivale a `app/logging_setup.py`).
//!
//! No executável não há console: sem isto, um erro inesperado não deixaria nenhuma pista.
//! O log vai para `logs/app.log`, rotativo como o `RotatingFileHandler` do Python
//! (1 MB, mais 3 arquivos antigos: `app.log.1` a `app.log.3`).

use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use chrono::Local;
use log::{Level, LevelFilter, Log, Metadata, Record};

pub const LOG_FILE_NAME: &str = "app.log";
pub const MAX_LOG_BYTES: u64 = 1_000_000;
pub const LOG_BACKUPS: usize = 3;

/// Só os registros do próprio programa; os do Tauri e do WebView ficariam enormes.
const OWN_TARGETS: &[&str] = &["pxg"];

pub struct FileLogger {
    path: PathBuf,
    file: Mutex<Option<File>>,
}

impl FileLogger {
    /// Abre (ou cria) o arquivo de log; `None` se a pasta não for gravável.
    pub fn open(logs_dir: &Path) -> Option<Self> {
        std::fs::create_dir_all(logs_dir).ok()?;
        let path = logs_dir.join(LOG_FILE_NAME);
        let file = OpenOptions::new().create(true).append(true).open(&path).ok()?;
        Some(Self { path, file: Mutex::new(Some(file)) })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// `app.log` vira `app.log.1`, que vira `app.log.2`, e assim por diante.
    fn rotate(&self, slot: &mut Option<File>) {
        *slot = None;
        let numbered = |n: usize| PathBuf::from(format!("{}.{n}", self.path.display()));
        let _ = std::fs::remove_file(numbered(LOG_BACKUPS));
        for n in (1..LOG_BACKUPS).rev() {
            let _ = std::fs::rename(numbered(n), numbered(n + 1));
        }
        let _ = std::fs::rename(&self.path, numbered(1));
        *slot = OpenOptions::new().create(true).append(true).open(&self.path).ok();
    }
}

/// `2026-11-08 09:02:59,123 INFO pxg_core::db: mensagem`, no formato do Python.
pub fn format_line(record: &Record) -> String {
    let level = match record.level() {
        Level::Error => "ERROR",
        Level::Warn => "WARNING",
        Level::Info => "INFO",
        Level::Debug | Level::Trace => "DEBUG",
    };
    format!("{} {level} {}: {}\n", Local::now().format("%Y-%m-%d %H:%M:%S,%3f"), record.target(), record.args())
}

impl Log for FileLogger {
    fn enabled(&self, metadata: &Metadata) -> bool {
        metadata.level() <= Level::Info && OWN_TARGETS.iter().any(|t| metadata.target().starts_with(t))
    }

    fn log(&self, record: &Record) {
        if !self.enabled(record.metadata()) {
            return;
        }
        let line = format_line(record);
        let mut slot = self.file.lock().unwrap_or_else(|e| e.into_inner());
        let size = slot.as_ref().and_then(|f| f.metadata().ok()).map_or(0, |m| m.len());
        if size > 0 && size + line.len() as u64 > MAX_LOG_BYTES {
            self.rotate(&mut slot);
        }
        if let Some(file) = slot.as_mut() {
            let _ = file.write_all(line.as_bytes());
        }
    }

    fn flush(&self) {
        if let Some(file) = self.file.lock().unwrap_or_else(|e| e.into_inner()).as_mut() {
            let _ = file.flush();
        }
    }
}

/// Instala o log em arquivo; devolve o caminho (ou `None` se não for gravável).
pub fn setup_logging(logs_dir: &Path) -> Option<PathBuf> {
    let logger = FileLogger::open(logs_dir)?;
    let path = logger.path().to_path_buf();
    log::set_boxed_logger(Box::new(logger)).ok()?;
    log::set_max_level(LevelFilter::Info);
    Some(path)
}
