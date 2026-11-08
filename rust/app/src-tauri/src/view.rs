//! O que as telas recebem: valores já formatados no formato numérico escolhido, como a
//! interface em Python mostra.

use std::collections::HashMap;

use pxg_core::dps::calculator::{BuffSpec, EffectivenessLevel, Element};
use pxg_core::dps::service::{BossData, DamageSource, PokemonData, RankingEntry, dummy_label};
use pxg_core::dps::transfer::{BundleBoss, BundlePokemon};
use pxg_core::format::{
    NumberFormat, PLACEHOLDER, format_duration_long, format_integer, format_money, format_percent, format_plain,
};
use pxg_core::text::sort_casefold;

use serde::Serialize;

use crate::forms::{damage_text, percent_text};

/// Cores clássicas dos tipos: as mesmas nos dois temas, para serem reconhecidas.
pub fn element_color(element: Element) -> &'static str {
    match element {
        Element::Normal => "#a8a77a",
        Element::Fire => "#ee8130",
        Element::Water => "#6390f0",
        Element::Grass => "#7ac74c",
        Element::Electric => "#f7d02c",
        Element::Ice => "#96d9d6",
        Element::Fighting => "#c22e28",
        Element::Poison => "#a33ea1",
        Element::Ground => "#e2bf65",
        Element::Flying => "#a98ff3",
        Element::Psychic => "#f95587",
        Element::Bug => "#a6b91a",
        Element::Rock => "#b6a136",
        Element::Ghost => "#735797",
        Element::Dragon => "#6f35fc",
        Element::Dark => "#705746",
        Element::Steel => "#b7b7ce",
        Element::Fairy => "#d685ad",
    }
}

/// Etiqueta de elemento: o texto escuro ou branco é o que contrasta mais com a cor do tipo.
#[derive(Serialize)]
pub struct ElementTag {
    pub label: &'static str,
    pub color: &'static str,
    pub text_color: &'static str,
}

impl ElementTag {
    pub fn new(element: Element) -> Self {
        let color = element_color(element);
        let channel = |i: usize| u8::from_str_radix(&color[i..i + 2], 16).unwrap_or(0) as f64;
        let luminance = 0.299 * channel(1) + 0.587 * channel(3) + 0.114 * channel(5);
        Self { label: element.label(), color, text_color: if luminance > 140.0 { "#15192a" } else { "#ffffff" } }
    }
}

#[derive(Serialize)]
pub struct TagGroup {
    pub title: String,
    pub elements: Vec<ElementTag>,
}

#[derive(Serialize)]
pub struct BossView {
    pub id: i64,
    pub name: String,
    /// "Padrão · 7min" para o seletor.
    pub label: String,
    pub time_limit_seconds: i64,
    pub dummy: String,
    /// Dummy de onde vem o dano (o Neutro na Efetividade); o diálogo do pokémon abre nele.
    pub base_dummy: String,
    pub damage_source: DamageSource,
    pub pokemon_ids: Vec<i64>,
    /// Elementos do boss e os ataques fora do Normal, agrupados como no jogo.
    pub groups: Vec<TagGroup>,
    /// Efetividade sem nenhuma fraqueza marcada: tudo conta como Normal.
    pub no_weaknesses: bool,
}

pub fn format_time(seconds: i64, fmt: NumberFormat) -> String {
    if seconds % 60 == 0 { format_duration_long(seconds as f64, fmt) } else { format!("{}s", format_plain(seconds as f64, fmt)) }
}

impl BossView {
    pub fn new(boss: &BossData, fmt: NumberFormat) -> Self {
        let mut groups = Vec::new();
        if !boss.elements.is_empty() {
            groups.push(TagGroup { title: "Elemento".into(), elements: boss.elements.iter().map(|e| ElementTag::new(*e)).collect() });
        }
        for level in EffectivenessLevel::ALL {
            let elements: Vec<ElementTag> = Element::ALL
                .iter()
                .filter(|e| boss.effectiveness.get(e) == Some(level))
                .map(|e| ElementTag::new(*e))
                .collect();
            if !elements.is_empty() {
                groups.push(TagGroup { title: format!("{} {}x", level.label(), format_plain(level.multiplier(), fmt)), elements });
            }
        }
        Self {
            id: boss.id,
            name: boss.name.clone(),
            label: format!("{} · {}", boss.name, format_time(boss.time_limit_seconds, fmt)),
            time_limit_seconds: boss.time_limit_seconds,
            dummy: boss.dummy.clone(),
            base_dummy: boss.base_dummy().to_owned(),
            damage_source: boss.damage_source,
            pokemon_ids: boss.pokemon_ids.iter().copied().collect(),
            groups,
            no_weaknesses: boss.damage_source == DamageSource::Effectiveness && boss.effectiveness.is_empty(),
        }
    }
}

#[derive(Serialize)]
pub struct LineView {
    pub source: String,
    pub detail: String,
    pub total: f64,
    pub total_text: String,
    pub share_text: String,
}

#[derive(Serialize)]
pub struct RankingView {
    pub position: usize,
    pub pokemon_id: i64,
    pub name: String,
    pub note: String,
    pub total_text: String,
    pub dps_text: String,
    pub share: f64,
    /// "2 sem teste · 1 sem elemento", embaixo da barra.
    pub warnings: String,
    /// Texto completo do que falta, no detalhamento.
    pub missing_text: String,
    pub lines: Vec<LineView>,
}

impl RankingView {
    pub fn new(entry: &RankingEntry, boss: &BossData, fmt: NumberFormat) -> Self {
        let total = entry.breakdown.total;
        let mut warnings = Vec::new();
        if !entry.missing.is_empty() {
            warnings.push(format!("{} sem teste", entry.missing.len()));
        }
        if !entry.no_element.is_empty() {
            warnings.push(format!("{} sem elemento", entry.no_element.len()));
        }
        let mut missing = Vec::new();
        if !entry.missing.is_empty() {
            let place = if boss.damage_source == DamageSource::Real {
                "neste boss".to_owned()
            } else {
                format!("no dummy {}", dummy_label(boss.base_dummy()))
            };
            missing.push(format!("Sem teste {place}: {}.", entry.missing.join(", ")));
        }
        if !entry.no_element.is_empty() {
            missing.push(format!("Sem elemento: {}.", entry.no_element.join(", ")));
        }
        Self {
            position: entry.position,
            pokemon_id: entry.pokemon.id,
            name: entry.pokemon.name.clone(),
            note: entry.pokemon.note.clone(),
            total_text: format_money(total, fmt),
            dps_text: format_money(entry.breakdown.dps, fmt),
            share: entry.share_of_leader,
            warnings: warnings.join(" · "),
            missing_text: missing.join(" "),
            lines: entry
                .breakdown
                .lines
                .iter()
                .map(|line| LineView {
                    source: line.source.clone(),
                    detail: line.detail.clone(),
                    total: line.total,
                    total_text: format_money(line.total, fmt),
                    share_text: format_percent((total != 0.0).then(|| line.total / total), fmt),
                })
                .collect(),
        }
    }
}

// ------------------------------------------------------------------------------ aba Pokémons

/// Uma skill no detalhe da aba Pokémons, com o dano no dummy escolhido.
#[derive(Serialize)]
pub struct SkillLine {
    pub label: String,
    pub shape: &'static str,
    pub reach: &'static str,
    pub element: String,
    pub damage: String,
    pub cooldown: String,
    pub efficiency: String,
    pub tests: String,
}

/// Uma linha da aba Pokémons (`dps_pokemons_tab.py`).
#[derive(Serialize)]
pub struct PokemonRow {
    pub id: i64,
    pub name: String,
    pub skill_count: usize,
    pub skill_count_text: String,
    /// "75% · Fire": aproveitamento e elemento do básico.
    pub basic: String,
    pub buff: String,
    pub bosses: String,
    /// Observação em uma linha, para a tabela.
    pub note_line: String,
    pub note: String,
    /// "Ataque básico: 1.234", ao lado do nome no detalhe.
    pub basic_damage: String,
    pub skills: Vec<SkillLine>,
}

fn percent_label(fraction: f64, fmt: NumberFormat) -> String {
    format!("{}%", percent_text(fraction, fmt))
}

fn buff_summary(buff: Option<&BuffSpec>, fmt: NumberFormat) -> String {
    let Some(buff) = buff else { return PLACEHOLDER.into() };
    let mut effects = Vec::new();
    if buff.basic_multiplier > 1.0 {
        effects.push(format!(
            "básico ×{} por {}s",
            format_plain(buff.basic_multiplier, fmt),
            format_plain(buff.basic_duration, fmt)
        ));
    }
    if buff.next_spell_multiplier > 1.0 {
        effects.push(format!("magia ×{}", format_plain(buff.next_spell_multiplier, fmt)));
    }
    format!("{} / {}s", effects.join(" + "), format_plain(buff.cooldown, fmt))
}

fn text_or_placeholder(text: String) -> String {
    if text.is_empty() { PLACEHOLDER.into() } else { text }
}

impl PokemonRow {
    pub fn new(pokemon: &PokemonData, boss_names: &HashMap<i64, String>, dummy: &str, fmt: NumberFormat) -> Self {
        let basic = pokemon.spec.basic.as_ref().map_or_else(
            || PLACEHOLDER.to_owned(),
            |b| {
                let mut parts = vec![percent_label(b.efficiency, fmt)];
                if let Some(element) = b.element {
                    parts.push(element.label().into());
                }
                parts.join(" · ")
            },
        );
        let mut bosses: Vec<String> = pokemon.boss_ids.iter().filter_map(|id| boss_names.get(id).cloned()).collect();
        sort_casefold(&mut bosses, |name| name.as_str());
        let basic_damage = if pokemon.spec.basic.is_some() {
            format!("Ataque básico: {}", damage_text(pokemon.damage_on(None, dummy), fmt))
        } else {
            String::new()
        };
        let skills = pokemon
            .spec
            .skills
            .iter()
            .enumerate()
            .map(|(index, skill)| SkillLine {
                label: skill.label(index + 1),
                shape: skill.shape.label(),
                reach: skill.reach.label(),
                element: skill.element.map_or(PLACEHOLDER, |e| e.label()).into(),
                damage: damage_text(pokemon.damage_on(skill.skill_id, dummy), fmt),
                cooldown: format_plain(skill.cooldown, fmt),
                efficiency: percent_label(skill.efficiency, fmt),
                tests: format_integer(pokemon.tests.get(&skill.skill_id).map_or(0, Vec::len) as i64, fmt),
            })
            .collect();
        Self {
            id: pokemon.id,
            name: pokemon.name.clone(),
            skill_count: pokemon.spec.skills.len(),
            skill_count_text: format_integer(pokemon.spec.skills.len() as i64, fmt),
            basic,
            buff: buff_summary(pokemon.spec.buff.as_ref(), fmt),
            bosses: text_or_placeholder(bosses.join(", ")),
            note_line: text_or_placeholder(pokemon.note.replace('\n', " ")),
            note: pokemon.note.clone(),
            basic_damage,
            skills,
        }
    }
}

// ------------------------------------------------------------------------------ importação

pub fn plural(count: usize, singular: &str, plural: &str, fmt: NumberFormat) -> String {
    format!("{} {}", format_integer(count as i64, fmt), if count == 1 { singular } else { plural })
}

pub fn boss_content(boss: &BundleBoss, fmt: NumberFormat) -> String {
    let source = if boss.damage_source == DamageSource::Dummy {
        format!("Dummy {}", dummy_label(&boss.dummy))
    } else {
        boss.damage_source.label().to_owned()
    };
    format!("{} · {source}", format_duration_long(boss.time_limit_seconds as f64, fmt))
}

pub fn pokemon_content(pokemon: &BundlePokemon, fmt: NumberFormat) -> String {
    format!(
        "{} · {}",
        plural(pokemon.spec.skills.len(), "skill", "skills", fmt),
        plural(pokemon.test_count(), "teste", "testes", fmt)
    )
}
