<script lang="ts" generics="T">
  // Tabela de registros (como RecordTable): ordenação pelo cabeçalho, pesquisa em todas as
  // colunas e seleção. Com `multiple`, Ctrl e Shift selecionam várias linhas, como no Qt.
  // Enter e o duplo clique ativam; Delete chama `ondelete`.
  import { untrack } from "svelte";
  import type { Column } from "../lib/table";

  let {
    columns,
    rows,
    rowKey,
    selected = $bindable(null),
    selectedKeys = $bindable([]),
    multiple = false,
    search = "",
    sortable = true,
    selectable = true,
    sortColumn = 0,
    sortAscending = true,
    visibleCount = $bindable(0),
    visibleKeys = $bindable([]),
    onactivate,
    ondelete,
  }: {
    columns: Column<T>[];
    rows: T[];
    rowKey: (row: T) => number;
    /** Seleção de uma linha (sem `multiple`): sempre fica numa linha visível. */
    selected?: number | null;
    /** Seleção com `multiple`: pode ficar vazia. */
    selectedKeys?: number[];
    multiple?: boolean;
    search?: string;
    /** Sem ordenação, as linhas ficam na ordem recebida. */
    sortable?: boolean;
    /** Sem seleção, a tabela só mostra os dados. */
    selectable?: boolean;
    sortColumn?: number;
    sortAscending?: boolean;
    visibleCount?: number;
    /** Chaves das linhas visíveis, na ordem exibida (para exportar o que se vê). */
    visibleKeys?: number[];
    onactivate?: (row: T) => void;
    ondelete?: (row: T) => void;
  } = $props();

  // svelte-ignore state_referenced_locally
  let sortIndex = $state(sortColumn);
  // svelte-ignore state_referenced_locally
  let ascending = $state(sortAscending);
  /** Linha de onde parte o Shift+clique e as setas, no modo de várias linhas. */
  let anchor = $state<number | null>(null);
  let body = $state<HTMLTableSectionElement>();

  function sortKey(column: Column<T>, row: T): string | number | null {
    return column.sort ? column.sort(row) : column.value(row).toLowerCase();
  }

  /** Vazios ficam depois dos demais na ordem crescente (e antes na decrescente), como no Qt. */
  function compare(a: string | number | null, b: string | number | null): number {
    if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1;
    return a < b ? -1 : a > b ? 1 : 0;
  }

  /** Colunas elásticas dividem o espaço por igual, como o modo Stretch do Qt. */
  const stretchWidth = $derived(`${100 / Math.max(1, columns.filter((c) => !c.fit).length)}%`);

  const visible = $derived.by(() => {
    const needle = search.trim().toLowerCase();
    const found = needle
      ? rows.filter((row) => columns.some((c) => c.value(row).toLowerCase().includes(needle)))
      : [...rows];
    if (!sortable) return found;
    const column = columns[sortIndex];
    const direction = ascending ? 1 : -1;
    // Ordem estável: empates mantêm a ordem recebida.
    return found
      .map((row, index) => ({ row, index, key: sortKey(column, row) }))
      .sort((a, b) => compare(a.key, b.key) * direction || a.index - b.index)
      .map((item) => item.row);
  });

  // Só depende das linhas visíveis: a seleção é lida com `untrack`, senão o efeito que a
  // corrige dispararia de novo a cada escrita.
  $effect(() => {
    const keys = visible.map(rowKey);
    untrack(() => {
      visibleCount = keys.length;
      visibleKeys = keys;
      if (multiple) {
        // Linhas que sumiram (pesquisa, filtro ou exclusão) saem da seleção.
        const shown = new Set(keys);
        const kept = selectedKeys.filter((k) => shown.has(k));
        if (kept.length !== selectedKeys.length) selectedKeys = kept;
      } else if (!keys.includes(selected as number)) {
        selected = keys[0] ?? null;
      }
    });
  });

  // Uma seleção vinda de fora (ex.: após salvar) que não está visível volta para a primeira.
  $effect(() => {
    if (multiple || selected === null) return;
    const keys = untrack(() => visible.map(rowKey));
    if (keys.length && !keys.includes(selected)) selected = keys[0];
  });

  function isSelected(row: T): boolean {
    if (!selectable) return false;
    return multiple ? selectedKeys.includes(rowKey(row)) : rowKey(row) === selected;
  }

  function choose(row: T, event?: MouseEvent | KeyboardEvent) {
    const key = rowKey(row);
    if (!multiple) {
      selected = key;
      return;
    }
    if (event?.shiftKey && anchor !== null) {
      const keys = visible.map(rowKey);
      const [from, to] = [keys.indexOf(anchor), keys.indexOf(key)].sort((a, b) => a - b);
      const range = from < 0 ? [key] : keys.slice(from, to + 1);
      selectedKeys = event.ctrlKey ? [...new Set([...selectedKeys, ...range])] : range;
      return;
    }
    if (event?.ctrlKey) {
      selectedKeys = selectedKeys.includes(key) ? selectedKeys.filter((k) => k !== key) : [...selectedKeys, key];
    } else {
      selectedKeys = [key];
    }
    anchor = key;
  }

  function sortBy(index: number) {
    if (!sortable) return;
    if (sortIndex === index) ascending = !ascending;
    else {
      sortIndex = index;
      ascending = true;
    }
  }

  function currentKey(): number | null {
    if (!multiple) return selected;
    return anchor !== null && selectedKeys.includes(anchor) ? anchor : (selectedKeys[0] ?? null);
  }

  function onkeydown(event: KeyboardEvent) {
    const position = visible.findIndex((row) => rowKey(row) === currentKey());
    const current = visible[position];
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      const next = visible[Math.min(Math.max(position + step, 0), visible.length - 1)];
      if (next !== undefined) {
        if (multiple && event.shiftKey) {
          const keep = anchor;
          choose(next, event);
          anchor = keep;
        } else choose(next);
        queueMicrotask(() => body?.querySelector(`tr[data-key="${rowKey(next)}"]`)?.scrollIntoView({ block: "nearest" }));
      }
    } else if (multiple && event.key === "a" && event.ctrlKey) {
      event.preventDefault();
      selectedKeys = visible.map(rowKey);
    } else if (event.key === "Enter" && current !== undefined) {
      onactivate?.(current);
    } else if (event.key === "Delete" && current !== undefined) {
      ondelete?.(current);
    }
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div class="wrap panel" tabindex="0" role="grid" {onkeydown}>
  <table class="records">
    <thead>
      <tr>
        {#each columns as column, index (column.title)}
          <th
            class:numeric={column.numeric}
            class:centered={column.centered}
            class:fit={column.fit}
            class:sortable
            style:width={column.fit ? undefined : stretchWidth}
            title={column.tooltip}
            onclick={() => sortBy(index)}
          >
            {column.title}
            {#if sortable && sortIndex === index}<span class="arrow">{ascending ? "▲" : "▼"}</span>{/if}
          </th>
        {/each}
      </tr>
    </thead>
    <tbody bind:this={body}>
      {#each visible as row (rowKey(row))}
        <tr
          data-key={rowKey(row)}
          class:selected={isSelected(row)}
          onmousedown={(e) => e.shiftKey && e.preventDefault()}
          onclick={(e) => choose(row, e)}
          ondblclick={() => onactivate?.(row)}
        >
          {#each columns as column (column.title)}
            <td
              class:numeric={column.numeric}
              class:centered={column.centered}
              class:fit={column.fit}
              class={column.color?.(row) ?? ""}
              title={column.cellTooltip?.(row)}>{column.value(row)}</td
            >
          {/each}
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .wrap {
    overflow: auto;
    outline: none;
  }

  .wrap:focus-visible {
    border-color: var(--accent);
  }

  thead th {
    position: sticky;
    top: 0;
    background: var(--surface);
  }

  th.sortable {
    cursor: pointer;
  }

  th.centered,
  td.centered {
    text-align: center;
  }

  .arrow {
    font-size: 9px;
    margin-left: 4px;
  }

  td {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 0;
  }

  td.fit {
    max-width: none;
  }

  td.positive {
    color: var(--positive);
  }

  td.negative {
    color: var(--negative);
  }

  td.warning {
    color: var(--warning);
  }

  td.accent {
    color: var(--accent);
  }

  tbody tr {
    cursor: default;
  }

  tbody tr:hover {
    background: var(--surface-hover);
  }

  tbody tr.selected {
    background: var(--selection);
  }
</style>
