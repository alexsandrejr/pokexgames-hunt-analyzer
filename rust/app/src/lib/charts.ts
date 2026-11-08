// Tipos dos gráficos montados no Rust (src-tauri/src/charts.rs) e o desenho das barras.

export interface Tick {
  value: number;
  label: string;
}

export interface ChartPoint {
  key: number | null;
  label: string;
  value: number | null;
  value_text: string;
  title: string;
}

export interface SeriesChartData {
  title: string;
  subtitle: string;
  points: ChartPoint[];
  line: boolean;
  low: number;
  high: number;
  average: number | null;
  y_ticks: Tick[];
  x_labels: [number, string][];
}

export interface RankedChartData {
  title: string;
  points: ChartPoint[];
  high: number;
  x_ticks: Tick[];
}

export const MAX_BAR_PX = 24;
/** Parte da faixa ocupada pela barra; o resto é o espaço entre elas. */
export const BAR_FILL_RATIO = 0.72;
export const END_RADIUS_PX = 4;

/** Barra com só a ponta de dados arredondada (base reta), como `_rounded_end`. */
export function barPath(x: number, y: number, width: number, height: number, tip: "top" | "bottom" | "right" | "left"): string {
  const r = Math.max(0, Math.min(END_RADIUS_PX, tip === "top" || tip === "bottom" ? height : width, (tip === "top" || tip === "bottom" ? width : height) / 2));
  const [x2, y2] = [x + width, y + height];
  switch (tip) {
    case "top":
      return `M${x},${y2} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x2 - r},${y} Q${x2},${y} ${x2},${y + r} L${x2},${y2} Z`;
    case "bottom":
      return `M${x},${y} L${x2},${y} L${x2},${y2 - r} Q${x2},${y2} ${x2 - r},${y2} L${x + r},${y2} Q${x},${y2} ${x},${y2 - r} Z`;
    case "right":
      return `M${x},${y} L${x2 - r},${y} Q${x2},${y} ${x2},${y + r} L${x2},${y2 - r} Q${x2},${y2} ${x2 - r},${y2} L${x},${y2} Z`;
    case "left":
      return `M${x2},${y} L${x2},${y2} L${x + r},${y2} Q${x},${y2} ${x},${y2 - r} L${x},${y + r} Q${x},${y} ${x + r},${y} Z`;
  }
}
