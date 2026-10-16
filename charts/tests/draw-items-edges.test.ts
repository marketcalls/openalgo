/**
 * A renderer that draws a segment between neighbouring bars (a line, a step,
 * an area, kagi) needs the bar beyond each edge of the view, or the segment
 * that crosses the edge is never drawn (src/render/draw-items.ts, `edges`).
 *
 * On a dense series that loss is one bar's width and nobody sees it. On a
 * sparse one it is most of the line: a level held from 09:20 to 09:40 on a
 * chart whose axis also carries a 5-second series disappears entirely once the
 * view starts at 09:30, because its only in-view bar is the one at 09:40.
 *
 * Each neighbour is marked with the x of the view edge it lies beyond
 * (`DrawItem.edgeX`), so the renderer can cut the segment there rather than
 * run it out to a bar that may be millions of pixels away. The neighbours go
 * straight into the items, around the level of detail rather than through
 * it: they are off screen, so they belong to no column, and the columns in
 * view come out exactly as they would without them.
 */
import { describe, it, expect } from 'vitest';
import { createSeriesDrawItems, type LodRequest } from '../src/render/draw-items';
import { DataLayer } from '../src/model/data-layer';
import { TimeScale } from '../src/scale/time-scale';
import { PriceScale } from '../src/scale/price-scale';
import { getChartType, type DrawItem, type RendererEntry, type SeriesRenderContext } from '../src/model/chart-type-registry';
import type { SeriesStyle } from '../src/render/series-style';
import type { Bar } from '../src/model/bar';
import { Chart } from '../src/core/chart';
import { InvalidationLevel } from '../src/core/invalidate-mask';
import { Canvas2dBackend } from '../src/render/canvas2d-backend';
import type { IRenderBackend } from '../src/render/backend';
import { fakeDocument } from './helpers/fake-dom';
import { makeCtx } from './helpers/fake-ctx';
import { registerTransformChartTypes } from '../src/transform';
import { registerIndicator } from '../src/model/indicator-registry';
import { darkTheme } from '../src/theme';

const bar = (time: number, v: number): Bar => ({ time, open: v, high: v, low: v, close: v });

function setup() {
  const layer = new DataLayer();
  // A dense series owns the axis: 101 logical indices, one per time.
  const dense = layer.createSeries();
  layer.setSeriesData(dense, Array.from({ length: 101 }, (_, i) => bar(1000 + i * 5, 10)));
  // The sparse line has three points on it: indices 0, 50 and 100.
  const sparse = layer.createSeries();
  layer.setSeriesData(sparse, [bar(1000, 20), bar(1250, 20), bar(1500, 20)]);
  const timeScale = new TimeScale({ barSpacing: 8, rightOffset: 0 });
  timeScale.setWidth(800);
  timeScale.setBaseIndex(layer.baseIndex);
  const scale = new PriceScale();
  scale.setHeight(200);
  scale.setPriceRange({ min: 0, max: 30 });
  return { layer, sparse, dense, timeScale, scale };
}

describe('series draw items at the edges of the view', () => {
  it('without edges, carries only the bars in view', () => {
    const { layer, sparse, timeScale, scale } = setup();
    const items = createSeriesDrawItems().build(layer, sparse, 20, 80, 0, timeScale, scale, null);
    expect(items.map((it) => it.bar.time)).toEqual([1250]);
    expect(items[0].edgeX).toBeUndefined();
  });

  it('with edges, adds the nearest bar beyond each side, off screen, marked with the edge it lies beyond', () => {
    const { layer, sparse, timeScale, scale } = setup();
    const buffer = createSeriesDrawItems();
    const items = buffer.build(layer, sparse, 20, 80, 0, timeScale, scale, null, true);
    expect(items.map((it) => it.bar.time)).toEqual([1000, 1250, 1500]);
    expect(items[0].x).toBeLessThan(timeScale.indexToX(20));
    expect(items[2].x).toBeGreaterThan(timeScale.indexToX(80));
    expect(items.map((it) => it.edgeX)).toEqual([0, undefined, timeScale.width]);
    // firstIndex still names the first bar IN view, for previous-close colouring.
    expect(buffer.firstIndex()).toBe(50);
  });

  it('crosses the whole view with the two neighbours when no bar of the series is in view', () => {
    const { layer, sparse, timeScale, scale } = setup();
    const buffer = createSeriesDrawItems();
    const items = buffer.build(layer, sparse, 60, 90, 0, timeScale, scale, null, true);
    expect(items.map((it) => it.bar.time)).toEqual([1250, 1500]);
    expect(items.map((it) => it.edgeX)).toEqual([0, timeScale.width]);
    expect(buffer.firstIndex()).toBe(-1);
  });

  it('adds nothing past the first or last bar of the series', () => {
    const { layer, sparse, timeScale, scale } = setup();
    const items = createSeriesDrawItems().build(layer, sparse, 0, 100, 0, timeScale, scale, null, true);
    expect(items.map((it) => it.bar.time)).toEqual([1000, 1250, 1500]);
    expect(items.every((it) => it.edgeX === undefined)).toBe(true);
  });

  it('forgets the mark on a later frame where the same pooled item is in view', () => {
    const { layer, sparse, timeScale, scale } = setup();
    const buffer = createSeriesDrawItems();
    buffer.build(layer, sparse, 20, 80, 0, timeScale, scale, null, true);
    const items = buffer.build(layer, sparse, 0, 100, 0, timeScale, scale, null, true);
    expect(items.map((it) => it.edgeX)).toEqual([undefined, undefined, undefined]);
  });

  it('keeps the neighbours out of the level of detail, which merges the bars in view exactly as without them', () => {
    const layer = new DataLayer();
    const id = layer.createSeries();
    // A seeded walk, dense enough that several bars share every device column.
    let s = 7, v = 100;
    const rnd = (): number => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0), s / 4294967296);
    layer.setSeriesData(id, Array.from({ length: 4000 }, (_, i) => bar(1000 + i * 5, (v += (rnd() - 0.5) * 2))));
    const timeScale = new TimeScale({ barSpacing: 0.3, rightOffset: 0, minBarSpacing: 0.01 });
    timeScale.setWidth(600);
    timeScale.setBaseIndex(layer.baseIndex);
    const scale = new PriceScale();
    scale.setHeight(200);
    scale.setPriceRange({ min: 50, max: 150 });
    const range = timeScale.visibleRange();
    const lod: LodRequest = { kind: 'line', dpr: 1, factor: 1 };
    const plain = createSeriesDrawItems().build(layer, id, range.from, range.to, 0, timeScale, scale, lod)
      .map((it) => ({ x: it.x, time: it.bar.time }));
    const edged = createSeriesDrawItems().build(layer, id, range.from, range.to, 0, timeScale, scale, lod, true);
    // Fewer items than bars: the level of detail did merge.
    expect(plain.length).toBeLessThan(range.to - range.from);
    expect(edged.map((it) => ({ x: it.x, time: it.bar.time })).slice(1)).toEqual(plain);
    const first = layer.visibleBars(id, range.from, range.to)[0];
    const left = layer.seriesBars(id)[layer.seriesBars(id).indexOf(first.bar) - 1];
    expect(edged[0].bar).toBe(left);
    expect(edged[0].edgeX).toBe(0);
    expect(edged[0].x).toBeCloseTo(timeScale.indexToX(first.index - 1), 9);
  });

  it('makes no function per call, so the series pass stays free of allocation', () => {
    // A closure built inside `build` is an allocation per series per frame
    // (the series pass has been allocation-free since 2.5.8), and the hot loop
    // calling through it is slower than the loop written out.
    const build = createSeriesDrawItems().build.toString();
    expect(build).not.toMatch(/=>|\bfunction\b/);
  });

  it('is on for the renderers that join bars and off for the rest', () => {
    registerTransformChartTypes();
    for (const t of ['line', 'line-markers', 'step', 'area', 'hlc-area', 'baseline', 'kagi'] as const) {
      expect(getChartType(t).connectsBars, t).toBe(true);
    }
    for (const t of ['candlestick', 'hollow-candle', 'volume-candle', 'bar', 'high-low', 'column', 'histogram', 'point-figure'] as const) {
      expect(getChartType(t).connectsBars, t).toBeFalsy();
    }
  });
});

/** The 2D backend, with every series pass it is asked for written down. */
class Recorder implements IRenderBackend {
  public readonly kind = 'canvas2d' as const;
  public readonly calls: { type: RendererEntry; items: DrawItem[] }[] = [];
  private readonly _inner = new Canvas2dBackend();
  public mount(canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D | null): void { this._inner.mount(canvas, ctx); }
  public resize(w: number, h: number, dpr: number): void { this._inner.resize(w, h, dpr); }
  public beginFrame(clear: boolean): void { this._inner.beginFrame(clear); }
  public drawSeries(
    entry: RendererEntry, items: readonly DrawItem[], priceToY: (p: number) => number,
    barSpacing: number, dpr: number, style: SeriesStyle, rc: SeriesRenderContext,
  ): void {
    this.calls.push({ type: entry, items: items.map((it) => ({ ...it })) });
    this._inner.drawSeries(entry, items, priceToY, barSpacing, dpr, style, rc);
  }
  public endFrame(): void { this._inner.endFrame(); }
  public overlay2d(): CanvasRenderingContext2D | null { return this._inner.overlay2d(); }
  public destroy(): void { this._inner.destroy(); }
}

function chartRig(minBarSpacing?: number) {
  const doc = fakeDocument();
  const recorders: Recorder[] = [];
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false, timeNavigator: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    renderBackend: () => { const r = new Recorder(); recorders.push(r); return r; },
    ...(minBarSpacing === undefined ? {} : { timeScale: { minBarSpacing } }),
  });
  chart.applySize(800, 500);
  const paint = (): void => { chart.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full)); };
  const last = (entry: RendererEntry): DrawItem[] => {
    const calls = recorders[0].calls.filter((c) => c.type === entry);
    return calls[calls.length - 1].items;
  };
  return { chart, paint, last };
}

/** Five-second bars: a seeded walk with a quiet and a busy stretch. */
function fiveSecond(count: number, t0: number): Bar[] {
  let s = 11, p = 22_000;
  const rnd = (): number => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0), s / 4294967296);
  return Array.from({ length: count }, (_, i) => {
    const vol = i % 900 < 300 ? 1.5 : 6;
    const o = p;
    p += (rnd() - 0.5) * vol;
    return { time: t0 + i * 5, open: o, high: Math.max(o, p) + rnd() * vol, low: Math.min(o, p) - rnd() * vol, close: p };
  });
}

describe('the pane hands a joining renderer its neighbours', () => {
  const T0 = 1_758_000_000;

  it('beyond the left edge: a level whose only bar in view is its last still reaches the plot\'s left edge', () => {
    const { chart, paint, last } = chartRig();
    chart.addSeries('candlestick').setData(fiveSecond(2000, T0));
    // A level held from bar 200 to bar 1400 of the five-second axis.
    const level = chart.addSeries('line');
    level.setData([bar(T0 + 200 * 5, 22_010), bar(T0 + 1400 * 5, 22_010)]);
    chart.timeScale.setBarSpacing(6);
    // Scroll so the view starts well after bar 200 and ends after bar 1400.
    chart.timeScale.setRightOffset(-(1999 - 1500));
    paint();
    const items = last(getChartType('line'));
    expect(items.map((it) => it.bar.time)).toEqual([T0 + 200 * 5, T0 + 1400 * 5]);
    expect(items[0].x).toBeLessThan(0);
    expect(items[0].edgeX).toBe(0);
    expect(items[1].edgeX).toBeUndefined();
    expect(items[1].x).toBeGreaterThan(0);
    expect(items[1].x).toBeLessThan(chart.timeScale.width);
    chart.destroy();
  });

  it('to a study plot, its own next point, gap or not, so a gap at the edge of the view is never bridged', () => {
    // A study stores a bar with no value as NaN rather than leaving it out,
    // so the neighbour is the plot's very next point. Were the gaps left out,
    // the neighbour would be the last value before the gap, and the segment
    // from it would join across the gap.
    const { chart, paint, last } = chartRig();
    const bars = fiveSecond(2000, T0);
    chart.addSeries('candlestick').setData(bars);
    chart.timeScale.setBarSpacing(6);
    chart.timeScale.setRightOffset(-600);
    paint();
    const first = Math.floor(chart.timeScale.visibleRange().from);
    // Two gaps: one that ends just beyond the left edge of the view, so the
    // neighbour there is a gap, and one that ends on the last bar in view, so
    // the neighbour beyond the right edge has a value and the bar before it
    // does not.
    const lastInView = Math.ceil(chart.timeScale.visibleRange().to);
    const gapAt = (i: number): boolean => (i >= first - 40 && i < first) || (i >= lastInView - 30 && i <= lastInView);
    const id = `edge-gap-study-${first}`;
    registerIndicator({
      id, name: 'Edge gap study', placement: 'onchart', inputs: [],
      plots: [{ key: 'level', type: 'area', title: 'Level' }],
      calc: (source) => ({ level: source.map((b, i) => (gapAt(i) ? null : b.close)) }),
    });
    chart.addIndicator(id);
    paint();
    const items = last(getChartType('area'));
    const toY = (p: number): number => 250 - (p - 22_000) * 4;
    expect(items[0].edgeX).toBe(0);
    expect(items[0].bar.close).toBeNaN();
    expect(items[0].x).toBeCloseTo(chart.timeScale.indexToX(first - 1), 9);
    expect(Number.isFinite(items[1].bar.close)).toBe(true);
    expect(items[items.length - 1].edgeX).toBe(chart.timeScale.width);
    expect(Number.isFinite(items[items.length - 1].bar.close)).toBe(true);
    expect(items[items.length - 2].bar.close).toBeNaN();
    // So the area paints exactly what its bars in view paint on their own.
    const drawn = (list: DrawItem[]): string[] => {
      const { ctx, rec } = makeCtx();
      getChartType('area').draw(ctx, list, toY, 6, 1, {}, { plotHeight: 400, maxVolume: 0, theme: darkTheme });
      return rec.ops.filter((o) => o.args.every(Number.isFinite)).map((o) => `${o.type} ${o.args.join(' ')}`);
    };
    expect(drawn(items)).toEqual(drawn(items.slice(1, -1)));
    chart.destroy();
  });

  it('through the level of detail: the neighbours arrive unmerged at either end', () => {
    const { chart, paint, last } = chartRig(0.01);
    chart.addSeries('candlestick').setData(fiveSecond(12_000, T0));
    const level = chart.addSeries('step');
    level.setData([bar(T0 + 100 * 5, 22_000), bar(T0 + 5000 * 5, 22_004), bar(T0 + 11_900 * 5, 22_008)]);
    chart.timeScale.setBarSpacing(0.2);
    // The view ends at bar 7000 and spans some 3,600 bars, so bar 5000 is in it.
    chart.timeScale.setRightOffset(7000 - 11_999);
    paint();
    const range = chart.timeScale.visibleRange();
    // The level of detail is on at this zoom, and the step series takes it.
    expect(range.to - range.from).toBeGreaterThan(3000);
    const items = last(getChartType('step'));
    expect(items.map((it) => it.bar.time)).toEqual([T0 + 100 * 5, T0 + 5000 * 5, T0 + 11_900 * 5]);
    expect(items.map((it) => it.edgeX)).toEqual([0, undefined, chart.timeScale.width]);
    chart.destroy();
  });
});
