/**
 * The chart's side of a series transform (`Chart.setSeriesTransform`):
 * turning one on or off, and forming a series' elements again on each tick.
 *
 * `registerSeriesTransform` installs it, and before anything is registered no
 * series can hold a transform, so a chart-only import, which registers
 * nothing, carries none of this. chart-series.ts keeps the map of runs, the
 * routing through it and the refusal of a spec when nothing is registered.
 */
import {
  addSeriesTransform, getSeriesTransform, type SeriesTransformDefinition, type SeriesTransformRun, type SeriesTransformSpec,
} from '../model/series-transform';
import type { SeriesApi, SeriesUpdateOptions } from '../model/series';
import type { Bar } from '../model/bar';
import type { Pane } from './pane';
import { installTransformRuns, type ChartSeries } from './chart-series';

/** The same element, whatever colour a study painted onto the copy the data layer holds. */
function sameElement(a: Bar, b: Bar): boolean {
  return a === b || (a.time === b.time && a.open === b.open && a.high === b.high && a.low === b.low
    && a.close === b.close && a.volume === b.volume && a.oi === b.oi);
}

function sameSpec(a: SeriesTransformSpec, b: SeriesTransformSpec): boolean {
  const x = a.options ?? {}, y = b.options ?? {};
  return a.type === b.type && Object.keys(x).length === Object.keys(y).length && Object.keys(x).every(key => x[key] === y[key]);
}

function setTransform(series: ChartSeries, api: SeriesApi, spec: SeriesTransformSpec | null, notify: boolean): boolean {
  const host = series._host;
  const record = host._seriesRecords.get(api)!, owner = host._seriesOwners.get(api)!;
  const dataId = record.dataId, current = series._transforms.get(dataId);
  const next = spec === null ? undefined : series._newTransform(spec);
  if (next === undefined ? current === undefined : current !== undefined && sameSpec(current.spec, next.spec)) return false;
  const source = current?.run.source() ?? host._dataLayer.seriesBars(dataId);
  const confirmation = host._seriesProvenance.get(dataId)?.snapshot().confirmation;
  if (next === undefined) series._transforms.delete(dataId);
  else {
    next.run.setData(source);
    series._transforms.set(dataId, next);
    // A new transform brings its renderer; new options keep the one the host chose.
    if (current?.spec.type !== next.spec.type) series._setSeriesType(api, getSeriesTransform(next.spec.type).renderer, false);
  }
  // The elements are a new index space, so the view is fitted as for a fresh load.
  host._hasFitContent = false;
  series._setData(dataId, next?.run.elements() ?? source, confirmation === undefined ? undefined : { confirmation }, owner);
  if (notify) host._emit('objects:change', {});
  return true;
}

/**
 * A tick on a transformed series: the run forms the elements again from its
 * last closed bar, and only the ones that moved are written. A tail that
 * grew or was replaced in place goes through the data layer's live path; one
 * that shrank or moved further back is rewritten whole and recorded as a
 * correction, so no study tails over an element that is gone. The element
 * still forming dated forward at its index (a Kagi vertex or a range bar a
 * newer source bar extends) is rewritten whole too, but it is the same
 * element revised, so the step stays live. A view scrolled into history
 * keeps its elements in place as bricks form and unform at the right edge.
 */
function tick(series: ChartSeries, dataId: number, run: SeriesTransformRun, bar: Bar, options: SeriesUpdateOptions | undefined,
  owner: { readonly pane: Pane }): void {
  const host = series._host, layer = host._dataLayer, scale = host._timeScale;
  const before = series._sharedAxis();
  const shown = layer.seriesBars(dataId), count = shown.length;
  const wasAtRight = scale.rightOffset >= 0;
  let first = run.update(bar);
  const next = run.elements();
  // Every read below is inside both lists: `first` stays under `count` and `next.length`.
  while (first < count && first < next.length && sameElement(shown[first]!, next[first]!)) first++;
  const forming = first === count - 1 && next.length >= count;
  const inPlace = first >= count || (forming && next[first]!.time === shown[first]!.time);
  if (inPlace) for (let i = first; i < next.length; i++) layer.update(dataId, next[i]!);
  else layer.setSeriesData(dataId, next);
  const tail = next[next.length - 1]?.time;
  const live = inPlace || (forming && next[first]!.time > shown[first]!.time);
  host._seriesProvenance.get(dataId)?.record(!live ? 'correction' : next.length > count ? 'append' : 'replace', tail, options);
  scale.setBaseIndex(layer.baseIndex);
  if (next.length !== count && !wasAtRight) host._mutateTimeScale(() => scale.setRightOffset(scale.rightOffset - (next.length - count)));
  const primary = dataId === host._firstDataId.value;
  if (primary) host._studies._invalidateIndicators();
  series._invalidateWrite([owner.pane], before);
  host._updateAccessibleSummary();
  if (primary) host._emit('data:update', { kind: 'update', time: tail ?? bar.time });
}

/** Register a transform under the id a `SeriesTransformSpec` names it by. */
export function registerSeriesTransform(type: string, definition: SeriesTransformDefinition): void {
  installTransformRuns({ set: setTransform, tick });
  addSeriesTransform(type, definition);
}
