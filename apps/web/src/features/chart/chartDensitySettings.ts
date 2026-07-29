export const chartDensityChangedEvent = "torum-chart-density-changed";
export const chartDensityStorageKey = "torum.chartDensity";

export type ChartDensity = "WIDE" | "NORMAL" | "COMPACT" | "ULTRA";

export interface ChartDensityOptions {
  density: ChartDensity;
  barSpacing: number;
  minBarSpacing: number;
}

const options: Record<ChartDensity, ChartDensityOptions> = {
  WIDE: { density: "WIDE", barSpacing: 14, minBarSpacing: 2 },
  NORMAL: { density: "NORMAL", barSpacing: 9, minBarSpacing: 1 },
  COMPACT: { density: "COMPACT", barSpacing: 5, minBarSpacing: 0.75 },
  ULTRA: { density: "ULTRA", barSpacing: 2.5, minBarSpacing: 0.5 }
};

export function readChartDensity(): ChartDensityOptions {
  try {
    const value = window.localStorage.getItem(chartDensityStorageKey) as ChartDensity | null;
    return options[value ?? "NORMAL"] ?? options.NORMAL;
  } catch {
    return options.NORMAL;
  }
}

export function saveChartDensity(density: ChartDensity): ChartDensityOptions {
  try {
    window.localStorage.setItem(chartDensityStorageKey, density);
    window.dispatchEvent(new Event(chartDensityChangedEvent));
  } catch {
    // Visual preference only.
  }
  return options[density] ?? options.NORMAL;
}
