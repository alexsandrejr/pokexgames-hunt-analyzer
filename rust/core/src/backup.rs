//! Backup e restauração do banco SQLite (equivale a `app/services/backup_service.py`).
//!
//! As cópias usam a API de backup do próprio SQLite, que gera um arquivo consistente mesmo com
//! o aplicativo aberto. Restaurar sempre cria antes um backup de segurança do banco atual.
//!
//! Os nomes dos arquivos são os mesmos da versão em Python
//! (`hunts_backup_AAAA-MM-DD_HH-MM-SS_<tipo>.db`), então as duas listam os backups uma da outra.

use std::path::{Path, PathBuf};

use chrono::{Local, NaiveDate, NaiveDateTime};
use rusqlite::{Connection, OpenFlags};

use crate::db::Database;
use crate::db::migrations::LATEST_VERSION;
use crate::error::{Error, Result};

pub const BACKUP_PREFIX: &str = "hunts_backup_";
pub const BACKUP_SUFFIX: &str = ".db";
const TIMESTAMP_FORMAT: &str = "%Y-%m-%d_%H-%M-%S";

/// Etiqueta no nome do arquivo, que indica a origem do backup.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum BackupKind {
    Manual,
    Automatic,
    BeforeRestore,
    BeforeMigration,
    BeforeImport,
    /// Etiqueta desconhecida, de um arquivo criado por outra versão.
    Other(String),
}

impl BackupKind {
    pub fn tag(&self) -> &str {
        match self {
            Self::Manual => "manual",
            Self::Automatic => "auto",
            Self::BeforeRestore => "antes-restauracao",
            Self::BeforeMigration => "antes-atualizacao",
            Self::BeforeImport => "antes-importacao",
            Self::Other(tag) => tag,
        }
    }

    pub fn from_tag(tag: &str) -> Self {
        match tag {
            "manual" => Self::Manual,
            "auto" => Self::Automatic,
            "antes-restauracao" => Self::BeforeRestore,
            "antes-atualizacao" => Self::BeforeMigration,
            "antes-importacao" => Self::BeforeImport,
            other => Self::Other(other.to_owned()),
        }
    }

    pub fn label(&self) -> &str {
        match self {
            Self::Manual => "Manual",
            Self::Automatic => "Automático",
            Self::BeforeRestore => "Antes de restaurar",
            Self::BeforeMigration => "Antes de atualizar",
            Self::BeforeImport => "Antes de importar",
            Self::Other(tag) => tag,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BackupInfo {
    pub path: PathBuf,
    pub created_at: NaiveDateTime,
    pub kind: BackupKind,
    pub size_bytes: u64,
}

/// Confere se o arquivo é um banco do aplicativo e devolve quantas sessões ele tem.
pub fn inspect_backup(path: &Path) -> Result<i64> {
    Ok(inspect(path)?.0)
}

/// Quantidade de sessões e versão do esquema.
fn inspect(path: &Path) -> Result<(i64, i64)> {
    if !path.is_file() {
        return Err(Error::user(format!("Arquivo não encontrado: {}", path.display())));
    }
    let invalid = |error: rusqlite::Error| {
        Error::user(format!("O arquivo não é um banco SQLite válido ({error})."))
    };
    let connection =
        Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(invalid)?;
    let has_sessions: bool = connection
        .query_row(
            "SELECT EXISTS (SELECT 1 FROM sqlite_master \
             WHERE type = 'table' AND name = 'hunt_sessions')",
            [],
            |row| row.get(0),
        )
        .map_err(invalid)?;
    if !has_sessions {
        return Err(Error::user("O arquivo não é um banco do PokeXGames Hunt Analyzer."));
    }
    let count = connection
        .query_row("SELECT COUNT(*) FROM hunt_sessions", [], |row| row.get(0))
        .map_err(invalid)?;
    let version = connection
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .map_err(invalid)?;
    Ok((count, version))
}

pub struct BackupService<'a> {
    database: &'a Database,
    backups_dir: PathBuf,
}

impl<'a> BackupService<'a> {
    pub fn new(database: &'a Database, backups_dir: PathBuf) -> Self {
        Self { database, backups_dir }
    }

    pub fn backups_dir(&self) -> &Path {
        &self.backups_dir
    }

    fn database_path(&self) -> Result<&Path> {
        self.database
            .path()
            .ok_or_else(|| Error::user("O banco atual não é um arquivo (banco em memória)."))
    }

    /// Copia o banco para `destination` ou para a pasta de backups.
    pub fn create_backup(&self, kind: BackupKind, destination: Option<&Path>) -> Result<PathBuf> {
        self.database_path()?;
        let destination = match destination {
            None => {
                std::fs::create_dir_all(&self.backups_dir)?;
                self.unique_path(&kind)
            }
            Some(path) => {
                if let Some(parent) = path.parent() {
                    std::fs::create_dir_all(parent)?;
                }
                if path.exists() {
                    std::fs::remove_file(path)?;
                }
                path.to_path_buf()
            }
        };
        self.database
            .with(|connection| Ok(connection.backup(rusqlite::MAIN_DB, &destination, None)?))
            .map_err(|error| Error::user(format!("Não foi possível criar o backup: {error}")))?;
        Ok(destination)
    }

    fn unique_path(&self, kind: &BackupKind) -> PathBuf {
        let stamp = Local::now().format(TIMESTAMP_FORMAT);
        let tag = kind.tag();
        let mut path = self.backups_dir.join(format!("{BACKUP_PREFIX}{stamp}_{tag}{BACKUP_SUFFIX}"));
        let mut counter = 2;
        while path.exists() {
            path = self
                .backups_dir
                .join(format!("{BACKUP_PREFIX}{stamp}_{tag}_{counter}{BACKUP_SUFFIX}"));
            counter += 1;
        }
        path
    }

    /// Backups da pasta padrão, do mais recente para o mais antigo.
    pub fn list_backups(&self) -> Result<Vec<BackupInfo>> {
        let Ok(entries) = std::fs::read_dir(&self.backups_dir) else {
            return Ok(Vec::new());
        };
        let mut backups: Vec<BackupInfo> = entries
            .filter_map(|entry| entry.ok())
            .filter_map(|entry| parse_name(&entry.path()))
            .collect();
        backups.sort_by(|a, b| {
            (b.created_at, b.path.file_name()).cmp(&(a.created_at, a.path.file_name()))
        });
        Ok(backups)
    }

    /// Mantém só os `keep` backups automáticos mais recentes; devolve os apagados.
    pub fn prune_automatic(&self, keep: usize) -> Result<Vec<PathBuf>> {
        let mut removed = Vec::new();
        let automatic = self.list_backups()?.into_iter().filter(|b| b.kind == BackupKind::Automatic);
        for backup in automatic.skip(keep) {
            match std::fs::remove_file(&backup.path) {
                Ok(()) => {}
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => return Err(error.into()),
            }
            removed.push(backup.path);
        }
        Ok(removed)
    }

    /// No máximo um backup automático por dia, e só se houver dados.
    pub fn automatic_backup_if_due(
        &self,
        keep: usize,
        today: Option<NaiveDate>,
    ) -> Result<Option<PathBuf>> {
        let today = today.unwrap_or_else(|| Local::now().date_naive());
        let done_today = self
            .list_backups()?
            .iter()
            .any(|b| b.kind == BackupKind::Automatic && b.created_at.date() == today);
        if done_today || inspect_backup(self.database_path()?)? == 0 {
            return Ok(None);
        }
        let path = self.create_backup(BackupKind::Automatic, None)?;
        self.prune_automatic(keep)?;
        Ok(Some(path))
    }

    /// Substitui o banco atual pelo backup; devolve o backup de segurança criado.
    ///
    /// Diferente da versão em Python, recusa um backup de uma versão mais nova do aplicativo
    /// antes de mexer no banco, em vez de deixar o app sem conseguir abri-lo.
    pub fn restore(&self, source: &Path) -> Result<PathBuf> {
        let (_, version) = inspect(source)?;
        let source = std::path::absolute(source)?;
        if same_file(&source, self.database_path()?) {
            return Err(Error::user("Este arquivo já é o banco em uso."));
        }
        if version > LATEST_VERSION {
            return Err(Error::user(format!(
                "O backup está na versão {version}, mas este aplicativo conhece até a \
                 {LATEST_VERSION}. Atualize o aplicativo para restaurá-lo."
            )));
        }
        let safety = self.create_backup(BackupKind::BeforeRestore, None)?;
        self.database
            .with_mut(|connection| {
                Ok(connection.restore(rusqlite::MAIN_DB, &source, None::<fn(rusqlite::backup::Progress)>)?)
            })
            .map_err(|error| {
                Error::user(format!(
                    "Falha ao restaurar ({error}). O banco anterior foi preservado em {}.",
                    safety.display()
                ))
            })?;
        self.database.create_schema()?; // backups antigos são migrados para a versão atual
        Ok(safety)
    }
}

fn same_file(a: &Path, b: &Path) -> bool {
    match (a.canonicalize(), b.canonicalize()) {
        (Ok(a), Ok(b)) => a == b,
        _ => a == b,
    }
}

/// `hunts_backup_2026-09-26_15-24-20_auto_2.db` → data, tipo `auto` e tamanho.
fn parse_name(path: &Path) -> Option<BackupInfo> {
    let name = path.file_name()?.to_str()?;
    let body = name.strip_prefix(BACKUP_PREFIX)?.strip_suffix(BACKUP_SUFFIX)?;
    let created_at = NaiveDateTime::parse_from_str(body.get(..19)?, TIMESTAMP_FORMAT).ok()?;
    let rest = body.get(20..).unwrap_or("");
    let kind = match rest.rsplit_once('_') {
        Some((head, counter))
            if !counter.is_empty() && counter.bytes().all(|b| b.is_ascii_digit()) =>
        {
            head
        }
        _ => rest,
    };
    let kind = if kind.is_empty() { BackupKind::Manual } else { BackupKind::from_tag(kind) };
    let size_bytes = std::fs::metadata(path).ok()?.len();
    Some(BackupInfo { path: path.to_path_buf(), created_at, kind, size_bytes })
}
