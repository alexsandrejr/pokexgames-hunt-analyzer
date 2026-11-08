// Colunas da RecordTable (como `Column` em app/ui/widgets/record_table.py).

export interface Column<T> {
  title: string;
  /** Texto exibido; a pesquisa procura nele. */
  value: (row: T) => string;
  /** Chave de ordenação; sem ela, ordena pelo texto sem diferenciar maiúsculas. */
  sort?: (row: T) => string | number | null;
  numeric?: boolean;
  centered?: boolean;
  /** Largura pelo conteúdo, sem cortar (`fit_contents`). */
  fit?: boolean;
  tooltip?: string;
  /** Classe da célula: "positive", "negative" ou "warning". */
  color?: (row: T) => string | null | undefined;
  cellTooltip?: (row: T) => string | undefined;
}

/** Tabela montada no Rust (`TableView`): colunas e linhas já formatadas. */
export interface ColumnView {
  title: string;
  numeric: boolean;
  fit: boolean;
  centered: boolean;
  tooltip: string | null;
}

export interface RowView {
  id: number;
  cells: string[];
  sort: (string | number | null)[];
  colors: (string | null)[];
}

export interface TableView {
  columns: ColumnView[];
  rows: RowView[];
}

/** Colunas da RecordTable para uma tabela vinda do Rust. */
export function viewColumns(columns: ColumnView[]): Column<RowView>[] {
  return columns.map((c, i) => ({
    title: c.title,
    value: (r) => r.cells[i],
    sort: (r) => r.sort[i],
    numeric: c.numeric,
    centered: c.centered,
    fit: c.fit,
    tooltip: c.tooltip ?? undefined,
    color: (r) => r.colors[i],
  }));
}
