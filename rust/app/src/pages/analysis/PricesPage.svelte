<script lang="ts">
  // Página Preços (como prices_widget.py): preços personalizados dos itens, aplicados a todas
  // as Hunts.
  import { ask } from "@tauri-apps/plugin-dialog";
  import { untrack } from "svelte";
  import RecordTable from "../../components/RecordTable.svelte";
  import { analysis, type Prices } from "../../lib/analysis.svelte";
  import Icon from "../../lib/Icon.svelte";
  import { announce } from "../../lib/status.svelte";
  import { viewColumns, type RowView } from "../../lib/table";
  import PriceDialog from "./PriceDialog.svelte";

  let { version, onchanged }: { version: number; onchanged: () => void } = $props();

  let prices = $state<Prices | null>(null);
  let error = $state("");
  let search = $state("");
  let onlyCustom = $state(false);
  let selectedKeys = $state<number[]>([]);
  let visibleCount = $state(0);
  let editing = $state<{ name: string; price: string } | null>(null);

  const columns = $derived(prices ? viewColumns(prices.table.columns) : []);
  const rows = $derived(
    prices ? prices.table.rows.filter((r) => !onlyCustom || prices!.items[r.id].has_custom_price) : [],
  );
  const selected = $derived(prices ? selectedKeys.map((k) => prices!.items[k]).filter(Boolean) : []);
  const canClear = $derived(selected.some((item) => item.has_custom_price));
  const countText = $derived(
    prices ? `${visibleCount} de ${prices.items.length} itens · ${prices.custom_count} com preço personalizado` : "",
  );

  async function load(selectName?: string) {
    try {
      const keep = selectName ?? selected[0]?.name;
      prices = await analysis.prices();
      error = "";
      const key = keep?.toLowerCase();
      const index = key === undefined ? -1 : prices.items.findIndex((i) => i.name.toLowerCase() === key);
      selectedKeys = index >= 0 ? [index] : [];
    } catch (e) {
      error = String(e);
    }
  }

  // `load` lê a seleção e a troca: sem o `untrack`, o efeito rodaria de novo sem parar.
  $effect(() => {
    void version;
    untrack(() => load());
  });

  function edit() {
    const item = selected.length === 1 ? selected[0] : null;
    editing = { name: item?.name ?? "", price: item?.price_text ?? "" };
  }

  async function save(name: string, price: string): Promise<string | null> {
    try {
      const text = await analysis.setPrice(name, price);
      editing = null;
      await load(name.trim());
      announce(text);
      onchanged();
      return null;
    } catch (e) {
      return String(e);
    }
  }

  async function clear() {
    const items = selected.filter((item) => item.has_custom_price);
    if (!items.length) return;
    const names = items.map((item) => item.name);
    const confirmed = await ask(`Voltar ao preço do Analyzer em: ${names.join(", ")}?\n\nAs Hunts serão recalculadas.`, {
      title: "Remover preço",
      kind: "warning",
      okLabel: "Sim",
      cancelLabel: "Não",
    });
    if (!confirmed) return;
    try {
      const text = await analysis.clearPrices(names);
      await load(names[0]);
      announce(text);
      onchanged();
    } catch (e) {
      error = String(e);
    }
  }
</script>

<header class="page-header">
  <div>
    <h1>Preços</h1>
    <p class="muted">Preços personalizados dos itens</p>
  </div>
  <div class="actions">
    <button disabled={!canClear} title="Voltar ao preço do Analyzer nos itens selecionados" onclick={clear}>
      <Icon name="close" /> Remover preço
    </button>
    <button class="primary" title="Definir o preço do item selecionado ou de outro item" onclick={edit}>
      <Icon name="prices" /> Definir preço
    </button>
  </div>
</header>

<p class="muted explanation">
  O preço personalizado substitui o do Analyzer em todas as Hunts, inclusive nas próximas importações. Raw gains,
  Supplies, Profit e as taxas por hora são recalculados. Ao remover o preço, volta a valer o do Analyzer.
</p>

<div class="toolbar">
  <input type="search" class="search" placeholder="Pesquisar item…" bind:value={search} />
  <label class="check"><input type="checkbox" bind:checked={onlyCustom} /> Somente com preço personalizado</label>
  <div class="grow"></div>
  <span class="muted">{countText}</span>
</div>

{#if error}<p class="warning">{error}</p>{/if}

<div class="content">
  {#if prices && prices.items.length}
    <RecordTable
      {columns}
      {rows}
      rowKey={(r: RowView) => r.id}
      multiple
      bind:selectedKeys
      bind:visibleCount
      {search}
      onactivate={edit}
      ondelete={clear}
    />
  {:else if prices}
    <div class="empty">
      <h2>Nenhum item ainda</h2>
      <p class="muted">
        Importe Hunts para ver os itens aqui, ou use “Definir preço” para cadastrar o preço de um item antes de importá-lo.
      </p>
    </div>
  {/if}
</div>

{#if editing}
  <PriceDialog
    names={prices?.items.map((i) => i.name) ?? []}
    initialName={editing.name}
    initialPrice={editing.price}
    onclose={() => (editing = null)}
    onsave={save}
  />
{/if}

<style>
  .page-header {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    flex-wrap: wrap;
  }

  .page-header > div:first-child {
    flex: 1;
    min-width: 220px;
  }

  h1 {
    margin: 0;
    font-size: 21px;
    font-weight: 600;
  }

  header p {
    margin: 2px 0 0;
  }

  .actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .explanation {
    margin: 16px 0 0;
  }

  .toolbar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px 12px;
    margin-top: 16px;
  }

  .toolbar > label,
  .toolbar > span {
    white-space: nowrap;
  }

  .search {
    flex: 1;
    min-width: 220px;
    max-width: 360px;
  }

  .grow {
    flex: 1;
  }

  .content {
    flex: 1;
    min-height: 260px;
    display: flex;
    flex-direction: column;
    margin-top: 16px;
  }

  .content > :global(.wrap) {
    flex: 1;
  }

  .empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
  }

  .empty h2 {
    margin: 0;
    font-size: 17px;
  }
</style>
