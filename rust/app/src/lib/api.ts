// Chamadas aos comandos do Rust (src-tauri/src/commands.rs) e os tipos que eles devolvem.

import { invoke } from "./diagnostics";

export interface AppInfo {
  version: string;
  theme: "dark" | "light";
  number_format: string;
  database_path: string;
  data_dir: string;
  portable: boolean;
  /** `--smoke-test`: visitar todas as páginas e fechar. */
  smoke_test: boolean;
}

export type DamageSource = "effectiveness" | "dummy" | "real";

export interface ElementTag {
  label: string;
  color: string;
  text_color: string;
}

export interface TagGroup {
  title: string;
  elements: ElementTag[];
}

export interface Boss {
  id: number;
  name: string;
  label: string;
  time_limit_seconds: number;
  dummy: string;
  base_dummy: string;
  damage_source: DamageSource;
  pokemon_ids: number[];
  groups: TagGroup[];
  no_weaknesses: boolean;
}

export interface DamageLine {
  source: string;
  detail: string;
  total: number;
  total_text: string;
  share_text: string;
}

export interface RankingEntry {
  position: number;
  pokemon_id: number;
  name: string;
  note: string;
  total_text: string;
  dps_text: string;
  share: number;
  warnings: string;
  missing_text: string;
  lines: DamageLine[];
}

export interface Choice {
  value: string;
  label: string;
}

export interface DpsOptions {
  sources: Choice[];
  dummies: Choice[];
  elements: Choice[];
  shapes: Choice[];
  reaches: Choice[];
  levels: Choice[];
}

export interface PokemonChoice {
  id: number;
  name: string;
  label: string;
}

export interface SkillLine {
  label: string;
  shape: string;
  reach: string;
  element: string;
  damage: string;
  cooldown: string;
  efficiency: string;
  tests: string;
}

export interface PokemonRow {
  id: number;
  name: string;
  skill_count: number;
  skill_count_text: string;
  basic: string;
  buff: string;
  bosses: string;
  note_line: string;
  note: string;
  basic_damage: string;
  skills: SkillLine[];
}

export interface SkillRow {
  skill_id: number | null;
  name: string;
  shape: string;
  reach: string;
  element: string | null;
  cooldown: string;
  percent: string;
  suggestion: string;
}

export interface PokemonForm {
  name: string;
  note: string;
  has_basic: boolean;
  basic_percent: string;
  basic_element: string | null;
  has_buff: boolean;
  buff_cooldown: string;
  buff_basic: string;
  buff_duration: string;
  buff_spell: string;
  skills: SkillRow[];
}

export interface PokemonDialogData {
  form: PokemonForm;
  suggestions: { target_melee: string; default: string };
  empty_skill: SkillRow;
  turn_hint: string;
}

export interface DamageTexts {
  basic: string;
  skills: Record<string, string>;
}

export interface BossForm {
  name: string;
  minutes: string;
  elements: (string | null)[];
  effectiveness: Record<string, string>;
}

export interface TestRow {
  place: string;
  damages: string[];
  average: string;
  created: string;
  created_tip: string;
  updated: string;
  updated_tip: string;
}

export interface TestTarget {
  skill_id: number | null;
  label: string;
  heading: string;
  tests: TestRow[];
}

export interface TestsDialogData {
  title: string;
  targets: TestTarget[];
  places: Choice[];
  dummy_count: number;
  empty_row: TestRow;
}

export interface SettingsForm {
  turn: string;
  target_melee: string;
  default: string;
  basic: string;
}

export interface ImportRow {
  kind: string;
  name: string;
  content: string;
  status: string;
  actions: Choice[];
  action: string;
}

export interface ImportPlan {
  summary: string;
  rows: ImportRow[];
}

export const api = {
  appInfo: () => invoke<AppInfo>("app_info"),
  dpsOptions: () => invoke<DpsOptions>("dps_options"),
  dpsBosses: () => invoke<{ bosses: Boss[]; last_boss_id: number | null }>("dps_bosses"),
  dpsRanking: (bossId: number) => invoke<RankingEntry[]>("dps_ranking", { bossId }),
  dpsRememberBoss: (bossId: number) => invoke<void>("dps_remember_boss", { bossId }),
  dpsSetSource: (bossId: number, source: DamageSource) => invoke<void>("dps_set_source", { bossId, source }),
  dpsSetDummy: (bossId: number, dummy: string) => invoke<void>("dps_set_dummy", { bossId, dummy }),
  dpsRemoveFromBoss: (bossId: number, pokemonId: number) =>
    invoke<void>("dps_remove_from_boss", { bossId, pokemonId }),
  dpsSetBossPokemons: (bossId: number, pokemonIds: number[]) =>
    invoke<void>("dps_set_boss_pokemons", { bossId, pokemonIds }),
  dpsPokemonChoices: () => invoke<PokemonChoice[]>("dps_pokemon_choices"),
  dpsBossForm: (bossId: number | null) => invoke<BossForm>("dps_boss_form", { bossId }),
  dpsSaveBoss: (bossId: number | null, form: BossForm) => invoke<number>("dps_save_boss", { bossId, form }),
  dpsDeleteBoss: (bossId: number) => invoke<void>("dps_delete_boss", { bossId }),
  dpsPokemons: (dummy: string) => invoke<PokemonRow[]>("dps_pokemons", { dummy }),
  dpsPokemonForm: (pokemonId: number | null) => invoke<PokemonDialogData>("dps_pokemon_form", { pokemonId }),
  dpsDamageTexts: (pokemonId: number | null, dummy: string) =>
    invoke<DamageTexts>("dps_damage_texts", { pokemonId, dummy }),
  dpsSavePokemon: (pokemonId: number | null, form: PokemonForm) =>
    invoke<number>("dps_save_pokemon", { pokemonId, form }),
  dpsDuplicatePokemon: (pokemonId: number) => invoke<number>("dps_duplicate_pokemon", { pokemonId }),
  dpsDeletePokemon: (pokemonId: number) => invoke<void>("dps_delete_pokemon", { pokemonId }),
  dpsTestsForm: (pokemonId: number) => invoke<TestsDialogData>("dps_tests_form", { pokemonId }),
  dpsSaveTests: (pokemonId: number, skillId: number | null, rows: { place: string; damages: string[] }[]) =>
    invoke<TestRow[]>("dps_save_tests", { pokemonId, skillId, rows }),
  dpsTestAverage: (damages: string[]) => invoke<string>("dps_test_average", { damages }),
  dpsSettingsForm: () => invoke<SettingsForm>("dps_settings_form"),
  dpsSaveSettings: (form: SettingsForm) => invoke<void>("dps_save_settings", { form }),
  dpsExportPath: () => invoke<string>("dps_export_path"),
  dpsExport: (path: string, bossIds: number[], pokemonIds: number[]) =>
    invoke<void>("dps_export", { path, bossIds, pokemonIds }),
  dpsImportPlan: (path: string) => invoke<ImportPlan>("dps_import_plan", { path }),
  dpsImportApply: (actions: string[]) =>
    invoke<{ summary: string; details: string | null }>("dps_import_apply", { actions }),
};
