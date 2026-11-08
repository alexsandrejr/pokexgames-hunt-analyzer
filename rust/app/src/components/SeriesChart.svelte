<script lang="ts">
  // Uma métrica por sessão, em ordem cronológica (como HuntSeriesChart): colunas finas com a
  // ponta arredondada, ou linha acima de 60 sessões; média em linha discreta, dica ao passar o
  // mouse e clique para abrir a sessão.
  import { BAR_FILL_RATIO, MAX_BAR_PX, barPath, type SeriesChartData } from "../lib/charts";

  let { chart, onactivate }: { chart: SeriesChartData; onactivate?: (key: number) => void } = $props();

  const HEIGHT = 230;
  const AXIS_WIDTH = 64;
  const BOTTOM = 22;
  const TOP = 6;

  let width = $state(400);
  let hover = $state(-1);
  let tip = $state({ x: 0, y: 0 });

  const plotWidth = $derived(Math.max(10, width - AXIS_WIDTH - 4));
  const plotHeight = HEIGHT - BOTTOM - TOP;
  const count = $derived(chart.points.length);
  const slot = $derived(plotWidth / Math.max(1, count + 0.2));
  const thickness = $derived(Math.max(1.5, Math.min(MAX_BAR_PX, slot * BAR_FILL_RATIO)));
  const hasData = $derived(chart.y_ticks.length > 0);

  /** Centro da sessão `i` no eixo X (com meia faixa de folga nas pontas, como o Python). */
  function x(i: number): number {
    return AXIS_WIDTH + slot * (i + 0.6);
  }

  function y(value: number): number {
    return TOP + plotHeight * (1 - (value - chart.low) / (chart.high - chart.low || 1));
  }

  const linePath = $derived(
    chart.points
      .map((p, i) => (p.value === null ? null : `${x(i)},${y(p.value)}`))
      .reduce<string[]>((parts, point, i, all) => {
        if (point === null) return parts;
        parts.push(`${i === 0 || all[i - 1] === null ? "M" : "L"}${point}`);
        return parts;
      }, [])
      .join(" "),
  );

  function onmove(event: MouseEvent) {
    const box = (event.currentTarget as SVGElement).getBoundingClientRect();
    const px = event.clientX - box.left;
    const index = Math.round((px - AXIS_WIDTH) / slot - 0.6);
    hover = px >= AXIS_WIDTH && index >= 0 && index < count ? index : -1;
    tip = { x: event.clientX - box.left, y: event.clientY - box.top };
  }

  function onclick() {
    const key = chart.points[hover]?.key;
    if (hover >= 0 && key !== null && key !== undefined) onactivate?.(key);
  }
</script>

<div class="card chart">
  <div class="title">{chart.title}</div>
  <div class="hint">{chart.subtitle}</div>
  <div class="plot" bind:clientWidth={width}>
    {#if hasData}
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <svg
        {width}
        height={HEIGHT}
        class:pointer={hover >= 0}
        onmousemove={onmove}
        onmouseleave={() => (hover = -1)}
        {onclick}
      >
        {#each chart.y_ticks as tick (tick.value)}
          <line class="grid" x1={AXIS_WIDTH} x2={width} y1={y(tick.value)} y2={y(tick.value)} />
          <text class="axis" x={AXIS_WIDTH - 6} y={y(tick.value)} text-anchor="end" dominant-baseline="middle"
            >{tick.label}</text
          >
        {/each}
        <line class="baseline" x1={AXIS_WIDTH} x2={width} y1={y(Math.max(0, chart.low))} y2={y(Math.max(0, chart.low))} />
        {#if chart.line}
          <path class="series-line" d={linePath} />
          {#if hover >= 0 && chart.points[hover].value !== null}
            <line class="reference" x1={x(hover)} x2={x(hover)} y1={TOP} y2={TOP + plotHeight} />
            <circle class="dot" cx={x(hover)} cy={y(chart.points[hover].value!)} r="5" />
          {/if}
        {:else}
          {#each chart.points as point, i (i)}
            {#if point.value}
              {@const base = y(0)}
              {@const top = y(point.value)}
              <path
                class="bar"
                class:hover={i === hover}
                d={barPath(x(i) - thickness / 2, Math.min(base, top), thickness, Math.abs(base - top), point.value > 0 ? "top" : "bottom")}
              />
            {/if}
          {/each}
        {/if}
        {#if chart.average !== null}
          <line class="reference" x1={AXIS_WIDTH} x2={width} y1={y(chart.average)} y2={y(chart.average)} />
        {/if}
        {#each chart.x_labels as [index, label] (index)}
          <text class="axis" x={x(index)} y={HEIGHT - 6} text-anchor="middle">{label}</text>
        {/each}
      </svg>
      {#if hover >= 0}
        <div class="tooltip" style:left="{tip.x + 14}px" style:top="{tip.y + 14}px">
          <strong>{chart.points[hover].value_text}</strong>
          <span>{chart.points[hover].title}</span>
        </div>
      {/if}
    {/if}
  </div>
</div>

<style>
  .chart {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 14px 16px 12px;
    min-width: 0;
  }

  .title {
    font-weight: 600;
  }

  /* Mantém os dois espaços em volta do "·", como no Python. */
  .hint {
    white-space: pre-wrap;
  }

  .plot {
    position: relative;
    margin-top: 6px;
    min-height: 230px;
  }

  svg {
    display: block;
  }

  svg.pointer {
    cursor: pointer;
  }

  .grid {
    stroke: var(--chart-grid);
    stroke-width: 1;
  }

  .baseline {
    stroke: var(--chart-baseline);
    stroke-width: 1;
  }

  .reference {
    stroke: var(--chart-reference);
    stroke-width: 1;
  }

  .axis {
    fill: var(--muted);
    font-size: 11px;
  }

  .bar {
    fill: var(--chart-series);
  }

  .bar.hover {
    fill: var(--chart-series-hover);
  }

  .series-line {
    fill: none;
    stroke: var(--chart-series);
    stroke-width: 2;
  }

  .dot {
    fill: var(--chart-series);
    stroke: var(--surface);
    stroke-width: 2;
  }

  .tooltip {
    position: absolute;
    z-index: 10;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 6px 10px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
    pointer-events: none;
    white-space: nowrap;
  }

  .tooltip strong {
    font-size: 15px;
  }

  .tooltip span {
    color: var(--muted);
  }
</style>
