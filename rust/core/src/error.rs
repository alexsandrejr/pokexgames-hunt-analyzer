//! Erros do núcleo, com mensagens em português prontas para mostrar ao usuário.
//!
//! [`UserError`] equivale ao `ValueError` (e ao `BackupError`) que os services da versão em
//! Python lançam. [`Error`] junta esse erro às falhas do banco e dos arquivos.

use std::fmt;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UserError(pub String);

impl UserError {
    pub fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }

    pub fn message(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for UserError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for UserError {}

#[derive(Debug)]
pub enum Error {
    /// Regra violada ou falha esperada, com a mensagem pronta para o usuário.
    User(UserError),
    /// O banco foi criado por uma versão mais nova do aplicativo.
    SchemaTooNew { current: i64, latest: i64 },
    Sqlite(rusqlite::Error),
    Io(std::io::Error),
}

pub type Result<T, E = Error> = std::result::Result<T, E>;

impl Error {
    pub fn user(message: impl Into<String>) -> Self {
        Self::User(UserError::new(message))
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::User(error) => error.fmt(f),
            Self::SchemaTooNew { current, latest } => write!(
                f,
                "O banco está na versão {current}, mas este aplicativo conhece até a \
                 {latest}. Atualize o aplicativo para abri-lo."
            ),
            Self::Sqlite(error) => write!(f, "Erro no banco de dados: {error}"),
            Self::Io(error) => write!(f, "Erro ao acessar um arquivo: {error}"),
        }
    }
}

impl std::error::Error for Error {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::User(error) => Some(error),
            Self::Sqlite(error) => Some(error),
            Self::Io(error) => Some(error),
            Self::SchemaTooNew { .. } => None,
        }
    }
}

impl From<UserError> for Error {
    fn from(error: UserError) -> Self {
        Self::User(error)
    }
}

impl From<rusqlite::Error> for Error {
    fn from(error: rusqlite::Error) -> Self {
        Self::Sqlite(error)
    }
}

impl From<std::io::Error> for Error {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error)
    }
}
