//! Porta de `CalculatorTests` (`tests/test_dps.py`). Os totais da lista do colega e o Chumbin em
//! 3.046.300 precisam continuar passando; mudar a fórmula de propósito exige combinar com o dono.

use pxg_core::dps::calculator::{
    BasicAttackSpec, BuffSpec, EffectivenessLevel, LineKind, PokemonSpec, SkillReach, SkillShape,
    SkillSpec, calculate, validate_spec,
};
use pxg_core::format::NumberFormat;

const FIGHT: f64 = 420.0;
const TURN: f64 = 2.5;
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

fn spec(skills: Vec<SkillSpec>, basic: Option<BasicAttackSpec>, buff: Option<BuffSpec>) -> PokemonSpec {
    PokemonSpec { skills, basic, buff }
}

fn sandsmauro() -> Vec<SkillSpec> {
    skills(&[(14000., 8., false), (22500., 32., false), (12900., 12., false), (25500., 35., false),
        (43700., 50., false), (10700., 20., true), (7500., 20., true)])
}
fn maurolem() -> Vec<SkillSpec> {
    area(&[(18000., 12.), (16000., 12.), (9800., 8.), (19000., 30.), (42000., 50.), (11000., 40.),
        (15000., 40.)])
}
fn polishop() -> Vec<SkillSpec> {
    area(&[(10700., 10.), (17600., 15.), (29300., 40.), (20400., 22.), (5500., 25.), (32500., 50.)])
}
fn jolt() -> Vec<SkillSpec> {
    area(&[(41000., 50.), (7900., 12.), (9400., 10.), (14000., 12.), (14600., 25.), (22100., 40.),
        (8400., 25.)])
}
fn jeremia() -> Vec<SkillSpec> {
    skills(&[(18000., 20., true), (12300., 10., false), (14800., 12., false), (22000., 28., false),
        (15000., 35., false), (30000., 50., false), (25500., 40., false)])
}
fn bartolomeu() -> Vec<SkillSpec> {
    area(&[(23000., 40.), (31000., 40.), (22600., 40.), (27000., 50.), (14300., 20.), (11400., 20.),
        (6600., 15.), (4400., 15.)])
}
fn chumbin() -> Vec<SkillSpec> {
    area(&[(20000., 35.), (13000., 8.), (15500., 12.), (22000., 20.), (14600., 50.), (33000., 50.)])
}
fn muq() -> Vec<SkillSpec> {
    area(&[(13000., 40.), (19000., 40.), (22000., 50.), (16000., 30.), (11600., 25.), (14700., 12.),
        (12200., 8.), (19000., 15.)])
}

fn assert_close(actual: f64, expected: f64, delta: f64) {
    assert!((actual - expected).abs() <= delta, "{actual} ≠ {expected} (± {delta})");
}

fn total(spec: &PokemonSpec, duration: f64, turn: f64) -> f64 {
    calculate(spec, duration, turn, BR).total
}

#[test]
fn reproduces_the_original_ranking() {
    // Básico a 100% e sem o bônus da próxima magia: as contas originais.
    let basic_only_buff = || Some(BuffSpec::new(50., 2., 15., 1.));
    let cases = [
        (spec(chumbin(), Some(BasicAttackSpec::new(2700., 1.)), basic_only_buff()), 2916520.),
        (spec(muq(), None, None), 2626680.),
        (spec(maurolem(), None, None), 2596300.),
        (spec(sandsmauro(), None, None), 2441543.),
        (spec(jeremia(), None, None), 2347850.),
        (spec(polishop(), Some(BasicAttackSpec::new(1600., 1.)), None), 2273505.),
        (spec(jolt(), None, None), 2124150.),
        (spec(bartolomeu(), None, None), 1878800.),
    ];
    for (spec, expected) in cases {
        assert_close(total(&spec, FIGHT, TURN), expected, 1.0);
    }
}

#[test]
fn dps_is_total_over_time() {
    assert_close(calculate(&spec(muq(), None, None), FIGHT, TURN, BR).dps, 6254., 1.0);
}

#[test]
fn full_buff_on_basic_at_75_percent_and_next_spell() {
    let spec = spec(chumbin(), Some(BasicAttackSpec::new(2700., 0.75)),
        Some(BuffSpec::new(50., 2., 15., 2.)));
    let result = calculate(&spec, FIGHT, TURN, BR);
    assert_close(result.total, 3046300., 1e-7);
    assert_close(result.dps, 7253.095, 0.005);
    let spell = result.lines.last().unwrap();
    assert_eq!(spell.kind, LineKind::Buff);
    assert_eq!(spell.source, "Buff: próxima magia (Skill 6)"); // a de 33.000
    assert_close(spell.total, 33000. * FIGHT / 50., 1e-7);
}

#[test]
fn next_spell_follows_the_slowest_cooldown() {
    // 40.000 a cada 100 s rende menos que 30.000 a cada 50 s, se o buff vem a cada 50 s.
    let spec = spec(area(&[(40000., 100.), (30000., 50.)]), None,
        Some(BuffSpec::new(50., 1., 0., 1.5)));
    let result = calculate(&spec, 100., TURN, BR);
    let spell = result.lines.last().unwrap();
    assert_eq!(spell.source, "Buff: próxima magia (Skill 2)");
    assert_close(spell.total, 30000. * 0.5 * 100. / 50., 1e-7);
}

#[test]
fn next_spell_respects_skill_efficiency() {
    let spec = spec(skills(&[(30000., 50., true), (25000., 50., false)]), None,
        Some(BuffSpec::new(50., 1., 0., 2.)));
    let result = calculate(&spec, 50., TURN, BR);
    assert_eq!(result.lines.last().unwrap().source, "Buff: próxima magia (Skill 2)"); // 25.000 > 22.500
}

#[test]
fn partial_buff_only_on_basic() {
    let spec = spec(vec![], Some(BasicAttackSpec::new(1000., 1.)), Some(BuffSpec::new(10., 1.5, 5., 1.)));
    let result = calculate(&spec, 100., 2., BR);
    let sources: Vec<_> = result.lines.iter().map(|l| l.source.as_str()).collect();
    assert_eq!(sources, ["Ataque básico", "Buff: ataque básico"]);
    assert_close(result.lines[1].total, 50000. * 0.5 * 0.5, 1e-7);
}

#[test]
fn buff_duration_longer_than_cooldown_counts_as_always_active() {
    let spec = spec(vec![], Some(BasicAttackSpec::new(1000., 1.)), Some(BuffSpec::new(10., 2., 30., 1.)));
    assert_close(total(&spec, 100., 2.), 100000., 1e-7);
}

#[test]
fn buff_without_basic_or_skills_adds_nothing() {
    let spec = spec(area(&[(1000., 10.)]), None, Some(BuffSpec::new(10., 2., 5., 1.)));
    assert_eq!(calculate(&spec, 100., 2., BR).lines.len(), 1);
}

#[test]
fn untested_skill_counts_zero_and_says_so() {
    let untested = SkillSpec::new("", SkillShape::Area, SkillReach::Ranged, 0., 10., 1.);
    let spec = spec(vec![untested], Some(BasicAttackSpec::new(0., 1.)),
        Some(BuffSpec::new(10., 2., 5., 2.)));
    let result = calculate(&spec, 100., 2., BR);
    assert_eq!(result.total, 0.);
    let sources: Vec<_> = result.lines.iter().map(|l| l.source.as_str()).collect();
    assert_eq!(sources, ["Skill 1", "Ataque básico"]);
    assert!(result.lines[0].detail.contains("sem teste"));
}

#[test]
fn multiplier_applies_to_skill_basic_and_buffs() {
    let buff = || Some(BuffSpec::new(50., 2., 15., 1.5));
    let plain = total(&spec(chumbin(), Some(BasicAttackSpec::new(2700., 1.)), buff()), FIGHT, TURN);
    let doubled_skills = chumbin()
        .into_iter()
        .map(|s| SkillSpec { multiplier: Some(2.), ..s })
        .collect();
    let doubled_basic = BasicAttackSpec { multiplier: Some(2.), ..BasicAttackSpec::new(2700., 1.) };
    let doubled = total(&spec(doubled_skills, Some(doubled_basic), buff()), FIGHT, TURN);
    assert_close(doubled, plain * 2., 1e-6);
}

#[test]
fn multiplier_is_shown_and_missing_element_counts_zero() {
    let skill = SkillSpec {
        multiplier: Some(0.75),
        ..SkillSpec::new("", SkillShape::Area, SkillReach::Ranged, 1000., 10., 1.)
    };
    let result = calculate(&spec(vec![skill.clone()], None, None), FIGHT, TURN, BR);
    assert_eq!(result.lines[0].detail, "Área · Ranged · 1.000 ×0,75 / 10s · 100%");
    let without = SkillSpec { multiplier: None, ..skill };
    let result = calculate(&spec(vec![without], None, None), FIGHT, TURN, BR);
    assert_eq!(result.total, 0.);
    assert!(result.lines[0].detail.contains("sem elemento"));
}

#[test]
fn null_effectiveness_gives_no_buff_line() {
    let basic = BasicAttackSpec { multiplier: Some(0.), ..BasicAttackSpec::new(1000., 1.) };
    let result = calculate(&spec(vec![], Some(basic), Some(BuffSpec::new(50., 2., 15., 1.))),
        FIGHT, TURN, BR);
    assert_eq!(result.total, 0.);
    let kinds: Vec<_> = result.lines.iter().map(|l| l.kind).collect();
    assert_eq!(kinds, [LineKind::Basic]);
}

#[test]
fn next_spell_picks_the_best_after_effectiveness() {
    let strong = SkillSpec {
        multiplier: Some(0.5),
        ..SkillSpec::new("Forte", SkillShape::Area, SkillReach::Ranged, 2000., 50., 1.)
    };
    let weak = SkillSpec {
        multiplier: Some(2.),
        ..SkillSpec::new("Fraca", SkillShape::Area, SkillReach::Ranged, 1500., 50., 1.)
    };
    let result = calculate(&spec(vec![strong, weak], None, Some(BuffSpec::new(50., 1., 0., 2.))),
        FIGHT, TURN, BR);
    assert_eq!(result.lines.last().unwrap().source, "Buff: próxima magia (Fraca)");
}

#[test]
fn effectiveness_levels_follow_the_game_table() {
    let multipliers: Vec<_> = EffectivenessLevel::ALL.iter().map(|l| l.multiplier()).collect();
    assert_eq!(multipliers, [2., 1.75, 1., 0.75, 0.5, 0.]);
}

#[test]
fn validation() {
    let ok_skill = || area(&[(1000., 10.)]);
    let invalid = [
        PokemonSpec::default(),
        spec(area(&[(1000., 0.)]), None, None),
        spec(vec![SkillSpec::new("", SkillShape::Area, SkillReach::Melee, 1., 1., 1.5)], None, None),
        spec(vec![], Some(BasicAttackSpec::new(10., -0.1)), None),
        spec(ok_skill(), None, Some(BuffSpec::new(0., 2., 5., 1.))),
        spec(ok_skill(), None, Some(BuffSpec::new(10., 1., 0., 1.))), // sem efeito
        spec(ok_skill(), None, Some(BuffSpec::new(10., 0.5, 5., 1.))),
        spec(ok_skill(), None, Some(BuffSpec::new(10., 2., 0., 1.))), // bônus sem duração
    ];
    for spec in &invalid {
        assert!(validate_spec(spec).is_err(), "{spec:?}");
    }
    validate_spec(&spec(ok_skill(), None, Some(BuffSpec::new(10., 1., 0., 2.)))).unwrap();
}
