//! Porta de `ServiceTests` (`tests/test_dps.py`).

mod common;

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};

use chrono::{NaiveDate, NaiveDateTime};
use pxg_core::db::migrations::LATEST_VERSION;
use pxg_core::dps::calculator::{
    BasicAttackSpec, BuffSpec, EffectivenessLevel, Element, PokemonSpec, SkillReach, SkillShape,
    SkillSpec,
};
use pxg_core::dps::service::{
    BossData, DamageSource, DamageTest, DpsService, DpsSettings, PokemonData, RankingEntry,
    damage_average, dummy_options,
};
use pxg_core::format::NumberFormat;
use pxg_core::{Database, Error};

const BR: NumberFormat = NumberFormat::PT_BR;

/// `(dano, recarga, target)`: target melee a 75%, o resto área ranged a 100%.
fn skills(rows: &[(f64, f64, bool)]) -> Vec<SkillSpec> {
    rows.iter()
        .map(|&(damage, cooldown, target)| {
            if target {
                SkillSpec::new("", SkillShape::Target, SkillReach::Melee, damage, cooldown, 0.75)
            } else {
                SkillSpec::new("", SkillShape::Area, SkillReach::Ranged, damage, cooldown, 1.0)
            }
        })
        .collect()
}

fn area(rows: &[(f64, f64)]) -> Vec<SkillSpec> {
    skills(&rows.iter().map(|&(d, c)| (d, c, false)).collect::<Vec<_>>())
}

fn sandsmauro() -> Vec<SkillSpec> {
    skills(&[(14000., 8., false), (22500., 32., false), (12900., 12., false), (25500., 35., false),
        (43700., 50., false), (10700., 20., true), (7500., 20., true)])
}
fn maurolem() -> Vec<SkillSpec> {
    area(&[(18000., 12.), (16000., 12.), (9800., 8.), (19000., 30.), (42000., 50.), (11000., 40.),
        (15000., 40.)])
}
fn jolt() -> Vec<SkillSpec> {
    area(&[(41000., 50.), (7900., 12.), (9400., 10.), (14000., 12.), (14600., 25.), (22100., 40.),
        (8400., 25.)])
}
fn muq() -> Vec<SkillSpec> {
    area(&[(13000., 40.), (19000., 40.), (22000., 50.), (16000., 30.), (11600., 25.), (14700., 12.),
        (12200., 8.), (19000., 15.)])
}

fn only_skills(skills: Vec<SkillSpec>) -> PokemonSpec {
    PokemonSpec { skills, basic: None, buff: None }
}

fn day(day: u32) -> NaiveDateTime {
    NaiveDate::from_ymd_opt(2026, 11, day).unwrap().and_hms_opt(12, 0, 0).unwrap()
}

fn test(dummy: &str, damages: &[i64]) -> DamageTest {
    DamageTest::new(dummy, &damages.iter().map(|d| Some(*d)).collect::<Vec<_>>())
}

fn boss_test(boss_id: i64, damages: &[i64]) -> DamageTest {
    DamageTest::in_boss(boss_id, &damages.iter().map(|d| Some(*d)).collect::<Vec<_>>())
}

fn close(actual: f64, expected: f64) {
    assert!((actual - expected).abs() < 1e-6, "{actual} ≠ {expected}");
}

fn user_error<T: std::fmt::Debug>(result: pxg_core::Result<T>) -> String {
    match result {
        Err(Error::User(error)) => error.0,
        other => panic!("esperava erro para o usuário, veio {other:?}"),
    }
}

struct Fixture {
    database: Database,
    now: Arc<Mutex<NaiveDateTime>>,
    default_boss: BossData,
}

impl Fixture {
    fn new() -> Self {
        let database = Database::in_memory().unwrap();
        let now = Arc::new(Mutex::new(day(7)));
        let default_boss = DpsService::new(&database).list_bosses().unwrap().remove(0);
        Self { database, now, default_boss }
    }

    fn service(&self) -> DpsService<'_> {
        let now = Arc::clone(&self.now);
        DpsService::with_clock(&self.database, Arc::new(move || *now.lock().unwrap()))
    }

    /// Cadastra o pokémon no boss padrão e grava o dano de cada skill como teste no dummy.
    fn add(&self, name: &str, rows: Vec<SkillSpec>, boss_id: Option<i64>) -> i64 {
        let boss_id = boss_id.or(Some(self.default_boss.id));
        let service = self.service();
        let id = service.save_pokemon(None, name, "", &only_skills(rows.clone()), boss_id).unwrap();
        let pokemon = self.pokemon(id);
        for (skill, row) in pokemon.spec.skills.iter().zip(&rows) {
            service.save_damage_tests(id, skill.skill_id, &[test("neutral", &[row.damage as i64])]).unwrap();
        }
        id
    }

    fn add_default(&self, name: &str) -> i64 {
        self.add(name, sandsmauro(), None)
    }

    fn pokemon(&self, id: i64) -> PokemonData {
        self.service().list_pokemons().unwrap().into_iter().find(|p| p.id == id).unwrap()
    }

    fn ranking(&self, boss_id: i64) -> Vec<RankingEntry> {
        self.service().ranking(boss_id, BR).unwrap()
    }

    fn only(&self, boss_id: i64) -> RankingEntry {
        let mut ranking = self.ranking(boss_id);
        assert_eq!(ranking.len(), 1);
        ranking.remove(0)
    }

    /// Salva os testes como se fosse o dia `day` e devolve o primeiro, relido do banco.
    fn save_on(&self, on: u32, pokemon_id: i64, skill_id: Option<i64>, tests: &[DamageTest]) -> DamageTest {
        *self.now.lock().unwrap() = day(on);
        self.service().save_damage_tests(pokemon_id, skill_id, tests).unwrap();
        self.pokemon(pokemon_id).tests[&skill_id][0].clone()
    }

    fn with_tests(&self) -> (i64, i64) {
        let spec = PokemonSpec {
            skills: area(&[(0., 10.), (0., 20.)]),
            basic: Some(BasicAttackSpec::new(0., 0.75)),
            buff: None,
        };
        let service = self.service();
        let id = service.save_pokemon(None, "Muq", "", &spec, Some(self.default_boss.id)).unwrap();
        let skill_id = service.list_pokemons().unwrap()[0].spec.skills[0].skill_id.unwrap();
        service.save_damage_tests(id, Some(skill_id), &[test("neutral", &[100, 200, 300])]).unwrap();
        service.save_damage_tests(id, None, &[DamageTest::new("ice", &[Some(50), None, None])]).unwrap();
        (id, skill_id)
    }

    /// Boss de 420 s que recebe 2x de Ground.
    fn ground_boss(&self, source: DamageSource) -> i64 {
        let effectiveness = BTreeMap::from([(Element::Ground, EffectivenessLevel::SuperEffective)]);
        let service = self.service();
        let id = service.save_boss(None, "Onix", 420, Some(&[Element::Ground]), Some(&effectiveness)).unwrap();
        service.set_boss_damage_source(id, source).unwrap();
        id
    }

    /// Steelix com Sand Tomb (100 s), anexado ao boss.
    fn steelix(&self, boss_id: i64, element: Option<Element>) -> (i64, i64) {
        let skill = SkillSpec { name: "Sand Tomb".into(), element, ..area(&[(0., 100.)]).remove(0) };
        let id = self.service().save_pokemon(None, "Steelix", "", &only_skills(vec![skill]), Some(boss_id)).unwrap();
        (id, self.pokemon(id).spec.skills[0].skill_id.unwrap())
    }

    fn count(&self, table: &str) -> i64 {
        self.database
            .with(|c| Ok(c.query_row(&format!("SELECT count(*) FROM {table}"), [], |r| r.get(0))?))
            .unwrap()
    }
}

fn ids(ranking: &[RankingEntry]) -> Vec<i64> {
    ranking.iter().map(|e| e.pokemon.id).collect()
}

#[test]
fn new_database_has_default_boss() {
    let f = Fixture::new();
    let boss = &f.default_boss;
    assert_eq!((boss.name.as_str(), boss.time_limit_seconds, boss.dummy.as_str()), ("Padrão", 420, "neutral"));
}

#[test]
fn ranking_orders_by_damage_and_shows_only_selected_pokemons() {
    let f = Fixture::new();
    let low = f.add("Jolt", jolt(), None);
    let high = f.add("Muq", muq(), None);
    let other = f.service().save_boss(None, "Terror", 300, None, None).unwrap();
    f.add("Fora", maurolem(), Some(other));

    let ranking = f.ranking(f.default_boss.id);
    assert_eq!(ids(&ranking), [high, low]);
    assert_eq!(ranking.iter().map(|e| e.position).collect::<Vec<_>>(), [1, 2]);
    assert_eq!(ranking[0].share_of_leader, 1.0);
    close(ranking[1].share_of_leader, 2124150. / 2626680.);
    close(ranking[0].breakdown.total, 2626680.);
    assert!(ranking[0].missing.is_empty());
}

#[test]
fn boss_time_limit_changes_the_total() {
    let f = Fixture::new();
    f.add("Muq", muq(), None);
    f.service().save_boss(Some(f.default_boss.id), "Padrão", 210, None, None).unwrap();
    close(f.only(f.default_boss.id).breakdown.total, 2626680. / 2.);
}

#[test]
fn ranking_uses_the_dummy_chosen_for_each_boss() {
    let f = Fixture::new();
    let service = f.service();
    let id = service.save_pokemon(None, "Muq", "", &only_skills(area(&[(0., 10.)])), Some(f.default_boss.id)).unwrap();
    let skill_id = f.pokemon(id).spec.skills[0].skill_id;
    service
        .save_damage_tests(id, skill_id, &[
            DamageTest::new("neutral", &[Some(1000), Some(3000), None]),
            DamageTest::new("water", &[Some(500), None, None]),
        ])
        .unwrap();
    let terror = service.save_boss(None, "Terror", 420, None, None).unwrap();
    service.set_boss_pokemons(terror, &[id]).unwrap();
    service.set_boss_dummy(terror, "water").unwrap();

    close(f.only(f.default_boss.id).breakdown.total, 2000. / 10. * 420.);
    close(f.only(terror).breakdown.total, 500. / 10. * 420.);
}

#[test]
fn skill_without_test_on_the_dummy_is_zero_and_listed() {
    let f = Fixture::new();
    let service = f.service();
    let spec = PokemonSpec {
        skills: vec![SkillSpec::new("Golpe", SkillShape::Area, SkillReach::Ranged, 0., 10., 1.)],
        basic: Some(BasicAttackSpec::new(0., 1.)),
        buff: None,
    };
    let id = service.save_pokemon(None, "Muq", "", &spec, Some(f.default_boss.id)).unwrap();
    let skill_id = f.pokemon(id).spec.skills[0].skill_id;
    service.save_damage_tests(id, skill_id, &[test("neutral", &[1000])]).unwrap();
    service.set_boss_dummy(f.default_boss.id, "water").unwrap();

    let entry = f.only(f.default_boss.id); // sem usar o Neutro como substituto
    assert_eq!(entry.breakdown.total, 0.);
    assert_eq!(entry.missing, ["Ataque básico", "Golpe"]);
    assert_eq!(entry.share_of_leader, 0.);
}

#[test]
fn set_boss_dummy_validation() {
    let f = Fixture::new();
    for (boss_id, dummy) in [(f.default_boss.id, "crystal"), (999, "water")] {
        user_error(f.service().set_boss_dummy(boss_id, dummy));
    }
}

#[test]
fn basic_turn_setting_changes_the_ranking() {
    let f = Fixture::new();
    let service = f.service();
    let spec = PokemonSpec { skills: vec![], basic: Some(BasicAttackSpec::new(0., 1.)), buff: None };
    let id = service.save_pokemon(None, "Básico", "", &spec, Some(f.default_boss.id)).unwrap();
    service.save_damage_tests(id, None, &[test("neutral", &[1000])]).unwrap();
    service.update_settings(&DpsSettings { basic_turn_seconds: 5., ..DpsSettings::default() }).unwrap();
    close(f.only(f.default_boss.id).breakdown.total, 1000. / 5. * 420.);
}

#[test]
fn settings_validation_and_suggestions() {
    let f = Fixture::new();
    let service = f.service();
    user_error(service.update_settings(&DpsSettings { basic_turn_seconds: 0., ..DpsSettings::default() }));
    user_error(service.update_settings(&DpsSettings { basic_efficiency: 1.1, ..DpsSettings::default() }));
    service.update_settings(&DpsSettings { target_melee_efficiency: 0.5, ..DpsSettings::default() }).unwrap();
    let settings = service.settings().unwrap();
    assert_eq!(settings.suggested_efficiency(SkillShape::Target, SkillReach::Melee), 0.5);
    assert_eq!(settings.suggested_efficiency(SkillShape::Target, SkillReach::Ranged), 1.);
    assert_eq!(settings.suggested_efficiency(SkillShape::Area, SkillReach::Melee), 1.);
}

#[test]
fn pokemon_round_trip_and_edit_replaces_skills() {
    let f = Fixture::new();
    let service = f.service();
    let spec = PokemonSpec {
        skills: skills(&[(0., 10., false), (0., 20., true)]),
        basic: Some(BasicAttackSpec::new(0., 0.75)),
        buff: Some(BuffSpec::new(50., 2., 15., 1.5)),
    };
    let id = service.save_pokemon(None, " Chumbin ", " +70 ", &spec, Some(f.default_boss.id)).unwrap();
    let saved = service.list_pokemons().unwrap().remove(0);
    assert_eq!((saved.id, saved.name.as_str(), saved.note.as_str()), (id, "Chumbin", "+70"));
    assert_eq!(saved.spec, spec);
    assert_eq!(saved.boss_ids.iter().copied().collect::<Vec<_>>(), [f.default_boss.id]);

    let edited = only_skills(area(&[(0., 30.)]));
    service.save_pokemon(Some(id), "Chumbin", "", &edited, None).unwrap();
    let saved = service.list_pokemons().unwrap().remove(0);
    assert_eq!(saved.spec, edited);
    assert_eq!(saved.boss_ids.iter().copied().collect::<Vec<_>>(), [f.default_boss.id]); // editar mantém os vínculos
}

#[test]
fn damage_in_the_spec_is_ignored_when_saving() {
    let f = Fixture::new();
    let id = f.service().save_pokemon(None, "Muq", "", &only_skills(area(&[(9999., 10.)])), None).unwrap();
    assert_eq!(f.pokemon(id).spec.skills[0].damage, 0.);
}

#[test]
fn duplicate_goes_to_the_same_bosses_with_independent_tests() {
    let f = Fixture::new();
    let service = f.service();
    let other = service.save_boss(None, "Terror", 300, None, None).unwrap();
    let original = f.add("Muq", muq(), None);
    service.set_boss_pokemons(other, &[original]).unwrap();
    service.save_damage_tests(original, None, &[test("ice", &[50])]).unwrap();
    let copy_id = service.duplicate_pokemon(original).unwrap();

    let (copy, source) = (f.pokemon(copy_id), f.pokemon(original));
    assert_eq!(copy.name, "Muq (cópia)");
    assert_eq!(copy.spec, source.spec);
    assert_eq!(copy.boss_ids.iter().copied().collect::<Vec<_>>(), {
        let mut expected = vec![f.default_boss.id, other];
        expected.sort();
        expected
    });
    assert_ne!(copy.spec.skills[0].skill_id, source.spec.skills[0].skill_id);
    assert_eq!(copy.damage_on(copy.spec.skills[0].skill_id, "neutral"), Some(13000.));
    assert_eq!(copy.damage_on(None, "ice"), Some(50.));
    assert_eq!(source.tests.len(), copy.tests.len()); // o original não perde nada

    service.save_damage_tests(copy_id, copy.spec.skills[0].skill_id, &[test("neutral", &[1])]).unwrap();
    assert_eq!(f.pokemon(original).damage_on(source.spec.skills[0].skill_id, "neutral"), Some(13000.));
    service.delete_pokemon(original).unwrap(); // a cópia é independente
    assert_eq!(f.ranking(other)[0].pokemon.id, copy_id);
}

#[test]
fn set_boss_pokemons() {
    let f = Fixture::new();
    let first = f.add_default("A");
    let second = f.add_default("B");
    f.service().set_boss_pokemons(f.default_boss.id, &[second]).unwrap();
    assert_eq!(ids(&f.ranking(f.default_boss.id)), [second]);
    let all: Vec<i64> = f.service().list_pokemons().unwrap().iter().map(|p| p.id).collect();
    assert_eq!(all, [first, second]);
}

#[test]
fn deleting_boss_keeps_pokemons_and_last_boss_is_protected() {
    let f = Fixture::new();
    let service = f.service();
    user_error(service.delete_boss(f.default_boss.id));
    let other = service.save_boss(None, "Terror", 300, None, None).unwrap();
    let pokemon = f.add("Muq", muq(), Some(other));
    service.remember_boss(other).unwrap();
    service.delete_boss(other).unwrap();
    let saved = service.list_pokemons().unwrap().remove(0);
    assert_eq!(saved.id, pokemon);
    assert!(saved.boss_ids.is_empty());
    assert_eq!(service.settings().unwrap().last_boss_id, None);
}

#[test]
fn deleting_pokemon_removes_it_from_every_boss() {
    let f = Fixture::new();
    let service = f.service();
    let other = service.save_boss(None, "Terror", 300, None, None).unwrap();
    let pokemon = f.add("Muq", muq(), None);
    service.set_boss_pokemons(other, &[pokemon]).unwrap();
    service.delete_pokemon(pokemon).unwrap();
    assert!(f.ranking(f.default_boss.id).is_empty());
    assert!(f.ranking(other).is_empty());
}

#[test]
fn boss_validation() {
    let f = Fixture::new();
    for (name, seconds) in [("", 60), ("Terror", 0), ("padrão", 60)] {
        user_error(f.service().save_boss(None, name, seconds, None, None));
    }
    f.service().save_boss(Some(f.default_boss.id), "PADRÃO", 60, None, None).unwrap(); // o próprio nome pode
}

#[test]
fn pokemon_validation() {
    let f = Fixture::new();
    user_error(f.service().save_pokemon(None, " ", "", &only_skills(muq()), None));
    user_error(f.service().save_pokemon(None, "Vazio", "", &PokemonSpec::default(), None));
    assert!(f.service().list_pokemons().unwrap().is_empty());
}

#[test]
fn dummies_are_neutral_and_the_18_elements() {
    let options = dummy_options();
    assert_eq!(options.len(), 19);
    let label = |value| options.iter().find(|(v, _)| *v == value).map(|(_, l)| *l);
    assert_eq!(label("neutral"), Some("Neutro"));
    assert_eq!(label("normal"), Some("Normal"));
    assert_eq!(label("fighting"), Some("Fighting"));
    assert_eq!(label("crystal"), None);
}

#[test]
fn average_uses_only_filled_damages() {
    assert_eq!(damage_average(&[Some(100), None, Some(300)]), Some(200.));
    assert_eq!(damage_average(&[None, None, None]), None);
    assert_eq!(test("ice", &[100, 200, 300]).average(), Some(200.));
}

#[test]
fn tests_round_trip_and_replace() {
    let f = Fixture::new();
    let (id, skill_id) = f.with_tests();
    let expected = BTreeMap::from([
        (None, vec![DamageTest::new("ice", &[Some(50), None, None])]),
        (Some(skill_id), vec![test("neutral", &[100, 200, 300])]),
    ]);
    assert_eq!(f.pokemon(id).tests, expected);
    f.service().save_damage_tests(id, Some(skill_id), &[]).unwrap();
    assert_eq!(f.pokemon(id).tests.keys().copied().collect::<Vec<_>>(), [None]);
}

#[test]
fn tests_validation() {
    let f = Fixture::new();
    let (id, skill_id) = f.with_tests();
    let invalid = [
        vec![DamageTest::new("crystal", &[Some(1), None, None])],
        vec![DamageTest::new("ice", &[None, None, None])],
        vec![DamageTest::new("ice", &[Some(0), None, None])],
        vec![test("ice", &[1, 2, 3, 4])],
        vec![test("ice", &[1]), test("ice", &[2])],
    ];
    for tests in invalid {
        user_error(f.service().save_damage_tests(id, Some(skill_id), &tests));
    }
    assert_eq!(f.pokemon(id).tests[&Some(skill_id)], [test("neutral", &[100, 200, 300])]); // nada mudou
}

#[test]
fn new_test_has_only_the_created_date() {
    let f = Fixture::new();
    let id = f.add_default("Muq");
    let saved = f.save_on(1, id, None, &[test("ice", &[100])]);
    assert_eq!((saved.created_at, saved.updated_at), (Some(day(1)), None));
}

#[test]
fn saving_the_same_damages_keeps_the_dates() {
    let f = Fixture::new();
    let id = f.add_default("Muq");
    f.save_on(1, id, None, &[test("ice", &[100])]);
    let saved = f.save_on(2, id, None, &[DamageTest::new("ice", &[Some(100), None, None])]);
    assert_eq!((saved.created_at, saved.updated_at), (Some(day(1)), None));
}

#[test]
fn changing_a_damage_records_the_modification() {
    let f = Fixture::new();
    let id = f.add_default("Muq");
    f.save_on(1, id, None, &[test("ice", &[100])]);
    f.save_on(2, id, None, &[test("ice", &[150])]);
    let saved = f.save_on(3, id, None, &[test("ice", &[150])]);
    assert_eq!((saved.created_at, saved.updated_at), (Some(day(1)), Some(day(2))));
}

#[test]
fn test_in_another_place_is_a_new_test() {
    let f = Fixture::new();
    let id = f.add_default("Muq");
    f.save_on(1, id, None, &[test("ice", &[100])]);
    let saved = f.save_on(2, id, None, &[test("water", &[100])]);
    assert_eq!((saved.created_at, saved.updated_at), (Some(day(2)), None));
}

#[test]
fn changing_one_test_keeps_the_dates_of_the_others() {
    let f = Fixture::new();
    let id = f.add_default("Muq");
    f.save_on(1, id, None, &[test("ice", &[100]), test("water", &[5])]);
    f.save_on(2, id, None, &[test("ice", &[100]), test("water", &[6])]);
    let tests = &f.pokemon(id).tests[&None];
    assert_eq!(tests[0].updated_at, None);
    assert_eq!(tests[1].updated_at, Some(day(2)));
}

#[test]
fn duplicate_keeps_the_dates_of_the_tests() {
    let f = Fixture::new();
    let id = f.add_default("Muq");
    f.save_on(1, id, None, &[test("ice", &[100])]);
    f.save_on(2, id, None, &[test("ice", &[150])]);
    let copy = f.pokemon(f.service().duplicate_pokemon(id).unwrap());
    let copied = &copy.tests[&None][0];
    assert_eq!((copied.created_at, copied.updated_at), (Some(day(1)), Some(day(2))));
}

#[test]
fn editing_keeps_tests_of_remaining_skills() {
    let f = Fixture::new();
    let (id, skill_id) = f.with_tests();
    let current = f.pokemon(id).spec.skills;
    let (first, second) = (current[0].clone(), current[1].clone());
    let changed = SkillSpec { cooldown: 99., element: Some(Element::Grass), ..first };
    let new = PokemonSpec {
        skills: vec![second.clone(), changed], // ordem trocada
        basic: Some(BasicAttackSpec::new(0., 0.75)),
        buff: None,
    };
    f.service().save_pokemon(Some(id), "Muq", "", &new, None).unwrap();
    let saved = f.pokemon(id);
    let skill_ids: Vec<_> = saved.spec.skills.iter().map(|s| s.skill_id).collect();
    assert_eq!(skill_ids, [second.skill_id, Some(skill_id)]);
    assert_eq!(saved.spec.skills[1].cooldown, 99.);
    assert!(saved.tests.contains_key(&Some(skill_id)));
}

#[test]
fn removing_a_skill_removes_its_tests_only() {
    let f = Fixture::new();
    let (id, _skill_id) = f.with_tests();
    let second = f.pokemon(id).spec.skills[1].clone();
    let spec = PokemonSpec { skills: vec![second], basic: Some(BasicAttackSpec::new(0., 0.75)), buff: None };
    f.service().save_pokemon(Some(id), "Muq", "", &spec, None).unwrap();
    assert_eq!(f.pokemon(id).tests.keys().copied().collect::<Vec<_>>(), [None]);
}

#[test]
fn removing_basic_keeps_its_tests_for_when_it_returns() {
    let f = Fixture::new();
    let (id, _skill_id) = f.with_tests();
    let skills = f.pokemon(id).spec.skills;
    f.service().save_pokemon(Some(id), "Muq", "", &only_skills(skills), None).unwrap();
    assert!(f.pokemon(id).spec.basic.is_none());
    assert!(f.pokemon(id).tests.contains_key(&None));
}

#[test]
fn deleting_pokemon_removes_its_tests() {
    let f = Fixture::new();
    let (id, _skill_id) = f.with_tests();
    f.service().delete_pokemon(id).unwrap();
    assert_eq!(f.count("dps_damage_tests"), 0);
}

#[test]
fn default_boss_is_not_created_again() {
    let dir = tempfile::tempdir().unwrap();
    let database = Database::open(&dir.path().join("hunts.db")).unwrap();
    database.create_schema().unwrap();
    let service = DpsService::new(&database);
    let renamed = service.list_bosses().unwrap()[0].id;
    service.save_boss(Some(renamed), "Terror", 300, None, None).unwrap();
    database.create_schema().unwrap();
    let names: Vec<String> = service.list_bosses().unwrap().into_iter().map(|b| b.name).collect();
    assert_eq!(names, ["Terror"]);
}

#[test]
fn existing_behavior_is_the_dummy_source() {
    let f = Fixture::new();
    assert_eq!(f.default_boss.damage_source, DamageSource::Dummy);
    assert!(f.default_boss.elements.is_empty());
    assert!(f.default_boss.effectiveness.is_empty());
}

#[test]
fn effectiveness_multiplies_the_neutral_test_and_ignores_the_boss_dummy() {
    let f = Fixture::new();
    let boss_id = f.ground_boss(DamageSource::Effectiveness);
    f.service().set_boss_dummy(boss_id, "water").unwrap();
    let (id, skill_id) = f.steelix(boss_id, Some(Element::Ground));
    f.service()
        .save_damage_tests(id, Some(skill_id), &[test("neutral", &[1000]), test("water", &[9000])])
        .unwrap();
    let entry = f.only(boss_id);
    close(entry.breakdown.total, 1000. * 2. / 100. * 420.);
    assert!(entry.breakdown.lines[0].detail.contains("1.000 ×2"));
    assert!(entry.missing.is_empty() && entry.no_element.is_empty());
}

#[test]
fn unmarked_element_is_normal_and_every_level_changes_the_total() {
    let f = Fixture::new();
    let boss_id = f.ground_boss(DamageSource::Effectiveness);
    let (id, skill_id) = f.steelix(boss_id, Some(Element::Ice));
    f.service().save_damage_tests(id, Some(skill_id), &[test("neutral", &[1000])]).unwrap();
    for level in EffectivenessLevel::ALL {
        let effectiveness = BTreeMap::from([(Element::Ice, *level)]);
        f.service().save_boss(Some(boss_id), "Onix", 420, None, Some(&effectiveness)).unwrap();
        close(f.only(boss_id).breakdown.total, 1000. * level.multiplier() / 100. * 420.);
    }
    f.service().save_boss(Some(boss_id), "Onix", 420, None, Some(&BTreeMap::new())).unwrap();
    close(f.only(boss_id).breakdown.total, 1000. / 100. * 420.);
}

#[test]
fn effectiveness_lists_what_has_no_test_or_no_element() {
    let f = Fixture::new();
    let boss_id = f.ground_boss(DamageSource::Effectiveness);
    let (id, skill_id) = f.steelix(boss_id, None);
    f.service().save_damage_tests(id, Some(skill_id), &[test("neutral", &[1000])]).unwrap();
    let entry = f.only(boss_id);
    assert_eq!(entry.breakdown.total, 0.);
    assert!(entry.missing.is_empty());
    assert_eq!(entry.no_element, ["Sand Tomb"]);

    f.service().save_damage_tests(id, Some(skill_id), &[]).unwrap();
    let entry = f.only(boss_id);
    assert_eq!((entry.missing, entry.no_element), (vec!["Sand Tomb".to_owned()], vec!["Sand Tomb".to_owned()]));
}

#[test]
fn real_damage_uses_only_tests_in_that_boss_without_multiplier() {
    let f = Fixture::new();
    let boss_id = f.ground_boss(DamageSource::Real);
    let other = f.service().save_boss(None, "Kame", 420, None, None).unwrap();
    f.service().set_boss_damage_source(other, DamageSource::Real).unwrap();
    let (id, skill_id) = f.steelix(boss_id, None);
    f.service().set_boss_pokemons(other, &[id]).unwrap();
    f.service()
        .save_damage_tests(id, Some(skill_id), &[
            test("neutral", &[9000]),
            DamageTest::in_boss(boss_id, &[Some(3000), Some(5000), None]),
        ])
        .unwrap();
    let entry = f.only(boss_id);
    close(entry.breakdown.total, 4000. / 100. * 420.);
    assert!(entry.missing.is_empty() && entry.no_element.is_empty());
    let elsewhere = f.only(other);
    assert_eq!(elsewhere.breakdown.total, 0.);
    assert_eq!(elsewhere.missing, ["Sand Tomb"]);
}

#[test]
fn boss_tests_do_not_count_as_dummy_tests() {
    let f = Fixture::new();
    let (id, skill_id) = f.steelix(f.default_boss.id, Some(Element::Ground));
    f.service().save_damage_tests(id, Some(skill_id), &[boss_test(f.default_boss.id, &[5000])]).unwrap();
    for (dummy, _label) in dummy_options() {
        assert_eq!(f.pokemon(id).damage_on(Some(skill_id), dummy), None);
    }
    assert_eq!(f.only(f.default_boss.id).missing, ["Sand Tomb"]);
}

#[test]
fn boss_tests_validation() {
    let f = Fixture::new();
    let (id, skill_id) = f.steelix(f.default_boss.id, Some(Element::Ground));
    let boss_id = f.default_boss.id;
    let invalid = [
        (vec![boss_test(boss_id, &[1]), boss_test(boss_id, &[2])], "O boss Padrão aparece em mais de um"),
        (vec![DamageTest::in_boss(boss_id, &[None])], "Boss Padrão: informe"),
        (vec![boss_test(boss_id, &[-1])], "Boss Padrão: o dano precisa"),
        (vec![boss_test(999, &[1])], "Boss não encontrado"),
    ];
    for (tests, expected) in invalid {
        let message = user_error(f.service().save_damage_tests(id, Some(skill_id), &tests));
        assert!(message.contains(expected), "{message}");
    }
    let other = f.service().save_boss(None, "Kame", 420, None, None).unwrap();
    f.service()
        .save_damage_tests(id, Some(skill_id), &[boss_test(boss_id, &[1]), boss_test(other, &[2]), test("neutral", &[3])])
        .unwrap();
    assert_eq!(f.pokemon(id).tests[&Some(skill_id)].len(), 3);
}

#[test]
fn deleting_boss_removes_its_tests_and_profile() {
    let f = Fixture::new();
    let boss_id = f.ground_boss(DamageSource::Effectiveness);
    let (id, skill_id) = f.steelix(boss_id, Some(Element::Ground));
    f.service()
        .save_damage_tests(id, Some(skill_id), &[test("neutral", &[1000]), boss_test(boss_id, &[2000])])
        .unwrap();
    f.service().delete_boss(boss_id).unwrap();
    assert_eq!(f.pokemon(id).tests[&Some(skill_id)], [DamageTest::new("neutral", &[Some(1000), None, None])]);
    assert_eq!(f.count("dps_boss_effectiveness"), 0);
}

#[test]
fn duplicate_copies_boss_tests() {
    let f = Fixture::new();
    let (id, skill_id) = f.steelix(f.default_boss.id, Some(Element::Ground));
    f.service().save_damage_tests(id, Some(skill_id), &[boss_test(f.default_boss.id, &[2000])]).unwrap();
    let copy = f.pokemon(f.service().duplicate_pokemon(id).unwrap());
    assert_eq!(copy.damage_in_boss(copy.spec.skills[0].skill_id, f.default_boss.id), Some(2000.));
}

#[test]
fn boss_profile_round_trip_and_validation() {
    let f = Fixture::new();
    let service = f.service();
    let effectiveness = BTreeMap::from([
        (Element::Fire, EffectivenessLevel::Effective),
        (Element::Normal, EffectivenessLevel::Normal),
    ]);
    let id = service
        .save_boss(None, "Venusaur", 420, Some(&[Element::Grass, Element::Poison]), Some(&effectiveness))
        .unwrap();
    let find = || service.list_bosses().unwrap().into_iter().find(|b| b.id == id).unwrap();
    let boss = find();
    assert_eq!(boss.elements, [Element::Grass, Element::Poison]);
    assert_eq!(boss.effectiveness, BTreeMap::from([(Element::Fire, EffectivenessLevel::Effective)]));

    // Salvar só nome e tempo não apaga o perfil; trocar o nível atualiza a mesma linha.
    service.save_boss(Some(id), "Venusaur", 300, None, None).unwrap();
    let ineffective = BTreeMap::from([(Element::Fire, EffectivenessLevel::Ineffective)]);
    service.save_boss(Some(id), "Venusaur", 300, Some(&[Element::Grass]), Some(&ineffective)).unwrap();
    let boss = find();
    assert_eq!(boss.elements, [Element::Grass]);
    assert_eq!(boss.effectiveness, ineffective);

    for elements in [&[Element::Fire, Element::Fire][..], &[Element::Fire, Element::Ice, Element::Water]] {
        user_error(service.save_boss(Some(id), "Venusaur", 300, Some(elements), None));
    }
}

#[test]
fn version_8_database_keeps_ranking_and_dummy_tests() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("hunts.db");
    {
        let database = Database::open(&path).unwrap();
        database.create_schema().unwrap();
        database
            .with(|c| {
                // Banco como a versão 8 deixava: sem origem do dano e sem testes em boss.
                c.execute_batch(
                    "DROP TABLE dps_damage_tests;
                     CREATE TABLE dps_damage_tests (id INTEGER PRIMARY KEY, pokemon_id INTEGER NOT NULL,
                         skill_id INTEGER, dummy VARCHAR(20) NOT NULL, damage_1 INTEGER,
                         damage_2 INTEGER, damage_3 INTEGER);
                     ALTER TABLE dps_bosses DROP COLUMN damage_source;
                     ALTER TABLE dps_bosses DROP COLUMN element_1;
                     ALTER TABLE dps_bosses DROP COLUMN element_2;
                     DROP TABLE dps_boss_effectiveness;
                     INSERT INTO dps_pokemons (id, name, note) VALUES (1, 'Steelix', '');
                     INSERT INTO dps_skills (id, pokemon_id, position, name, shape, reach, cooldown, efficiency)
                         VALUES (5, 1, 1, '', 'area', 'ranged', 100, 1);
                     INSERT INTO dps_damage_tests (pokemon_id, skill_id, dummy, damage_1) VALUES (1, 5, 'neutral', 1000);
                     INSERT INTO dps_boss_pokemons VALUES (1, 1);
                     PRAGMA user_version = 8;",
                )?;
                Ok(())
            })
            .unwrap();
    }
    let database = Database::open(&path).unwrap();
    let applied: Vec<i64> = database.create_schema().unwrap().iter().map(|m| m.version).collect();
    assert_eq!(applied, (9..=LATEST_VERSION).collect::<Vec<_>>());
    let service = DpsService::new(&database);
    let boss = service.list_bosses().unwrap().remove(0);
    assert_eq!(boss.damage_source, DamageSource::Dummy);
    let ranking = service.ranking(boss.id, BR).unwrap();
    close(ranking[0].breakdown.total, 1000. / 100. * 420.);
    // O teste antigo fica sem data de cadastro, e a modificação passa a ser registrada.
    let pokemon = service.list_pokemons().unwrap().remove(0);
    let old = &pokemon.tests[&Some(5)][0];
    assert_eq!((old.created_at, old.updated_at), (None, None));
    let saved = service.save_damage_tests(1, Some(5), &[test("neutral", &[2000])]).unwrap();
    assert_eq!(saved[0].created_at, None);
    assert!(saved[0].updated_at.is_some());
}

#[test]
fn version_7_database_loses_typed_damage_and_keeps_the_rest() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("hunts.db");
    {
        let database = Database::open(&path).unwrap();
        database.create_schema().unwrap();
        database
            .with(|c| {
                // Banco como a versão 7 deixava: dano digitado e boss sem dummy.
                c.execute_batch(
                    "ALTER TABLE dps_bosses DROP COLUMN dummy;
                     ALTER TABLE dps_skills ADD COLUMN damage INTEGER;
                     ALTER TABLE dps_pokemons ADD COLUMN basic_damage INTEGER;
                     INSERT INTO dps_pokemons (id, name, note, basic_damage, basic_efficiency)
                         VALUES (1, 'Steelix', '', 2110, 0.75), (2, 'Muq', '', NULL, NULL);
                     INSERT INTO dps_skills (pokemon_id, position, name, shape, reach, damage, cooldown, efficiency)
                         VALUES (1, 1, 'Sand Tomb', 'area', 'ranged', 12160, 40, 1);
                     PRAGMA user_version = 7;",
                )?;
                Ok(())
            })
            .unwrap();
    }
    let database = Database::open(&path).unwrap();
    assert_eq!(database.create_schema().unwrap()[0].version, 8);
    let service = DpsService::new(&database);
    let pokemons = service.list_pokemons().unwrap();
    let (muq, steelix) = (&pokemons[0], &pokemons[1]);
    assert!(muq.spec.basic.is_none());
    assert_eq!(steelix.spec.basic.as_ref().unwrap().efficiency, 0.75);
    assert_eq!(steelix.spec.skills[0].cooldown, 40.);
    assert_eq!(steelix.spec.skills[0].damage, 0.);
    assert_eq!(service.list_bosses().unwrap()[0].dummy, "neutral");
}
