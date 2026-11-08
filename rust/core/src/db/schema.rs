//! Criação das tabelas, como o `Base.metadata.create_all` do SQLAlchemy.
//!
//! O DDL vem de `sql/schema_models.sql`, gerado dos modelos do Python. Como no `create_all`,
//! só as tabelas que faltam são criadas, junto com os índices delas. Uma tabela que já existe
//! fica como está, porque num banco antigo alguns índices apontam para colunas que só uma
//! migração cria (por exemplo, `ix_hunt_sessions_category`).

use std::sync::LazyLock;

use rusqlite::Connection;

use crate::error::Result;

const SCHEMA_SQL: &str = include_str!("../../sql/schema_models.sql");

/// Uma tabela e os comandos que a criam: o `CREATE TABLE` seguido dos `CREATE INDEX`.
#[derive(Debug)]
pub struct TableDdl {
    pub name: String,
    pub statements: Vec<String>,
}

/// Tabelas na ordem do arquivo (a do `create_all`, que respeita as chaves estrangeiras).
pub static TABLES: LazyLock<Vec<TableDdl>> = LazyLock::new(|| parse(SCHEMA_SQL));

fn parse(sql: &str) -> Vec<TableDdl> {
    let without_comments: String = sql
        .lines()
        .filter(|line| !line.trim_start().starts_with("--"))
        .collect::<Vec<_>>()
        .join("\n");
    let mut tables: Vec<TableDdl> = Vec::new();
    for statement in without_comments.split(';').map(str::trim).filter(|s| !s.is_empty()) {
        let words: Vec<&str> = statement.split_whitespace().collect();
        match words.as_slice() {
            ["CREATE", "TABLE", name, ..] => tables.push(TableDdl {
                name: (*name).to_owned(),
                statements: vec![statement.to_owned()],
            }),
            ["CREATE", "INDEX", _, "ON", table, ..] | ["CREATE", "UNIQUE", "INDEX", _, "ON", table, ..] => {
                let owner = tables.last_mut().expect("índice antes de qualquer tabela");
                assert_eq!(&owner.name, table, "índice fora do bloco da tabela: {statement}");
                owner.statements.push(statement.to_owned());
            }
            _ => panic!("comando inesperado em schema_models.sql: {statement}"),
        }
    }
    tables
}

/// Cria as tabelas que faltam e devolve os nomes das criadas.
pub fn create_missing_tables(connection: &Connection) -> Result<Vec<String>> {
    let mut created = Vec::new();
    for table in TABLES.iter() {
        let exists: bool = connection.query_row(
            "SELECT EXISTS (SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?1)",
            [&table.name],
            |row| row.get(0),
        )?;
        if !exists {
            for statement in &table.statements {
                connection.execute_batch(statement)?;
            }
            created.push(table.name.clone());
        }
    }
    Ok(created)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_table_of_the_python_models_is_known() {
        let names: Vec<&str> = TABLES.iter().map(|t| t.name.as_str()).collect();
        assert_eq!(names.len(), 13);
        for expected in ["hunt_sessions", "drops", "supplies", "enemies_defeated", "item_prices",
            "chat_rewards", "dps_bosses", "dps_pokemons", "dps_skills", "dps_damage_tests",
            "dps_boss_pokemons", "dps_boss_effectiveness", "dps_settings"]
        {
            assert!(names.contains(&expected), "{expected}");
        }
        // As tabelas referenciadas vêm antes das que as referenciam.
        let position = |name| names.iter().position(|n| *n == name).unwrap();
        assert!(position("hunt_sessions") < position("drops"));
        assert!(position("chat_rewards") < position("drops"));
    }
}
