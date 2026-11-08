//! Conexão com o banco SQLite (equivale a `app/database/database.py`).
//!
//! Uma única conexão, protegida por um `Mutex`: o app é de um usuário só, e os comandos do
//! Tauri, que rodam em várias threads, entram um de cada vez.

pub mod datetime;
pub mod migrations;
pub mod schema;

use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard};

use rusqlite::{Connection, Transaction};

use crate::backup::{BackupKind, BackupService};
use crate::config::backups_dir_for;
use crate::error::Result;
use migrations::Migration;

pub struct Database {
    connection: Mutex<Connection>,
    path: Option<PathBuf>,
}

impl Database {
    /// Abre (ou cria) o arquivo, sem migrar. Use [`Database::create_schema`] em seguida.
    pub fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let path = std::path::absolute(path)?;
        let connection = Connection::open(&path)?;
        Self::configure(&connection)?;
        Ok(Self { connection: Mutex::new(connection), path: Some(path) })
    }

    /// Banco em memória, já com o esquema atual (útil nos testes).
    pub fn in_memory() -> Result<Self> {
        let connection = Connection::open_in_memory()?;
        Self::configure(&connection)?;
        let database = Self { connection: Mutex::new(connection), path: None };
        database.create_schema()?;
        Ok(database)
    }

    fn configure(connection: &Connection) -> Result<()> {
        // O SQLite só aplica ON DELETE CASCADE com foreign_keys ativado por conexão.
        connection.pragma_update(None, "foreign_keys", "ON")?;
        Ok(())
    }

    /// Arquivo do banco; `None` no banco em memória.
    pub fn path(&self) -> Option<&Path> {
        self.path.as_deref()
    }

    fn lock(&self) -> MutexGuard<'_, Connection> {
        // Um pânico no meio de um comando não deixa a conexão inválida: a transação dele já
        // foi desfeita ao sair de escopo.
        self.connection.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    /// Executa `f` com a conexão, fora de transação explícita.
    pub fn with<T>(&self, f: impl FnOnce(&Connection) -> Result<T>) -> Result<T> {
        f(&self.lock())
    }

    /// Executa `f` numa transação: grava se der certo e desfaz tudo em caso de erro.
    pub fn transaction<T>(&self, f: impl FnOnce(&Transaction<'_>) -> Result<T>) -> Result<T> {
        let mut connection = self.lock();
        let transaction = connection.transaction()?;
        let value = f(&transaction)?;
        transaction.commit()?;
        Ok(value)
    }

    /// Acesso exclusivo à conexão (restauração de backup).
    pub(crate) fn with_mut<T>(&self, f: impl FnOnce(&mut Connection) -> Result<T>) -> Result<T> {
        f(&mut self.lock())
    }

    pub fn schema_version(&self) -> Result<i64> {
        self.with(migrations::schema_version)
    }

    pub fn pending_migrations(&self) -> Result<Vec<&'static Migration>> {
        self.with(migrations::pending_migrations)
    }

    /// Cria as tabelas que faltam e aplica as migrações pendentes (idempotente).
    ///
    /// Devolve as migrações aplicadas nesta chamada. Um banco de uma versão mais nova é
    /// recusado antes de qualquer alteração.
    pub fn create_schema(&self) -> Result<Vec<&'static Migration>> {
        self.transaction(|tx| {
            migrations::pending_migrations(tx)?;
            schema::create_missing_tables(tx)?;
            migrations::apply_migrations(tx)
        })
    }
}

/// Abre o banco do app e o atualiza, com backup antes de migrar um banco que já tinha dados
/// (equivale a `open_database` em `app/application.py`).
pub fn open_and_migrate(path: &Path) -> Result<Database> {
    let had_data = std::fs::metadata(path).is_ok_and(|m| m.len() > 0);
    let database = Database::open(path)?;
    if had_data && !database.pending_migrations()?.is_empty() {
        let backups = BackupService::new(&database, backups_dir_for(path));
        // Não impede a abertura: a migração só cria índices e colunas.
        if let Err(error) = backups.create_backup(BackupKind::BeforeMigration, None) {
            log::warn!("Backup antes da atualização não realizado: {error}");
        }
    }
    database.create_schema()?;
    Ok(database)
}
