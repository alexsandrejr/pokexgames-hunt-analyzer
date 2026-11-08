//! Estimativa do dano de um pokémon em um boss com tempo limite (equivale a
//! `app/services/dps_calculator.py`).
//!
//! O cálculo usa o dano médio, sem simular a luta (animações e usos inteiros ficam de fora):
//!
//! * skill: `dano ÷ recarga × tempo × aproveitamento`;
//! * ataque básico: `dano ÷ turno × tempo × aproveitamento`;
//! * buff no básico: fração do tempo com o buff ativo × `(multiplicador − 1)` × dano do básico;
//! * buff na próxima magia: a magia que mais rende, supondo que ela é guardada para o buff.
//!   Ela só é reforçada na recarga mais lenta entre a magia e o buff.
//!
//! O `dano` acima já inclui o multiplicador de efetividade, que vale 1 quando o dano medido já
//! a considera. Mudar a fórmula de propósito exige combinar com o dono (ver `CLAUDE.md`).

use serde::{Deserialize, Serialize};

use crate::UserError;
use crate::format::{NumberFormat, format_number, format_plain, round_to};
use crate::macros::text_enum;

text_enum!(SkillShape { Area = "area" => "Área", Target = "target" => "Target" });

text_enum!(SkillReach { Melee = "melee" => "Melee", Ranged = "ranged" => "Ranged" });

text_enum!(
    /// Elementos dos golpes e dos bosses (ver `docs/efetividade-pxg.md`).
    Element {
        Normal = "normal" => "Normal",
        Fire = "fire" => "Fire",
        Water = "water" => "Water",
        Grass = "grass" => "Grass",
        Electric = "electric" => "Electric",
        Ice = "ice" => "Ice",
        Fighting = "fighting" => "Fighting",
        Poison = "poison" => "Poison",
        Ground = "ground" => "Ground",
        Flying = "flying" => "Flying",
        Psychic = "psychic" => "Psychic",
        Bug = "bug" => "Bug",
        Rock = "rock" => "Rock",
        Ghost = "ghost" => "Ghost",
        Dragon = "dragon" => "Dragon",
        Dark = "dark" => "Dark",
        Steel = "steel" => "Steel",
        Fairy = "fairy" => "Fairy",
    }
);

text_enum!(
    /// Resultado de um ataque contra o boss, como o jogo mostra (valores de PvE).
    EffectivenessLevel {
        SuperEffective = "super_effective" => "Super Efetivo",
        Effective = "effective" => "Efetivo",
        Normal = "normal" => "Normal",
        Ineffective = "ineffective" => "Inefetivo",
        VeryIneffective = "very_ineffective" => "Muito Inefetivo",
        Null = "null" => "Nulo",
    }
);

impl EffectivenessLevel {
    pub fn multiplier(self) -> f64 {
        match self {
            Self::SuperEffective => 2.0,
            Self::Effective => 1.75,
            Self::Normal => 1.0,
            Self::Ineffective => 0.75,
            Self::VeryIneffective => 0.5,
            Self::Null => 0.0,
        }
    }
}

/// A igualdade ignora o `skill_id`, como no Python: a ficha salva é igual à digitada.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SkillSpec {
    /// Opcional: sem nome, a skill aparece como "Skill N".
    pub name: String,
    pub shape: SkillShape,
    pub reach: SkillReach,
    /// Média do teste em uso; 0 = sem teste.
    pub damage: f64,
    /// Segundos.
    pub cooldown: f64,
    /// Fração 0–1.
    pub efficiency: f64,
    pub element: Option<Element>,
    /// Skill já salva: permite editar o pokémon sem perder os testes dela.
    pub skill_id: Option<i64>,
    /// Efetividade; `None` = sem elemento (conta como 0).
    pub multiplier: Option<f64>,
}

impl PartialEq for SkillSpec {
    fn eq(&self, other: &Self) -> bool {
        self.name == other.name
            && self.shape == other.shape
            && self.reach == other.reach
            && self.damage == other.damage
            && self.cooldown == other.cooldown
            && self.efficiency == other.efficiency
            && self.element == other.element
            && self.multiplier == other.multiplier
    }
}

impl SkillSpec {
    /// Skill sem elemento, sem id e com multiplicador 1, como o construtor do Python.
    pub fn new(
        name: impl Into<String>,
        shape: SkillShape,
        reach: SkillReach,
        damage: f64,
        cooldown: f64,
        efficiency: f64,
    ) -> Self {
        Self {
            name: name.into(),
            shape,
            reach,
            damage,
            cooldown,
            efficiency,
            element: None,
            skill_id: None,
            multiplier: Some(1.0),
        }
    }

    pub fn effective_damage(&self) -> f64 {
        self.damage * self.multiplier.unwrap_or(0.0)
    }

    /// `position` começa em 1.
    pub fn label(&self, position: usize) -> String {
        if self.name.is_empty() { format!("Skill {position}") } else { self.name.clone() }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BasicAttackSpec {
    /// Média do teste em uso; 0 = sem teste.
    pub damage: f64,
    /// Fração 0–1.
    pub efficiency: f64,
    pub element: Option<Element>,
    /// Efetividade; `None` = sem elemento (conta como 0).
    pub multiplier: Option<f64>,
}

impl BasicAttackSpec {
    pub fn new(damage: f64, efficiency: f64) -> Self {
        Self { damage, efficiency, element: None, multiplier: Some(1.0) }
    }

    pub fn effective_damage(&self) -> f64 {
        self.damage * self.multiplier.unwrap_or(0.0)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BuffSpec {
    /// Segundos.
    pub cooldown: f64,
    /// 1 = não afeta o ataque básico.
    pub basic_multiplier: f64,
    /// Segundos.
    pub basic_duration: f64,
    /// 1 = não afeta a próxima magia.
    pub next_spell_multiplier: f64,
}

impl BuffSpec {
    pub fn new(cooldown: f64, basic_multiplier: f64, basic_duration: f64, next_spell: f64) -> Self {
        Self { cooldown, basic_multiplier, basic_duration, next_spell_multiplier: next_spell }
    }
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct PokemonSpec {
    pub skills: Vec<SkillSpec>,
    pub basic: Option<BasicAttackSpec>,
    pub buff: Option<BuffSpec>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LineKind {
    Skill,
    Basic,
    Buff,
}

/// Quanto uma fonte de dano soma ao total.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DamageLine {
    pub kind: LineKind,
    pub source: String,
    pub detail: String,
    pub total: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DamageBreakdown {
    pub lines: Vec<DamageLine>,
    pub total: f64,
    pub dps: f64,
}

/// Devolve a primeira regra violada.
pub fn validate_spec(spec: &PokemonSpec) -> Result<(), UserError> {
    if spec.skills.is_empty() && spec.basic.is_none() {
        return Err(UserError::new("Cadastre ao menos uma skill ou o ataque básico."));
    }
    for (index, skill) in spec.skills.iter().enumerate() {
        let label = skill.label(index + 1);
        if skill.cooldown.is_nan() || skill.cooldown <= 0.0 {
            return Err(UserError::new(format!("{label}: a recarga precisa ser maior que zero.")));
        }
        validate_efficiency(skill.efficiency, &label)?;
    }
    if let Some(basic) = &spec.basic {
        validate_efficiency(basic.efficiency, "Ataque básico")?;
    }
    if let Some(buff) = &spec.buff {
        validate_buff(buff)?;
    }
    Ok(())
}

fn validate_efficiency(efficiency: f64, label: &str) -> Result<(), UserError> {
    if (0.0..=1.0).contains(&efficiency) {
        Ok(())
    } else {
        Err(UserError::new(format!("{label}: o aproveitamento precisa estar entre 0% e 100%.")))
    }
}

fn validate_buff(buff: &BuffSpec) -> Result<(), UserError> {
    if buff.cooldown.is_nan() || buff.cooldown <= 0.0 {
        return Err(UserError::new("Buff: a recarga precisa ser maior que zero."));
    }
    if buff.basic_multiplier < 1.0 || buff.next_spell_multiplier < 1.0 {
        return Err(UserError::new("Buff: os multiplicadores não podem ser menores que 1."));
    }
    if buff.basic_multiplier == 1.0 && buff.next_spell_multiplier == 1.0 {
        return Err(UserError::new(
            "Buff: aumente ao menos um dos multiplicadores (1 = sem efeito).",
        ));
    }
    if buff.basic_duration < 0.0 || (buff.basic_multiplier > 1.0 && buff.basic_duration == 0.0) {
        return Err(UserError::new("Buff: informe a duração do bônus no ataque básico."));
    }
    Ok(())
}

/// Dano estimado em `duration` segundos, com um ataque básico a cada `basic_turn`.
pub fn calculate(
    spec: &PokemonSpec,
    duration: f64,
    basic_turn: f64,
    fmt: NumberFormat,
) -> DamageBreakdown {
    let text = Texts(fmt);
    let mut lines: Vec<DamageLine> = spec
        .skills
        .iter()
        .enumerate()
        .map(|(index, skill)| skill_line(skill, index + 1, duration, text))
        .collect();
    if let Some(basic) = &spec.basic {
        lines.push(basic_line(basic, duration, basic_turn, text));
        if let Some(buff) = &spec.buff {
            if buff.basic_multiplier > 1.0 && basic.effective_damage() > 0.0 {
                lines.push(basic_buff_line(basic, buff, duration, basic_turn, text));
            }
        }
    }
    if let Some(buff) = &spec.buff {
        if buff.next_spell_multiplier > 1.0 {
            if let Some(line) = next_spell_line(&spec.skills, buff, duration, text) {
                lines.push(line);
            }
        }
    }
    // Soma na mesma ordem do Python, para dar o mesmo resultado de ponto flutuante.
    let total = lines.iter().fold(0.0, |sum, line| sum + line.total);
    DamageBreakdown { lines, total, dps: total / duration }
}

fn skill_line(skill: &SkillSpec, position: usize, duration: f64, text: Texts) -> DamageLine {
    let detail = format!(
        "{} · {} · {} / {}s · {}",
        skill.shape.label(),
        skill.reach.label(),
        text.damage(skill.damage, skill.multiplier),
        text.plain(skill.cooldown),
        text.percent(skill.efficiency),
    );
    let total = skill.effective_damage() / skill.cooldown * duration * skill.efficiency;
    DamageLine { kind: LineKind::Skill, source: skill.label(position), detail, total }
}

fn basic_damage(basic: &BasicAttackSpec, duration: f64, basic_turn: f64) -> f64 {
    basic.effective_damage() / basic_turn * duration * basic.efficiency
}

fn basic_line(basic: &BasicAttackSpec, duration: f64, basic_turn: f64, text: Texts) -> DamageLine {
    let detail = format!(
        "{} / {}s · {}",
        text.damage(basic.damage, basic.multiplier),
        text.plain(basic_turn),
        text.percent(basic.efficiency),
    );
    DamageLine {
        kind: LineKind::Basic,
        source: "Ataque básico".to_owned(),
        detail,
        total: basic_damage(basic, duration, basic_turn),
    }
}

fn basic_buff_line(
    basic: &BasicAttackSpec,
    buff: &BuffSpec,
    duration: f64,
    basic_turn: f64,
    text: Texts,
) -> DamageLine {
    let uptime = (buff.basic_duration / buff.cooldown).min(1.0);
    let detail = format!(
        "×{} por {}s / {}s",
        text.plain(buff.basic_multiplier),
        text.plain(buff.basic_duration),
        text.plain(buff.cooldown),
    );
    let total =
        basic_damage(basic, duration, basic_turn) * uptime * (buff.basic_multiplier - 1.0);
    DamageLine { kind: LineKind::Buff, source: "Buff: ataque básico".to_owned(), detail, total }
}

/// A magia com o maior ganho; `None` se nenhuma ganhar dano.
fn next_spell_line(
    skills: &[SkillSpec],
    buff: &BuffSpec,
    duration: f64,
    text: Texts,
) -> Option<DamageLine> {
    let mut best: Option<DamageLine> = None;
    for (index, skill) in skills.iter().enumerate() {
        let interval = skill.cooldown.max(buff.cooldown);
        let total = skill.effective_damage()
            * skill.efficiency
            * (buff.next_spell_multiplier - 1.0)
            * duration
            / interval;
        if total > 0.0 && best.as_ref().is_none_or(|b| total > b.total) {
            let detail = format!(
                "{} ×{} / {}s · {}",
                text.damage(skill.damage, skill.multiplier),
                text.plain(buff.next_spell_multiplier),
                text.plain(interval),
                text.percent(skill.efficiency),
            );
            let source = format!("Buff: próxima magia ({})", skill.label(index + 1));
            best = Some(DamageLine { kind: LineKind::Buff, source, detail, total });
        }
    }
    best
}

/// Textos do detalhamento, no formato numérico escolhido.
#[derive(Clone, Copy)]
struct Texts(NumberFormat);

impl Texts {
    fn plain(self, value: f64) -> String {
        format_plain(value, self.0)
    }

    fn damage(self, damage: f64, multiplier: Option<f64>) -> String {
        if damage <= 0.0 {
            return "sem teste".to_owned();
        }
        match multiplier {
            None => "sem elemento".to_owned(),
            Some(1.0) => format_number(damage, 0, self.0),
            Some(m) => format!("{} ×{}", format_number(damage, 0, self.0), self.plain(m)),
        }
    }

    fn percent(self, fraction: f64) -> String {
        format!("{}%", self.plain(round_to(fraction * 100.0, 2)))
    }
}
