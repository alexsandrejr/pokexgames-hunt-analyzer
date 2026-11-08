<script lang="ts">
  // Lista de sessões de uma categoria (como HuntListView): pesquisa, detalhes, comparação,
  // mudança de categoria, exclusão e exportação. As ações sobre a seleção só aparecem quando
  // podem ser usadas.
  import { ask } from "@tauri-apps/plugin-dialog";
  import ExportButton from "../../components/ExportButton.svelte";
  import MenuButton from "../../components/MenuButton.svelte";
  import RecordTable from "../../components/RecordTable.svelte";
  import Icon from "../../lib/Icon.svelte";
  import { filterPanel } from "../../lib/filters.svelte";
  import { sessions, type CategoryChoice } from "../../lib/sessions";
  import { announce } from "../../lib/status.svelte";
  import { viewColumns, type RowView, type TableView } from "../../lib/table";
  import ComparisonDialog from "./ComparisonDialog.svelte";
  import HuntDetails from "./HuntDetails.svelte";

  export interface ListTexts {
    singular: string;
    plural: string;
    emptyTitle: string;
    emptyMessage: string;
  }

  let {
    category,
    texts,
    categories,
    version,
    onchanged,
    select = $bindable([]),
  }: {
    /** Sem categoria, a lista mostra as sessões de todas. */
    category: string | null;
    texts: ListTexts;
    categories: CategoryChoice[];
    version: number;
    onchanged: () => void;
    /** Sessões a selecionar quando a lista carregar (as recém-importadas). */
    select?: number[];
  } = $props();

  let table = $state<TableView | null>(null);
  let totalAll = $state(0);
  let search = $state("");
  let selectedKeys = $state<number[]>([]);
  let visibleKeys = $state<number[]>([]);
  let visibleCount = $state(0);
  let error = $state("");
  let detailsId = $state<number | null>(null);
  let comparing = $state<number[] | null>(null);

  const columns = $derived(table ? viewColumns(table.columns) : []);
  const total = $derived(table?.rows.length ?? 0);
  const count = $derived(selectedKeys.length);
  const countText = $derived.by(() => {
    let text = visibleCount !== total ? `${visibleCount} de ${total} ${texts.plural}` : `${total} ${texts.plural}`;
    if (total !== totalAll) text += " (filtradas)";
    return text;
  });
  const moveItems = $derived(
    categories.filter((c) => c.value !== category).map((c) => ({ label: c.plural, action: () => move(c) })),
  );

  $effect(() => {
    void version;
    void filterPanel.version;
    load();
  });

  async function load() {
    try {
      const data = await sessions.list(category);
      table = data.table;
      totalAll = data.total_all;
      if (select.length) {
        const ids = new Set(data.table.rows.map((r) => r.id));
        selectedKeys = select.filter((id) => ids.has(id));
        const hidden = select.length - selectedKeys.length;
        if (hidden > 0) announce(`${hidden} sessão(ões) importada(s) não aparecem por causa dos filtros ativos.`);
        select = [];
      }
    } catch (e) {
      error = String(e);
    }
  }

  function openSelected() {
    if (selectedKeys.length === 1) detailsId = selectedKeys[0];
  }

  async function move(target: CategoryChoice) {
    if (!selectedKeys.length) return;
    try {
      announce(await sessions.move(selectedKeys, target.value));
      selectedKeys = [];
      onchanged();
    } catch (e) {
      error = String(e);
    }
  }

  async function remove() {
    const ids = [...selectedKeys];
    if (!ids.length) return;
    const noun = ids.length === 1 ? `a ${texts.singular} selecionada` : `as ${ids.length} ${texts.plural} selecionadas`;
    const confirmed = await ask(`Deseja excluir ${noun}?\n\nOs dados e o JSON original serão removidos do banco.`, {
      title: `Excluir ${texts.plural}`,
      kind: "warning",
      okLabel: "Sim",
      cancelLabel: "Não",
    });
    if (!confirmed) return;
    try {
      await sessions.delete(ids);
      selectedKeys = [];
      onchanged();
    } catch (e) {
      error = String(e);
    }
  }
</script>

<div class="toolbar">
  <input type="search" class="search" placeholder="Pesquisar por data, player, sessão…" bind:value={search} />
  {#if count === 0}
    <span class="muted" title="Dê duplo clique em uma linha para abrir os detalhes.&#10;Use Ctrl+clique para selecionar mais de uma."
      >{countText}</span
    >
  {/if}
  <div class="grow"></div>
  {#if count > 1}<span class="selection">{count} selecionada(s)</span>{/if}
  {#if count === 1}<button onclick={openSelected}><Icon name="open" /> Detalhes</button>{/if}
  {#if count >= 2}<button onclick={() => (comparing = [...selectedKeys])}><Icon name="compare" /> Comparar</button>{/if}
  {#if count > 0}
    <MenuButton
      label="Mover"
      icon="folder"
      items={moveItems}
      title="Mover as sessões selecionadas para outra categoria (Hunts ou um tipo de boss)"
      align="right"
    />
    <button class="danger" onclick={remove}><Icon name="trash" /> Excluir</button>
  {/if}
  <ExportButton
    disabled={visibleCount === 0}
    title="Exporta as {texts.plural} visíveis na tabela"
    request={() => ({ kind: "hunts", hunt_ids: [...visibleKeys], category })}
  />
</div>
{#if error}<p class="warning">{error}</p>{/if}

<div class="content">
  {#if table && total > 0}
    <RecordTable
      {columns}
      rows={table.rows}
      rowKey={(r: RowView) => r.id}
      multiple
      bind:selectedKeys
      bind:visibleKeys
      bind:visibleCount
      {search}
      sortAscending={false}
      onactivate={(r) => (detailsId = r.id)}
      ondelete={remove}
    />
  {:else if table && totalAll > 0}
    <div class="empty">
      <h2>Nenhuma {texts.singular} corresponde aos filtros</h2>
      <p class="muted">Ajuste ou limpe os filtros acima para ver mais {texts.plural}.</p>
    </div>
  {:else if table}
    <div class="empty">
      <h2>{texts.emptyTitle}</h2>
      <p class="muted">{texts.emptyMessage}</p>
    </div>
  {/if}
</div>

{#if detailsId !== null}
  <HuntDetails huntId={detailsId} onclose={() => (detailsId = null)} onchanged={load} />
{/if}

{#if comparing}
  <ComparisonDialog huntIds={comparing} onclose={() => (comparing = null)} />
{/if}

<style>
  .toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .search {
    flex: 1;
    min-width: 130px;
    max-width: 300px;
  }

  .grow {
    flex: 1;
  }

  .selection {
    color: var(--accent);
    font-weight: 600;
  }

  .content {
    flex: 1;
    min-height: 0;
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
    font-weight: 600;
  }

  .empty p {
    margin: 6px 0 0;
  }
</style>
