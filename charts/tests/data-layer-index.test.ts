/**
 * The shared time index is rebuilt only when the set of times changes. A whole
 * write that keeps the set (a study's plot rewritten with the source's times,
 * a colour overlay on the source) extends or keeps the index instead, and the
 * index must come out exactly as a rebuild would have made it.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DataLayer, type SeriesId } from '../src/model/data-layer';
import type { Bar } from '../src/model/bar';

const bar = (time: number, close = 1): Bar => ({ time, open: close, high: close + 1, low: close - 1, close });
const at = (...times: number[]): Bar[] => times.map((t) => bar(t, t / 100));

function watch(layer: DataLayer): { count: () => number } {
  const spy = vi.spyOn(layer as unknown as { _rebuild(): void }, '_rebuild');
  return { count: () => spy.mock.calls.length };
}

/** The index a rebuild makes: every time any series holds, once, in order. */
function expectIndexOf(layer: DataLayer, ids: readonly SeriesId[]): void {
  const union = [...new Set(ids.flatMap((id) => layer.seriesBars(id).map((b) => b.time)))].sort((a, b) => a - b);
  expect(layer.length).toBe(union.length);
  expect(Array.from({ length: layer.length }, (_, i) => layer.indexToTime(i))).toEqual(union);
  union.forEach((time, i) => expect(layer.timeToIndex(time)).toBe(i));
  for (const id of ids) {
    expect(layer.indexedBars(id).map((ib) => ib.index)).toEqual(layer.seriesBars(id).map((b) => union.indexOf(b.time)));
  }
}

afterEach(() => { vi.restoreAllMocks(); });

describe('DataLayer.setSeriesData keeps the index when the set of times stays', () => {
  it('rewriting a series with the same times rebuilds nothing', () => {
    const layer = new DataLayer();
    const source = layer.createSeries(), plot = layer.createSeries();
    layer.setSeriesData(source, at(100, 200, 300));
    layer.setSeriesData(plot, at(100, 200, 300));
    const rebuilds = watch(layer);
    layer.setSeriesData(plot, [bar(100, 7), bar(200, 8), bar(300, 9)]);
    layer.setSeriesData(source, [bar(100, 5), bar(200, 5), bar(300, 6)]);
    expect(rebuilds.count()).toBe(0);
    expect(layer.seriesBars(plot).map((b) => b.close)).toEqual([7, 8, 9]);
    expectIndexOf(layer, [source, plot]);
  });

  it('a plot following its source onto an appended bar rebuilds nothing', () => {
    const layer = new DataLayer();
    const source = layer.createSeries(), plot = layer.createSeries();
    layer.setSeriesData(source, at(100, 200, 300));
    layer.setSeriesData(plot, at(100, 200, 300));
    const rebuilds = watch(layer);
    expect(layer.update(source, bar(400))).toBe('append');
    layer.setSeriesData(plot, at(100, 200, 300, 400));
    expect(rebuilds.count()).toBe(0);
    expectIndexOf(layer, [source, plot]);
  });

  it('times past the right edge extend the index in order', () => {
    const layer = new DataLayer();
    const a = layer.createSeries();
    layer.setSeriesData(a, at(100, 200));
    const rebuilds = watch(layer);
    layer.setSeriesData(a, at(100, 200, 300, 450, 600));
    expect(rebuilds.count()).toBe(0);
    expect(layer.baseIndex).toBe(4);
    expectIndexOf(layer, [a]);
  });

  it('a plot catching up with older history its source already paged in rebuilds nothing', () => {
    const layer = new DataLayer();
    const source = layer.createSeries(), plot = layer.createSeries();
    layer.setSeriesData(source, at(300, 400));
    layer.setSeriesData(plot, at(300, 400));
    const rebuilds = watch(layer);
    layer.addBars(source, at(100, 200));
    expect(rebuilds.count()).toBe(1); // the prepend itself changes the set
    layer.setSeriesData(plot, at(100, 200, 300, 400));
    expect(rebuilds.count()).toBe(1);
    expectIndexOf(layer, [source, plot]);
  });

  it('a new time inside the axis rebuilds', () => {
    const layer = new DataLayer();
    const a = layer.createSeries();
    layer.setSeriesData(a, at(100, 300));
    const rebuilds = watch(layer);
    layer.setSeriesData(a, at(100, 200, 300));
    expect(rebuilds.count()).toBe(1);
    expectIndexOf(layer, [a]);
  });

  it('older history no series holds rebuilds', () => {
    const layer = new DataLayer();
    const a = layer.createSeries();
    layer.setSeriesData(a, at(300, 400));
    const rebuilds = watch(layer);
    layer.setSeriesData(a, at(100, 200, 300, 400));
    expect(rebuilds.count()).toBe(1);
    expectIndexOf(layer, [a]);
  });

  it('a time another series still holds stays without a rebuild, and leaves with one when none does', () => {
    const layer = new DataLayer();
    const a = layer.createSeries(), b = layer.createSeries();
    layer.setSeriesData(a, at(100, 200, 300));
    layer.setSeriesData(b, at(200));
    const rebuilds = watch(layer);
    layer.setSeriesData(a, at(100, 300));
    expect(rebuilds.count()).toBe(0);
    expect(layer.timeToIndex(200)).toBe(1);
    expectIndexOf(layer, [a, b]);
    layer.setSeriesData(b, []);
    expect(rebuilds.count()).toBe(1);
    expect(layer.timeToIndex(200)).toBeUndefined();
    expectIndexOf(layer, [a, b]);
  });

  it('keeps sorting and collapsing input that is out of order', () => {
    const layer = new DataLayer();
    const a = layer.createSeries();
    layer.setSeriesData(a, at(100, 200, 300));
    layer.setSeriesData(a, [bar(300, 3), bar(100, 1), bar(200, 2), bar(300, 33)]);
    expect(layer.seriesBars(a).map((b) => [b.time, b.close])).toEqual([[100, 1], [200, 2], [300, 33]]);
    expectIndexOf(layer, [a]);
  });

  it('matches a rebuilt index through any sequence of writes', () => {
    // Seeded, so a failure names the same sequence every run.
    let s = 20260926 >>> 0;
    const rnd = (): number => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0), s / 4294967296);
    const pick = <T,>(xs: readonly T[]): T => xs[Math.floor(rnd() * xs.length)];
    const times = (): Bar[] => {
      const out: Bar[] = [];
      for (let t = 1; t <= 40; t++) if (rnd() < 0.5) out.push(bar(t * 60, rnd() * 100));
      return out;
    };
    const layer = new DataLayer();
    const ids = [layer.createSeries(), layer.createSeries(), layer.createSeries()];
    for (let step = 0; step < 3000; step++) {
      const id = pick(ids);
      const current = layer.seriesBars(id);
      const kind = rnd();
      if (kind < 0.25) layer.setSeriesData(id, times());
      else if (kind < 0.45) layer.setSeriesData(id, current.map((b) => ({ ...b, close: rnd() })));
      else if (kind < 0.6) {
        const last = current[current.length - 1]?.time ?? 0;
        layer.setSeriesData(id, [...current, ...at(last + 60 * (1 + Math.floor(rnd() * 3)))]);
      } else if (kind < 0.7) layer.setSeriesData(id, current.filter(() => rnd() < 0.9));
      else if (kind < 0.8) layer.setSeriesData(id, pick(ids.map((other) => layer.seriesBars(other))));
      else if (kind < 0.9) layer.update(id, bar(60 * (1 + Math.floor(rnd() * 45)), rnd()));
      else layer.addBars(id, times().slice(0, 3));
      expectIndexOf(layer, ids);
    }
  });
});

describe('DataLayer.update on an older bar', () => {
  it('replaces the bar at that time wherever it sits', () => {
    const layer = new DataLayer();
    const a = layer.createSeries();
    const times = Array.from({ length: 101 }, (_, i) => 1000 + i * 60);
    layer.setSeriesData(a, at(...times));
    const rebuilds = watch(layer);
    for (const i of [0, 1, 37, 50, 98, 99]) expect(layer.update(a, bar(times[i], -i))).toBe('replace');
    expect(rebuilds.count()).toBe(0);
    for (const i of [0, 1, 37, 50, 98, 99]) expect(layer.seriesBars(a)[i].close).toBe(-i);
    expect(layer.seriesBars(a).map((b) => b.time)).toEqual(times);
  });

  it('still finds a time in a series a time that does not order has scrambled', () => {
    const layer = new DataLayer();
    const a = layer.createSeries();
    layer.setSeriesData(a, [bar(NaN), bar(100), bar(200), bar(300), bar(NaN), bar(400)]);
    const before = layer.seriesBars(a).map((b) => b.time);
    const target = before.findIndex((t) => t === 200);
    expect(layer.update(a, bar(200, 42))).toBe('replace');
    expect(layer.seriesBars(a)[target].close).toBe(42);
    expect(layer.seriesBars(a).map((b) => b.time)).toEqual(before);
  });
});
