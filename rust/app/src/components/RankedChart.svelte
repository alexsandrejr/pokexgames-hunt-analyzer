<script lang="ts">
  // Barras horizontais ordenadas, com o valor na ponta (como RankedBarChart).
  import { BAR_FILL_RATIO, MAX_BAR_PX, barPath, type RankedChartData } from "../lib/charts";

  let { chart }: { chart: RankedChartData } = $props();

  const ROW_HEIGHT = 28;
  const LABEL_WIDTH = 150;
  const BOTTOM = 22;

  let width = $state(400);
  let hover = $state(-1);
  let tip = $state({ x: 0, y: 0 });

  const height = $derived(Math.max(90, chart.points.length * ROW_HEIGHT + 36));
  const plotHeight = $derived(height - BOTTOM);
  const plotWidth = $derived(Math.max(10, width - LABEL_WIDTH - 8));
  const slot = $derived(plotHeight / Math.max(1, chart.points.length + 0.2));
  const thickness = $derived(Math.max(1.5, Math.min(MAX_BAR_PX, slot * BAR_FILL_RATIO)));

  function x(value: number): number {
    return LABEL_WIDTH + (plotWidth * value) / (chart.high || 1);
  }

  function y(i: number): number {
    return slot * (i + 0.6);
  }

  function onmove(event: MouseEvent) {
    const box = (event.currentTarget as SVGElement).getBoundingClientRect();
    const index = Math.round((event.clientY - box.top) / slot - 0.6);
    hover = index >= 0 && index < chart.points.length && event.clientY - box.top < plotHeight ? index : -1;
    tip = { x: event.clientX - box.left, y: event.clientY - box.top };
  }
</script>

<div class="card chart">
  <div class="title">{chart.title}</div>
  <div class="plot" bind:clientWidth={width}>
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <svg {width} {height} onmousemove={onmove} onmouseleave={() => (hover = -1)}>
      {#each chart.x_ticks as tick (tick.value)}
        <line class="grid" x1={x(tick.value)} x2={x(tick.value)} y1="0" y2={plotHeight} />
        <text class="axis" x={x(tick.value)} y={height - 6} text-anchor="middle">{tick.label}</text>
      {/each}
      <line class="baseline" x1={LABEL_WIDTH} x2={LABEL_WIDTH} y1="0" y2={plotHeight} />
      {#each chart.points as point, i (i)}
        <text class="axis" x={LABEL_WIDTH - 8} y={y(i)} text-anchor="end" dominant-baseline="middle">{point.label}</text>
        {#if point.value}
          <path
            class="bar"
            class:hover={i === hover}
            d={barPath(LABEL_WIDTH, y(i) - thickness / 2, x(point.value) - LABEL_WIDTH, thickness, "right")}
          />
        {/if}
        <text class="axis" x={x(point.value ?? 0) + 4} y={y(i)} dominant-baseline="middle">{point.value_text}</text>
      {/each}
    </svg>
    {#if hover >= 0}
      <div class="tooltip" style:left="{tip.x + 14}px" style:top="{tip.y + 14}px">
        <strong>{chart.points[hover].value_text}</strong>
        <span>{chart.points[hover].title}</span>
      </div>
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

  .plot {
    position: relative;
    margin-top: 8px;
  }

  svg {
    display: block;
  }

  .grid {
    stroke: var(--chart-grid);
    stroke-width: 1;
  }

  .baseline {
    stroke: var(--chart-baseline);
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
