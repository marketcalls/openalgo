/**
 * Which bars a study computes on, when its chart applies a transform
 * (`Chart.setSeriesTransform`).
 *
 * `'chart'`, the default, is the bars the chart draws: a Renko chart's bricks,
 * a Heikin Ashi chart's candles. That is what a study computed on before the
 * chart could transform, when a host fed it the elements, so a study nobody
 * sets reads what it always read. `'underlying'` is the bars the host feeds.
 * On a chart with no transform the two are the same bars.
 *
 * A study on the underlying bars still draws on the chart's elements, or its
 * points would put the host's times on the shared axis and scatter the bricks
 * (data-layer.ts). So its values are read at the source bar each element was
 * completed on, which is the value a trader could have read when that element
 * formed, and a mark it dates at a source bar moves to the element that bar
 * completed into. Heikin Ashi keeps one candle per bar at the bar's own time,
 * so there the values need no reading across at all.
 */
import type { Bar } from './bar';
import type { IndicatorValues } from './indicator-registry';

/** The bars a study computes on: the chart's (default), or the host's under a transform. */
export type IndicatorBarSource = 'chart' | 'underlying';

/** A bar source from a caller or a saved layout, or a throw naming it. */
export function parseIndicatorBarSource(value: unknown): IndicatorBarSource {
  if (value !== 'chart' && value !== 'underlying') {
    throw new TypeError(`openalgo-charts: a study bar source is 'chart' or 'underlying', not ${String(value)}`);
  }
  return value;
}

/** Values computed on the underlying bars, read at the source bar each drawn element was completed on. */
export function sampleIndicatorValues(values: IndicatorValues, sourceIndex: readonly number[]): IndicatorValues {
  const out: Record<string, (number | null)[]> = {};
  for (const key of Object.keys(values)) {
    const column = values[key]!;
    out[key] = sourceIndex.map(i => column[i] ?? null);
  }
  return out;
}

/** The first index whose value is at least `target` in an ascending list, or its length. */
function lowerBound(length: number, at: (i: number) => number, target: number): number {
  let lo = 0, hi = length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (at(mid) < target) lo = mid + 1; else hi = mid;
  }
  return lo;
}

/**
 * The drawn time for a time a study dated on the bars it computed on. A time
 * the chart draws stands; any other moves to the element completed at or
 * after the source bar at that time, and to none, null, while that bar has
 * completed nothing yet.
 */
export function drawnTime(time: number, drawn: readonly Bar[], source: readonly Bar[], sourceIndex: readonly number[]): number | null {
  const at = lowerBound(drawn.length, i => drawn[i]!.time, time);
  if (drawn[at]?.time === time) return time;
  const bar = lowerBound(source.length, i => source[i]!.time, time);
  return drawn[lowerBound(sourceIndex.length, i => sourceIndex[i]!, bar)]?.time ?? null;
}
