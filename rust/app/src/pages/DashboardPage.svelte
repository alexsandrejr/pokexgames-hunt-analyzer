<script lang="ts">
  // Página Início (como dashboard_widget.py): cards e gráficos das sessões filtradas. O seletor
  // começa em "Hunts e bosses"; o resumo por categoria não depende dele.
  import FilterPanel from "../components/FilterPanel.svelte";
  import SeriesChart from "../components/SeriesChart.svelte";
  import StatCard from "../components/StatCard.svelte";
  import { analysis, analysisState, type Dashboard } from "../lib/analysis.svelte";
  import { filterPanel } from "../lib/filters.svelte";
  import ScopeSelect from "./analysis/ScopeSelect.svelte";
  import HuntDetails from "./sessions/HuntDetails.svelte";

  let { version, onchanged }: { version: number; onchanged: () => void } = $props();

  let view = $state<Dashboard | null>(null);
  let error = $state("");
  let detailsId = $state<number | null>(null);

  if (analysisState.dashboardScope < 0) {
    analysis.dashboardDefaultScope().then((index) => (analysisState.dashboardScope = index));
  }

  $effect(() => {
    void version;
    void filterPanel.version;
    const scope = analysisState.dashboardScope;
    if (scope < 0) return;
    analysis
      .dashboard(scope)
      .then((value) => {
        view = value;
        error = "";
      })
      .catch((e) => (error = String(e)));
  });
</script>

<header class="page-header">
  <div>
    <h1>Início</h1>
    <p class="muted">{view?.subtitle ?? "Visão geral das sessões importadas"}</p>
  </div>
  {#if analysisState.dashboardScope >= 0}
    <ScopeSelect bind:value={analysisState.dashboardScope} />
  {/if}
</header>

<div class="filters"><FilterPanel /></div>

{#if error}<p class="warning">{error}</p>{/if}
{#if view}
  <div class="body">
    {#if view.main_cards.length}
      <div class="cards">
        {#each view.main_cards as card (card.title)}
          <StatCard title={card.title} value={card.value} hint={card.hint} />
        {/each}
      </div>
      <div class="cards">
        {#each view.small_cards as card (card.title)}
          <StatCard title={card.title} value={card.value} hint={card.hint} compact />
        {/each}
      </div>
    {/if}
    {#if view.hint}<p class="muted">{view.hint}</p>{/if}

    {#if view.categories.length}
      <section>
        <h3 class="section-title">Resumo por categoria</h3>
        <p class="hint">Independente do seletor acima. O resumo completo de cada boss fica em Sessões.</p>
        <div class="categories">
          {#each view.categories as card (card.title)}
            <StatCard title={card.title} value={card.value} hint={card.hint} compact />
          {/each}
        </div>
      </section>
    {/if}

    {#if view.charts.length}
      <section>
        <h3 class="section-title">{view.charts_title}</h3>
        <p class="hint">{view.charts_hint}</p>
        <div class="charts">
          {#each view.charts as chart (chart.title)}
            <SeriesChart {chart} onactivate={(id) => (detailsId = id)} />
          {/each}
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

  .filters {
    margin-top: 16px;
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: 18px;
    padding: 18px 0 8px;
  }

  .body p {
    margin: 0;
  }

  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 14px;
  }

  section {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding-top: 8px;
  }

  /* Até 5 por linha, como o ResponsiveGrid do Python. */
  .categories {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(max(200px, calc((100% - 4 * 14px) / 5)), 1fr));
    gap: 14px;
  }

  /* Até 2 por linha. */
  .charts {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(max(440px, calc((100% - 14px) / 2)), 1fr));
    gap: 14px;
  }
</style>
