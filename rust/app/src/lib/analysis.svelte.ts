// Chamadas da seção Análise (src-tauri/src/commands/analysis.rs) e os tipos que elas devolvem.

import { invoke } from "./diagnostics";
import type { SeriesChartData } from "./charts";
import type { EntityKind, StatCard } from "./sessions";
import type { TableView } from "./table";

export interface Report {
  subtitle: string;
  cards: StatCard[];
  metrics: TableView;
  drops: TableView;
  supplies: TableView;
  enemies: TableView;
}

export interface Dashboard {
  subtitle: string;
  main_cards: StatCard[];
  small_cards: StatCard[];
  hint: string | null;
  categories: StatCard[];
  charts_title: string;
  charts_hint: string;
  charts: SeriesChartData[];
}

export interface EntityReport {
  /** Aviso no lugar dos resultados: [título, mensagem]. */
  empty: [string, string] | null;
  cards: StatCard[];
  chart: SeriesChartData | null;
  table_title: string;
  table: TableView | null;
}

export interface PriceItem {
  name: string;
  has_custom_price: boolean;
  price_text: string;
}

export interface Prices {
  table: TableView;
  items: PriceItem[];
  custom_count: number;
}

export interface PriceCheck {
  text: string;
  error: boolean;
  valid: boolean;
}

export const analysis = {
  scopes: () => invoke<string[]>("analysis_scopes"),
  report: (scope: number) => invoke<Report>("analysis_report", { scope }),
  dashboardDefaultScope: () => invoke<number>("dashboard_default_scope"),
  dashboard: (scopeIndex: number) => invoke<Dashboard>("dashboard", { scopeIndex }),
  entityNames: (kind: EntityKind) => invoke<string[]>("entity_names", { kind }),
  entityReport: (kind: EntityKind, name: string, scope: number) =>
    invoke<EntityReport>("entity_report", { kind, name, scope }),
  prices: () => invoke<Prices>("price_list"),
  priceCheck: (name: string, price: string) => invoke<PriceCheck>("price_check_input", { name, price }),
  setPrice: (name: string, price: string) => invoke<string>("price_set", { name, price }),
  clearPrices: (names: string[]) => invoke<string>("price_clear", { names }),
};

/**
 * O que cada página guarda enquanto o app está aberto, como os widgets do Python: o escopo
 * (começa em "Hunts", como o CategoryScopeCombo) e o último item analisado.
 */
export const analysisState = $state({
  /** -1 até o Rust dizer o padrão do Início ("Hunts e bosses"). */
  dashboardScope: -1,
  reportsScope: 0,
  items: { scope: 0, kind: "drops" as EntityKind, name: "", analyzed: null as { kind: EntityKind; name: string } | null },
  enemies: { scope: 0, kind: "enemies" as EntityKind, name: "", analyzed: null as { kind: EntityKind; name: string } | null },
});
