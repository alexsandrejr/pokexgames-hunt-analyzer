//! Versionamento do esquema do banco (`PRAGMA user_version`), igual a
//! `app/database/migrations.py`.
//!
//! As tabelas são criadas por [`super::schema`] (versão 1). Mudanças posteriores entram como
//! novas [`Migration`] no fim de [`MIGRATIONS`], com comandos SQL idempotentes. Ao abrir um
//! banco, as migrações com versão maior que a gravada nele são aplicadas em ordem.
//!
//! A lista continua a do app Python (migrações 1 a 10), que foi apagado no corte para o Rust;
//! a próxima migração é a 11.

use rusqlite::Connection;

use crate::error::{Error, Result};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Migration {
    pub version: i64,
    pub description: &'static str,
    pub statements: &'static [&'static str],
    /// (tabela, coluna, tipo SQL) criadas antes dos `statements`, se ainda não existirem.
    pub columns: &'static [(&'static str, &'static str, &'static str)],
    /// (tabela, coluna) apagadas depois dos `statements`, se ainda existirem.
    pub dropped_columns: &'static [(&'static str, &'static str)],
}

impl Migration {
    const fn new(version: i64, description: &'static str) -> Self {
        Self { version, description, statements: &[], columns: &[], dropped_columns: &[] }
    }
}

pub const MIGRATIONS: &[Migration] = &[
    Migration::new(1, "Esquema inicial (tabelas criadas pelos modelos)"),
    Migration {
        statements: &[
            "CREATE INDEX IF NOT EXISTS ix_drops_item_lower ON drops (lower(item))",
            "CREATE INDEX IF NOT EXISTS ix_supplies_item_lower ON supplies (lower(item))",
            "CREATE INDEX IF NOT EXISTS ix_enemies_defeated_enemy_lower \
             ON enemies_defeated (lower(enemy))",
        ],
        ..Migration::new(2, "Índices sem diferenciar maiúsculas para filtros por item e inimigo")
    },
    Migration {
        statements: &[
            "UPDATE drops SET original_unit_price = unit_price, \
             original_total_price = total_price \
             WHERE original_unit_price IS NULL AND original_total_price IS NULL",
            "UPDATE supplies SET original_unit_price = unit_price, \
             original_total_price = total_price \
             WHERE original_unit_price IS NULL AND original_total_price IS NULL",
        ],
        columns: &[
            ("drops", "original_unit_price", "FLOAT"),
            ("drops", "original_total_price", "INTEGER"),
            ("supplies", "original_unit_price", "FLOAT"),
            ("supplies", "original_total_price", "INTEGER"),
        ],
        ..Migration::new(3, "Preços personalizados de itens (preço do Analyzer preservado)")
    },
    Migration {
        statements: &[
            "CREATE INDEX IF NOT EXISTS ix_hunt_sessions_category ON hunt_sessions (category)",
        ],
        columns: &[("hunt_sessions", "category", "VARCHAR(20) NOT NULL DEFAULT 'hunt'")],
        ..Migration::new(4, "Categoria da sessão (Hunt, Rift, bosses de energia e Terror)")
    },
    Migration {
        statements: &["CREATE INDEX IF NOT EXISTS ix_drops_chat_reward_id ON drops (chat_reward_id)"],
        columns: &[(
            "drops",
            "chat_reward_id",
            "INTEGER REFERENCES chat_rewards (id) ON DELETE CASCADE",
        )],
        ..Migration::new(5, "Recompensas do chat (\"Você recebeu:\") como drops da sessão")
    },
    Migration {
        statements: &[
            "INSERT INTO dps_bosses (name, time_limit_seconds) SELECT 'Padrão', 420 \
             WHERE NOT EXISTS (SELECT 1 FROM dps_bosses)",
        ],
        ..Migration::new(6, "Página DPS: boss inicial (tabelas criadas pelos modelos)")
    },
    Migration {
        columns: &[
            ("dps_skills", "element", "VARCHAR(20)"),
            ("dps_pokemons", "basic_element", "VARCHAR(20)"),
        ],
        ..Migration::new(
            7,
            "Página DPS: elemento dos golpes (testes em dummies criados pelos modelos)",
        )
    },
    Migration {
        columns: &[("dps_bosses", "dummy", "VARCHAR(20) NOT NULL DEFAULT 'neutral'")],
        dropped_columns: &[("dps_skills", "damage"), ("dps_pokemons", "basic_damage")],
        ..Migration::new(
            8,
            "Página DPS: o dano passa a vir dos testes, no dummy escolhido em cada boss",
        )
    },
    Migration {
        statements: &[
            "CREATE INDEX IF NOT EXISTS ix_dps_damage_tests_boss_id ON dps_damage_tests (boss_id)",
        ],
        columns: &[
            ("dps_bosses", "damage_source", "VARCHAR(20) NOT NULL DEFAULT 'dummy'"),
            ("dps_bosses", "element_1", "VARCHAR(20)"),
            ("dps_bosses", "element_2", "VARCHAR(20)"),
            (
                "dps_damage_tests",
                "boss_id",
                "INTEGER REFERENCES dps_bosses (id) ON DELETE CASCADE",
            ),
        ],
        ..Migration::new(
            9,
            "Página DPS: origem do dano, elementos do boss e testes dentro do boss",
        )
    },
    Migration {
        columns: &[
            ("dps_damage_tests", "created_at", "DATETIME"),
            ("dps_damage_tests", "updated_at", "DATETIME"),
        ],
        ..Migration::new(10, "Página DPS: datas de cadastro e de modificação dos testes")
    },
];

pub const LATEST_VERSION: i64 = MIGRATIONS[MIGRATIONS.len() - 1].version;

pub fn schema_version(connection: &Connection) -> Result<i64> {
    Ok(connection.pragma_query_value(None, "user_version", |row| row.get(0))?)
}

/// Migrações que faltam; erro se o banco for de uma versão mais nova do aplicativo.
pub fn pending_migrations(connection: &Connection) -> Result<Vec<&'static Migration>> {
    let current = schema_version(connection)?;
    if current > LATEST_VERSION {
        return Err(Error::SchemaTooNew { current, latest: LATEST_VERSION });
    }
    Ok(MIGRATIONS.iter().filter(|m| m.version > current).collect())
}

/// Aplica as migrações pendentes (na transação de quem chama) e devolve as aplicadas.
pub fn apply_migrations(connection: &Connection) -> Result<Vec<&'static Migration>> {
    let applied = pending_migrations(connection)?;
    for migration in &applied {
        for (table, column, sql_type) in migration.columns {
            if !column_names(connection, table)?.iter().any(|c| c == column) {
                connection.execute_batch(&format!(
                    "ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
                ))?;
            }
        }
        for statement in migration.statements {
            connection.execute_batch(statement)?;
        }
        for (table, column) in migration.dropped_columns {
            if column_names(connection, table)?.iter().any(|c| c == column) {
                connection.execute_batch(&format!("ALTER TABLE {table} DROP COLUMN {column}"))?;
            }
        }
    }
    if let Some(last) = applied.last() {
        // PRAGMA não aceita parâmetros; o valor vem de uma constante do código.
        connection.pragma_update(None, "user_version", last.version)?;
    }
    Ok(applied)
}

/// Colunas de uma tabela; o nome vem sempre de uma constante do código.
pub fn column_names(connection: &Connection, table: &str) -> Result<Vec<String>> {
    let mut statement = connection.prepare(&format!("PRAGMA table_info({table})"))?;
    let names = statement.query_map([], |row| row.get::<_, String>(1))?;
    Ok(names.collect::<rusqlite::Result<_>>()?)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn versions_are_sequential_and_latest_is_the_last() {
        for (index, migration) in MIGRATIONS.iter().enumerate() {
            assert_eq!(migration.version, index as i64 + 1);
        }
        assert_eq!(LATEST_VERSION, MIGRATIONS.len() as i64);
    }
}
