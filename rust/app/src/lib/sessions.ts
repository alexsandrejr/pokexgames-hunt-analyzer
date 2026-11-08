// Chamadas da seção Sessões (src-tauri/src/commands/sessions.rs) e os tipos que elas devolvem.

import { invoke } from "./diagnostics";
import type { Choice } from "./api";
import type { RankedChartData, SeriesChartData } from "./charts";
import type { TableView } from "./table";

export interface CategoryChoice {
  value: string;
  label: string;
  plural: string;
}

export interface ImportOutcome {
  status: "imported" | "duplicate" | "error";
  source_name: string;
  message: string;
  hunt_id: number | null;
  warnings: string[];
  detail: string | null;
  saved_path: string | null;
  category: string | null;
}

export interface FilterSetup {
  presets: Choice[];
  operators: Choice[];
  item_sources: Choice[];
  metrics: [string, string, string][];
  players: string[];
  enemies: string[];
  drop_items: string[];
  supply_items: string[];
  parts: string[];
}

export interface FilterForm {
  preset: string;
  date_from: string;
  date_to: string;
  player: string;
  enemy: string;
  enemy_operator: string;
  enemy_quantity: string;
  item_source: string;
  item: string;
  item_operator: string;
  item_quantity: string;
  metrics: [string, { operator: string; value: string }][];
  advanced: string;
}

export interface StatCard {
  title: string;
  value: string;
  hint: string;
}

export interface ListTab {
  summary: [string, string][];
  table: TableView;
  sort_column: number;
  empty_message: string;
}

export interface HuntDetails {
  id: number;
  title: string;
  subtitle: string;
  cards: StatCard[];
  groups: { title: string; fields: [string, string][] }[];
  enemies: ListTab;
  drops: ListTab;
  supplies: ListTab;
  json: string;
  chat_messages: string[];
  charts: RankedChartData[];
}

export interface BossSummary {
  cards: StatCard[];
  has_sessions: boolean;
  hint: string | null;
  enemies: TableView;
  drops: TableView;
  elements: TableView;
  charts: SeriesChartData[];
}

export interface RewardLine {
  chat_name: string;
  item: string;
  count: number;
  unit_price: number | null;
  known: boolean;
  count_text: string;
  price_text: string;
  total_text: string;
}

export interface Comparison {
  title: string;
  subtitle: string;
  headers: [string, string][];
  rows: string[][];
}

export type ExportRequest =
  | { kind: "hunts"; hunt_ids: number[]; category: string | null }
  | { kind: "comparison"; hunt_ids: number[] }
  | { kind: "report"; scope: number }
  | { kind: "entity"; entity: EntityKind; name: string; scope: number };

export type EntityKind = "drops" | "supplies" | "enemies";

export const sessions = {
  counts: () => invoke<Record<string, number>>("session_counts"),
  categories: () => invoke<CategoryChoice[]>("session_categories"),
  list: (category: string | null) => invoke<{ table: TableView; total_all: number }>("hunt_list", { category }),
  delete: (huntIds: number[]) => invoke<number>("hunts_delete", { huntIds }),
  move: (huntIds: number[], category: string) => invoke<string>("hunts_move", { huntIds, category }),
  importTarget: (huntIds: number[]) =>
    invoke<{ category: string; hunt_ids: number[]; message: string | null }>("import_target", { huntIds }),
  filterSetup: () => invoke<FilterSetup>("filter_setup"),
  presetRange: (preset: string) => invoke<[string | null, string | null]>("filter_preset_range", { preset }),
  filterApply: (form: FilterForm) =>
    invoke<{ errors: string[]; invalid: string[]; parts: string[] }>("filter_apply", { form }),
  filterClear: () => invoke<void>("filter_clear"),
  droppedPaths: (paths: string[]) => invoke<string[]>("dropped_paths", { paths }),
  collectFiles: (paths: string[]) => invoke<string[]>("collect_files", { paths }),
  importFile: (path: string, allowDuplicate: boolean, category: string | null) =>
    invoke<ImportOutcome>("import_file", { path, allowDuplicate, category }),
  importPasted: (text: string, allowDuplicate: boolean, category: string | null) =>
    invoke<ImportOutcome>("import_pasted", { text, allowDuplicate, category }),
  importReport: (results: ImportOutcome[], cancelled: boolean) =>
    invoke<{ summary: string; lines: string[] }>("import_report", { results, cancelled }),
  pasteCheck: (text: string) => invoke<{ message: string; color: string; valid: boolean }>("paste_check", { text }),
  pasteSaveDir: (category: string | null) => invoke<string>("paste_save_dir", { category }),
  importStartDir: () => invoke<string>("import_start_dir"),
  details: (huntId: number) => invoke<HuntDetails | null>("hunt_details", { huntId }),
  chatPreview: (huntId: number, text: string) =>
    invoke<{ lines: RewardLine[]; status: string; color: string }>("chat_preview", { huntId, text }),
  chatQuote: (chatName: string, item: string, count: number) =>
    invoke<RewardLine>("chat_quote", { chatName, item, count }),
  chatStatus: (huntId: number, text: string, lines: RewardLine[]) =>
    invoke<[string, string]>("chat_status_for", { huntId, text, lines }),
  chatAdd: (huntId: number, text: string, lines: RewardLine[]) => invoke<number>("chat_add", { huntId, text, lines }),
  chatRemove: (huntId: number) => invoke<number>("chat_remove", { huntId }),
  comparison: (huntIds: number[]) => invoke<Comparison>("hunts_comparison", { huntIds }),
  exportFormats: () => invoke<{ value: string; label: string; description: string }[]>("export_formats"),
  exportDefaultPath: (request: ExportRequest, format: string) =>
    invoke<string>("export_default_path", { request, format }),
  bossSummary: (category: string) => invoke<BossSummary>("boss_summary", { category }),
  exportRun: (request: ExportRequest, format: string, path: string) =>
    invoke<string>("export_run", { request, format, path }),
};
