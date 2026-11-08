//! Exportação e importação dos cadastros da página DPS em um arquivo JSON (equivale a
//! `app/services/dps_transfer.py`). O formato é o mesmo: um arquivo exportado por uma versão
//! abre na outra.
//!
//! O arquivo leva bosses e pokémons, com os testes e as datas deles. Os bosses são citados pelo
//! nome, porque os ids mudam de um banco para outro. O conteúdo pode vir de outra pessoa, então
//! é validado por inteiro antes de gravar, e a importação acontece em uma única transação.
//! Os ajustes da página (turno do básico e aproveitamentos sugeridos) são de cada usuário e não
//! entram no arquivo.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::Path;
use std::str::FromStr;

use chrono::{DateTime, Local, NaiveDate, NaiveDateTime};
use serde_json::{Map, Value, json};

use super::calculator::{
    BasicAttackSpec, BuffSpec, EffectivenessLevel, Element, PokemonSpec, SkillReach, SkillShape,
    SkillSpec, validate_spec,
};
use super::repository as repo;
use super::service::{
    BOSS_TEST_DUMMY, BossData, DAMAGES_PER_TEST, DamageSource, DamageTest, DpsService,
    PokemonData, is_dummy, validate_boss_profile, validate_tests,
};
use crate::db::Database;
use crate::error::{Error, Result};
use crate::text::{casefold, py_strip, sort_casefold};

pub const FORMAT_ID: &str = "pxg-hunt-analyzer-dps";
pub const FORMAT_VERSION: i64 = 1;
pub const MAX_FILE_BYTES: u64 = 20 * 1024 * 1024;
pub const MAX_NAME_LENGTH: usize = 200;
pub const MAX_NOTE_LENGTH: usize = 10_000;
pub const MAX_DAMAGE: i64 = 1_000_000_000_000_000;
pub const MAX_TIME_LIMIT: i64 = 10_000_000;
pub const COPY_SUFFIX: &str = "importado";

/// Um teste no arquivo: em um dummy ou no boss citado pelo nome.
#[derive(Debug, Clone, PartialEq)]
pub struct BundleTest {
    pub dummy: String,
    pub boss: Option<String>,
    pub damages: [Option<i64>; DAMAGES_PER_TEST],
    pub created_at: Option<NaiveDateTime>,
    pub updated_at: Option<NaiveDateTime>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BundleBoss {
    pub name: String,
    pub time_limit_seconds: i64,
    pub dummy: String,
    pub damage_source: DamageSource,
    pub elements: Vec<Element>,
    pub effectiveness: BTreeMap<Element, EffectivenessLevel>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BundlePokemon {
    pub name: String,
    pub note: String,
    pub spec: PokemonSpec,
    pub bosses: Vec<String>,
    pub basic_tests: Vec<BundleTest>,
    /// Na ordem de `spec.skills`.
    pub skill_tests: Vec<Vec<BundleTest>>,
}

impl BundlePokemon {
    pub fn test_count(&self) -> usize {
        self.basic_tests.len() + self.skill_tests.iter().map(Vec::len).sum::<usize>()
    }
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct DpsBundle {
    pub bosses: Vec<BundleBoss>,
    pub pokemons: Vec<BundlePokemon>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ImportKind {
    Boss,
    Pokemon,
}

impl ImportKind {
    pub fn label(self) -> &'static str {
        match self {
            Self::Boss => "Boss",
            Self::Pokemon => "Pokémon",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ImportAction {
    Skip,
    /// Cadastro novo; com o nome em uso, é uma cópia "(importado)".
    Create,
    Replace,
}

/// Um cadastro do arquivo, o cadastro de mesmo nome (se houver) e o que fazer com ele.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ImportItem {
    pub kind: ImportKind,
    /// Posição em `DpsBundle::bosses` ou `DpsBundle::pokemons`.
    pub index: usize,
    pub name: String,
    pub existing_id: Option<i64>,
    pub action: ImportAction,
}

impl ImportItem {
    pub fn actions(&self) -> &'static [ImportAction] {
        match self.existing_id {
            None => &[ImportAction::Create, ImportAction::Skip],
            Some(_) => &[ImportAction::Skip, ImportAction::Replace, ImportAction::Create],
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ImportResult {
    pub created: usize,
    pub replaced: usize,
    pub skipped: usize,
    /// Testes e vínculos com bosses que não vieram no arquivo e não existem neste banco.
    pub dropped_tests: usize,
    pub dropped_links: usize,
}

// -------------------------------------------------------------- exportação

/// Monta o conteúdo do arquivo; `boss_names` tem todos os bosses, mesmo os não exportados.
pub fn build_bundle(
    bosses: &[BossData],
    pokemons: &[PokemonData],
    boss_names: &HashMap<i64, String>,
) -> DpsBundle {
    let bundle_test = |test: &DamageTest| BundleTest {
        dummy: test.dummy.clone(),
        boss: test.boss_id.and_then(|id| boss_names.get(&id).cloned()),
        damages: test.padded_damages(),
        created_at: test.created_at,
        updated_at: test.updated_at,
    };
    let tests_of = |pokemon: &PokemonData, skill_id| -> Vec<BundleTest> {
        pokemon.tests.get(&skill_id).map_or_else(Vec::new, |t| t.iter().map(bundle_test).collect())
    };
    DpsBundle {
        bosses: bosses
            .iter()
            .map(|boss| BundleBoss {
                name: boss.name.clone(),
                time_limit_seconds: boss.time_limit_seconds,
                dummy: boss.dummy.clone(),
                damage_source: boss.damage_source,
                elements: boss.elements.clone(),
                effectiveness: boss.effectiveness.clone(),
            })
            .collect(),
        pokemons: pokemons
            .iter()
            .map(|pokemon| {
                let mut names: Vec<String> =
                    pokemon.boss_ids.iter().filter_map(|id| boss_names.get(id).cloned()).collect();
                sort_casefold(&mut names, String::as_str);
                BundlePokemon {
                    name: pokemon.name.clone(),
                    note: pokemon.note.clone(),
                    spec: pokemon.spec.clone(),
                    bosses: names,
                    basic_tests: tests_of(pokemon, None),
                    skill_tests: pokemon
                        .spec
                        .skills
                        .iter()
                        .map(|skill| tests_of(pokemon, skill.skill_id))
                        .collect(),
                }
            })
            .collect(),
    }
}

/// `datetime.isoformat(timespec="seconds")` do Python.
fn iso_seconds(moment: NaiveDateTime) -> String {
    moment.format("%Y-%m-%dT%H:%M:%S").to_string()
}

fn element_json(element: Option<Element>) -> Value {
    element.map_or(Value::Null, |e| json!(e.as_str()))
}

fn test_json(test: &BundleTest) -> Value {
    json!({
        "dummy": if test.boss.is_some() { Value::Null } else { json!(test.dummy) },
        "boss": test.boss,
        "damages": test.damages,
        "created_at": test.created_at.map(iso_seconds),
        "updated_at": test.updated_at.map(iso_seconds),
    })
}

fn boss_json(boss: &BundleBoss) -> Value {
    let effectiveness: Map<String, Value> = boss
        .effectiveness
        .iter()
        .map(|(element, level)| (element.as_str().to_owned(), json!(level.as_str())))
        .collect();
    json!({
        "name": boss.name,
        "time_limit_seconds": boss.time_limit_seconds,
        "dummy": boss.dummy,
        "damage_source": boss.damage_source.as_str(),
        "elements": boss.elements.iter().map(|e| e.as_str()).collect::<Vec<_>>(),
        "effectiveness": effectiveness,
    })
}

fn pokemon_json(pokemon: &BundlePokemon) -> Value {
    let spec = &pokemon.spec;
    json!({
        "name": pokemon.name,
        "note": pokemon.note,
        "bosses": pokemon.bosses,
        "basic": spec.basic.as_ref().map(|basic| json!({
            "efficiency": basic.efficiency,
            "element": element_json(basic.element),
        })),
        "basic_tests": pokemon.basic_tests.iter().map(test_json).collect::<Vec<_>>(),
        "buff": spec.buff.as_ref().map(|buff| json!({
            "cooldown": buff.cooldown,
            "basic_multiplier": buff.basic_multiplier,
            "basic_duration": buff.basic_duration,
            "next_spell_multiplier": buff.next_spell_multiplier,
        })),
        "skills": spec.skills.iter().zip(&pokemon.skill_tests).map(|(skill, tests)| json!({
            "name": skill.name,
            "shape": skill.shape.as_str(),
            "reach": skill.reach.as_str(),
            "cooldown": skill.cooldown,
            "efficiency": skill.efficiency,
            "element": element_json(skill.element),
            "tests": tests.iter().map(test_json).collect::<Vec<_>>(),
        })).collect::<Vec<_>>(),
    })
}

pub fn bundle_to_json(bundle: &DpsBundle, exported_at: Option<NaiveDateTime>) -> String {
    let exported_at = exported_at.unwrap_or_else(|| Local::now().naive_local());
    let document = json!({
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "app_version": crate::APP_VERSION,
        "exported_at": iso_seconds(exported_at),
        "bosses": bundle.bosses.iter().map(boss_json).collect::<Vec<_>>(),
        "pokemons": bundle.pokemons.iter().map(pokemon_json).collect::<Vec<_>>(),
    });
    serde_json::to_string_pretty(&document).expect("o documento sempre vira JSON")
}

// ------------------------------------------------------------------ leitura

/// Falha ao ler um campo. `Incomplete` corresponde ao `KeyError`/`TypeError` do Python.
enum ParseError {
    Message(String),
    Incomplete(String),
}

type Parsed<T> = std::result::Result<T, ParseError>;

fn message(text: impl Into<String>) -> ParseError {
    ParseError::Message(text.into())
}

/// Acrescenta o contexto (`label: `) a uma mensagem de validação.
fn prefixed(label: &str, error: Error) -> ParseError {
    message(format!("{label}: {error}"))
}

fn object(value: &Value) -> Parsed<&Map<String, Value>> {
    value.as_object().ok_or_else(|| ParseError::Incomplete("esperava um objeto".to_owned()))
}

/// `data[key]` do Python: a chave precisa existir.
fn field<'v>(data: &'v Map<String, Value>, key: &str) -> Parsed<&'v Value> {
    data.get(key).ok_or_else(|| ParseError::Incomplete(format!("'{key}'")))
}

/// `data.get(key)` do Python.
fn optional<'v>(data: &'v Map<String, Value>, key: &str) -> &'v Value {
    data.get(key).unwrap_or(&Value::Null)
}

fn text(value: &Value, label: &str, limit: usize, required: bool) -> Parsed<String> {
    let Some(raw) = value.as_str() else {
        return Err(message(format!("{label}: texto inválido.")));
    };
    let text = py_strip(raw);
    if required && text.is_empty() {
        return Err(message(format!("{label}: não pode ficar vazio.")));
    }
    if text.chars().count() > limit {
        return Err(message(format!("{label}: texto longo demais.")));
    }
    Ok(text.to_owned())
}

fn name_text(value: &Value, label: &str, required: bool) -> Parsed<String> {
    text(value, label, MAX_NAME_LENGTH, required)
}

fn number(value: &Value, label: &str) -> Parsed<f64> {
    value
        .as_f64()
        .filter(|n| n.is_finite())
        .ok_or_else(|| message(format!("{label}: número inválido.")))
}

/// Inteiro do JSON (sem casas e sem `true`/`false`); `None` se não for.
fn integer(value: &Value) -> Option<i128> {
    match value {
        Value::Number(n) if n.is_i64() => n.as_i64().map(i128::from),
        Value::Number(n) if n.is_u64() => n.as_u64().map(i128::from),
        _ => None,
    }
}

fn enum_value<T: FromStr>(value: &Value, label: &str) -> Parsed<T> {
    value
        .as_str()
        .and_then(|t| T::from_str(t).ok())
        .ok_or_else(|| message(format!("{label}: valor desconhecido.")))
}

fn optional_element(value: &Value, label: &str) -> Parsed<Option<Element>> {
    if value.is_null() { Ok(None) } else { enum_value(value, label).map(Some) }
}

/// O que o `datetime.fromisoformat` aceita nos casos práticos; o fuso é descartado, porque o
/// banco guarda a hora local.
fn moment(value: &Value, label: &str) -> Parsed<Option<NaiveDateTime>> {
    if value.is_null() {
        return Ok(None);
    }
    let invalid = || message(format!("{label}: data inválida."));
    let text = value.as_str().ok_or_else(invalid)?;
    let naive = ["%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%d %H:%M:%S%.f", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"]
        .iter()
        .find_map(|fmt| NaiveDateTime::parse_from_str(text, fmt).ok())
        .or_else(|| DateTime::parse_from_rfc3339(text).ok().map(|d| d.naive_local()))
        .or_else(|| DateTime::parse_from_str(text, "%Y-%m-%d %H:%M:%S%.f%:z").ok().map(|d| d.naive_local()))
        .or_else(|| NaiveDate::parse_from_str(text, "%Y-%m-%d").ok().and_then(|d| d.and_hms_opt(0, 0, 0)));
    naive.map(Some).ok_or_else(invalid)
}

fn list<'v>(value: &'v Value, label: &str) -> Parsed<&'v Vec<Value>> {
    value.as_array().ok_or_else(|| message(format!("{label}: lista inválida.")))
}

fn parse_test(value: &Value, label: &str) -> Parsed<BundleTest> {
    let data = object(value)?;
    let boss = optional(data, "boss");
    let mut damages = Vec::new();
    for value in list(field(data, "damages")?, &format!("{label}: danos"))? {
        if value.is_null() {
            damages.push(None);
            continue;
        }
        match integer(value) {
            Some(damage) if damage <= i128::from(MAX_DAMAGE) => damages.push(Some(damage as i64)),
            _ => return Err(message(format!("{label}: dano inválido."))),
        }
    }
    if damages.len() > DAMAGES_PER_TEST {
        return Err(message(format!("{label}: informe no máximo {DAMAGES_PER_TEST} danos.")));
    }
    let mut padded = [None; DAMAGES_PER_TEST];
    padded[..damages.len()].copy_from_slice(&damages);
    let created_at = moment(optional(data, "created_at"), label)?;
    let updated_at = moment(optional(data, "updated_at"), label)?;
    if !boss.is_null() {
        return Ok(BundleTest {
            dummy: BOSS_TEST_DUMMY.to_owned(),
            boss: Some(name_text(boss, &format!("{label}: boss"), true)?),
            damages: padded,
            created_at,
            updated_at,
        });
    }
    // Um dummy que não é texto não está na lista, e a validação dos testes o recusa.
    let dummy = match field(data, "dummy")? {
        Value::String(text) => text.clone(),
        other => other.to_string(),
    };
    Ok(BundleTest { dummy, boss: None, damages: padded, created_at, updated_at })
}

fn parse_tests(values: &Value, label: &str) -> Parsed<Vec<BundleTest>> {
    let tests = list(values, &format!("{label}: testes"))?
        .iter()
        .map(|data| parse_test(data, label))
        .collect::<Parsed<Vec<_>>>()?;
    // Reaproveita a validação do cadastro; aqui o id do boss é só a identidade do nome.
    let mut names: Vec<String> = tests.iter().filter_map(|t| t.boss.as_deref().map(casefold)).collect();
    names.sort();
    names.dedup();
    let ids: HashMap<&str, i64> = names.iter().enumerate().map(|(i, n)| (n.as_str(), i as i64)).collect();
    let as_tests: Vec<DamageTest> = tests
        .iter()
        .map(|test| DamageTest {
            dummy: test.dummy.clone(),
            damages: test.damages.to_vec(),
            boss_id: test.boss.as_deref().map(|b| ids[casefold(b).as_str()]),
            created_at: None,
            updated_at: None,
        })
        .collect();
    let boss_names: HashMap<i64, String> = ids.iter().map(|(n, i)| (*i, (*n).to_owned())).collect();
    validate_tests(&as_tests, &boss_names).map_err(|e| prefixed(label, e))?;
    Ok(tests)
}

fn parse_boss(value: &Value) -> Parsed<BundleBoss> {
    let data = object(value)?;
    let name = name_text(field(data, "name")?, "Boss", true)?;
    let label = format!("Boss {name}");
    let limit = integer(field(data, "time_limit_seconds")?)
        .filter(|l| 0 < *l && *l <= i128::from(MAX_TIME_LIMIT))
        .ok_or_else(|| message(format!("{label}: tempo limite inválido.")))?;
    let dummy = field(data, "dummy")?
        .as_str()
        .filter(|d| is_dummy(d))
        .ok_or_else(|| message(format!("{label}: dummy desconhecido.")))?
        .to_owned();
    let elements = list(field(data, "elements")?, &format!("{label}: elementos"))?
        .iter()
        .map(|v| enum_value::<Element>(v, &format!("{label}: elemento")))
        .collect::<Parsed<Vec<_>>>()?;
    validate_boss_profile(&elements).map_err(|e| prefixed(&label, e))?;
    let effectiveness = field(data, "effectiveness")?
        .as_object()
        .ok_or_else(|| message(format!("{label}: efetividade inválida.")))?;
    let damage_source = enum_value(field(data, "damage_source")?, &format!("{label}: origem do dano"))?;
    let effectiveness_label = format!("{label}: efetividade");
    let effectiveness = effectiveness
        .iter()
        .map(|(element, level)| {
            Ok((
                enum_value(&Value::String(element.clone()), &effectiveness_label)?,
                enum_value(level, &effectiveness_label)?,
            ))
        })
        .collect::<Parsed<BTreeMap<_, _>>>()?;
    Ok(BundleBoss { name, time_limit_seconds: limit as i64, dummy, damage_source, elements, effectiveness })
}

fn parse_pokemon(value: &Value) -> Parsed<BundlePokemon> {
    let data = object(value)?;
    let name = name_text(field(data, "name")?, "Pokémon", true)?;
    let label = format!("Pokémon {name}");
    let mut skills = Vec::new();
    let mut skill_tests = Vec::new();
    for (index, skill) in list(field(data, "skills")?, &format!("{label}: skills"))?.iter().enumerate() {
        let skill = object(skill)?;
        let skill_label = format!("{label}, skill {}", index + 1);
        // Na ordem do Python, para o primeiro erro ser o mesmo.
        let skill_name = name_text(field(skill, "name")?, &skill_label, false)?;
        let shape: SkillShape = enum_value(field(skill, "shape")?, &format!("{skill_label}: forma"))?;
        let reach: SkillReach = enum_value(field(skill, "reach")?, &format!("{skill_label}: alcance"))?;
        let cooldown = number(field(skill, "cooldown")?, &format!("{skill_label}: recarga"))?;
        let efficiency = number(field(skill, "efficiency")?, &format!("{skill_label}: aproveitamento"))?;
        let element = optional_element(optional(skill, "element"), &format!("{skill_label}: elemento"))?;
        skills.push(SkillSpec {
            element,
            ..SkillSpec::new(skill_name, shape, reach, 0.0, cooldown, efficiency)
        });
        skill_tests.push(parse_tests(field(skill, "tests")?, &skill_label)?);
    }
    let basic = match optional(data, "basic") {
        Value::Null => None,
        basic => {
            let basic = object(basic)?;
            let basic_label = format!("{label}: básico");
            Some(BasicAttackSpec {
                element: optional_element(optional(basic, "element"), &basic_label)?,
                ..BasicAttackSpec::new(0.0, number(field(basic, "efficiency")?, &basic_label)?)
            })
        }
    };
    let buff = match optional(data, "buff") {
        Value::Null => None,
        buff => {
            let buff = object(buff)?;
            let buff_label = format!("{label}: buff");
            Some(BuffSpec::new(
                number(field(buff, "cooldown")?, &buff_label)?,
                number(field(buff, "basic_multiplier")?, &buff_label)?,
                number(field(buff, "basic_duration")?, &buff_label)?,
                number(field(buff, "next_spell_multiplier")?, &buff_label)?,
            ))
        }
    };
    let spec = PokemonSpec { skills, basic, buff };
    validate_spec(&spec).map_err(|e| prefixed(&label, e.into()))?;
    let note = match data.get("note") {
        None => String::new(),
        Some(note) => text(note, &format!("{label}: observação"), MAX_NOTE_LENGTH, false)?,
    };
    let bosses = list(field(data, "bosses")?, &format!("{label}: bosses"))?
        .iter()
        .map(|boss| name_text(boss, &format!("{label}: boss"), true))
        .collect::<Parsed<Vec<_>>>()?;
    let basic_tests = parse_tests(field(data, "basic_tests")?, &format!("{label}, ataque básico"))?;
    Ok(BundlePokemon { name, note, spec, bosses, basic_tests, skill_tests })
}

/// Lê o conteúdo do arquivo, com a mensagem para o usuário em caso de erro.
pub fn parse_bundle(text: &str) -> Result<DpsBundle> {
    let not_dps = || Error::user("Este arquivo não é uma exportação do DPS.");
    let data: Value =
        serde_json::from_str(text).map_err(|_| Error::user("O arquivo não é um JSON válido."))?;
    let Some(data) = data.as_object().filter(|d| d.get("format") == Some(&json!(FORMAT_ID))) else {
        return Err(not_dps());
    };
    let version = data.get("version").and_then(integer).ok_or_else(not_dps)?;
    if version > i128::from(FORMAT_VERSION) {
        return Err(Error::user(
            "O arquivo foi criado por uma versão mais nova do aplicativo. \
             Atualize o aplicativo para importá-lo.",
        ));
    }
    let parsed = (|| -> Parsed<DpsBundle> {
        let bosses = list(field(data, "bosses")?, "Bosses")?
            .iter()
            .map(parse_boss)
            .collect::<Parsed<Vec<_>>>()?;
        let pokemons = list(field(data, "pokemons")?, "Pokémons")?
            .iter()
            .map(parse_pokemon)
            .collect::<Parsed<Vec<_>>>()?;
        Ok(DpsBundle { bosses, pokemons })
    })();
    let bundle = parsed.map_err(|error| match error {
        ParseError::Message(text) => Error::user(text),
        ParseError::Incomplete(detail) => {
            Error::user(format!("O arquivo está incompleto ou foi alterado ({detail})."))
        }
    })?;
    let mut seen = HashSet::new();
    for boss in &bundle.bosses {
        if !seen.insert(casefold(&boss.name)) {
            return Err(Error::user(format!(
                "O boss {} aparece mais de uma vez no arquivo.",
                boss.name
            )));
        }
    }
    if bundle.bosses.is_empty() && bundle.pokemons.is_empty() {
        return Err(Error::user("O arquivo não tem bosses nem pokémons."));
    }
    Ok(bundle)
}

pub fn read_bundle(path: &Path) -> Result<DpsBundle> {
    let unreadable = |error: std::io::Error| Error::user(format!("Não foi possível ler o arquivo: {error}"));
    if std::fs::metadata(path).map_err(unreadable)?.len() > MAX_FILE_BYTES {
        return Err(Error::user("O arquivo é grande demais para ser uma exportação do DPS."));
    }
    let bytes = std::fs::read(path).map_err(unreadable)?;
    let bytes = bytes.strip_prefix(b"\xef\xbb\xbf").unwrap_or(&bytes);
    let text = std::str::from_utf8(bytes)
        .map_err(|_| Error::user("Este arquivo não é uma exportação do DPS."))?;
    parse_bundle(text)
}

// --------------------------------------------------------------- importação

/// O que há no arquivo e o padrão de cada um: importar o novo e pular o de nome repetido.
pub fn plan_import(bundle: &DpsBundle, bosses: &[BossData], pokemons: &[PokemonData]) -> Vec<ImportItem> {
    let default = |existing: Option<i64>| {
        if existing.is_none() { ImportAction::Create } else { ImportAction::Skip }
    };
    let boss_ids: HashMap<String, i64> = bosses.iter().map(|b| (casefold(&b.name), b.id)).collect();
    let mut items: Vec<ImportItem> = bundle
        .bosses
        .iter()
        .enumerate()
        .map(|(index, boss)| {
            let existing = boss_ids.get(&casefold(&boss.name)).copied();
            ImportItem {
                kind: ImportKind::Boss,
                index,
                name: boss.name.clone(),
                existing_id: existing,
                action: default(existing),
            }
        })
        .collect();
    // Pokémons podem repetir o nome: cada um do arquivo corresponde a no máximo um daqui.
    let mut by_id: Vec<&PokemonData> = pokemons.iter().collect();
    by_id.sort_by_key(|p| p.id);
    let mut available: HashMap<String, std::collections::VecDeque<i64>> = HashMap::new();
    for pokemon in by_id {
        available.entry(casefold(&pokemon.name)).or_default().push_back(pokemon.id);
    }
    for (index, pokemon) in bundle.pokemons.iter().enumerate() {
        let existing = available.get_mut(&casefold(&pokemon.name)).and_then(|ids| ids.pop_front());
        items.push(ImportItem {
            kind: ImportKind::Pokemon,
            index,
            name: pokemon.name.clone(),
            existing_id: existing,
            action: default(existing),
        });
    }
    items
}

fn copy_name(name: &str, taken: &mut HashSet<String>) -> String {
    let mut candidate = format!("{name} ({COPY_SUFFIX})");
    let mut number = 2;
    while taken.contains(&casefold(&candidate)) {
        candidate = format!("{name} ({COPY_SUFFIX} {number})");
        number += 1;
    }
    taken.insert(casefold(&candidate));
    candidate
}

pub struct DpsTransferService<'a> {
    database: &'a Database,
}

impl<'a> DpsTransferService<'a> {
    pub fn new(database: &'a Database) -> Self {
        Self { database }
    }

    fn dps(&self) -> DpsService<'a> {
        DpsService::new(self.database)
    }

    pub fn export_file(&self, path: &Path, boss_ids: &[i64], pokemon_ids: &[i64]) -> Result<()> {
        let bosses = self.dps().list_bosses()?;
        let names: HashMap<i64, String> = bosses.iter().map(|b| (b.id, b.name.clone())).collect();
        let chosen_bosses: Vec<BossData> =
            bosses.into_iter().filter(|b| boss_ids.contains(&b.id)).collect();
        let chosen_pokemons: Vec<PokemonData> = self
            .dps()
            .list_pokemons()?
            .into_iter()
            .filter(|p| pokemon_ids.contains(&p.id))
            .collect();
        let bundle = build_bundle(&chosen_bosses, &chosen_pokemons, &names);
        std::fs::write(path, bundle_to_json(&bundle, None))
            .map_err(|error| Error::user(format!("Não foi possível salvar o arquivo: {error}")))
    }

    pub fn plan(&self, bundle: &DpsBundle) -> Result<Vec<ImportItem>> {
        Ok(plan_import(bundle, &self.dps().list_bosses()?, &self.dps().list_pokemons()?))
    }

    /// Grava as escolhas de `items` de uma vez: se algo falhar, nada muda.
    pub fn apply(&self, bundle: &DpsBundle, items: &[ImportItem]) -> Result<ImportResult> {
        self.database.transaction(|tx| {
            let mut result = ImportResult::default();
            let count = |result: &mut ImportResult, action| match action {
                ImportAction::Create => result.created += 1,
                ImportAction::Replace => result.replaced += 1,
                ImportAction::Skip => result.skipped += 1,
            };
            let current_bosses = repo::bosses(tx)?;
            let current_pokemons = repo::pokemons(tx, None)?;
            let mut taken_bosses: HashSet<String> = current_bosses
                .iter()
                .map(|b| casefold(&b.name))
                .chain(bundle.bosses.iter().map(|b| casefold(&b.name)))
                .collect();
            let mut taken_pokemons: HashSet<String> = current_pokemons
                .iter()
                .map(|p| casefold(&p.name))
                .chain(bundle.pokemons.iter().map(|p| casefold(&p.name)))
                .collect();
            // Para qual boss deste banco aponta cada nome citado no arquivo.
            let mut boss_of_name: HashMap<String, i64> =
                current_bosses.iter().map(|b| (casefold(&b.name), b.id)).collect();
            let missing = |kind: &str| Error::user(format!("{kind} fora do arquivo."));

            for item in items.iter().filter(|i| i.kind == ImportKind::Boss) {
                count(&mut result, item.action);
                if item.action == ImportAction::Skip {
                    continue;
                }
                let data = bundle.bosses.get(item.index).ok_or_else(|| missing("Boss"))?;
                let replacing = match (item.action, item.existing_id) {
                    (ImportAction::Replace, Some(id)) if repo::boss_exists(tx, id)? => Some(id),
                    _ => None,
                };
                let boss_id = match replacing {
                    Some(id) => id,
                    None => {
                        let name = if item.existing_id.is_some() {
                            copy_name(&data.name, &mut taken_bosses)
                        } else {
                            data.name.clone()
                        };
                        repo::insert_boss(tx, &name, data.time_limit_seconds)?
                    }
                };
                repo::set_boss_time_limit(tx, boss_id, data.time_limit_seconds)?;
                repo::set_boss_column(tx, boss_id, "dummy", &data.dummy)?;
                repo::set_boss_column(tx, boss_id, "damage_source", data.damage_source.as_str())?;
                repo::set_boss_profile(tx, boss_id, &data.elements, &data.effectiveness)?;
                boss_of_name.insert(casefold(&data.name), boss_id);
            }

            for item in items.iter().filter(|i| i.kind == ImportKind::Pokemon) {
                count(&mut result, item.action);
                if item.action == ImportAction::Skip {
                    continue;
                }
                let data = bundle.pokemons.get(item.index).ok_or_else(|| missing("Pokémon"))?;
                let replacing = match (item.action, item.existing_id) {
                    (ImportAction::Replace, Some(id)) if repo::pokemon_exists(tx, id)? => Some(id),
                    _ => None,
                };
                let pokemon_id = match replacing {
                    Some(id) => {
                        // O arquivo substitui a ficha e os testes; o nome continua.
                        repo::delete_all_damage_tests(tx, id)?;
                        repo::set_pokemon_note(tx, id, &data.note)?;
                        id
                    }
                    None => {
                        let name = if item.existing_id.is_some() {
                            copy_name(&data.name, &mut taken_pokemons)
                        } else {
                            data.name.clone()
                        };
                        repo::insert_pokemon(tx, &name, &data.note)?
                    }
                };
                let mut spec = data.spec.clone();
                for skill in &mut spec.skills {
                    skill.skill_id = None;
                }
                let skill_ids = repo::apply_spec(tx, pokemon_id, &spec)?;
                // Substituir mantém os bosses que o pokémon já tinha.
                for boss_name in &data.bosses {
                    match boss_of_name.get(&casefold(boss_name)) {
                        Some(boss_id) => repo::link(tx, *boss_id, pokemon_id)?,
                        None => result.dropped_links += 1,
                    }
                }
                let groups = std::iter::once((None, &data.basic_tests))
                    .chain(skill_ids.iter().map(|id| Some(*id)).zip(&data.skill_tests));
                for (skill_id, tests) in groups {
                    for test in tests {
                        let boss_id = match &test.boss {
                            None => None,
                            Some(name) => match boss_of_name.get(&casefold(name)) {
                                Some(id) => Some(*id),
                                None => {
                                    result.dropped_tests += 1;
                                    continue;
                                }
                            },
                        };
                        let row = DamageTest {
                            dummy: test.dummy.clone(),
                            damages: test.damages.to_vec(),
                            boss_id,
                            created_at: test.created_at,
                            updated_at: test.updated_at,
                        };
                        repo::insert_damage_test(tx, pokemon_id, skill_id, &row)?;
                    }
                }
            }
            Ok(result)
        })
    }
}
