//! SQL da página DPS (equivale a `DpsRepository` e às partes de `dps_service.py` que montam
//! os objetos a partir das linhas).
//!
//! As funções recebem uma conexão ou transação; quem decide a transação é o serviço.

use std::collections::{BTreeMap, BTreeSet};
use std::str::FromStr;

use rusqlite::{Connection, OptionalExtension, Row, params};

use super::calculator::{BasicAttackSpec, BuffSpec, EffectivenessLevel, Element, PokemonSpec, SkillSpec};
use super::service::{
    BossData, DamageTest, DpsSettings, MAX_BOSS_ELEMENTS, PokemonData, TestsBySkill,
};
use crate::db::datetime::{from_db, to_db};
use crate::error::{Error, Result};
use crate::text::sort_casefold;

/// Lê um valor de enum gravado; um texto desconhecido indica um banco alterado à mão.
fn parse_enum<T: FromStr<Err = crate::UserError>>(text: &str) -> Result<T> {
    T::from_str(text).map_err(Error::User)
}

fn parse_element(text: Option<String>) -> Result<Option<Element>> {
    text.filter(|t| !t.is_empty()).map(|t| parse_enum(&t)).transpose()
}

/// O `valor or padrão` do Python: `None` e zero viram o padrão.
fn or_default(value: Option<f64>, default: f64) -> f64 {
    value.filter(|v| *v != 0.0).unwrap_or(default)
}

// ------------------------------------------------------------------ bosses

/// Todos os bosses, em ordem alfabética sem diferenciar maiúsculas.
pub fn bosses(c: &Connection) -> Result<Vec<BossData>> {
    let mut bosses = load_bosses(c, None)?;
    sort_casefold(&mut bosses, |b| &b.name);
    Ok(bosses)
}

pub fn boss(c: &Connection, boss_id: i64) -> Result<Option<BossData>> {
    Ok(load_bosses(c, Some(boss_id))?.pop())
}

fn load_bosses(c: &Connection, only: Option<i64>) -> Result<Vec<BossData>> {
    let mut statement = c.prepare(
        "SELECT id, name, time_limit_seconds, dummy, damage_source, element_1, element_2 \
         FROM dps_bosses WHERE ?1 IS NULL OR id = ?1 ORDER BY id",
    )?;
    let rows = statement.query_map([only], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, i64>(2)?,
            r.get::<_, String>(3)?,
            r.get::<_, String>(4)?,
            r.get::<_, Option<String>>(5)?,
            r.get::<_, Option<String>>(6)?,
        ))
    })?;
    let mut bosses = Vec::new();
    for row in rows {
        let (id, name, time_limit_seconds, dummy, source, element_1, element_2) = row?;
        let elements = [element_1, element_2]
            .into_iter()
            .map(parse_element)
            .collect::<Result<Vec<_>>>()?
            .into_iter()
            .flatten()
            .collect();
        bosses.push(BossData {
            id,
            name,
            time_limit_seconds,
            pokemon_ids: BTreeSet::new(),
            dummy,
            damage_source: parse_enum(&source)?,
            elements,
            effectiveness: BTreeMap::new(),
        });
    }
    let mut links = c.prepare("SELECT boss_id, pokemon_id FROM dps_boss_pokemons")?;
    for link in links.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, i64>(1)?)))? {
        let (boss_id, pokemon_id) = link?;
        if let Some(boss) = bosses.iter_mut().find(|b| b.id == boss_id) {
            boss.pokemon_ids.insert(pokemon_id);
        }
    }
    let mut levels = c.prepare("SELECT boss_id, element, level FROM dps_boss_effectiveness")?;
    let rows = levels.query_map([], |r| {
        Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?))
    })?;
    for row in rows {
        let (boss_id, element, level) = row?;
        if let Some(boss) = bosses.iter_mut().find(|b| b.id == boss_id) {
            boss.effectiveness.insert(parse_enum(&element)?, parse_enum(&level)?);
        }
    }
    Ok(bosses)
}

pub fn boss_exists(c: &Connection, boss_id: i64) -> Result<bool> {
    Ok(c.query_row("SELECT EXISTS (SELECT 1 FROM dps_bosses WHERE id = ?1)", [boss_id], |r| r.get(0))?)
}

pub fn boss_count(c: &Connection) -> Result<i64> {
    Ok(c.query_row("SELECT COUNT(*) FROM dps_bosses", [], |r| r.get(0))?)
}

pub fn insert_boss(c: &Connection, name: &str, time_limit_seconds: i64) -> Result<i64> {
    c.execute(
        "INSERT INTO dps_bosses (name, time_limit_seconds, dummy, damage_source) \
         VALUES (?1, ?2, 'neutral', 'dummy')",
        params![name, time_limit_seconds],
    )?;
    Ok(c.last_insert_rowid())
}

pub fn update_boss(c: &Connection, boss_id: i64, name: &str, time_limit_seconds: i64) -> Result<()> {
    c.execute(
        "UPDATE dps_bosses SET name = ?2, time_limit_seconds = ?3 WHERE id = ?1",
        params![boss_id, name, time_limit_seconds],
    )?;
    Ok(())
}

/// Altera `dummy` ou `damage_source`; devolve se o boss existe.
pub fn set_boss_column(c: &Connection, boss_id: i64, column: &str, value: &str) -> Result<bool> {
    assert!(matches!(column, "dummy" | "damage_source"), "coluna inesperada: {column}");
    let changed =
        c.execute(&format!("UPDATE dps_bosses SET {column} = ?2 WHERE id = ?1"), params![boss_id, value])?;
    Ok(changed > 0)
}

/// Elementos informativos e efetividade; só os níveis diferentes de Normal são gravados.
pub fn set_boss_profile(
    c: &Connection,
    boss_id: i64,
    elements: &[Element],
    effectiveness: &BTreeMap<Element, EffectivenessLevel>,
) -> Result<()> {
    let mut values = elements.iter().map(|e| Some(e.as_str())).chain(std::iter::repeat(None));
    let (first, second) = (values.next().flatten(), values.next().flatten());
    debug_assert!(elements.len() <= MAX_BOSS_ELEMENTS);
    c.execute(
        "UPDATE dps_bosses SET element_1 = ?2, element_2 = ?3 WHERE id = ?1",
        params![boss_id, first, second],
    )?;
    c.execute("DELETE FROM dps_boss_effectiveness WHERE boss_id = ?1", [boss_id])?;
    let mut insert = c.prepare(
        "INSERT INTO dps_boss_effectiveness (boss_id, element, level) VALUES (?1, ?2, ?3)",
    )?;
    for (element, level) in effectiveness {
        if *level != EffectivenessLevel::Normal {
            insert.execute(params![boss_id, element.as_str(), level.as_str()])?;
        }
    }
    Ok(())
}

/// Os vínculos, a efetividade e os testes no boss saem junto, pelas chaves estrangeiras.
pub fn delete_boss(c: &Connection, boss_id: i64) -> Result<()> {
    c.execute("DELETE FROM dps_bosses WHERE id = ?1", [boss_id])?;
    Ok(())
}

/// Troca os pokémons do boss; ids que não existem são ignorados.
pub fn set_boss_pokemons(c: &Connection, boss_id: i64, pokemon_ids: &[i64]) -> Result<()> {
    c.execute("DELETE FROM dps_boss_pokemons WHERE boss_id = ?1", [boss_id])?;
    let mut insert = c.prepare(
        "INSERT OR IGNORE INTO dps_boss_pokemons (boss_id, pokemon_id) \
         SELECT ?1, id FROM dps_pokemons WHERE id = ?2",
    )?;
    for pokemon_id in pokemon_ids {
        insert.execute(params![boss_id, pokemon_id])?;
    }
    Ok(())
}

pub fn link(c: &Connection, boss_id: i64, pokemon_id: i64) -> Result<()> {
    c.execute(
        "INSERT OR IGNORE INTO dps_boss_pokemons (boss_id, pokemon_id) VALUES (?1, ?2)",
        params![boss_id, pokemon_id],
    )?;
    Ok(())
}

// ---------------------------------------------------------------- pokémons

/// Todos os pokémons ou só os marcados no boss, com skills, bosses e testes, em ordem
/// alfabética sem diferenciar maiúsculas.
pub fn pokemons(c: &Connection, boss_id: Option<i64>) -> Result<Vec<PokemonData>> {
    let mut pokemons = load_pokemons(
        c,
        "?1 IS NULL OR id IN (SELECT pokemon_id FROM dps_boss_pokemons WHERE boss_id = ?1)",
        boss_id,
    )?;
    sort_casefold(&mut pokemons, |p| &p.name);
    Ok(pokemons)
}

pub fn pokemon(c: &Connection, pokemon_id: i64) -> Result<Option<PokemonData>> {
    Ok(load_pokemons(c, "id = ?1", Some(pokemon_id))?.pop())
}

pub fn pokemon_exists(c: &Connection, pokemon_id: i64) -> Result<bool> {
    Ok(c.query_row(
        "SELECT EXISTS (SELECT 1 FROM dps_pokemons WHERE id = ?1)",
        [pokemon_id],
        |r| r.get(0),
    )?)
}

/// `filter` é uma condição sobre `dps_pokemons` com o parâmetro `?1`.
fn load_pokemons(c: &Connection, filter: &str, value: Option<i64>) -> Result<Vec<PokemonData>> {
    let ids = format!("SELECT id FROM dps_pokemons WHERE {filter}");
    let mut statement = c.prepare(&format!(
        "SELECT id, name, note, basic_efficiency, basic_element, buff_cooldown, \
         buff_basic_multiplier, buff_basic_duration, buff_next_spell_multiplier \
         FROM dps_pokemons WHERE {filter} ORDER BY id"
    ))?;
    let rows = statement.query_map([value], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, Option<f64>>(3)?,
            r.get::<_, Option<String>>(4)?,
            r.get::<_, Option<f64>>(5)?,
            r.get::<_, Option<f64>>(6)?,
            r.get::<_, Option<f64>>(7)?,
            r.get::<_, Option<f64>>(8)?,
        ))
    })?;
    let mut pokemons = Vec::new();
    for row in rows {
        let (id, name, note, basic_efficiency, basic_element, cooldown, basic_mult, duration, next) =
            row?;
        let basic = match basic_efficiency {
            Some(efficiency) => Some(BasicAttackSpec {
                element: parse_element(basic_element)?,
                ..BasicAttackSpec::new(0.0, efficiency)
            }),
            None => None,
        };
        let buff = cooldown.map(|cooldown| {
            BuffSpec::new(
                cooldown,
                or_default(basic_mult, 1.0),
                or_default(duration, 0.0),
                or_default(next, 1.0),
            )
        });
        pokemons.push(PokemonData {
            id,
            name,
            note,
            spec: PokemonSpec { skills: Vec::new(), basic, buff },
            boss_ids: BTreeSet::new(),
            tests: TestsBySkill::new(),
        });
    }

    let mut skills = c.prepare(&format!(
        "SELECT pokemon_id, id, name, shape, reach, cooldown, efficiency, element \
         FROM dps_skills WHERE pokemon_id IN ({ids}) ORDER BY pokemon_id, position, id"
    ))?;
    let rows = skills.query_map([value], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, i64>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, String>(3)?,
            r.get::<_, String>(4)?,
            r.get::<_, f64>(5)?,
            r.get::<_, f64>(6)?,
            r.get::<_, Option<String>>(7)?,
        ))
    })?;
    for row in rows {
        let (pokemon_id, id, name, shape, reach, cooldown, efficiency, element) = row?;
        let skill = SkillSpec {
            element: parse_element(element)?,
            skill_id: Some(id),
            ..SkillSpec::new(name, parse_enum(&shape)?, parse_enum(&reach)?, 0.0, cooldown, efficiency)
        };
        if let Some(pokemon) = pokemons.iter_mut().find(|p| p.id == pokemon_id) {
            pokemon.spec.skills.push(skill);
        }
    }

    let mut links = c.prepare(&format!(
        "SELECT pokemon_id, boss_id FROM dps_boss_pokemons WHERE pokemon_id IN ({ids})"
    ))?;
    for link in links.query_map([value], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, i64>(1)?)))? {
        let (pokemon_id, boss_id) = link?;
        if let Some(pokemon) = pokemons.iter_mut().find(|p| p.id == pokemon_id) {
            pokemon.boss_ids.insert(boss_id);
        }
    }

    let mut tests = c.prepare(&format!(
        "SELECT pokemon_id, skill_id, dummy, boss_id, damage_1, damage_2, damage_3, \
         created_at, updated_at FROM dps_damage_tests WHERE pokemon_id IN ({ids}) ORDER BY id"
    ))?;
    let rows = tests.query_map([value], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, Option<i64>>(1)?, test_row(r)?)))?;
    for row in rows {
        let (pokemon_id, skill_id, test) = row?;
        if let Some(pokemon) = pokemons.iter_mut().find(|p| p.id == pokemon_id) {
            pokemon.tests.entry(skill_id).or_default().push(test);
        }
    }
    Ok(pokemons)
}

/// Colunas `dummy, boss_id, damage_1..3, created_at, updated_at` a partir da posição 2.
fn test_row(r: &Row<'_>) -> rusqlite::Result<DamageTest> {
    let date = |i| r.get::<_, Option<String>>(i).map(|t| t.as_deref().and_then(from_db));
    Ok(DamageTest {
        dummy: r.get(2)?,
        boss_id: r.get(3)?,
        damages: vec![r.get(4)?, r.get(5)?, r.get(6)?],
        created_at: date(7)?,
        updated_at: date(8)?,
    })
}

pub fn insert_pokemon(c: &Connection, name: &str, note: &str) -> Result<i64> {
    c.execute("INSERT INTO dps_pokemons (name, note) VALUES (?1, ?2)", params![name, note])?;
    Ok(c.last_insert_rowid())
}

pub fn update_pokemon(c: &Connection, pokemon_id: i64, name: &str, note: &str) -> Result<()> {
    c.execute(
        "UPDATE dps_pokemons SET name = ?2, note = ?3 WHERE id = ?1",
        params![pokemon_id, name, note],
    )?;
    Ok(())
}

/// Grava a ficha e devolve os ids das skills, na ordem da ficha.
///
/// Reaproveita as skills que continuam (os testes apontam para elas), pelo `skill_id`; as
/// que saíram da lista são apagadas, com os testes delas.
pub fn apply_spec(c: &Connection, pokemon_id: i64, spec: &PokemonSpec) -> Result<Vec<i64>> {
    let basic = spec.basic.as_ref();
    let buff = spec.buff.as_ref();
    c.execute(
        "UPDATE dps_pokemons SET basic_efficiency = ?2, basic_element = ?3, buff_cooldown = ?4, \
         buff_basic_multiplier = ?5, buff_basic_duration = ?6, buff_next_spell_multiplier = ?7 \
         WHERE id = ?1",
        params![
            pokemon_id,
            basic.map(|b| b.efficiency),
            basic.and_then(|b| b.element).map(Element::as_str),
            buff.map(|b| b.cooldown),
            buff.map(|b| b.basic_multiplier),
            buff.map(|b| b.basic_duration),
            buff.map(|b| b.next_spell_multiplier),
        ],
    )?;
    let current: BTreeSet<i64> = {
        let mut statement = c.prepare("SELECT id FROM dps_skills WHERE pokemon_id = ?1")?;
        statement.query_map([pokemon_id], |r| r.get(0))?.collect::<rusqlite::Result<_>>()?
    };
    let mut kept = Vec::with_capacity(spec.skills.len());
    for (index, skill) in spec.skills.iter().enumerate() {
        let position = index as i64 + 1;
        let element = skill.element.map(Element::as_str);
        let id = match skill.skill_id.filter(|id| current.contains(id) && !kept.contains(id)) {
            Some(id) => {
                c.execute(
                    "UPDATE dps_skills SET position = ?2, name = ?3, shape = ?4, reach = ?5, \
                     cooldown = ?6, efficiency = ?7, element = ?8 WHERE id = ?1",
                    params![id, position, skill.name, skill.shape.as_str(), skill.reach.as_str(),
                        skill.cooldown, skill.efficiency, element],
                )?;
                id
            }
            None => {
                c.execute(
                    "INSERT INTO dps_skills (pokemon_id, position, name, shape, reach, cooldown, \
                     efficiency, element) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                    params![pokemon_id, position, skill.name, skill.shape.as_str(),
                        skill.reach.as_str(), skill.cooldown, skill.efficiency, element],
                )?;
                c.last_insert_rowid()
            }
        };
        kept.push(id);
    }
    for id in current.iter().filter(|id| !kept.contains(id)) {
        c.execute("DELETE FROM dps_skills WHERE id = ?1", [id])?;
    }
    Ok(kept)
}

/// Skills, testes e vínculos saem junto, pelas chaves estrangeiras.
pub fn delete_pokemon(c: &Connection, pokemon_id: i64) -> Result<()> {
    c.execute("DELETE FROM dps_pokemons WHERE id = ?1", [pokemon_id])?;
    Ok(())
}

// ------------------------------------------------------------------ testes

/// Testes da skill; sem `skill_id`, os do ataque básico.
pub fn damage_tests(c: &Connection, pokemon_id: i64, skill_id: Option<i64>) -> Result<Vec<DamageTest>> {
    let mut statement = c.prepare(
        "SELECT pokemon_id, skill_id, dummy, boss_id, damage_1, damage_2, damage_3, created_at, \
         updated_at FROM dps_damage_tests WHERE pokemon_id = ?1 AND skill_id IS ?2 ORDER BY id",
    )?;
    let rows = statement.query_map(params![pokemon_id, skill_id], test_row)?;
    Ok(rows.collect::<rusqlite::Result<_>>()?)
}

/// Todos os testes do pokémon, na ordem em que foram gravados, com a skill de cada um.
pub fn damage_tests_in_order(c: &Connection, pokemon_id: i64) -> Result<Vec<(Option<i64>, DamageTest)>> {
    let mut statement = c.prepare(
        "SELECT pokemon_id, skill_id, dummy, boss_id, damage_1, damage_2, damage_3, created_at, \
         updated_at FROM dps_damage_tests WHERE pokemon_id = ?1 ORDER BY id",
    )?;
    let rows = statement.query_map([pokemon_id], |r| Ok((r.get(1)?, test_row(r)?)))?;
    Ok(rows.collect::<rusqlite::Result<_>>()?)
}

pub fn delete_damage_tests(c: &Connection, pokemon_id: i64, skill_id: Option<i64>) -> Result<()> {
    c.execute(
        "DELETE FROM dps_damage_tests WHERE pokemon_id = ?1 AND skill_id IS ?2",
        params![pokemon_id, skill_id],
    )?;
    Ok(())
}

pub fn delete_all_damage_tests(c: &Connection, pokemon_id: i64) -> Result<()> {
    c.execute("DELETE FROM dps_damage_tests WHERE pokemon_id = ?1", [pokemon_id])?;
    Ok(())
}

pub fn insert_damage_test(
    c: &Connection,
    pokemon_id: i64,
    skill_id: Option<i64>,
    test: &DamageTest,
) -> Result<()> {
    let [d1, d2, d3] = test.padded_damages();
    c.execute(
        "INSERT INTO dps_damage_tests (pokemon_id, skill_id, dummy, boss_id, damage_1, damage_2, \
         damage_3, created_at, updated_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
        params![
            pokemon_id,
            skill_id,
            test.dummy,
            test.boss_id,
            d1,
            d2,
            d3,
            test.created_at.map(to_db),
            test.updated_at.map(to_db),
        ],
    )?;
    Ok(())
}

// ----------------------------------------------------------------- ajustes

pub fn settings(c: &Connection) -> Result<Option<DpsSettings>> {
    Ok(c.query_row(
        "SELECT basic_turn_seconds, target_melee_efficiency, default_efficiency, \
         basic_efficiency, last_boss_id FROM dps_settings ORDER BY id LIMIT 1",
        [],
        |r| {
            Ok(DpsSettings {
                basic_turn_seconds: r.get(0)?,
                target_melee_efficiency: r.get(1)?,
                default_efficiency: r.get(2)?,
                basic_efficiency: r.get(3)?,
                last_boss_id: r.get(4)?,
            })
        },
    )
    .optional()?)
}

/// Garante a linha única de ajustes, com os padrões, e devolve o id dela.
fn settings_row(c: &Connection) -> Result<i64> {
    let id = c
        .query_row("SELECT id FROM dps_settings ORDER BY id LIMIT 1", [], |r| r.get(0))
        .optional()?;
    if let Some(id) = id {
        return Ok(id);
    }
    let defaults = DpsSettings::default();
    c.execute(
        "INSERT INTO dps_settings (basic_turn_seconds, target_melee_efficiency, \
         default_efficiency, basic_efficiency) VALUES (?1, ?2, ?3, ?4)",
        params![defaults.basic_turn_seconds, defaults.target_melee_efficiency,
            defaults.default_efficiency, defaults.basic_efficiency],
    )?;
    Ok(c.last_insert_rowid())
}

/// Grava os ajustes, sem mexer no último boss escolhido.
pub fn save_settings(c: &Connection, settings: &DpsSettings) -> Result<()> {
    let id = settings_row(c)?;
    c.execute(
        "UPDATE dps_settings SET basic_turn_seconds = ?2, target_melee_efficiency = ?3, \
         default_efficiency = ?4, basic_efficiency = ?5 WHERE id = ?1",
        params![id, settings.basic_turn_seconds, settings.target_melee_efficiency,
            settings.default_efficiency, settings.basic_efficiency],
    )?;
    Ok(())
}

pub fn set_last_boss(c: &Connection, boss_id: i64) -> Result<()> {
    let id = settings_row(c)?;
    c.execute("UPDATE dps_settings SET last_boss_id = ?2 WHERE id = ?1", params![id, boss_id])?;
    Ok(())
}

// ---------------------------------------------------------------- importação

pub fn set_boss_time_limit(c: &Connection, boss_id: i64, time_limit_seconds: i64) -> Result<()> {
    c.execute(
        "UPDATE dps_bosses SET time_limit_seconds = ?2 WHERE id = ?1",
        params![boss_id, time_limit_seconds],
    )?;
    Ok(())
}

pub fn set_pokemon_note(c: &Connection, pokemon_id: i64, note: &str) -> Result<()> {
    c.execute("UPDATE dps_pokemons SET note = ?2 WHERE id = ?1", params![pokemon_id, note])?;
    Ok(())
}
