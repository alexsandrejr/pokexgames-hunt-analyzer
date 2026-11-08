//! Formulários dos diálogos do DPS (equivale aos campos de `app/ui/dps/dps_dialogs.py` e
//! `dps_tests_dialog.py`). Os textos vão para as telas preenchidos como no Python e voltam
//! para cá, que valida na mesma ordem e com as mesmas mensagens.

use std::collections::{BTreeMap, HashMap};

use pxg_core::UserError;
use pxg_core::dps::calculator::{
    BasicAttackSpec, BuffSpec, EffectivenessLevel, Element, PokemonSpec, SkillReach, SkillShape, SkillSpec,
    validate_spec,
};
use pxg_core::dps::service::{
    BossData, DAMAGES_PER_TEST, DamageTest, DpsSettings, MAX_BOSS_ELEMENTS, PokemonData, damage_average, dummy_label,
    validate_boss_profile, validate_settings,
};
use pxg_core::format::{
    NumberFormat, format_date, format_datetime_short, format_integer, format_money, format_plain, round_half_even, round_to,
};
use pxg_core::parse::parse_user_number;
use pxg_core::text::{casefold, py_strip};
use serde::{Deserialize, Serialize};

type FormResult<T> = Result<T, UserError>;

fn number(text: &str, label: &str, fmt: NumberFormat) -> FormResult<f64> {
    parse_user_number(text, fmt).ok_or_else(|| UserError(format!("{label}: informe um número válido.")))
}

fn seconds(text: &str, label: &str, fmt: NumberFormat) -> FormResult<f64> {
    number(py_strip(text).trim_end_matches(['s', 'S']), label, fmt)
}

fn fraction(text: &str, label: &str, fmt: NumberFormat) -> FormResult<f64> {
    Ok(number(py_strip(text).trim_end_matches('%'), label, fmt)? / 100.0)
}

/// Fração em % para um campo: 0,75 vira "75".
pub fn percent_text(fraction: f64, fmt: NumberFormat) -> String {
    format_plain(round_to(fraction * 100.0, 2), fmt)
}

// ------------------------------------------------------------------------------ ajustes

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SettingsForm {
    pub turn: String,
    pub target_melee: String,
    pub default: String,
    pub basic: String,
}

impl SettingsForm {
    pub fn fill(settings: &DpsSettings, fmt: NumberFormat) -> Self {
        Self {
            turn: format_plain(settings.basic_turn_seconds, fmt),
            target_melee: percent_text(settings.target_melee_efficiency, fmt),
            default: percent_text(settings.default_efficiency, fmt),
            basic: percent_text(settings.basic_efficiency, fmt),
        }
    }

    /// Mantém o último boss escolhido, que não aparece no diálogo.
    pub fn parse(&self, current: &DpsSettings, fmt: NumberFormat) -> pxg_core::Result<DpsSettings> {
        let settings = DpsSettings {
            basic_turn_seconds: seconds(&self.turn, "Turno do ataque básico", fmt)?,
            target_melee_efficiency: fraction(&self.target_melee, "Target + Melee", fmt)?,
            default_efficiency: fraction(&self.default, "Demais skills", fmt)?,
            basic_efficiency: fraction(&self.basic, "Ataque básico", fmt)?,
            last_boss_id: current.last_boss_id,
        };
        validate_settings(&settings)?;
        Ok(settings)
    }
}

// ------------------------------------------------------------------------------ pokémon

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SkillRow {
    /// Id da skill salva: os testes apontam para ele, então precisa voltar igual.
    pub skill_id: Option<i64>,
    pub name: String,
    pub shape: SkillShape,
    pub reach: SkillReach,
    pub element: Option<Element>,
    pub cooldown: String,
    pub percent: String,
    /// % sugerido para a forma e o alcance; troca junto com eles se o % não foi alterado.
    pub suggestion: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PokemonForm {
    pub name: String,
    pub note: String,
    pub has_basic: bool,
    pub basic_percent: String,
    pub basic_element: Option<Element>,
    pub has_buff: bool,
    pub buff_cooldown: String,
    pub buff_basic: String,
    pub buff_duration: String,
    pub buff_spell: String,
    pub skills: Vec<SkillRow>,
}

/// O que a tela precisa para sugerir o % ao trocar a forma ou o alcance de uma skill.
#[derive(Debug, Clone, Serialize)]
pub struct Suggestions {
    pub target_melee: String,
    pub default: String,
}

impl Suggestions {
    pub fn new(settings: &DpsSettings, fmt: NumberFormat) -> Self {
        Self {
            target_melee: percent_text(settings.target_melee_efficiency, fmt),
            default: percent_text(settings.default_efficiency, fmt),
        }
    }
}

fn skill_row(skill: &SkillSpec, empty: bool, settings: &DpsSettings, fmt: NumberFormat) -> SkillRow {
    SkillRow {
        skill_id: skill.skill_id,
        name: skill.name.clone(),
        shape: skill.shape,
        reach: skill.reach,
        element: skill.element,
        cooldown: if empty { String::new() } else { format_plain(skill.cooldown, fmt) },
        percent: percent_text(skill.efficiency, fmt),
        suggestion: percent_text(settings.suggested_efficiency(skill.shape, skill.reach), fmt),
    }
}

/// Linha nova da tabela de skills: Área + Ranged, com o % sugerido e a recarga vazia.
pub fn empty_skill_row(settings: &DpsSettings, fmt: NumberFormat) -> SkillRow {
    let (shape, reach) = (SkillShape::Area, SkillReach::Ranged);
    let skill = SkillSpec::new("", shape, reach, 0.0, 0.0, settings.suggested_efficiency(shape, reach));
    skill_row(&skill, true, settings, fmt)
}

impl PokemonForm {
    pub fn fill(pokemon: Option<&PokemonData>, settings: &DpsSettings, fmt: NumberFormat) -> Self {
        let basic = pokemon.and_then(|p| p.spec.basic.as_ref());
        let buff = pokemon.and_then(|p| p.spec.buff.as_ref());
        let skills = match pokemon {
            None => vec![empty_skill_row(settings, fmt)],
            Some(p) => p.spec.skills.iter().map(|s| skill_row(s, false, settings, fmt)).collect(),
        };
        Self {
            name: pokemon.map(|p| p.name.clone()).unwrap_or_default(),
            note: pokemon.map(|p| p.note.clone()).unwrap_or_default(),
            has_basic: basic.is_some(),
            basic_percent: percent_text(basic.map_or(settings.basic_efficiency, |b| b.efficiency), fmt),
            basic_element: basic.and_then(|b| b.element),
            has_buff: buff.is_some(),
            buff_cooldown: buff.map(|b| format_plain(b.cooldown, fmt)).unwrap_or_default(),
            buff_basic: buff.map_or_else(|| "1".into(), |b| format_plain(b.basic_multiplier, fmt)),
            buff_duration: buff.map_or_else(|| "0".into(), |b| format_plain(b.basic_duration, fmt)),
            buff_spell: buff.map_or_else(|| "1".into(), |b| format_plain(b.next_spell_multiplier, fmt)),
            skills,
        }
    }

    pub fn clean_name(&self) -> String {
        py_strip(&self.name).to_owned()
    }

    pub fn clean_note(&self) -> String {
        py_strip(&self.note).to_owned()
    }

    /// Primeiro o nome, depois as skills na ordem da tabela, o básico e o buff, como no Python.
    pub fn parse(&self, fmt: NumberFormat) -> FormResult<PokemonSpec> {
        if self.clean_name().is_empty() {
            return Err(UserError("Informe o nome do pokémon.".into()));
        }
        let mut skills = Vec::with_capacity(self.skills.len());
        for (row, skill) in self.skills.iter().enumerate() {
            let name = py_strip(&skill.name).to_owned();
            let label = if name.is_empty() { format!("Skill {}", row + 1) } else { name.clone() };
            let cooldown = seconds(&skill.cooldown, &format!("{label}, recarga"), fmt)?;
            let efficiency = fraction(&skill.percent, &format!("{label}, aproveitamento"), fmt)?;
            let mut spec = SkillSpec::new(name, skill.shape, skill.reach, 0.0, cooldown, efficiency);
            spec.element = skill.element;
            spec.skill_id = skill.skill_id;
            skills.push(spec);
        }
        let basic = if self.has_basic {
            let mut basic = BasicAttackSpec::new(0.0, fraction(&self.basic_percent, "Ataque básico, aproveitamento", fmt)?);
            basic.element = self.basic_element;
            Some(basic)
        } else {
            None
        };
        let buff = if self.has_buff {
            Some(BuffSpec::new(
                seconds(&self.buff_cooldown, "Buff, recarga", fmt)?,
                number(&self.buff_basic, "Buff, multiplicador do básico", fmt)?,
                seconds(&self.buff_duration, "Buff, duração", fmt)?,
                number(&self.buff_spell, "Buff, multiplicador da próxima magia", fmt)?,
            ))
        } else {
            None
        };
        let spec = PokemonSpec { skills, basic, buff };
        validate_spec(&spec)?;
        Ok(spec)
    }
}

/// Dano médio de cada skill no dummy escolhido, só para mostrar: ele vem dos testes.
#[derive(Debug, Clone, Serialize)]
pub struct DamageTexts {
    pub basic: String,
    /// Por id da skill; uma skill ainda não salva não tem testes.
    pub skills: BTreeMap<i64, String>,
}

pub fn damage_text(damage: Option<f64>, fmt: NumberFormat) -> String {
    damage.map_or_else(|| "sem teste".into(), |d| format_money(d, fmt))
}

impl DamageTexts {
    pub fn new(pokemon: Option<&PokemonData>, dummy: &str, fmt: NumberFormat) -> Self {
        let Some(pokemon) = pokemon else {
            return Self { basic: damage_text(None, fmt), skills: BTreeMap::new() };
        };
        let basic = if pokemon.spec.basic.is_some() { pokemon.damage_on(None, dummy) } else { None };
        let skills = pokemon
            .spec
            .skills
            .iter()
            .filter_map(|s| s.skill_id.map(|id| (id, damage_text(pokemon.damage_on(Some(id), dummy), fmt))))
            .collect();
        Self { basic: damage_text(basic, fmt), skills }
    }
}

// ------------------------------------------------------------------------------ boss

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BossForm {
    pub name: String,
    pub minutes: String,
    /// Sempre `MAX_BOSS_ELEMENTS` seletores; `None` é o "—".
    pub elements: Vec<Option<Element>>,
    /// Todos os elementos, com Normal nos que não foram marcados.
    pub effectiveness: BTreeMap<Element, EffectivenessLevel>,
}

/// Boss pronto para salvar.
#[derive(Debug, Clone, PartialEq)]
pub struct BossInput {
    pub name: String,
    pub time_limit_seconds: i64,
    pub elements: Vec<Element>,
    pub effectiveness: BTreeMap<Element, EffectivenessLevel>,
}

impl BossForm {
    pub fn fill(boss: Option<&BossData>, fmt: NumberFormat) -> Self {
        let minutes = boss.map_or(7.0, |b| b.time_limit_seconds as f64 / 60.0);
        let elements = (0..MAX_BOSS_ELEMENTS).map(|i| boss.and_then(|b| b.elements.get(i).copied())).collect();
        let effectiveness = Element::ALL
            .iter()
            .map(|e| (*e, boss.and_then(|b| b.effectiveness.get(e).copied()).unwrap_or(EffectivenessLevel::Normal)))
            .collect();
        Self {
            name: boss.map(|b| b.name.clone()).unwrap_or_default(),
            minutes: format_plain(round_to(minutes, 2), fmt),
            elements,
            effectiveness,
        }
    }

    /// `others` são os demais bosses, para recusar um nome repetido.
    pub fn parse(&self, others: &[&BossData], fmt: NumberFormat) -> pxg_core::Result<BossInput> {
        let elements: Vec<Element> = self.elements.iter().flatten().copied().collect();
        validate_boss_profile(&elements)?;
        let name = py_strip(&self.name).to_owned();
        let time_limit_seconds =
            parse_user_number(&self.minutes, fmt).map_or(0, |minutes| round_half_even(minutes * 60.0) as i64);
        if name.is_empty() {
            return Err(UserError("Informe o nome do boss.".into()).into());
        }
        let folded = casefold(&name);
        if others.iter().any(|b| casefold(&b.name) == folded) {
            return Err(UserError(format!("Já existe um boss chamado {name}.")).into());
        }
        if time_limit_seconds <= 0 {
            return Err(UserError("O tempo limite precisa ser maior que zero.".into()).into());
        }
        let effectiveness =
            self.effectiveness.iter().filter(|(_, level)| **level != EffectivenessLevel::Normal).map(|(e, l)| (*e, *l)).collect();
        Ok(BossInput { name, time_limit_seconds, elements, effectiveness })
    }
}

// ------------------------------------------------------------------------------ testes

/// Onde o teste foi feito: o valor do dummy ou `boss:<id>`.
pub fn place_value(test: &DamageTest) -> String {
    match test.boss_id {
        Some(id) => format!("boss:{id}"),
        None => test.dummy.clone(),
    }
}

fn boss_place(place: &str) -> Option<i64> {
    place.strip_prefix("boss:").and_then(|id| id.parse().ok())
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct TestRow {
    pub place: String,
    pub damages: Vec<String>,
    pub average: String,
    pub created: String,
    pub created_tip: String,
    pub updated: String,
    pub updated_tip: String,
}

impl TestRow {
    pub fn saved(test: &DamageTest, fmt: NumberFormat) -> Self {
        Self {
            place: place_value(test),
            damages: test.padded_damages().iter().map(|d| d.map(|d| format_integer(d, fmt)).unwrap_or_default()).collect(),
            average: format_money(test.average(), fmt),
            created: format_date(test.created_at),
            created_tip: test
                .created_at
                .map_or_else(|| "Teste anterior ao registro de datas.".into(), |d| format_datetime_short(Some(d))),
            updated: format_date(test.updated_at),
            updated_tip: test
                .updated_at
                .map_or_else(|| "Os danos não mudaram desde o cadastro.".into(), |d| format_datetime_short(Some(d))),
        }
    }

    /// Linha nova, ainda sem danos; a tela escolhe o lugar.
    pub fn empty(fmt: NumberFormat) -> Self {
        Self {
            place: String::new(),
            damages: vec![String::new(); DAMAGES_PER_TEST],
            average: format_money(None, fmt),
            created: format_date(None),
            created_tip: "Ainda não foi salvo.".into(),
            updated: format_date(None),
            updated_tip: "Ainda não foi salvo.".into(),
        }
    }
}

/// Uma linha da tabela de testes como foi digitada.
#[derive(Debug, Clone, Deserialize)]
pub struct TestInput {
    pub place: String,
    pub damages: Vec<String>,
}

fn place_label(place: &str, boss_names: &HashMap<i64, String>) -> String {
    match boss_place(place) {
        Some(id) => format!("Boss: {}", boss_names.get(&id).map_or("", String::as_str)),
        None => format!("Dummy {}", dummy_label(place)),
    }
}

/// Dano de uma célula; vazia é `None`.
fn cell_damage(text: &str, place: &str, fmt: NumberFormat) -> FormResult<Option<i64>> {
    let clean = py_strip(text);
    if clean.is_empty() {
        return Ok(None);
    }
    let invalid = || UserError(format!("{place}: “{clean}” não é um dano válido."));
    let value = parse_user_number(text, fmt).ok_or_else(invalid)?;
    let rounded = round_half_even(value);
    if !rounded.is_finite() || rounded.abs() >= 9.2e18 {
        return Err(invalid());
    }
    Ok(Some(rounded as i64))
}

/// Testes da tabela, sem as linhas vazias.
pub fn parse_tests(rows: &[TestInput], boss_names: &HashMap<i64, String>, fmt: NumberFormat) -> FormResult<Vec<DamageTest>> {
    let mut tests = Vec::new();
    for row in rows {
        let label = place_label(&row.place, boss_names);
        let damages = row.damages.iter().map(|d| cell_damage(d, &label, fmt)).collect::<FormResult<Vec<_>>>()?;
        if damages.iter().any(Option::is_some) {
            tests.push(match boss_place(&row.place) {
                Some(id) => DamageTest::in_boss(id, &damages),
                None => DamageTest::new(&row.place, &damages),
            });
        }
    }
    Ok(tests)
}

/// Média da linha enquanto a pessoa digita; com um dano inválido, fica "—".
pub fn average_text(damages: &[String], fmt: NumberFormat) -> String {
    let parsed: FormResult<Vec<Option<i64>>> = damages.iter().map(|d| cell_damage(d, "", fmt)).collect();
    format_money(parsed.ok().and_then(|d| damage_average(&d)), fmt)
}

#[cfg(test)]
mod tests {
    use super::*;

    const FMT: NumberFormat = NumberFormat::PT_BR;

    fn settings() -> DpsSettings {
        DpsSettings {
            basic_turn_seconds: 2.5,
            target_melee_efficiency: 0.75,
            default_efficiency: 1.0,
            basic_efficiency: 0.75,
            last_boss_id: Some(3),
        }
    }

    #[test]
    fn new_pokemon_form_has_one_empty_skill_and_default_buff() {
        let form = PokemonForm::fill(None, &settings(), FMT);
        assert_eq!(form.skills.len(), 1);
        assert_eq!(form.skills[0].cooldown, "");
        assert_eq!(form.skills[0].percent, "100");
        assert_eq!(form.basic_percent, "75");
        assert_eq!((form.buff_basic.as_str(), form.buff_duration.as_str(), form.buff_spell.as_str()), ("1", "0", "1"));
        assert!(!form.has_basic && !form.has_buff);
    }

    #[test]
    fn pokemon_form_validates_in_python_order() {
        let mut form = PokemonForm::fill(None, &settings(), FMT);
        assert_eq!(form.parse(FMT).unwrap_err().0, "Informe o nome do pokémon.");
        form.name = "  Chumbin ".into();
        assert_eq!(form.parse(FMT).unwrap_err().0, "Skill 1, recarga: informe um número válido.");
        form.skills[0].cooldown = "12s".into();
        form.skills[0].percent = "abc".into();
        assert_eq!(form.parse(FMT).unwrap_err().0, "Skill 1, aproveitamento: informe um número válido.");
        form.skills[0].percent = "80%".into();
        form.has_buff = true;
        assert_eq!(form.parse(FMT).unwrap_err().0, "Buff, recarga: informe um número válido.");
        form.buff_cooldown = "50".into();
        assert_eq!(form.parse(FMT).unwrap_err().0, "Buff: aumente ao menos um dos multiplicadores (1 = sem efeito).");
        form.buff_spell = "1,5".into();
        let spec = form.parse(FMT).unwrap();
        assert_eq!(spec.skills[0].cooldown, 12.0);
        assert!((spec.skills[0].efficiency - 0.8).abs() < 1e-12);
        assert_eq!(form.clean_name(), "Chumbin");
    }

    #[test]
    fn pokemon_form_keeps_skill_ids() {
        let mut form = PokemonForm::fill(None, &settings(), FMT);
        form.name = "X".into();
        form.skills[0].cooldown = "10".into();
        form.skills[0].skill_id = Some(42);
        assert_eq!(form.parse(FMT).unwrap().skills[0].skill_id, Some(42));
    }

    #[test]
    fn settings_form_round_trip_keeps_last_boss() {
        let form = SettingsForm::fill(&settings(), FMT);
        assert_eq!(form.turn, "2,5");
        assert_eq!(form.parse(&settings(), FMT).unwrap(), settings());
        let bad = SettingsForm { turn: "x".into(), ..form };
        assert_eq!(bad.parse(&settings(), FMT).unwrap_err().to_string(), "Turno do ataque básico: informe um número válido.");
    }

    fn boss(id: i64, name: &str) -> BossData {
        BossData {
            id,
            name: name.into(),
            time_limit_seconds: 420,
            pokemon_ids: Default::default(),
            dummy: "neutral".into(),
            damage_source: pxg_core::dps::service::DamageSource::Dummy,
            elements: vec![],
            effectiveness: BTreeMap::new(),
        }
    }

    #[test]
    fn boss_form_validates_name_and_time() {
        let other = boss(1, "Terror");
        let mut form = BossForm::fill(None, FMT);
        assert_eq!(form.minutes, "7");
        assert_eq!(form.parse(&[&other], FMT).unwrap_err().to_string(), "Informe o nome do boss.");
        form.name = "terror".into();
        assert_eq!(form.parse(&[&other], FMT).unwrap_err().to_string(), "Já existe um boss chamado terror.");
        form.name = "Novo".into();
        form.minutes = "0".into();
        assert_eq!(form.parse(&[&other], FMT).unwrap_err().to_string(), "O tempo limite precisa ser maior que zero.");
        form.minutes = "7,5".into();
        form.effectiveness.insert(Element::Fire, EffectivenessLevel::SuperEffective);
        let input = form.parse(&[&other], FMT).unwrap();
        assert_eq!(input.time_limit_seconds, 450);
        assert_eq!(input.effectiveness.len(), 1);
    }

    #[test]
    fn tests_parse_skips_empty_rows_and_reports_place() {
        let names = HashMap::from([(7, "Terror".to_owned())]);
        let rows = vec![
            TestInput { place: "neutral".into(), damages: vec!["".into(), "".into(), "".into()] },
            TestInput { place: "boss:7".into(), damages: vec!["14k".into(), "".into(), "".into()] },
        ];
        let tests = parse_tests(&rows, &names, FMT).unwrap();
        assert_eq!(tests.len(), 1);
        assert_eq!(tests[0].boss_id, Some(7));
        assert_eq!(tests[0].damages[0], Some(14_000));
        let bad = vec![TestInput { place: "boss:7".into(), damages: vec![" abc ".into()] }];
        assert_eq!(parse_tests(&bad, &names, FMT).unwrap_err().0, "Boss: Terror: “abc” não é um dano válido.");
        let bad = vec![TestInput { place: "neutral".into(), damages: vec!["x".into()] }];
        assert_eq!(parse_tests(&bad, &names, FMT).unwrap_err().0, "Dummy Neutro: “x” não é um dano válido.");
        assert_eq!(average_text(&["10".into(), "20".into(), "".into()], FMT), "15");
        assert_eq!(average_text(&["x".into()], FMT), "—");
    }
}
