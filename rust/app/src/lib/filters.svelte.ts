// Estado do painel de filtros, o mesmo em todas as páginas que o mostram (como a instância
// única do FilterPanel no Python). O filtro aplicado fica no Rust; aqui ficam os campos.

import type { FilterForm } from "./sessions";

export const filterPanel = $state({
  expanded: false,
  /** Resumo dos filtros ativos, um item por critério. */
  parts: [] as string[],
  /** Sobe a cada filtro aplicado ou limpo: as páginas recarregam. */
  version: 0,
  form: emptyForm(),
});

export function emptyForm(): FilterForm {
  return {
    preset: "all",
    date_from: today(),
    date_to: today(),
    player: "",
    enemy: "",
    enemy_operator: ">=",
    enemy_quantity: "",
    item_source: "drops",
    item: "",
    item_operator: ">=",
    item_quantity: "",
    metrics: [
      ["profit", { operator: ">=", value: "" }],
      ["profit_per_hour", { operator: ">=", value: "" }],
      ["kills", { operator: ">=", value: "" }],
      ["kills_per_hour", { operator: ">=", value: "" }],
      ["duration", { operator: ">=", value: "" }],
    ],
    advanced: "",
  };
}

function today(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
