<script lang="ts">
  // Resumo de um tipo de boss (como BossSummaryView): cards, tabelas e a evolução por sessão,
  // sobre as sessões filtradas.
  import RecordTable from "../../components/RecordTable.svelte";
  import SeriesChart from "../../components/SeriesChart.svelte";
  import StatCard from "../../components/StatCard.svelte";
  import { filterPanel } from "../../lib/filters.svelte";
  import { sessions, type BossSummary } from "../../lib/sessions";
  import { viewColumns, type RowView, type TableView } from "../../lib/table";

  let { category, version, onopen }: { category: string; version: number; onopen: (huntId: number) => void } =
    $props();

  let summary = $state<BossSummary | null>(null);
  let error = $state("");

  const RANKING_LIMIT = 25;

  $effect(() => {
    void version;
    void filterPanel.version;
    sessions
      .bossSummary(category)
      .then((value) => (summary = value))
      .catch((e) => (error = String(e)));
  });

  /** Altura da tabela: entre 3 e 8 linhas, como `_fit_rows`. */
  function tableHeight(table: TableView): string {
    return `${40 + 34 * Math.min(8, Math.max(3, table.rows.length)) + 4}px`;
  }
</script>

{#if error}<p class="warning">{error}</p>{/if}
{#if summary}
  <div class="summary">
    {#if summary.has_sessions}
      <div class="cards">
        {#each summary.cards as card (card.title)}
          <StatCard title={card.title} value={card.value} hint={card.hint} />
        {/each}
      </div>
    {/if}
    {#if summary.hint}<p class="muted">{summary.hint}</p>{/if}
    {#if summary.has_sessions}
      <div class="tables">
        {#each [["Bosses derrotados", summary.enemies, 1], [`Drops mais valiosos (top ${RANKING_LIMIT})`, summary.drops, 2], ["Dano por elemento", summary.elements, 1]] as [title, table, sort] (title)}
          {@const view = table as TableView}
          <section>
            <h3 class="section-title">{title}</h3>
            <div class="table" style:height={tableHeight(view)}>
              <RecordTable
                columns={viewColumns(view.columns)}
                rows={view.rows}
                rowKey={(r: RowView) => r.id}
                multiple
                sortColumn={sort as number}
                sortAscending={false}
              />
            </div>
          </section>
        {/each}
      </div>
    {/if}
    {#if summary.charts.length}
      <section>
        <h3 class="section-title">Evolução por sessão</h3>
        <div class="charts">
          {#each summary.charts as chart (chart.title)}
            <SeriesChart {chart} onactivate={onopen} />
          {/each}
        </div>
      </section>
    {/if}
  </div>
{/if}

<style>
  .summary {
    display: flex;
    flex-direction: column;
    gap: 18px;
    padding: 16px 0;
  }

  .summary p {
    margin: 0;
  }

  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 14px;
  }

  .tables {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
    gap: 14px;
    align-items: start;
  }

  section {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }

  .table {
    display: flex;
  }

  .table > :global(.wrap) {
    flex: 1;
  }

  .charts {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(440px, 1fr));
    gap: 14px;
  }
</style>
