<script lang="ts">
  // Página Relatórios (como reports_widget.py): estatísticas agregadas das Hunts filtradas.
  import ExportButton from "../../components/ExportButton.svelte";
  import FilterPanel from "../../components/FilterPanel.svelte";
  import RecordTable from "../../components/RecordTable.svelte";
  import StatCard from "../../components/StatCard.svelte";
  import { analysis, analysisState, type Report } from "../../lib/analysis.svelte";
  import { filterPanel } from "../../lib/filters.svelte";
  import { viewColumns, type RowView, type TableView } from "../../lib/table";
  import ScopeSelect from "./ScopeSelect.svelte";

  let { version }: { version: number } = $props();

  const RANKING_LIMIT = 25;
  const ROW_HEIGHT = 34;
  const HEADER_HEIGHT = 40;

  let report = $state<Report | null>(null);
  let error = $state("");
  let tab = $state<"drops" | "supplies" | "enemies">("drops");

  $effect(() => {
    void version;
    void filterPanel.version;
    analysis
      .report(analysisState.reportsScope)
      .then((value) => {
        report = value;
        error = "";
      })
      .catch((e) => (error = String(e)));
  });

  function height(rows: number): string {
    return `${HEADER_HEIGHT + ROW_HEIGHT * rows + 4}px`;
  }

  const ranking = $derived.by((): [TableView, number] | null => {
    if (!report) return null;
    if (tab === "drops") return [report.drops, 2];
    if (tab === "supplies") return [report.supplies, 2];
    return [report.enemies, 1];
  });
</script>

<header class="page-header">
  <div>
    <h1>Relatórios</h1>
    <p class="muted">{report?.subtitle ?? "Estatísticas agregadas das Hunts filtradas"}</p>
  </div>
  <div class="actions">
    <ScopeSelect bind:value={analysisState.reportsScope} />
    <ExportButton request={() => ({ kind: "report", scope: analysisState.reportsScope })} />
  </div>
</header>

<div class="filters"><FilterPanel /></div>

{#if error}<p class="warning">{error}</p>{/if}
{#if report}
  <div class="body">
    <div class="cards">
      {#each report.cards as card (card.title)}
        <StatCard title={card.title} value={card.value} hint={card.hint} />
      {/each}
    </div>

    <section>
      <h3 class="section-title">Métricas</h3>
      <!-- +10 px: a barra horizontal da janela mínima não esconde a última linha. -->
      <div class="table" style:height="calc({height(8)} + 10px)">
        <RecordTable
          columns={viewColumns(report.metrics.columns)}
          rows={report.metrics.rows}
          rowKey={(r: RowView) => r.id}
          sortable={false}
          multiple
        />
      </div>
      <p class="hint">
        “Média das taxas” é a média simples dos valores por hora (ou por segundo) de cada Hunt: todas pesam igual.
        “Total ÷ tempo total” divide a soma pelo tempo somado, então Hunts mais longas pesam mais.
      </p>
    </section>

    <section>
      <h3 class="section-title">Mais frequentes (top {RANKING_LIMIT})</h3>
      <div class="panel ranking">
        <div class="tabs" role="tablist">
          <button role="tab" class:active={tab === "drops"} onclick={() => (tab = "drops")}>Drops</button>
          <button role="tab" class:active={tab === "supplies"} onclick={() => (tab = "supplies")}>Supplies</button>
          <button role="tab" class:active={tab === "enemies"} onclick={() => (tab = "enemies")}>Inimigos</button>
        </div>
        {#if ranking}
          {@const [table, sort] = ranking}
          {#key tab}
            <div class="table" style:height={height(10)}>
              <RecordTable
                columns={viewColumns(table.columns)}
                rows={table.rows}
                rowKey={(r: RowView) => r.id}
                sortColumn={sort}
                sortAscending={false}
                multiple
              />
            </div>
          {/key}
        {/if}
      </div>
    </section>
  </div>
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

  .body {
    display: flex;
    flex-direction: column;
    gap: 20px;
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
    min-width: 0;
  }

  .hint {
    margin: 0;
  }

  .table {
    display: flex;
    flex-shrink: 0;
  }

  .table > :global(.wrap) {
    flex: 1;
  }

  .ranking {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 4px 12px 12px;
  }

  .tabs {
    display: flex;
    gap: 4px;
  }

  .tabs button {
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    background: transparent;
    padding: 8px 16px;
    color: var(--muted);
  }

  .tabs button.active {
    color: var(--text);
    border-bottom-color: var(--accent);
  }
</style>
