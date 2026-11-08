//! Núcleo do PokeXGames Hunt Analyzer em Rust: regras de negócio e banco, sem interface.
//!
//! Equivale a `app/services`, `app/database` e `app/utils` da versão em Python. A interface
//! (Tauri) só chama este crate. O plano da migração está em `docs/migracao-rust.md`.

mod macros;

pub mod backup;
pub mod config;
pub mod db;
pub mod dps;
pub mod error;
pub mod export;
pub mod format;
pub mod hunts;
pub mod logging;
pub mod parse;
pub mod prices;
pub mod pyjson;
pub mod settings;
pub mod text;
pub mod update;

/// Versão do aplicativo, gravada nos arquivos exportados.
pub const APP_VERSION: &str = env!("CARGO_PKG_VERSION");

pub use db::Database;
pub use error::{Error, Result, UserError};
