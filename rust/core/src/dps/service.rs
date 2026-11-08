//! Cadastro de bosses e pokémons da página DPS e o ranking de cada boss (equivale a
//! `app/services/dps_service.py`).
//!
//! Cada boss tem um tempo limite, a origem do dano no ranking e os pokémons marcados para ele.
//! O dano não é digitado no cadastro: vem da média dos testes, em cada skill e no ataque
//! básico, feitos no dummy ou dentro do boss, conforme a [`DamageSource`] dele. A conta fica em
//! [`super::calculator`] e o SQL em [`super::repository`].

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::sync::Arc;

use chrono::{Local, NaiveDateTime};
use serde::{Deserialize, Serialize};

use super::calculator::{
    DamageBreakdown, EffectivenessLevel, Element, PokemonSpec, SkillReach, SkillShape, calculate,
    validate_spec,
};
use super::repository as repo;
use crate::db::Database;
use crate::error::{Error, Result};
use crate::format::NumberFormat;
use crate::macros::text_enum;
use crate::text::{casefold, py_strip};

pub const DEFAULT_BASIC_TURN: f64 = 2.5;
pub const DEFAULT_TARGET_MELEE_EFFICIENCY: f64 = 0.75;
pub const DEFAULT_EFFICIENCY: f64 = 1.0;
pub const DEFAULT_BASIC_EFFICIENCY: f64 = 0.75;

pub const NEUTRAL_DUMMY: &str = "neutral";
/// Coluna `dummy` de um teste feito dentro de um boss.
pub const BOSS_TEST_DUMMY: &str = "boss";
pub const MAX_BOSS_ELEMENTS: usize = 2;
pub const DAMAGES_PER_TEST: usize = 3;

/// (valor gravado, nome exibido) dos dummies do jogo: o Neutro e o Normal são diferentes.
pub fn dummy_options() -> Vec<(&'static str, &'static str)> {
    std::iter::once((NEUTRAL_DUMMY, "Neutro"))
        .chain(Element::ALL.iter().map(|e| (e.as_str(), e.label())))
        .collect()
}

pub fn dummy_label(dummy: &str) -> String {
    dummy_options()
        .into_iter()
        .find(|(value, _)| *value == dummy)
        .map_or_else(|| dummy.to_owned(), |(_, label)| label.to_owned())
}

pub fn is_dummy(dummy: &str) -> bool {
    dummy_options().iter().any(|(value, _)| *value == dummy)
}

text_enum!(
    /// De onde vem o dano de cada skill no ranking de um boss.
    DamageSource {
        /// Teste no dummy Neutro × efetividade contra o boss.
        Effectiveness = "effectiveness" => "Efetividade",
        /// Teste no dummy escolhido no boss.
        Dummy = "dummy" => "Dummy",
        /// Teste dentro do boss, que já inclui a efetividade.
        Real = "real" => "Dano real",
    }
);

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct DpsSettings {
    pub basic_turn_seconds: f64,
    pub target_melee_efficiency: f64,
    pub default_efficiency: f64,
    pub basic_efficiency: f64,
    pub last_boss_id: Option<i64>,
}

impl Default for DpsSettings {
    fn default() -> Self {
        Self {
            basic_turn_seconds: DEFAULT_BASIC_TURN,
            target_melee_efficiency: DEFAULT_TARGET_MELEE_EFFICIENCY,
            default_efficiency: DEFAULT_EFFICIENCY,
            basic_efficiency: DEFAULT_BASIC_EFFICIENCY,
            last_boss_id: None,
        }
    }
}

impl DpsSettings {
    /// Aproveitamento sugerido: target melee exige achar um espaço colado no boss.
    pub fn suggested_efficiency(&self, shape: SkillShape, reach: SkillReach) -> f64 {
        if shape == SkillShape::Target && reach == SkillReach::Melee {
            self.target_melee_efficiency
        } else {
            self.default_efficiency
        }
    }
}

pub fn validate_settings(settings: &DpsSettings) -> Result<()> {
    if !settings.basic_turn_seconds.is_finite() || settings.basic_turn_seconds <= 0.0 {
        return Err(Error::user("O turno do ataque básico precisa ser maior que zero."));
    }
    let efficiencies =
        [settings.target_melee_efficiency, settings.default_efficiency, settings.basic_efficiency];
    if efficiencies.iter().any(|v| !(0.0..=1.0).contains(v)) {
        return Err(Error::user("Os aproveitamentos precisam estar entre 0% e 100%."));
    }
    Ok(())
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BossData {
    pub id: i64,
    pub name: String,
    pub time_limit_seconds: i64,
    pub pokemon_ids: BTreeSet<i64>,
    pub dummy: String,
    pub damage_source: DamageSource,
    /// Só informativos: a conta usa `effectiveness`.
    pub elements: Vec<Element>,
    /// Só o que difere de Normal, como o jogo lista contra aquele boss.
    pub effectiveness: BTreeMap<Element, EffectivenessLevel>,
}

impl BossData {
    /// Dummy de onde vem o dano; na origem Efetividade, é sempre o Neutro.
    pub fn base_dummy(&self) -> &str {
        if self.damage_source == DamageSource::Effectiveness { NEUTRAL_DUMMY } else { &self.dummy }
    }

    /// Multiplicador do elemento contra o boss; `None` se não houver elemento.
    pub fn multiplier(&self, element: Option<Element>) -> Option<f64> {
        element.map(|e| {
            self.effectiveness.get(&e).copied().unwrap_or(EffectivenessLevel::Normal).multiplier()
        })
    }
}

/// Danos medidos em um dummy ou boss; `None` é um dano ainda não preenchido.
///
/// A igualdade ignora as datas, como no Python: quem as define é o `save_damage_tests`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DamageTest {
    pub dummy: String,
    pub damages: Vec<Option<i64>>,
    /// Preenchido só em testes dentro de um boss.
    pub boss_id: Option<i64>,
    pub created_at: Option<NaiveDateTime>,
    pub updated_at: Option<NaiveDateTime>,
}

impl PartialEq for DamageTest {
    fn eq(&self, other: &Self) -> bool {
        self.dummy == other.dummy && self.damages == other.damages && self.boss_id == other.boss_id
    }
}

impl DamageTest {
    pub fn new(dummy: &str, damages: &[Option<i64>]) -> Self {
        Self {
            dummy: dummy.to_owned(),
            damages: damages.to_vec(),
            boss_id: None,
            created_at: None,
            updated_at: None,
        }
    }

    pub fn in_boss(boss_id: i64, damages: &[Option<i64>]) -> Self {
        Self { boss_id: Some(boss_id), ..Self::new(BOSS_TEST_DUMMY, damages) }
    }

    pub fn average(&self) -> Option<f64> {
        damage_average(&self.damages)
    }

    /// Os danos com `None` até completar [`DAMAGES_PER_TEST`].
    pub fn padded_damages(&self) -> [Option<i64>; DAMAGES_PER_TEST] {
        let mut damages = [None; DAMAGES_PER_TEST];
        for (slot, damage) in damages.iter_mut().zip(&self.damages) {
            *slot = *damage;
        }
        damages
    }
}

/// Média só dos danos preenchidos; `None` se não houver nenhum.
pub fn damage_average(damages: &[Option<i64>]) -> Option<f64> {
    let filled: Vec<i64> = damages.iter().flatten().copied().collect();
    if filled.is_empty() {
        None
    } else {
        Some(filled.iter().sum::<i64>() as f64 / filled.len() as f64)
    }
}

pub fn validate_tests(tests: &[DamageTest], boss_names: &HashMap<i64, String>) -> Result<()> {
    let mut seen: HashSet<(&str, Option<i64>)> = HashSet::new();
    for test in tests {
        let (kind, label) = match test.boss_id {
            Some(boss_id) => match boss_names.get(&boss_id) {
                Some(name) => ("Boss", name.clone()),
                None => return Err(Error::user("Boss não encontrado.")),
            },
            None if is_dummy(&test.dummy) => ("Dummy", dummy_label(&test.dummy)),
            None => return Err(Error::user("Escolha um dummy da lista.")),
        };
        if !seen.insert((test.dummy.as_str(), test.boss_id)) {
            return Err(Error::user(format!(
                "O {} {label} aparece em mais de um teste.",
                kind.to_lowercase()
            )));
        }
        let filled: Vec<i64> = test.damages.iter().flatten().copied().collect();
        if filled.is_empty() || test.damages.len() > DAMAGES_PER_TEST {
            return Err(Error::user(format!(
                "{kind} {label}: informe de 1 a {DAMAGES_PER_TEST} danos."
            )));
        }
        if filled.iter().any(|d| *d <= 0) {
            return Err(Error::user(format!("{kind} {label}: o dano precisa ser maior que zero.")));
        }
    }
    Ok(())
}

pub fn validate_boss_profile(elements: &[Element]) -> Result<()> {
    if elements.len() > MAX_BOSS_ELEMENTS {
        return Err(Error::user(format!("Um boss tem no máximo {MAX_BOSS_ELEMENTS} elementos.")));
    }
    if elements.iter().collect::<HashSet<_>>().len() != elements.len() {
        return Err(Error::user("Escolha dois elementos diferentes para o boss."));
    }
    Ok(())
}

/// Testes de um pokémon por skill; a chave `None` é o ataque básico.
pub type TestsBySkill = BTreeMap<Option<i64>, Vec<DamageTest>>;

#[derive(Debug, Clone, PartialEq)]
pub struct PokemonData {
    pub id: i64,
    pub name: String,
    pub note: String,
    /// Dano zerado: ele depende do dummy (ver [`spec_for_dummy`]).
    pub spec: PokemonSpec,
    pub boss_ids: BTreeSet<i64>,
    pub tests: TestsBySkill,
}

impl PokemonData {
    fn tests_of(&self, skill_id: Option<i64>) -> &[DamageTest] {
        self.tests.get(&skill_id).map_or(&[], Vec::as_slice)
    }

    /// Média do teste no dummy; `None` se a skill não foi testada nele.
    pub fn damage_on(&self, skill_id: Option<i64>, dummy: &str) -> Option<f64> {
        self.tests_of(skill_id).iter().find(|t| t.dummy == dummy).and_then(DamageTest::average)
    }

    /// Média do teste dentro do boss; `None` se a skill não foi testada nele.
    pub fn damage_in_boss(&self, skill_id: Option<i64>, boss_id: i64) -> Option<f64> {
        self.tests_of(skill_id)
            .iter()
            .find(|t| t.boss_id == Some(boss_id))
            .and_then(DamageTest::average)
    }
}

/// A ficha com o dano medido no dummy, e os nomes do que não foi testado nele.
pub fn spec_for_dummy(pokemon: &PokemonData, dummy: &str) -> (PokemonSpec, Vec<String>) {
    spec_with_damages(pokemon, |skill_id| pokemon.damage_on(skill_id, dummy))
}

/// A ficha com o dano da origem do boss, o que está sem teste e o que está sem elemento.
pub fn spec_for_boss(
    pokemon: &PokemonData,
    boss: &BossData,
) -> (PokemonSpec, Vec<String>, Vec<String>) {
    if boss.damage_source == DamageSource::Real {
        let (spec, missing) =
            spec_with_damages(pokemon, |skill_id| pokemon.damage_in_boss(skill_id, boss.id));
        return (spec, missing, Vec::new());
    }
    let (spec, missing) = spec_for_dummy(pokemon, boss.base_dummy());
    if boss.damage_source == DamageSource::Dummy {
        return (spec, missing, Vec::new());
    }
    let (spec, no_element) = with_effectiveness(spec, boss);
    (spec, missing, no_element)
}

fn with_effectiveness(mut spec: PokemonSpec, boss: &BossData) -> (PokemonSpec, Vec<String>) {
    let mut no_element = Vec::new();
    if let Some(basic) = &mut spec.basic {
        if basic.element.is_none() {
            no_element.push("Ataque básico".to_owned());
        }
        basic.multiplier = boss.multiplier(basic.element);
    }
    for (index, skill) in spec.skills.iter_mut().enumerate() {
        if skill.element.is_none() {
            no_element.push(skill.label(index + 1));
        }
        skill.multiplier = boss.multiplier(skill.element);
    }
    (spec, no_element)
}

fn spec_with_damages(
    pokemon: &PokemonData,
    damage_of: impl Fn(Option<i64>) -> Option<f64>,
) -> (PokemonSpec, Vec<String>) {
    let mut missing = Vec::new();
    let mut damage = |skill_id, label: String| match damage_of(skill_id) {
        Some(value) => value,
        None => {
            missing.push(label);
            0.0
        }
    };
    let mut spec = pokemon.spec.clone();
    // Como no Python: o básico entra na lista do que falta antes das skills.
    if let Some(basic) = &mut spec.basic {
        basic.damage = damage(None, "Ataque básico".to_owned());
    }
    for (index, skill) in spec.skills.iter_mut().enumerate() {
        skill.damage = damage(skill.skill_id, skill.label(index + 1));
    }
    (spec, missing)
}

#[derive(Debug, Clone, PartialEq)]
pub struct RankingEntry {
    pub position: usize,
    pub pokemon: PokemonData,
    pub breakdown: DamageBreakdown,
    /// Fração 0–1 do dano do 1º colocado.
    pub share_of_leader: f64,
    /// O que não foi testado na origem do boss (conta como 0).
    pub missing: Vec<String>,
    /// Na origem Efetividade, golpes sem elemento (contam como 0).
    pub no_element: Vec<String>,
}

/// Relógio usado nas datas dos testes; os testes automatizados trocam por um fixo.
pub type Clock = Arc<dyn Fn() -> NaiveDateTime + Send + Sync>;

pub fn system_clock() -> Clock {
    Arc::new(|| Local::now().naive_local())
}

pub struct DpsService<'a> {
    database: &'a Database,
    clock: Clock,
}

impl<'a> DpsService<'a> {
    pub fn new(database: &'a Database) -> Self {
        Self::with_clock(database, system_clock())
    }

    pub fn with_clock(database: &'a Database, clock: Clock) -> Self {
        Self { database, clock }
    }

    // ------------------------------------------------------------- ajustes

    pub fn settings(&self) -> Result<DpsSettings> {
        Ok(self.database.with(repo::settings)?.unwrap_or_default())
    }

    pub fn update_settings(&self, settings: &DpsSettings) -> Result<()> {
        validate_settings(settings)?;
        self.database.transaction(|tx| repo::save_settings(tx, settings))
    }

    pub fn remember_boss(&self, boss_id: i64) -> Result<()> {
        self.database.transaction(|tx| repo::set_last_boss(tx, boss_id))
    }

    // -------------------------------------------------------------- bosses

    pub fn list_bosses(&self) -> Result<Vec<BossData>> {
        self.database.with(repo::bosses)
    }

    /// Cria (`boss_id` `None`) ou altera um boss e devolve o id dele.
    ///
    /// Sem `elements` e `effectiveness`, os que o boss já tem continuam como estão.
    pub fn save_boss(
        &self,
        boss_id: Option<i64>,
        name: &str,
        time_limit_seconds: i64,
        elements: Option<&[Element]>,
        effectiveness: Option<&BTreeMap<Element, EffectivenessLevel>>,
    ) -> Result<i64> {
        let name = py_strip(name);
        if name.is_empty() {
            return Err(Error::user("Informe o nome do boss."));
        }
        if time_limit_seconds <= 0 {
            return Err(Error::user("O tempo limite precisa ser maior que zero."));
        }
        if let Some(elements) = elements {
            validate_boss_profile(elements)?;
        }
        self.database.transaction(|tx| {
            let bosses = repo::bosses(tx)?;
            let key = casefold(name);
            if bosses.iter().any(|b| Some(b.id) != boss_id && casefold(&b.name) == key) {
                return Err(Error::user(format!("Já existe um boss chamado {name}.")));
            }
            let current = boss_id.and_then(|id| bosses.into_iter().find(|b| b.id == id));
            let id = match &current {
                Some(boss) => {
                    repo::update_boss(tx, boss.id, name, time_limit_seconds)?;
                    boss.id
                }
                None => repo::insert_boss(tx, name, time_limit_seconds)?,
            };
            if elements.is_some() || effectiveness.is_some() {
                let (old_elements, old_effectiveness) = current
                    .map(|b| (b.elements, b.effectiveness))
                    .unwrap_or_default();
                repo::set_boss_profile(
                    tx,
                    id,
                    elements.unwrap_or(&old_elements),
                    effectiveness.unwrap_or(&old_effectiveness),
                )?;
            }
            Ok(id)
        })
    }

    /// Escolhe de qual dummy vem o dano no ranking deste boss.
    pub fn set_boss_dummy(&self, boss_id: i64, dummy: &str) -> Result<()> {
        if !is_dummy(dummy) {
            return Err(Error::user("Escolha um dummy da lista."));
        }
        self.database.transaction(|tx| {
            require_boss(repo::set_boss_column(tx, boss_id, "dummy", dummy)?)
        })
    }

    /// Escolhe como o ranking deste boss calcula o dano.
    pub fn set_boss_damage_source(&self, boss_id: i64, source: DamageSource) -> Result<()> {
        self.database.transaction(|tx| {
            require_boss(repo::set_boss_column(tx, boss_id, "damage_source", source.as_str())?)
        })
    }

    /// Remove o boss e os vínculos dele; os pokémons continuam cadastrados.
    pub fn delete_boss(&self, boss_id: i64) -> Result<()> {
        self.database.transaction(|tx| {
            if repo::boss_count(tx)? <= 1 {
                return Err(Error::user("O último boss não pode ser excluído."));
            }
            repo::delete_boss(tx, boss_id)
        })
    }

    pub fn set_boss_pokemons(&self, boss_id: i64, pokemon_ids: &[i64]) -> Result<()> {
        self.database.transaction(|tx| {
            if !repo::boss_exists(tx, boss_id)? {
                return Err(Error::user("Boss não encontrado."));
            }
            repo::set_boss_pokemons(tx, boss_id, pokemon_ids)
        })
    }

    // ------------------------------------------------------------ pokémons

    pub fn list_pokemons(&self) -> Result<Vec<PokemonData>> {
        self.database.with(|c| repo::pokemons(c, None))
    }

    /// Cria ou altera um pokémon; um pokémon novo entra no boss `boss_id`.
    ///
    /// O dano de `spec` é ignorado: ele vem dos testes. As skills são reaproveitadas pelo
    /// `skill_id`, porque os testes apontam para elas.
    pub fn save_pokemon(
        &self,
        pokemon_id: Option<i64>,
        name: &str,
        note: &str,
        spec: &PokemonSpec,
        boss_id: Option<i64>,
    ) -> Result<i64> {
        let name = py_strip(name);
        if name.is_empty() {
            return Err(Error::user("Informe o nome do pokémon."));
        }
        validate_spec(spec)?;
        self.database.transaction(|tx| {
            let existing = match pokemon_id {
                Some(id) if repo::pokemon_exists(tx, id)? => Some(id),
                _ => None,
            };
            let id = match existing {
                Some(id) => {
                    repo::update_pokemon(tx, id, name, py_strip(note))?;
                    id
                }
                None => {
                    let id = repo::insert_pokemon(tx, name, py_strip(note))?;
                    if let Some(boss_id) = boss_id {
                        if repo::boss_exists(tx, boss_id)? {
                            repo::link(tx, boss_id, id)?;
                        }
                    }
                    id
                }
            };
            repo::apply_spec(tx, id, spec)?;
            Ok(id)
        })
    }

    /// Cópia independente, com os testes e nos mesmos bosses do original.
    pub fn duplicate_pokemon(&self, pokemon_id: i64) -> Result<i64> {
        self.database.transaction(|tx| {
            let original = repo::pokemon(tx, pokemon_id)?
                .ok_or_else(|| Error::user("Pokémon não encontrado."))?;
            let copy = repo::insert_pokemon(tx, &format!("{} (cópia)", original.name), &original.note)?;
            // Sem ids na ficha, para criar skills novas em vez de mover as do original.
            let mut spec = original.spec.clone();
            for skill in &mut spec.skills {
                skill.skill_id = None;
            }
            let new_ids = repo::apply_spec(tx, copy, &spec)?;
            for boss_id in &original.boss_ids {
                repo::link(tx, *boss_id, copy)?;
            }
            let skill_map: HashMap<i64, i64> = original
                .spec
                .skills
                .iter()
                .filter_map(|s| s.skill_id)
                .zip(new_ids)
                .collect();
            // Na ordem dos ids originais, e com as datas: copiar não torna a medição mais nova.
            for (skill_id, test) in repo::damage_tests_in_order(tx, pokemon_id)? {
                let new_skill = skill_id.and_then(|id| skill_map.get(&id).copied());
                repo::insert_damage_test(tx, copy, new_skill, &test)?;
            }
            Ok(copy)
        })
    }

    pub fn delete_pokemon(&self, pokemon_id: i64) -> Result<()> {
        self.database.transaction(|tx| repo::delete_pokemon(tx, pokemon_id))
    }

    // -------------------------------------------------------------- testes

    /// Substitui os testes da skill (sem `skill_id`, os do ataque básico) e os devolve.
    ///
    /// Um teste é o mesmo se continua no mesmo dummy ou boss. Ele mantém as datas se os danos
    /// não mudaram e ganha a data de modificação se mudaram; em outro lugar, é um teste novo.
    pub fn save_damage_tests(
        &self,
        pokemon_id: i64,
        skill_id: Option<i64>,
        tests: &[DamageTest],
    ) -> Result<Vec<DamageTest>> {
        let now = (self.clock)();
        self.database.transaction(|tx| {
            let boss_names: HashMap<i64, String> =
                repo::bosses(tx)?.into_iter().map(|b| (b.id, b.name)).collect();
            validate_tests(tests, &boss_names)?;
            let previous: HashMap<(String, Option<i64>), DamageTest> =
                repo::damage_tests(tx, pokemon_id, skill_id)?
                    .into_iter()
                    .map(|t| ((t.dummy.clone(), t.boss_id), t))
                    .collect();
            repo::delete_damage_tests(tx, pokemon_id, skill_id)?;
            let mut saved = Vec::with_capacity(tests.len());
            for test in tests {
                let damages = test.padded_damages();
                let (created_at, updated_at) =
                    match previous.get(&(test.dummy.clone(), test.boss_id)) {
                        None => (Some(now), None),
                        Some(old) if old.padded_damages() != damages => {
                            (old.created_at, Some(now))
                        }
                        Some(old) => (old.created_at, old.updated_at),
                    };
                let row = DamageTest {
                    dummy: test.dummy.clone(),
                    damages: damages.to_vec(),
                    boss_id: test.boss_id,
                    created_at,
                    updated_at,
                };
                repo::insert_damage_test(tx, pokemon_id, skill_id, &row)?;
                saved.push(row);
            }
            Ok(saved)
        })
    }

    // ------------------------------------------------------------- ranking

    /// Pokémons marcados no boss, do maior para o menor dano na origem e tempo dele.
    pub fn ranking(&self, boss_id: i64, fmt: NumberFormat) -> Result<Vec<RankingEntry>> {
        let settings = self.settings()?;
        let Some((boss, pokemons)) = self.database.with(|c| {
            let Some(boss) = repo::boss(c, boss_id)? else { return Ok(None) };
            Ok(Some((boss, repo::pokemons(c, Some(boss_id))?)))
        })?
        else {
            return Ok(Vec::new());
        };
        let mut results: Vec<_> = pokemons
            .into_iter()
            .map(|pokemon| {
                let (spec, missing, no_element) = spec_for_boss(&pokemon, &boss);
                let breakdown = calculate(
                    &spec,
                    boss.time_limit_seconds as f64,
                    settings.basic_turn_seconds,
                    fmt,
                );
                (pokemon, breakdown, missing, no_element)
            })
            .collect();
        // Ordenação estável, do maior para o menor, como o `sort(reverse=True)` do Python.
        results.sort_by(|a, b| b.1.total.total_cmp(&a.1.total));
        let leader = results.first().map_or(0.0, |r| r.1.total);
        Ok(results
            .into_iter()
            .enumerate()
            .map(|(index, (pokemon, breakdown, missing, no_element))| RankingEntry {
                position: index + 1,
                share_of_leader: if leader > 0.0 { breakdown.total / leader } else { 0.0 },
                pokemon,
                breakdown,
                missing,
                no_element,
            })
            .collect())
    }
}

fn require_boss(changed: bool) -> Result<()> {
    if changed { Ok(()) } else { Err(Error::user("Boss não encontrado.")) }
}
