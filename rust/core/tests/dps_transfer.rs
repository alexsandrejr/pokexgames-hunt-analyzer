//! Porta de `tests/test_dps_transfer.py` (sem os testes das telas, que vêm na fase 4), mais a
//! compatibilidade do arquivo com o app Python.

use std::collections::{BTreeMap, HashMap};
use std::sync::Arc;

use chrono::{NaiveDate, NaiveDateTime};
use pxg_core::dps::calculator::{
    BasicAttackSpec, BuffSpec, EffectivenessLevel, Element, PokemonSpec, SkillReach, SkillShape,
    SkillSpec,
};
use pxg_core::dps::service::{DamageSource, DamageTest, DpsService, PokemonData};
use pxg_core::dps::transfer::{
    DpsBundle, DpsTransferService, FORMAT_ID, ImportAction, ImportItem, ImportResult,
    build_bundle, bundle_to_json, parse_bundle, read_bundle,
};
use pxg_core::format::NumberFormat;
use pxg_core::{Database, Error};
use serde_json::{Value, json};

const PYTHON_FILE: &str = include_str!("fixtures/dps_export_python.json");

fn moment(month: u32, day: u32, h: u32, m: u32, s: u32) -> NaiveDateTime {
    NaiveDate::from_ymd_opt(2026, month, day).unwrap().and_hms_opt(h, m, s).unwrap()
}

fn created() -> NaiveDateTime {
    moment(1, 2, 3, 4, 5)
}

fn updated() -> NaiveDateTime {
    moment(2, 3, 4, 5, 6)
}

fn skill(name: &str, cooldown: f64) -> SkillSpec {
    SkillSpec {
        element: Some(Element::Ice),
        ..SkillSpec::new(name, SkillShape::Target, SkillReach::Melee, 0., cooldown, 0.75)
    }
}

fn spec() -> PokemonSpec {
    PokemonSpec {
        skills: vec![skill("Golpe", 10.), skill("Outro", 20.)],
        basic: Some(BasicAttackSpec { element: Some(Element::Fire), ..BasicAttackSpec::new(0., 0.5) }),
        buff: Some(BuffSpec::new(60., 1.5, 10., 2.)),
    }
}

fn one_skill(name: &str) -> PokemonSpec {
    PokemonSpec { skills: vec![skill(name, 10.)], basic: None, buff: None }
}

fn padded(damages: &[Option<i64>]) -> DamageTest {
    let mut all = damages.to_vec();
    all.resize(3, None);
    DamageTest::new("", &all)
}

fn dummy_test(dummy: &str, damages: &[Option<i64>]) -> DamageTest {
    DamageTest { dummy: dummy.to_owned(), ..padded(damages) }
}

fn user_message<T: std::fmt::Debug>(result: pxg_core::Result<T>) -> String {
    match result {
        Err(Error::User(error)) => error.0,
        other => panic!("esperava erro para o usuário, veio {other:?}"),
    }
}

struct Fixture {
    source: Database,
    target: Database,
}

impl Fixture {
    fn new() -> Self {
        Self { source: Database::in_memory().unwrap(), target: Database::in_memory().unwrap() }
    }

    fn source_dps(&self) -> DpsService<'_> {
        DpsService::new(&self.source)
    }

    fn target_dps(&self) -> DpsService<'_> {
        DpsService::new(&self.target)
    }

    /// Na origem: um boss completo e um pokémon nele, com testes em dummy e no boss.
    fn seed(&self) -> (i64, i64) {
        let dps = self.source_dps();
        let effectiveness = BTreeMap::from([(Element::Fire, EffectivenessLevel::SuperEffective)]);
        let boss_id = dps
            .save_boss(None, "Venusaur", 300, Some(&[Element::Grass, Element::Poison]), Some(&effectiveness))
            .unwrap();
        dps.set_boss_damage_source(boss_id, DamageSource::Real).unwrap();
        dps.set_boss_dummy(boss_id, "ice").unwrap();
        let pokemon_id = dps.save_pokemon(None, "Muq", "Com boost", &spec(), Some(boss_id)).unwrap();
        let skill_id = pokemon(&dps, "Muq").spec.skills[0].skill_id;
        let at = |when: NaiveDateTime| DpsService::with_clock(&self.source, Arc::new(move || when));
        at(created())
            .save_damage_tests(pokemon_id, skill_id, &[
                dummy_test("neutral", &[Some(100), Some(200), None]),
                DamageTest::in_boss(boss_id, &[Some(300)]),
            ])
            .unwrap();
        at(created()).save_damage_tests(pokemon_id, None, &[dummy_test("ice", &[Some(50)])]).unwrap();
        at(updated()).save_damage_tests(pokemon_id, None, &[dummy_test("ice", &[Some(60)])]).unwrap();
        (boss_id, pokemon_id)
    }

    fn all_ids(&self) -> (Vec<i64>, Vec<i64>) {
        let dps = self.source_dps();
        (
            dps.list_bosses().unwrap().iter().map(|b| b.id).collect(),
            dps.list_pokemons().unwrap().iter().map(|p| p.id).collect(),
        )
    }

    fn bundle(&self, boss_ids: Option<Vec<i64>>, pokemon_ids: Option<Vec<i64>>) -> DpsBundle {
        let (all_bosses, all_pokemons) = self.all_ids();
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("cadastros.json");
        DpsTransferService::new(&self.source)
            .export_file(&path, &boss_ids.unwrap_or(all_bosses), &pokemon_ids.unwrap_or(all_pokemons))
            .unwrap();
        read_bundle(&path).unwrap()
    }

    fn plan(&self, bundle: &DpsBundle) -> Vec<ImportItem> {
        DpsTransferService::new(&self.target).plan(bundle).unwrap()
    }

    /// Importa com o padrão, trocando as ações dos nomes citados em `choices`.
    fn import(&self, bundle: &DpsBundle, choices: &[(&str, ImportAction)]) -> ImportResult {
        let chosen: HashMap<&str, ImportAction> = choices.iter().copied().collect();
        let items: Vec<ImportItem> = self
            .plan(bundle)
            .into_iter()
            .map(|item| ImportItem { action: chosen.get(item.name.as_str()).copied().unwrap_or(item.action), ..item })
            .collect();
        DpsTransferService::new(&self.target).apply(bundle, &items).unwrap()
    }
}

fn pokemon(dps: &DpsService<'_>, name: &str) -> PokemonData {
    dps.list_pokemons().unwrap().into_iter().find(|p| p.name == name).unwrap()
}

// ------------------------------------------------------------- ida e volta

#[test]
fn everything_arrives_in_an_empty_database() {
    let f = Fixture::new();
    f.seed();
    let result = f.import(&f.bundle(None, None), &[]);
    // "Padrão" existe nos dois bancos e, por padrão, é pulado.
    assert_eq!((result.created, result.replaced, result.skipped), (2, 0, 1));

    let target = f.target_dps();
    let boss = target.list_bosses().unwrap().into_iter().find(|b| b.name == "Venusaur").unwrap();
    assert_eq!(boss.time_limit_seconds, 300);
    assert_eq!(boss.dummy, "ice");
    assert_eq!(boss.damage_source, DamageSource::Real);
    assert_eq!(boss.elements, [Element::Grass, Element::Poison]);
    assert_eq!(boss.effectiveness, BTreeMap::from([(Element::Fire, EffectivenessLevel::SuperEffective)]));

    let muq = pokemon(&target, "Muq");
    assert_eq!(muq.note, "Com boost");
    assert_eq!(muq.spec, spec());
    assert_eq!(muq.boss_ids.iter().copied().collect::<Vec<_>>(), [boss.id]);
    let skill_id = muq.spec.skills[0].skill_id;
    assert_eq!(muq.tests[&skill_id], [
        dummy_test("neutral", &[Some(100), Some(200), None]),
        DamageTest::in_boss(boss.id, &[Some(300), None, None]),
    ]);
    assert_eq!(muq.tests[&None], [dummy_test("ice", &[Some(60), None, None])]);
    assert!(!muq.tests.contains_key(&muq.spec.skills[1].skill_id));
}

#[test]
fn dates_of_the_tests_are_kept() {
    let f = Fixture::new();
    f.seed();
    f.import(&f.bundle(None, None), &[]);
    let muq = pokemon(&f.target_dps(), "Muq");
    let basic = &muq.tests[&None][0];
    assert_eq!((basic.created_at, basic.updated_at), (Some(created()), Some(updated())));
    let first = &muq.tests[&muq.spec.skills[0].skill_id][0];
    assert_eq!((first.created_at, first.updated_at), (Some(created()), None));
}

#[test]
fn ranking_is_the_same_on_both_sides() {
    let f = Fixture::new();
    f.seed();
    f.import(&f.bundle(None, None), &[]);
    let total = |dps: DpsService<'_>| {
        let boss = dps.list_bosses().unwrap().into_iter().find(|b| b.name == "Venusaur").unwrap();
        dps.ranking(boss.id, NumberFormat::PT_BR).unwrap()[0].breakdown.total
    };
    let source = total(f.source_dps());
    assert!(source > 0.);
    assert_eq!(source, total(f.target_dps()));
}

#[test]
fn export_only_what_was_chosen() {
    let f = Fixture::new();
    let (boss_id, _) = f.seed();
    let other = f.source_dps().save_pokemon(None, "Jolt", "", &spec(), None).unwrap();
    let bundle = f.bundle(Some(vec![boss_id]), Some(vec![other]));
    assert_eq!(bundle.bosses.iter().map(|b| b.name.as_str()).collect::<Vec<_>>(), ["Venusaur"]);
    assert_eq!(bundle.pokemons.iter().map(|p| p.name.as_str()).collect::<Vec<_>>(), ["Jolt"]);
}

#[test]
fn export_does_not_change_the_database() {
    let f = Fixture::new();
    f.seed();
    let before = f.source_dps().list_pokemons().unwrap();
    f.bundle(None, None);
    assert_eq!(f.source_dps().list_pokemons().unwrap(), before);
}

// ------------------------------------------------------- compatibilidade

#[test]
fn python_file_is_read_exactly() {
    // Gerado por rust/tools/export_fixture.py com o mesmo cenário de `seed`.
    let f = Fixture::new();
    f.seed();
    assert_eq!(parse_bundle(PYTHON_FILE).unwrap(), f.bundle(None, None));
}

#[test]
fn rust_writes_the_same_file_as_python() {
    let f = Fixture::new();
    f.seed();
    let dps = f.source_dps();
    let bosses = dps.list_bosses().unwrap();
    let names = bosses.iter().map(|b| (b.id, b.name.clone())).collect();
    let bundle = build_bundle(&bosses, &dps.list_pokemons().unwrap(), &names);
    let text = bundle_to_json(&bundle, Some(moment(11, 7, 12, 0, 0)));
    let python = PYTHON_FILE.replace("\r\n", "\n");
    let python = python.trim_end().replace(
        "\"app_version\": \"1.6.0\"",
        &format!("\"app_version\": \"{}\"", pxg_core::APP_VERSION),
    );
    assert_eq!(text, python);
}

// ---------------------------------------------------------------- conflitos

#[test]
fn default_is_to_skip_repeated_names() {
    let f = Fixture::new();
    f.seed();
    f.target_dps().save_pokemon(None, "muq", "minha nota", &one_skill("Meu"), None).unwrap();
    let result = f.import(&f.bundle(None, None), &[]);
    assert_eq!(result.skipped, 2); // Padrão e muq
    let local: Vec<_> = f.target_dps().list_pokemons().unwrap().into_iter().filter(|p| p.name.to_lowercase() == "muq").collect();
    assert_eq!(local.len(), 1);
    assert_eq!(local[0].note, "minha nota");
}

#[test]
fn replace_changes_the_card_and_the_tests_but_keeps_the_id_and_bosses() {
    let f = Fixture::new();
    f.seed();
    let target = f.target_dps();
    let local_boss = target.list_bosses().unwrap().remove(0);
    let local = target.save_pokemon(None, "Muq", "antiga", &one_skill("Meu"), Some(local_boss.id)).unwrap();
    target.save_damage_tests(local, None, &[dummy_test("water", &[Some(999)])]).unwrap();
    let result = f.import(&f.bundle(None, None), &[("Muq", ImportAction::Replace)]);
    assert_eq!(result.replaced, 1);

    let muq = pokemon(&target, "Muq");
    assert_eq!(muq.id, local);
    assert_eq!(muq.note, "Com boost");
    assert_eq!(muq.spec, spec());
    assert_eq!(muq.tests[&None], [dummy_test("ice", &[Some(60), None, None])]);
    assert!(muq.boss_ids.contains(&local_boss.id)); // o vínculo que já existia continua
    assert_eq!(muq.boss_ids.len(), 2);
}

#[test]
fn copy_keeps_the_current_one_and_gets_a_free_name() {
    let f = Fixture::new();
    f.seed();
    let target = f.target_dps();
    target.save_pokemon(None, "Muq", "minha", &one_skill("Meu"), None).unwrap();
    target.save_pokemon(None, "Muq (importado)", "", &one_skill("Meu"), None).unwrap();
    f.import(&f.bundle(None, None), &[("Muq", ImportAction::Create)]);
    let mut names: Vec<String> = target.list_pokemons().unwrap().into_iter().map(|p| p.name).collect();
    names.sort();
    assert_eq!(names, ["Muq", "Muq (importado 2)", "Muq (importado)"]);
    assert_eq!(pokemon(&target, "Muq").note, "minha");
}

#[test]
fn replace_boss_keeps_its_pokemons() {
    let f = Fixture::new();
    f.seed();
    let target = f.target_dps();
    let boss = target.save_boss(None, "Venusaur", 60, None, None).unwrap();
    let local = target.save_pokemon(None, "Local", "", &one_skill("X"), Some(boss)).unwrap();
    f.import(&f.bundle(None, None), &[("Venusaur", ImportAction::Replace)]);
    let saved = target.list_bosses().unwrap().into_iter().find(|b| b.id == boss).unwrap();
    assert_eq!(saved.time_limit_seconds, 300);
    assert!(saved.pokemon_ids.contains(&local));
}

#[test]
fn pokemon_follows_a_copied_boss() {
    let f = Fixture::new();
    f.seed();
    let target = f.target_dps();
    let original = target.save_boss(None, "Venusaur", 60, None, None).unwrap();
    f.import(&f.bundle(None, None), &[("Venusaur", ImportAction::Create)]);
    let copy = target.list_bosses().unwrap().into_iter().find(|b| b.name == "Venusaur (importado)").unwrap();
    let muq = pokemon(&target, "Muq");
    assert!(muq.boss_ids.contains(&copy.id));
    assert!(!muq.boss_ids.contains(&original));
}

#[test]
fn skipped_boss_still_receives_the_pokemon_by_name() {
    let f = Fixture::new();
    f.seed();
    let target = f.target_dps();
    let local = target.save_boss(None, "VENUSAUR", 60, None, None).unwrap();
    f.import(&f.bundle(None, None), &[]);
    let saved = target.list_bosses().unwrap().into_iter().find(|b| b.id == local).unwrap();
    assert_eq!(saved.time_limit_seconds, 60);
    let muq = pokemon(&target, "Muq");
    assert_eq!(muq.boss_ids.iter().copied().collect::<Vec<_>>(), [local]);
    assert_eq!(muq.damage_in_boss(muq.spec.skills[0].skill_id, local), Some(300.));
}

#[test]
fn tests_in_an_unknown_boss_stay_out_and_are_counted() {
    let f = Fixture::new();
    let (_, pokemon_id) = f.seed();
    let bundle = f.bundle(Some(vec![]), Some(vec![pokemon_id])); // o boss não vai no arquivo
    let result = f.import(&bundle, &[]);
    assert_eq!((result.dropped_tests, result.dropped_links), (1, 1));
    let muq = pokemon(&f.target_dps(), "Muq");
    assert!(muq.boss_ids.is_empty());
    assert_eq!(muq.tests[&muq.spec.skills[0].skill_id], [dummy_test("neutral", &[Some(100), Some(200), None])]);
}

#[test]
fn two_with_the_same_name_in_the_file_replace_one_local_each() {
    let f = Fixture::new();
    f.source_dps().save_pokemon(None, "Muq", "A", &spec(), None).unwrap();
    f.source_dps().save_pokemon(None, "Muq", "B", &spec(), None).unwrap();
    let local = f.target_dps().save_pokemon(None, "Muq", "local", &spec(), None).unwrap();
    let bundle = f.bundle(None, None);
    let items: Vec<ImportItem> = f
        .plan(&bundle)
        .into_iter()
        .map(|item| if item.existing_id == Some(local) { ImportItem { action: ImportAction::Replace, ..item } } else { item })
        .collect();
    DpsTransferService::new(&f.target).apply(&bundle, &items).unwrap();
    let pokemons = f.target_dps().list_pokemons().unwrap();
    assert_eq!(pokemons.iter().filter(|p| p.name == "Muq").count(), 2);
    assert_eq!(pokemons.iter().find(|p| p.id == local).unwrap().note, "A");
}

#[test]
fn failure_in_the_middle_changes_nothing() {
    let f = Fixture::new();
    f.seed();
    let bundle = f.bundle(None, None);
    let before = f.target_dps().list_bosses().unwrap();
    let mut items = f.plan(&bundle);
    // Um item que aponta para fora do arquivo falha depois de o boss já ter sido gravado.
    let mut broken = items.iter().find(|i| i.name == "Muq").unwrap().clone();
    broken.index = 99;
    items.push(broken);
    assert!(DpsTransferService::new(&f.target).apply(&bundle, &items).is_err());
    assert_eq!(f.target_dps().list_bosses().unwrap(), before);
    assert!(f.target_dps().list_pokemons().unwrap().is_empty());
}

// --------------------------------------------------------- arquivos inválidos

fn valid() -> Value {
    serde_json::from_str(PYTHON_FILE).unwrap()
}

fn assert_rejected(data: &Value, fragment: &str) {
    let message = user_message(parse_bundle(&data.to_string()));
    assert!(message.contains(fragment), "esperava {fragment:?} em {message:?}");
}

#[test]
fn not_a_dps_file() {
    for text in ["não é json", "[]", r#"{"Session": {}}"#, r#"{"format": "outro", "version": 1}"#] {
        user_message(parse_bundle(text));
    }
}

#[test]
fn file_from_a_newer_version() {
    let message = user_message(parse_bundle(&json!({"format": FORMAT_ID, "version": 99}).to_string()));
    assert!(message.contains("versão mais nova"));
}

#[test]
fn empty_file() {
    let text = json!({"format": FORMAT_ID, "version": 1, "bosses": [], "pokemons": []}).to_string();
    assert!(user_message(parse_bundle(&text)).contains("não tem bosses nem pokémons"));
}

#[test]
fn nan_is_rejected() {
    let text = PYTHON_FILE.replacen("\"cooldown\": 10.0", "\"cooldown\": NaN", 1);
    assert!(text.contains("NaN"));
    assert!(user_message(parse_bundle(&text)).contains("JSON válido"));
}

#[test]
fn broken_fields_give_a_message_and_not_a_crash() {
    type Change = fn(&mut Value);
    let cases: Vec<(Change, &str)> = vec![
        (|d| { d["pokemons"][0].as_object_mut().unwrap().remove("skills"); }, "incompleto"),
        (|d| d["pokemons"][0]["name"] = json!(""), "vazio"),
        (|d| d["pokemons"][0]["name"] = json!(123), "texto"),
        (|d| d["pokemons"][0]["skills"] = json!("x"), "lista"),
        (|d| d["pokemons"][0]["skills"][0]["cooldown"] = json!(0), "recarga"),
        (|d| d["pokemons"][0]["skills"][0]["cooldown"] = json!(true), "número"),
        (|d| d["pokemons"][0]["skills"][0]["efficiency"] = json!(2), "aproveitamento"),
        (|d| d["pokemons"][0]["skills"][0]["element"] = json!("crystal"), "elemento"),
        (|d| d["pokemons"][0]["skills"][0]["tests"][0]["damages"] = json!([-1]), "maior"),
        (|d| d["pokemons"][0]["skills"][0]["tests"][0]["damages"] = json!([1e20]), "dano"),
        (|d| d["pokemons"][0]["skills"][0]["tests"][0]["damages"] = json!([1, 2, 3, 4]), "no máximo"),
        (|d| d["pokemons"][0]["skills"][0]["tests"][0]["created_at"] = json!("ontem"), "data"),
        (|d| d["pokemons"][0]["skills"][0]["tests"][0]["dummy"] = json!("crystal"), "dummy"),
        (|d| { let first = d["bosses"][0].clone(); d["bosses"].as_array_mut().unwrap().push(first); }, "mais de uma vez"),
        (|d| d["bosses"][0]["time_limit_seconds"] = json!(0), "tempo limite"),
        (|d| d["bosses"][0]["dummy"] = json!("x"), "dummy"),
        (|d| d["bosses"][0]["damage_source"] = json!("x"), "origem"),
        (|d| d["bosses"][0]["elements"] = json!(["fire", "ice", "water"]), "elementos"),
        (|d| d["bosses"][0]["effectiveness"] = json!({"fire": "x"}), "efetividade"),
    ];
    for (change, fragment) in cases {
        let mut data = valid();
        change(&mut data);
        assert_rejected(&data, fragment);
    }
}

#[test]
fn huge_number_is_rejected() {
    // O Python lê 10**400 e falha ao converter ("incompleto"); o leitor de JSON do Rust já o
    // recusa ao ler o arquivo. Nos dois casos, nada é importado e o usuário vê uma mensagem.
    let text = PYTHON_FILE.replacen("\"cooldown\": 10.0", &format!("\"cooldown\": 1{}", "0".repeat(400)), 1);
    user_message(parse_bundle(&text));
}

#[test]
fn missing_file_and_binary_file() {
    let dir = tempfile::tempdir().unwrap();
    assert!(user_message(read_bundle(&dir.path().join("nao_existe.json"))).contains("Não foi possível ler"));
    let binary = dir.path().join("foto.json");
    std::fs::write(&binary, b"\xff\xfe\x00\x01").unwrap();
    assert!(user_message(read_bundle(&binary)).contains("não é uma exportação"));
}

#[test]
fn file_with_bom_is_read() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("bom.json");
    std::fs::write(&path, format!("\u{feff}{PYTHON_FILE}")).unwrap();
    assert_eq!(read_bundle(&path).unwrap().pokemons.len(), 1);
}
