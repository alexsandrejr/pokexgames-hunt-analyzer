//! Arquivos do Analyzer: busca em pastas e gravação de textos colados como `.json` (equivale a
//! `app/services/json_files.py`).

use std::io::Write;
use std::path::{Path, PathBuf};

use chrono::{Local, NaiveDateTime};

use super::analyzer::ParsedSession;

pub const FILENAME_PREFIX: &str = "hunt";
/// Extensões procuradas ao importar pastas.
pub const ANALYZER_EXTENSIONS: [&str; 2] = ["json", "tsv"];

/// `hunt_1080_2026-09-26_15-24-20.json`; usa a hora atual se faltar o início.
pub fn suggested_filename(session: &ParsedSession, now: Option<NaiveDateTime>) -> String {
    let moment = session.start_datetime.or(now).unwrap_or_else(|| Local::now().naive_local());
    let mut parts = vec![FILENAME_PREFIX.to_owned()];
    if let Some(id) = session.session_id {
        parts.push(id.to_string());
    }
    parts.push(moment.format("%Y-%m-%d_%H-%M-%S").to_string());
    parts.join("_") + ".json"
}

fn has_analyzer_extension(path: &Path) -> bool {
    path.extension()
        .and_then(|e| e.to_str())
        .is_some_and(|e| ANALYZER_EXTENSIONS.contains(&e.to_lowercase().as_str()))
}

fn walk(folder: &Path, found: &mut Vec<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(folder) else { return };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            walk(&path, found);
        } else if path.is_file() && has_analyzer_extension(&path) {
            found.push(path);
        }
    }
}

/// Expande pastas (com subpastas) em arquivos `.json`/`.tsv`, sem repetições.
///
/// Arquivos indicados diretamente entram com qualquer extensão (o importador informa se não
/// forem JSON ou TSV válidos); em pastas, só `.json`/`.tsv`.
pub fn collect_analyzer_files(paths: &[PathBuf]) -> Vec<PathBuf> {
    let mut found: Vec<PathBuf> = Vec::new();
    let mut add = |path: &Path| {
        let resolved = path.canonicalize().unwrap_or_else(|_| path.to_path_buf());
        if !found.contains(&resolved) {
            found.push(resolved);
        }
    };
    for path in paths {
        if path.is_dir() {
            let mut children = Vec::new();
            walk(path, &mut children);
            children.sort_by_key(|p| p.to_string_lossy().to_lowercase());
            for child in children {
                add(&child);
            }
        } else if path.is_file() {
            add(path);
        }
    }
    found
}

/// Cria o arquivo sem sobrescrever: `nome.json`, `nome_2.json`, `nome_3.json`...
pub fn write_new_json_file(directory: &Path, filename: &str, text: &str) -> std::io::Result<PathBuf> {
    std::fs::create_dir_all(directory)?;
    let base = Path::new(filename);
    let stem = base.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
    let suffix = base.extension().map(|e| format!(".{}", e.to_string_lossy())).unwrap_or_default();
    let mut counter = 1;
    loop {
        let name = if counter == 1 { filename.to_owned() } else { format!("{stem}_{counter}{suffix}") };
        let path = directory.join(name);
        match std::fs::OpenOptions::new().write(true).create_new(true).open(&path) {
            Ok(mut file) => {
                file.write_all(text.as_bytes())?;
                return Ok(path);
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => counter += 1,
            Err(error) => return Err(error),
        }
    }
}
