/**
 * The value-level helpers of the chart-wide history (history.ts): equality
 * over the plain data a capture holds, and the study-source references inside
 * a study's settings. Pure and stateless, so they live apart from the class
 * that records and walks the steps.
 */
import type { Chart, IndicatorSettings, SeriesApi, SeriesType } from 'openalgo-charts';
import { isRecord } from '../helpers/validate';

/** Structural equality for the plain data a capture holds. */
export function same(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a === 'number' && typeof b === 'number') return Math.abs(a - b) < 1e-9;
  if (Array.isArray(a) || Array.isArray(b)) {
    return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((v, i) => same(v, b[i]));
  }
  if (!isRecord(a) || !isRecord(b)) return false;
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const key of keys) if (!same(a[key], b[key])) return false;
  return true;
}

export const isSource = (v: unknown): v is { kind: 'indicator'; instanceId: string; plotKey: string } =>
  isRecord(v) && v.kind === 'indicator' && typeof v.instanceId === 'string';

/** Settings with every study-source reference renamed, as a detached copy. */
export function renameSources(settings: Readonly<IndicatorSettings>, rename: (id: string) => string): IndicatorSettings {
  const out: IndicatorSettings = {};
  for (const [key, value] of Object.entries(settings)) {
    out[key] = isSource(value) ? { ...value, instanceId: rename(value.instanceId) }
      : Array.isArray(value) ? value.map(item => (isRecord(item) ? { ...item } : item)) as never
      : isRecord(value) ? { ...value } as never : value;
  }
  return out;
}

/**
 * A series' chart type as a step records it: the renderer, and after a `+` the
 * transform the chart applies, so point and figure drawn from a host's own
 * columns and point and figure the chart forms are two types, and a series
 * with no transform records exactly what it always did.
 */
export function chartTypeOf(chart: Chart, series: SeriesApi): string | null {
  const type = chart.seriesType(series), transform = chart.seriesTransform(series);
  return type === null || transform === null ? type : `${type}+${transform.type}`;
}

/** Put a recorded chart type back, through the host's own setter when it gave one. */
export function setChartTypeOf(chart: Chart, series: SeriesApi, recorded: string, set?: (type: string) => unknown): void {
  const [type, transform] = recorded.split('+') as [SeriesType, string | undefined];
  if (set !== undefined) { set(transform ?? type); return; }
  chart.setSeriesTransform(series, transform === undefined ? null : { type: transform });
  chart.setSeriesType(series, type);
}
