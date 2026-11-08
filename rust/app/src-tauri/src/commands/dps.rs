//! Comandos da página DPS (equivale às ações de `app/ui/dps/`).

use std::collections::HashMap;
use std::path::PathBuf;

use pxg_core::backup::BackupKind;
use pxg_core::dps::calculator::{EffectivenessLevel, Element, SkillReach, SkillShape};
use pxg_core::dps::service::{DamageSource, DpsService, PokemonData, dummy_options};
use pxg_core::dps::transfer::{DpsTransferService, ImportAction, ImportItem, ImportKind, read_bundle};
use pxg_core::format::{format_integer, format_plain};
use serde::Serialize;
use tauri::State;

use super::{Choice, CommandResult, message};
use crate::AppState;
use crate::forms::{
    BossForm, DamageTexts, PokemonForm, SettingsForm, SkillRow, Suggestions, TestInput, TestRow, average_text,
    empty_skill_row, parse_tests,
};
use crate::view::{BossView, PokemonRow, RankingView, boss_content, plural, pokemon_content};

fn service(state: &AppState) -> DpsService<'_> {
    DpsService::new(&state.database)
}

fn find_pokemon(service: &DpsService<'_>, pokemon_id: i64) -> CommandResult<PokemonData> {
    service
        .list_pokemons()
        .map_err(message)?
        .into_iter()
        .find(|p| p.id == pokemon_id)
        .ok_or_else(|| "Pokémon não encontrado.".to_owned())
}

// ------------------------------------------------------------------------------ opções

#[derive(Serialize)]
pub struct DpsOptions {
    sources: Vec<Choice>,
    dummies: Vec<Choice>,
    elements: Vec<Choice>,
    shapes: Vec<Choice>,
    reaches: Vec<Choice>,
    /// "Super Efetivo (2x)", para a efetividade do boss.
    levels: Vec<Choice>,
}

#[tauri::command]
pub fn dps_options(state: State<'_, AppState>) -> DpsOptions {
    let fmt = state.number_format();
    DpsOptions {
        sources: DamageSource::ALL.iter().map(|s| Choice::new(s.as_str(), s.label())).collect(),
        dummies: dummy_options().into_iter().map(|(v, l)| Choice::new(v, l)).collect(),
        elements: Element::ALL.iter().map(|e| Choice::new(e.as_str(), e.label())).collect(),
        shapes: SkillShape::ALL.iter().map(|s| Choice::new(s.as_str(), s.label())).collect(),
        reaches: SkillReach::ALL.iter().map(|r| Choice::new(r.as_str(), r.label())).collect(),
        levels: EffectivenessLevel::ALL
            .iter()
            .map(|l| Choice::new(l.as_str(), format!("{} ({}x)", l.label(), format_plain(l.multiplier(), fmt))))
            .collect(),
    }
}

// ------------------------------------------------------------------------------ ranking

#[derive(Serialize)]
pub struct DpsBosses {
    bosses: Vec<BossView>,
    /// Último boss escolhido, para abrir a página nele.
    last_boss_id: Option<i64>,
}

#[tauri::command]
pub fn dps_bosses(state: State<'_, AppState>) -> CommandResult<DpsBosses> {
    let service = service(&state);
    let fmt = state.number_format();
    Ok(DpsBosses {
        bosses: service.list_bosses().map_err(message)?.iter().map(|b| BossView::new(b, fmt)).collect(),
        last_boss_id: service.settings().map_err(message)?.last_boss_id,
    })
}

#[tauri::command]
pub fn dps_ranking(state: State<'_, AppState>, boss_id: i64) -> CommandResult<Vec<RankingView>> {
    let service = service(&state);
    let fmt = state.number_format();
    let Some(boss) = service.list_bosses().map_err(message)?.into_iter().find(|b| b.id == boss_id) else {
        return Ok(Vec::new());
    };
    Ok(service.ranking(boss_id, fmt).map_err(message)?.iter().map(|e| RankingView::new(e, &boss, fmt)).collect())
}

#[tauri::command]
pub fn dps_remember_boss(state: State<'_, AppState>, boss_id: i64) -> CommandResult<()> {
    service(&state).remember_boss(boss_id).map_err(message)
}

#[tauri::command]
pub fn dps_set_source(state: State<'_, AppState>, boss_id: i64, source: DamageSource) -> CommandResult<()> {
    service(&state).set_boss_damage_source(boss_id, source).map_err(message)
}

#[tauri::command]
pub fn dps_set_dummy(state: State<'_, AppState>, boss_id: i64, dummy: String) -> CommandResult<()> {
    service(&state).set_boss_dummy(boss_id, &dummy).map_err(message)
}

/// Tira o pokémon do boss, sem apagar o cadastro.
#[tauri::command]
pub fn dps_remove_from_boss(state: State<'_, AppState>, boss_id: i64, pokemon_id: i64) -> CommandResult<()> {
    let service = service(&state);
    let boss = service.list_bosses().map_err(message)?.into_iter().find(|b| b.id == boss_id).ok_or("Boss não encontrado.")?;
    let remaining: Vec<i64> = boss.pokemon_ids.into_iter().filter(|id| *id != pokemon_id).collect();
    service.set_boss_pokemons(boss_id, &remaining).map_err(message)
}

#[tauri::command]
pub fn dps_set_boss_pokemons(state: State<'_, AppState>, boss_id: i64, pokemon_ids: Vec<i64>) -> CommandResult<()> {
    service(&state).set_boss_pokemons(boss_id, &pokemon_ids).map_err(message)
}

#[derive(Serialize)]
pub struct PokemonChoice {
    id: i64,
    name: String,
    /// "Nome — observação", em uma linha.
    label: String,
}

#[tauri::command]
pub fn dps_pokemon_choices(state: State<'_, AppState>) -> CommandResult<Vec<PokemonChoice>> {
    Ok(service(&state)
        .list_pokemons()
        .map_err(message)?
        .into_iter()
        .map(|p| {
            let label = if p.note.is_empty() { p.name.clone() } else { format!("{} — {}", p.name, p.note) };
            PokemonChoice { id: p.id, name: p.name, label: label.replace('\n', " ") }
        })
        .collect())
}

// ------------------------------------------------------------------------------ bosses

#[tauri::command]
pub fn dps_boss_form(state: State<'_, AppState>, boss_id: Option<i64>) -> CommandResult<BossForm> {
    let bosses = service(&state).list_bosses().map_err(message)?;
    let boss = match boss_id {
        Some(id) => Some(bosses.iter().find(|b| b.id == id).ok_or("Boss não encontrado.")?),
        None => None,
    };
    Ok(BossForm::fill(boss, state.number_format()))
}

/// Cria ou altera o boss e devolve o id dele.
#[tauri::command]
pub fn dps_save_boss(state: State<'_, AppState>, boss_id: Option<i64>, form: BossForm) -> CommandResult<i64> {
    let service = service(&state);
    let bosses = service.list_bosses().map_err(message)?;
    let others: Vec<_> = bosses.iter().filter(|b| Some(b.id) != boss_id).collect();
    let input = form.parse(&others, state.number_format()).map_err(message)?;
    service
        .save_boss(boss_id, &input.name, input.time_limit_seconds, Some(&input.elements), Some(&input.effectiveness))
        .map_err(message)
}

#[tauri::command]
pub fn dps_delete_boss(state: State<'_, AppState>, boss_id: i64) -> CommandResult<()> {
    service(&state).delete_boss(boss_id).map_err(message)
}

// ------------------------------------------------------------------------------ pokémons

#[tauri::command]
pub fn dps_pokemons(state: State<'_, AppState>, dummy: String) -> CommandResult<Vec<PokemonRow>> {
    let service = service(&state);
    let fmt = state.number_format();
    let boss_names: HashMap<i64, String> = service.list_bosses().map_err(message)?.into_iter().map(|b| (b.id, b.name)).collect();
    Ok(service.list_pokemons().map_err(message)?.iter().map(|p| PokemonRow::new(p, &boss_names, &dummy, fmt)).collect())
}

#[derive(Serialize)]
pub struct PokemonDialog {
    form: PokemonForm,
    suggestions: Suggestions,
    /// Linha para "Adicionar skill".
    empty_skill: SkillRow,
    /// "Um ataque a cada 2,5s (ajuste o turno em Ajustes)."
    turn_hint: String,
}

#[tauri::command]
pub fn dps_pokemon_form(state: State<'_, AppState>, pokemon_id: Option<i64>) -> CommandResult<PokemonDialog> {
    let service = service(&state);
    let fmt = state.number_format();
    let settings = service.settings().map_err(message)?;
    let pokemon = pokemon_id.map(|id| find_pokemon(&service, id)).transpose()?;
    Ok(PokemonDialog {
        form: PokemonForm::fill(pokemon.as_ref(), &settings, fmt),
        suggestions: Suggestions::new(&settings, fmt),
        empty_skill: empty_skill_row(&settings, fmt),
        turn_hint: format!(
            "Um ataque a cada {}s (ajuste o turno em Ajustes).",
            format_plain(settings.basic_turn_seconds, fmt)
        ),
    })
}

#[tauri::command]
pub fn dps_damage_texts(state: State<'_, AppState>, pokemon_id: Option<i64>, dummy: String) -> CommandResult<DamageTexts> {
    let service = service(&state);
    let pokemon = pokemon_id.map(|id| find_pokemon(&service, id)).transpose()?;
    Ok(DamageTexts::new(pokemon.as_ref(), &dummy, state.number_format()))
}

/// Cria ou altera o pokémon e devolve o id dele.
#[tauri::command]
pub fn dps_save_pokemon(state: State<'_, AppState>, pokemon_id: Option<i64>, form: PokemonForm) -> CommandResult<i64> {
    let spec = form.parse(state.number_format()).map_err(|e| e.0)?;
    service(&state).save_pokemon(pokemon_id, &form.clean_name(), &form.clean_note(), &spec, None).map_err(message)
}

#[tauri::command]
pub fn dps_duplicate_pokemon(state: State<'_, AppState>, pokemon_id: i64) -> CommandResult<i64> {
    service(&state).duplicate_pokemon(pokemon_id).map_err(message)
}

#[tauri::command]
pub fn dps_delete_pokemon(state: State<'_, AppState>, pokemon_id: i64) -> CommandResult<()> {
    service(&state).delete_pokemon(pokemon_id).map_err(message)
}

// ------------------------------------------------------------------------------ testes

/// Uma skill ou o ataque básico (`skill_id` `None`), com os testes dela.
#[derive(Serialize)]
pub struct TestTarget {
    skill_id: Option<i64>,
    label: String,
    /// "Ataque básico · Elemento: Fire", acima da tabela.
    heading: String,
    tests: Vec<TestRow>,
}

#[derive(Serialize)]
pub struct TestsDialog {
    title: String,
    targets: Vec<TestTarget>,
    /// Dummies e depois os bosses ("Boss: nome", valor `boss:<id>`).
    places: Vec<Choice>,
    dummy_count: usize,
    empty_row: TestRow,
}

#[tauri::command]
pub fn dps_tests_form(state: State<'_, AppState>, pokemon_id: i64) -> CommandResult<TestsDialog> {
    let service = service(&state);
    let fmt = state.number_format();
    let pokemon = find_pokemon(&service, pokemon_id)?;
    let rows = |skill_id: Option<i64>| -> Vec<TestRow> {
        pokemon.tests.get(&skill_id).map(|t| t.iter().map(|t| TestRow::saved(t, fmt)).collect()).unwrap_or_default()
    };
    let target = |skill_id, label: String, element: Option<Element>| TestTarget {
        skill_id,
        heading: format!("{label} · Elemento: {}", element.map_or(pxg_core::format::PLACEHOLDER, |e| e.label())),
        label,
        tests: rows(skill_id),
    };
    let mut targets = Vec::new();
    if let Some(basic) = &pokemon.spec.basic {
        targets.push(target(None, "Ataque básico".into(), basic.element));
    }
    for (index, skill) in pokemon.spec.skills.iter().enumerate() {
        targets.push(target(skill.skill_id, skill.label(index + 1), skill.element));
    }
    let dummies = dummy_options();
    let mut places: Vec<Choice> = dummies.iter().map(|(v, l)| Choice::new(*v, *l)).collect();
    for boss in service.list_bosses().map_err(message)? {
        places.push(Choice::new(format!("boss:{}", boss.id), format!("Boss: {}", boss.name)));
    }
    Ok(TestsDialog {
        title: format!("Testes de {}", pokemon.name),
        targets,
        places,
        dummy_count: dummies.len(),
        empty_row: TestRow::empty(fmt),
    })
}

/// Grava os testes de uma skill e devolve como ficaram, com as datas.
#[tauri::command]
pub fn dps_save_tests(
    state: State<'_, AppState>,
    pokemon_id: i64,
    skill_id: Option<i64>,
    rows: Vec<TestInput>,
) -> CommandResult<Vec<TestRow>> {
    let service = service(&state);
    let fmt = state.number_format();
    let boss_names: HashMap<i64, String> = service.list_bosses().map_err(message)?.into_iter().map(|b| (b.id, b.name)).collect();
    let tests = parse_tests(&rows, &boss_names, fmt).map_err(|e| e.0)?;
    let saved = service.save_damage_tests(pokemon_id, skill_id, &tests).map_err(message)?;
    Ok(saved.iter().map(|t| TestRow::saved(t, fmt)).collect())
}

#[tauri::command]
pub fn dps_test_average(state: State<'_, AppState>, damages: Vec<String>) -> String {
    average_text(&damages, state.number_format())
}

// ------------------------------------------------------------------------------ ajustes

#[tauri::command]
pub fn dps_settings_form(state: State<'_, AppState>) -> CommandResult<SettingsForm> {
    Ok(SettingsForm::fill(&service(&state).settings().map_err(message)?, state.number_format()))
}

#[tauri::command]
pub fn dps_save_settings(state: State<'_, AppState>, form: SettingsForm) -> CommandResult<()> {
    let service = service(&state);
    let settings = form.parse(&service.settings().map_err(message)?, state.number_format()).map_err(message)?;
    service.update_settings(&settings).map_err(message)
}

// ------------------------------------------------------------------------------ exportar e importar

/// Sugestão de arquivo: `dps_cadastros_<data>.json` na pasta do usuário.
#[tauri::command]
pub fn dps_export_path() -> String {
    let name = format!("dps_cadastros_{}.json", chrono::Local::now().format("%Y-%m-%d"));
    crate::home().join(name).display().to_string()
}

#[tauri::command]
pub fn dps_export(state: State<'_, AppState>, path: PathBuf, boss_ids: Vec<i64>, pokemon_ids: Vec<i64>) -> CommandResult<()> {
    DpsTransferService::new(&state.database).export_file(&path, &boss_ids, &pokemon_ids).map_err(message)
}

fn action_value(action: ImportAction) -> &'static str {
    match action {
        ImportAction::Skip => "skip",
        ImportAction::Create => "create",
        ImportAction::Replace => "replace",
    }
}

fn action_label(item: &ImportItem, action: ImportAction) -> &'static str {
    match action {
        ImportAction::Create if item.existing_id.is_some() => "Criar cópia",
        ImportAction::Create => "Importar",
        ImportAction::Skip => "Pular",
        ImportAction::Replace => "Substituir",
    }
}

#[derive(Serialize)]
pub struct ImportRow {
    kind: &'static str,
    name: String,
    content: String,
    status: &'static str,
    actions: Vec<Choice>,
    action: &'static str,
}

#[derive(Serialize)]
pub struct ImportPlan {
    summary: String,
    rows: Vec<ImportRow>,
}

/// Lê o arquivo e guarda o plano até a pessoa confirmar; nada é gravado aqui.
#[tauri::command]
pub fn dps_import_plan(state: State<'_, AppState>, path: PathBuf) -> CommandResult<ImportPlan> {
    let fmt = state.number_format();
    let bundle = read_bundle(&path).map_err(message)?;
    let items = DpsTransferService::new(&state.database).plan(&bundle).map_err(message)?;
    let new_count = items.iter().filter(|i| i.existing_id.is_none()).count();
    let summary = format!(
        "{} no arquivo: {} novos e {} com o nome já em uso. Nada é gravado até você confirmar.",
        plural(items.len(), "cadastro", "cadastros", fmt),
        format_integer(new_count as i64, fmt),
        format_integer((items.len() - new_count) as i64, fmt),
    );
    let rows = items
        .iter()
        .map(|item| ImportRow {
            kind: item.kind.label(),
            name: item.name.clone(),
            content: match item.kind {
                ImportKind::Boss => boss_content(&bundle.bosses[item.index], fmt),
                ImportKind::Pokemon => pokemon_content(&bundle.pokemons[item.index], fmt),
            },
            status: if item.existing_id.is_none() { "Novo" } else { "Nome já existe" },
            actions: item.actions().iter().map(|a| Choice::new(action_value(*a), action_label(item, *a))).collect(),
            action: action_value(item.action),
        })
        .collect();
    *state.pending_import.lock().unwrap_or_else(|e| e.into_inner()) = Some((bundle, items));
    Ok(ImportPlan { summary, rows })
}

#[derive(Serialize)]
pub struct ImportOutcome {
    summary: String,
    /// Aviso dos testes e vínculos que ficaram de fora, se houver.
    details: Option<String>,
}

/// Aplica o plano lido por `dps_import_plan`, com a escolha de cada linha.
#[tauri::command]
pub fn dps_import_apply(state: State<'_, AppState>, actions: Vec<String>) -> CommandResult<ImportOutcome> {
    let fmt = state.number_format();
    let (bundle, mut items) =
        state.pending_import.lock().unwrap_or_else(|e| e.into_inner()).take().ok_or("Escolha o arquivo de novo.")?;
    for (item, chosen) in items.iter_mut().zip(&actions) {
        if let Some(action) = item.actions().iter().find(|a| action_value(**a) == chosen) {
            item.action = *action;
        }
    }
    // Substituir apaga testes: sem o backup, a importação não continua.
    if items.iter().any(|i| i.action == ImportAction::Replace) {
        state
            .backups()
            .create_backup(BackupKind::BeforeImport, None)
            .map_err(|e| format!("Nada foi importado, porque o backup falhou.\n\n{e}"))?;
    }
    let result = DpsTransferService::new(&state.database).apply(&bundle, &items).map_err(message)?;
    let summary = format!(
        "Importação concluída: {} novos, {} substituídos e {} pulados.",
        format_integer(result.created as i64, fmt),
        format_integer(result.replaced as i64, fmt),
        format_integer(result.skipped as i64, fmt),
    );
    let details = (result.dropped_tests > 0 || result.dropped_links > 0).then(|| {
        format!(
            "{summary}\n\nFicaram de fora {} testes e {} vínculos, porque citam bosses que não vieram no arquivo e não existem aqui.",
            format_integer(result.dropped_tests as i64, fmt),
            format_integer(result.dropped_links as i64, fmt),
        )
    });
    Ok(ImportOutcome { summary, details })
}
