<script lang="ts">
  // Relatório de um item (drop ou supply) ou inimigo sobre as Hunts filtradas (como
  // entity_report_page.py): cards, quantidade por Hunt e as Hunts em que apareceu.
  import ExportButton from "../../components/ExportButton.svelte";
  import FilterPanel from "../../components/FilterPanel.svelte";
  import RecordTable from "../../components/RecordTable.svelte";
  import SeriesChart from "../../components/SeriesChart.svelte";
  import StatCard from "../../components/StatCard.svelte";
  import { analysis, analysisState, type EntityReport } from "../../lib/analysis.svelte";
  import { filterPanel } from "../../lib/filters.svelte";
  import type { EntityKind } from "../../lib/sessions";
  import { viewColumns, type RowView } from "../../lib/table";
  import HuntDetails from "../sessions/HuntDetails.svelte";
  import ScopeSelect from "./ScopeSelect.svelte";

  let { page, version, onchanged }: { page: "items" | "enemies"; version: number; onchanged: () => void } = $props();

  const ROW_HEIGHT = 34;

  const texts = $derived(
    page === "items"
      ? { title: "Itens", subtitle: "Drops e supplies ao longo das Hunts filtradas", noun: "item" }
      : { title: "Inimigos", subtitle: "Pokémon derrotados ao longo das Hunts filtradas", noun: "inimigo" },
  );
  const kinds: { value: EntityKind; label: string }[] = [
    { value: "drops", label: "Drops" },
    { value: "supplies", label: "Supplies" },
  ];
  const memory = $derived(analysisState[page]);

  let names = $state<string[]>([]);
  let report = $state<EntityReport | null>(null);
  let error = $state("");
  let detailsId = $state<number | null>(null);

  // Sugestões do tipo escolhido; recarregam com as importações.
  $effect(() => {
    void version;
    analysis
      .entityNames(memory.kind)
      .then((value) => (names = value))
      .catch((e) => (error = String(e)));
  });

  // Refaz a última análise quando mudam os dados, os filtros ou o escopo.
  $effect(() => {
    void version;
    void filterPanel.version;
    const analyzed = memory.analyzed;
    const scope = memory.scope;
    if (!analyzed) {
      report = null;
      return;
    }
    analysis
      .entityReport(analyzed.kind, analyzed.name, scope)
      .then((value) => {
        report = value;
        error = "";
      })
      .catch((e) => (error = String(e)));
  });

  function analyze() {
    const name = memory.name.trim();
    if (!name) return;
    memory.name = name;
    memory.analyzed = { kind: memory.kind, name };
  }

  function oninput(event: Event) {
    // Escolher uma sugestão da lista já analisa, como o `activated` do combo.
    if ((event as InputEvent).inputType === "insertReplacementText" || !(event instanceof InputEvent)) analyze();
  }

  const tableHeight = $derived(
    report?.table ? `${44 + ROW_HEIGHT * Math.min(12, Math.max(3, report.table.rows.length))}px` : "0",
  );
</script>

<header class="page-header">
  <div>
    <h1>{texts.title}</h1>
    <p class="muted">{texts.subtitle}</p>
  </div>
  <div class="actions">
    <ScopeSelect bind:value={memory.scope} />
    <ExportButton
      disabled={!report || report.empty !== null}
      request={() =>
        memory.analyzed
          ? { kind: "entity", entity: memory.analyzed.kind, name: memory.analyzed.name, scope: memory.scope }
          : null}
    />
  </div>
</header>

<div class="filters"><FilterPanel /></div>

<div class="selector">
  {#if page === "items"}
    <select bind:value={memory.kind}>
      {#each kinds as kind (kind.value)}<option value={kind.value}>{kind.label}</option>{/each}
    </select>
  {/if}
  <input
    class="name"
    list="entity-names-{page}"
    placeholder="Escolha ou digite o {texts.noun}…"
    bind:value={memory.name}
    {oninput}
    onkeydown={(e) => e.key === "Enter" && analyze()}
  />
  <datalist id="entity-names-{page}">{#each names as name (name)}<option value={name}></option>{/each}</datalist>
  <button class="primary" onclick={analyze}>Analisar</button>
</div>

{#if error}<p class="warning">{error}</p>{/if}

{#if !report || report.empty}
  <div class="empty">
    <h2>{report?.empty?.[0] ?? "Nenhum item selecionado"}</h2>
    <p class="muted">
      {report?.empty?.[1] ??
        `Escolha um ${texts.noun} acima para ver quantidade total, médias, presença nas Hunts e o histórico.`}
    </p>
  </div>
{:else}
  <div class="body">
    <div class="cards">
      {#each report.cards as card (card.title)}
        <StatCard title={card.title} value={card.value} hint={card.hint} />
      {/each}
    </div>
    {#if report.chart}
      <SeriesChart chart={report.chart} onactivate={(id) => (detailsId = id)} />
    {/if}
    {#if report.table}
      <section>
        <h3 class="section-title">{report.table_title}</h3>
        <div class="table" style:height={tableHeight}>
          <RecordTable
            columns={viewColumns(report.table.columns)}
            rows={report.table.rows}
            rowKey={(r: RowView) => r.id}
            sortAscending={false}
            onactivate={(r) => (detailsId = r.id)}
          />
        </div>
      </section>
    {/if}
  </div>
{/if}

{#if detailsId !== null}
  <HuntDetails huntId={detailsId} onclose={() => (detailsId = null)} {onchanged} />
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

  .filters {
    margin-top: 16px;
  }

  .selector {
    display: flex;
    gap: 8px;
    margin-top: 14px;
  }

  .name {
    flex: 1;
    min-width: 280px;
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 14px 0 8px;
  }

  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 14px;
  }

  section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .table {
    display: flex;
    flex-shrink: 0;
  }

  .table > :global(.wrap) {
    flex: 1;
  }

  .empty {
    flex: 1;
    min-height: 220px;
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

  .empty p {
    max-width: 520px;
  }
</style>
