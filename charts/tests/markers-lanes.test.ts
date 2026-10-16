/**
 * Marker lanes (src/primitives/markers.ts).
 *
 * A signal label is a plate wider than a bar: about thirty pixels for "Sell"
 * where bars sit six to ten pixels apart. Markers used to avoid each other only
 * on one bar, and there by the glyph size rather than the plate height, so a
 * whipsaw (buy, sell, buy on neighbouring bars) drew its labels over each
 * other. These cases read the plates the renderer asked for and check that
 * neighbours on one side never overlap, that a label with no neighbour stays
 * where it always was, and that panning does not move a label.
 */
import { describe, it, expect } from 'vitest';
import { SeriesMarkers, effectiveMarkerPx, type SeriesMarker } from '../src/primitives/markers';
import { makeCtx, type Op } from './helpers/fake-ctx';
import { DataLayer } from '../src/model/data-layer';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { darkTheme } from '../src/theme';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import type { Bar } from '../src/model/bar';

const T0 = 1_000;
const STEP = 60;
const at = (i: number): number => T0 + i * STEP;

/** A quiet seeded random walk: highs and lows of neighbouring bars sit close together. */
function walk(count: number, seed = 5): Bar[] {
  let state = seed >>> 0;
  const random = (): number => { state = (state * 1664525 + 1013904223) >>> 0; return state / 4294967296; };
  const bars: Bar[] = [];
  let close = 100;
  for (let i = 0; i < count; i++) {
    const open = close;
    close = open + (random() - 0.5) * 0.6;
    bars.push({ time: at(i), open, high: Math.max(open, close) + random() * 0.3, low: Math.min(open, close) - random() * 0.3, close });
  }
  return bars;
}

function makeRc(dl: DataLayer, barSpacing = 6, rightOffset = 0, width = 600): PrimitiveRenderContext {
  const priceScale = new PriceScale();
  priceScale.setHeight(400);
  priceScale.setPriceRange({ min: 90, max: 110 });
  const timeScale = new TimeScale({ barSpacing, rightOffset });
  timeScale.setWidth(width);
  timeScale.setBaseIndex(dl.baseIndex);
  return { timeScale, priceScale, dataLayer: dl, plotWidth: width, plotHeight: 400, priceAxisWidth: 56, dpr: 1, theme: darkTheme };
}

interface Plate { color: string; l: number; r: number; t: number; b: number; apexX: number; apexY: number }

/** Each plate drawn: its body rectangle, joined with its tail down or up to the apex. */
function plates(ops: Op[]): Plate[] {
  const out: Plate[] = [];
  for (let i = 0; i < ops.length; i++) {
    if (ops[i].type !== 'roundRect') continue;
    const [x, y, w, h] = ops[i].args;
    const fill = ops.slice(i).find(o => o.type === 'fill')!;
    const apex = ops.slice(i).find(o => o.type === 'moveTo')!;
    const [apexX, apexY] = apex.args;
    out.push({ color: String(fill.fillStyle), l: x, r: x + w, t: Math.min(y, apexY), b: Math.max(y + h, apexY), apexX, apexY });
  }
  return out;
}

const overlaps = (a: Plate, b: Plate): boolean => a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b;
function collisions(list: Plate[]): Array<[Plate, Plate]> {
  const hits: Array<[Plate, Plate]> = [];
  for (let i = 0; i < list.length; i++) for (let j = i + 1; j < list.length; j++) if (overlaps(list[i], list[j])) hits.push([list[i], list[j]]);
  return hits;
}

/** A buy below and a sell above, alternating bar by bar: the whipsaw a crossover study draws. */
function whipsaw(from: number, to: number, idPrefix = ''): SeriesMarker[] {
  const out: SeriesMarker[] = [];
  for (let i = from; i <= to; i++) {
    const buy = i % 2 === 0;
    // One colour per mark, so a plate in the recording names its mark.
    const tone = (i % 256).toString(16).padStart(2, '0');
    out.push(buy
      ? { time: at(i), position: 'belowBar', shape: 'labelUp', size: 'small', color: `#26${tone}9a`, text: 'Buy', id: `${idPrefix}b${i}` }
      : { time: at(i), position: 'aboveBar', shape: 'labelDown', size: 'small', color: `#ef${tone}50`, text: 'Sell', id: `${idPrefix}s${i}` });
  }
  return out;
}

const sells = (list: Plate[]): Plate[] => list.filter(p => p.color.startsWith('#ef'));
const buys = (list: Plate[]): Plate[] => list.filter(p => p.color.startsWith('#26'));

function paint(markers: SeriesMarker[], bars: Bar[], spacing = 6, rightOffset = 0): { list: Plate[]; rc: PrimitiveRenderContext; layer: SeriesMarkers } {
  const dl = new DataLayer();
  const id = dl.createSeries();
  dl.setSeriesData(id, bars);
  const layer = new SeriesMarkers(id);
  layer.setMarkers(markers);
  const rc = makeRc(dl, spacing, rightOffset);
  const { ctx, rec } = makeCtx();
  layer.draw(ctx, rc);
  return { list: plates(rec.ops), rc, layer };
}

describe('marker lanes', () => {
  it('keeps same-side labels on a whipsaw apart at a six pixel bar spacing', () => {
    const bars = walk(120);
    const { list } = paint(whipsaw(60, 99), bars);
    expect(sells(list)).toHaveLength(20);
    expect(buys(list)).toHaveLength(20);
    expect(collisions(sells(list))).toEqual([]);
    expect(collisions(buys(list))).toEqual([]);
  });

  it('keeps two labels on one bar apart by the plate height, not the glyph size', () => {
    const bars = walk(60);
    const markers: SeriesMarker[] = [
      { time: at(40), position: 'aboveBar', shape: 'labelDown', size: 'small', color: '#ef1150', text: 'Sell' },
      { time: at(40), position: 'aboveBar', shape: 'labelDown', size: 'small', color: '#ef2250', text: 'Exit' },
    ];
    const { list } = paint(markers, bars);
    expect(list).toHaveLength(2);
    expect(collisions(list)).toEqual([]);
  });

  it('leaves a label with no neighbour, and the first of a cluster, where it always was', () => {
    const bars = walk(120);
    const lone: SeriesMarker = { time: at(30), position: 'aboveBar', shape: 'labelDown', size: 'small', color: '#ef0150', text: 'Sell' };
    const loneBuy: SeriesMarker = { time: at(45), position: 'belowBar', shape: 'labelUp', size: 'small', color: '#260f9a', text: 'Buy' };
    const { list, rc } = paint([lone, loneBuy, ...whipsaw(80, 95)], bars);
    const px = effectiveMarkerPx('small', 6);
    const natural = (_: Plate, bar: Bar, above: boolean): number =>
      above ? rc.priceScale.priceToY(bar.high) - px : rc.priceScale.priceToY(bar.low) + px;
    const find = (color: string): Plate => list.find(p => p.color === color)!;
    expect(find('#ef0150').apexY).toBe(natural(find('#ef0150'), bars[30], true));
    expect(find('#260f9a').apexY).toBe(natural(find('#260f9a'), bars[45], false));
    // The cluster's first sell and first buy have nothing before them.
    expect(find('#ef5150').apexY).toBe(natural(find('#ef5150'), bars[81], true));
    expect(find('#26509a').apexY).toBe(natural(find('#26509a'), bars[80], false));
    // A later one in the cluster has made room.
    expect(find('#ef5350').apexY).toBeLessThan(natural(find('#ef5350'), bars[83], true));
  });

  it('does not move a label while the view pans, even when the start of its cluster scrolls away', () => {
    const bars = walk(200);
    const markers = whipsaw(120, 170);
    // At rightOffset 0 the view shows bars 100 to 199; at 40 it has scrolled
    // left to bars 60 to 159, and at -30 right to 130 to 229, which hides the
    // cluster's first dozen marks.
    const views = [0, 40, -30].map(offset => new Map(paint(markers, bars, 6, offset).list.map(p => [p.color, p])));
    let compared = 0;
    for (const [color, plate] of views[0]) {
      for (const other of views.slice(1)) {
        const moved = other.get(color);
        if (moved === undefined) continue;
        // x shifts with the pan; the height a label sits at does not.
        expect(moved.apexY).toBe(plate.apexY);
        compared++;
      }
    }
    expect(compared).toBeGreaterThan(40);
  });

  it('hit-tests a label where it is drawn', () => {
    const bars = walk(120);
    const { list, layer } = paint(whipsaw(80, 95), bars);
    const moved = list.find(p => p.color === '#ef5350')!;
    const hit = layer.hitTest(moved.apexX, moved.apexY);
    expect(hit?.externalId).toBe('s83');
  });

  it('keeps bare text marks on neighbouring bars apart', () => {
    const bars = walk(80);
    const markers: SeriesMarker[] = Array.from({ length: 12 }, (_, k) => ({
      time: at(50 + k), position: 'aboveBar', shape: 'text', size: 'small', color: '#e0e0e0', text: 'Sell',
    }));
    const dl = new DataLayer();
    const id = dl.createSeries();
    dl.setSeriesData(id, bars);
    const layer = new SeriesMarkers(id);
    layer.setMarkers(markers);
    const { ctx, rec } = makeCtx();
    layer.draw(ctx, makeRc(dl));
    // Baseline bottom, centred: 'Sell' measures 24 px in the recording context.
    const boxes = rec.ops.filter(o => o.type === 'fillText').map(o => ({
      color: '', l: o.args[0] - 12, r: o.args[0] + 12, t: o.args[1] - 9, b: o.args[1], apexX: 0, apexY: 0,
    }));
    expect(boxes).toHaveLength(12);
    expect(collisions(boxes)).toEqual([]);
  });

  it('leaves glyph marks without text on the path they always took', () => {
    const bars = walk(80);
    const markers: SeriesMarker[] = Array.from({ length: 10 }, (_, k) => ({
      time: at(50 + k), position: 'aboveBar', shape: 'arrowDown', size: 'small', color: '#e53935',
    }));
    const dl = new DataLayer();
    const id = dl.createSeries();
    dl.setSeriesData(id, bars);
    const layer = new SeriesMarkers(id);
    layer.setMarkers(markers);
    const rc = makeRc(dl);
    const { ctx, rec } = makeCtx();
    layer.draw(ctx, rc);
    const px = effectiveMarkerPx('small', 6);
    const tips = rec.ops.filter(o => o.type === 'moveTo').map(o => o.args[1]);
    expect(tips).toEqual(bars.slice(50, 60).map(b => rc.priceScale.priceToY(b.high) - px + px / 2));
  });

  it('reads no bar for labels far left of the view that cannot reach it', () => {
    const n = 20_000;
    let reads = 0;
    const bars: Bar[] = [];
    for (let i = 0; i < n; i++) {
      const b = { time: at(i), open: 100, high: 101, low: 99, close: 100 };
      let close = b.close;
      Object.defineProperty(b, 'close', { get: () => { reads++; return close; }, set: (v: number) => { close = v; }, enumerable: true });
      bars.push(b);
    }
    // A label every 50 bars across the whole history, plus a whipsaw in view.
    const markers: SeriesMarker[] = [];
    for (let i = 0; i < n - 200; i += 50) markers.push({ time: at(i), position: 'aboveBar', shape: 'labelDown', size: 'small', color: '#ef5350', text: 'Sell' });
    markers.push(...whipsaw(n - 60, n - 20));
    const dl = new DataLayer();
    const id = dl.createSeries();
    dl.setSeriesData(id, bars);
    const layer = new SeriesMarkers(id);
    layer.setMarkers(markers);
    const { ctx } = makeCtx();
    const rc = makeRc(dl, 10);
    layer.draw(ctx, rc);
    reads = 0;
    layer.draw(ctx, rc);
    expect(reads).toBeLessThan(120);
  });

  // Signals on every bar of a long history: buys below and sells above, each
  // with its own colour so a recorded plate names the bar it belongs to.
  const everyBar = (count: number): SeriesMarker[] => Array.from({ length: count }, (_, i) => {
    const tag = i.toString(16).padStart(4, '0');
    return i % 2 === 0
      ? { time: at(i), position: 'belowBar', shape: 'labelUp', size: 'small', color: `#26${tag}`, text: 'Buy' }
      : { time: at(i), position: 'aboveBar', shape: 'labelDown', size: 'small', color: `#ef${tag}`, text: 'Sell' };
  });

  it('moves a label at most five of its own heights, so a wide zoom overlaps instead of stacking out of the pane', () => {
    const bars = walk(2000, 11);
    const { list, rc } = paint(everyBar(2000), bars, 0.5);
    const px = effectiveMarkerPx('small', 0.5);
    // A 9 px plate: its body and tail, and the gap between lanes.
    const lane = 9 + 9 * 0.64 + 9 * 0.42 + 2;
    let most = 0;
    for (const plate of list) {
      const i = parseInt(plate.color.slice(3), 16);
      const natural = plate.color.startsWith('#ef') ? rc.priceScale.priceToY(bars[i].high) - px : rc.priceScale.priceToY(bars[i].low) + px;
      most = Math.max(most, Math.abs(plate.apexY - natural));
    }
    expect(list.length).toBeGreaterThan(1000);
    // Some labels did take lanes, and none went further than five.
    expect(most).toBeGreaterThan(lane);
    expect(most).toBeLessThanOrEqual(5 * lane + 1e-6);
  });

  it('lays out a bounded run before the view, not the history, when labels never leave a gap', () => {
    const n = 20_000;
    let reads = 0;
    const bars: Bar[] = walk(n, 3);
    for (const b of bars) {
      let close = b.close;
      Object.defineProperty(b, 'close', { get: () => { reads++; return close; }, set: (v: number) => { close = v; }, enumerable: true });
    }
    const dl = new DataLayer();
    const id = dl.createSeries();
    dl.setSeriesData(id, bars);
    const layer = new SeriesMarkers(id);
    let texts = 0;
    // A study sets its marks again on every recompute, so a paint right after
    // a set must not measure or read every mark in the history either.
    const markers = everyBar(n).map(m => {
      const text = m.text;
      return Object.defineProperty({ ...m }, 'text', { get: () => { texts++; return text; }, enumerable: true });
    });
    layer.setMarkers(markers);
    const rc = makeRc(dl, 6);
    const { ctx } = makeCtx();
    reads = 0;
    texts = 0;
    layer.draw(ctx, rc);
    // About a hundred bars in view, and at most two windows of 256 laid out before them.
    expect(reads).toBeLessThan(1000);
    expect(texts).toBeLessThan(n / 4);
  });

  it('keeps labels still while a dense run pans by a few bars', () => {
    const bars = walk(2000, 13);
    const markers = everyBar(2000);
    const views = [0, 5, -7, 12].map(offset => new Map(paint(markers, bars, 6, offset).list.map(p => [p.color, p.apexY])));
    let compared = 0;
    for (const [color, y] of views[0]) {
      for (const other of views.slice(1)) {
        const moved = other.get(color);
        if (moved === undefined) continue;
        expect(moved).toBe(y);
        compared++;
      }
    }
    expect(compared).toBeGreaterThan(200);
  });

  it('keeps whipsaw labels apart at a fractional device pixel ratio', () => {
    const bars = walk(120);
    const dl = new DataLayer();
    const id = dl.createSeries();
    dl.setSeriesData(id, bars);
    const layer = new SeriesMarkers(id);
    layer.setMarkers(whipsaw(60, 99));
    const { ctx, rec } = makeCtx();
    layer.draw(ctx, { ...makeRc(dl), dpr: 1.25 });
    const list = plates(rec.ops);
    expect(sells(list)).toHaveLength(20);
    expect(collisions(sells(list))).toEqual([]);
    expect(collisions(buys(list))).toEqual([]);
  });
});
