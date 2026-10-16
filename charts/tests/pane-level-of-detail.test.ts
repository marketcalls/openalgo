/**
 * The default candle level of detail (ARCHITECTURE.md §4.4): once bars are
 * narrower than the stick a candle is drawn with, the series pass draws one
 * OHLC-preserving stick per device-pixel column, so a frame costs the plot's
 * width and not the bar count.
 *
 * Three claims, each checked where it can fail:
 *  - the frame is bounded: 200,000 bars fitted into the plot put at most a few
 *    marks in each device-pixel column, where drawing every bar puts 400,000;
 *  - nothing changes above the threshold: the same chart with the level of
 *    detail switched off paints the identical op stream at every zoom that
 *    gives each bar a column of its own;
 *  - nothing is lost below it: the sticks cover exactly the pixels every bar
 *    covered, column by column, and the volume columns do too.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { InvalidationLevel } from '../src/core/invalidate-mask';
import { Canvas2dBackend } from '../src/render/canvas2d-backend';
import type { IRenderBackend } from '../src/render/backend';
import { getChartType, registerChartType, type DrawItem, type RendererEntry, type SeriesRenderContext } from '../src/model/chart-type-registry';
import type { SeriesStyle } from '../src/render/series-style';
import { createLodColumns, lodActive, lodColumnWidth, lodKind, type LodKind } from '../src/model/conflation';
import type { Bar } from '../src/model/bar';
import { fakeDocument } from './helpers/fake-dom';
import { RecordingContext, makeCtx, type Op } from './helpers/fake-ctx';

afterEach(() => { vi.unstubAllGlobals(); });

/** A random walk whose bars overlap their neighbours: each opens at the last close. */
function walk(count: number, seed = 20260926): Bar[] {
  let s = seed >>> 0;
  const rnd = (): number => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0), s / 4294967296);
  const out: Bar[] = [];
  let price = 1000;
  for (let i = 0; i < count; i++) {
    const open = price;
    const close = Math.max(1, open + (rnd() - 0.5) * 8);
    out.push({
      time: 1_600_000_000 + i * 60, open,
      high: Math.max(open, close) + rnd() * 3, low: Math.min(open, close) - rnd() * 3,
      close, volume: Math.floor(1000 + rnd() * 9000),
    });
    price = close;
  }
  return out;
}

const MARKS = new Set(['fillRect', 'strokeRect', 'fill', 'stroke', 'fillText', 'drawImage']);

/** A recording context that only counts the marks, for frames too big to record. */
class Tally extends RecordingContext {
  public marks = 0;
  public constructor() {
    super();
    this.ops = { push: (op: Op): number => { if (MARKS.has(op.type)) this.marks++; return 0; } } as unknown as Op[];
  }
}

/**
 * The 2D backend, except that the series pass goes into a context of its own,
 * so a test can read the series' ops apart from the grid, axes and labels.
 */
class SeriesOnly implements IRenderBackend {
  public readonly kind = 'canvas2d' as const;
  public readonly series = makeCtx();
  public calls: { items: readonly DrawItem[]; barSpacing: number }[] = [];
  private readonly _inner = new Canvas2dBackend();
  public mount(canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D | null): void { this._inner.mount(canvas, ctx); }
  public resize(w: number, h: number, dpr: number): void { this._inner.resize(w, h, dpr); }
  public beginFrame(clear: boolean): void { this._inner.beginFrame(clear); this.series.rec.ops.length = 0; this.calls = []; }
  public drawSeries(
    entry: RendererEntry, items: readonly DrawItem[], priceToY: (p: number) => number,
    barSpacing: number, dpr: number, style: SeriesStyle, rc: SeriesRenderContext,
  ): void {
    this.calls.push({ items, barSpacing });
    entry.draw(this.series.ctx, items, priceToY, barSpacing, dpr, style, rc);
  }
  public endFrame(): void { this._inner.endFrame(); }
  public overlay2d(): CanvasRenderingContext2D | null { return this._inner.overlay2d(); }
  public destroy(): void { this._inner.destroy(); }
}

interface Rig {
  chart: Chart;
  backends: SeriesOnly[];
  paint(): void;
}

/** Candles over a volume pane, laid out and painted synchronously, `bars` fitted into the plot. */
function rig(bars: readonly Bar[], options: { conflate?: boolean; dpr?: number; conflationFactor?: number; tally?: boolean } = {}): Rig {
  const doc = fakeDocument();
  if (options.tally === true) {
    const make = doc.createElement.bind(doc);
    doc.createElement = ((tag: string) => {
      const el = make(tag) as unknown as { getContext?: () => unknown };
      if (tag === 'canvas') el.getContext = () => new Tally();
      return el;
    }) as typeof doc.createElement;
  }
  const backends: SeriesOnly[] = [];
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => options.dpr ?? 1, shortcuts: false, timeNavigator: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    timeScale: { minBarSpacing: 0.0005 },
    ...(options.conflate === undefined ? {} : { conflate: options.conflate }),
    ...(options.conflationFactor === undefined ? {} : { conflationFactor: options.conflationFactor }),
    ...(options.tally === true ? {} : { renderBackend: () => { const b = new SeriesOnly(); backends.push(b); return b; } }),
  });
  chart.applySize(1000, 600);
  chart.addSeries('candlestick').setData(bars as Bar[]);
  chart.addSeries('histogram', { paneIndex: 1 }).setData(bars.map((b) => ({ time: b.time, open: 0, high: b.volume ?? 0, low: 0, close: b.volume ?? 0 })));
  chart.fitContent();
  const paint = (): void => { chart.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full)); };
  paint();
  return { chart, backends, paint };
}

function marksOf(chart: Chart): number {
  let marks = 0;
  for (const pane of chart.panes()) marks += (pane.base.ctx as unknown as Tally).marks;
  return marks;
}

function resetMarks(chart: Chart): void {
  for (const pane of chart.panes()) (pane.base.ctx as unknown as Tally).marks = 0;
}

/** Every device pixel a fillRect op covered, as `x,y`. */
function coverage(ops: readonly Op[]): Set<string> {
  const out = new Set<string>();
  for (const op of ops) {
    if (op.type !== 'fillRect') continue;
    const [x, y, w, h] = op.args;
    for (let px = x; px < x + w; px++) for (let py = y; py < y + h; py++) out.add(`${px},${py}`);
  }
  return out;
}

describe('the level-of-detail threshold', () => {
  it('is one stick wide: one device pixel under a ratio of two, the whole ratio above it', () => {
    expect(lodColumnWidth(1)).toBe(1);
    expect(lodColumnWidth(1.5)).toBe(1);
    expect(lodColumnWidth(2)).toBe(2);
    expect(lodColumnWidth(3)).toBe(3);
    // The factor widens the column; nothing below one narrows it.
    expect(lodColumnWidth(1, 3)).toBe(3);
    expect(lodColumnWidth(2, 2)).toBe(4);
    expect(lodColumnWidth(1, 0.25)).toBe(1);
    expect(lodColumnWidth(1, Number.NaN)).toBe(1);
    // A line or a column bar is one device pixel at any ratio.
    expect(lodColumnWidth(2, 1, 'line')).toBe(1);
    expect(lodColumnWidth(3, 1, 'column')).toBe(1);
    expect(lodColumnWidth(2, 3, 'column')).toBe(3);
  });

  it('engages under one CSS px at a whole ratio, and never at or above it', () => {
    for (const dpr of [1, 2, 3]) {
      const w = lodColumnWidth(dpr);
      expect(lodActive(1, dpr, w)).toBe(false);
      expect(lodActive(8, dpr, w)).toBe(false);
      expect(lodActive(0.99, dpr, w)).toBe(true);
    }
    // At 1.5 a stick is one device pixel, which 0.7 CSS px (1.05 device px) still clears.
    expect(lodActive(0.7, 1.5, lodColumnWidth(1.5))).toBe(false);
    expect(lodActive(0.6, 1.5, lodColumnWidth(1.5))).toBe(true);
    expect(lodActive(0, 1, 1)).toBe(false);
  });

  it('reduces the built-in types it knows and leaves anything else in full', () => {
    const kinds: Record<string, LodKind | null> = {
      candlestick: 'ohlc', 'hollow-candle': 'ohlc', 'volume-candle': 'ohlc', bar: 'ohlc', 'high-low': 'ohlc', 'hlc-area': 'band',
      line: 'line', 'line-markers': 'line', step: 'line', area: 'line', baseline: 'line',
      column: 'column', histogram: 'column', kagi: null, 'point-figure': null, 'my-custom-style': null,
    };
    for (const [type, kind] of Object.entries(kinds)) expect(lodKind(type), type).toBe(kind);
  });
});

describe('createLodColumns', () => {
  const bar = (time: number, o: number, h: number, l: number, c: number, extra: Partial<Bar> = {}): Bar =>
    ({ time, open: o, high: h, low: l, close: c, ...extra });

  function run(kind: LodKind, dpr: number, factor: number, input: readonly [number, Bar][]): { x: number; bar: Bar }[] {
    const out: { x: number; bar: Bar }[] = [];
    const lod = createLodColumns((x, b) => out.push({ x, bar: { ...b } }));
    lod.begin(kind, dpr, factor);
    for (const [x, b] of input) lod.push(x, b);
    lod.end();
    return out;
  }

  it('merges a column into one OHLC-preserving stick placed on the column', () => {
    const out = run('ohlc', 1, 1, [
      [10.1, bar(1, 10, 12, 9, 11, { volume: 100, oi: 5 })],
      [10.3, bar(2, 11, 15, 8, 14, { volume: 200, color: '#111111' })],
      [10.45, bar(3, 14, 14, 7, 9, { volume: 50, oi: 7, color: '#222222', wickColor: '#333333' })],
      [11.2, bar(4, 9, 10, 8, 10)],
    ]);
    expect(out).toHaveLength(2);
    expect(out[0].x).toBe(10);
    expect(out[0].bar).toMatchObject({ time: 1, open: 10, high: 15, low: 7, close: 9, volume: 350, oi: 7,
      color: '#222222', wickColor: '#333333', borderColor: undefined });
    expect(out[1].x).toBe(11);
    expect(out[1].bar).toMatchObject({ time: 4, open: 9, high: 10, low: 8, close: 10, volume: undefined, oi: undefined });
  });

  it('keeps whitespace and non-finite fields out of the stick, and draws nothing for a column of whitespace', () => {
    const gap = bar(0, NaN, NaN, NaN, NaN);
    const out = run('ohlc', 1, 1, [
      [3.1, gap],
      [3.2, bar(1, 10, 12, 9, 11)],
      [3.3, bar(2, 11, NaN, 8, 12)],
      [4.1, gap],
      [4.2, gap],
    ]);
    expect(out).toHaveLength(1);
    expect(out[0].bar).toMatchObject({ open: 10, high: 12, low: 8, close: 12 });
  });

  it('lays sticks one wick wide at a ratio of two, and centres them in a widened column', () => {
    // dpr 2: a stick is 2 device px; centres at 2.0 and 2.4 media px round to
    // device 4 and 5, whose sticks start at 3 and 4: columns 1 and 2.
    const at2 = run('ohlc', 2, 1, [[2.0, bar(1, 1, 2, 0, 1)], [2.4, bar(2, 1, 2, 0, 1)], [2.6, bar(3, 1, 3, 0, 2)]]);
    expect(at2.map((o) => o.x)).toEqual([1.5, 2.5]);
    // Factor 4 at dpr 1: four-pixel columns, the one-pixel stick one in from
    // the left edge, as near the middle as a whole pixel gets.
    const wide = run('ohlc', 1, 4, [[0.2, bar(1, 1, 2, 0, 1)], [3.4, bar(2, 1, 5, 0, 3)], [4.1, bar(3, 3, 4, 2, 2)]]);
    expect(wide.map((o) => o.x)).toEqual([1, 5]);
    expect(wide[0].bar).toMatchObject({ open: 1, high: 5, low: 0, close: 3 });
  });

  it('puts a stick wider than a pixel in the column holding its middle, so it lands within half a stick of every bar it stands for', () => {
    // At a ratio of three a stick is three device pixels and a column is one
    // stick. Read from the stick's left edge, a bar centred on a column's last
    // pixel went to the column before and was drawn two pixels from where it
    // is drawn in full; at a ratio of four, three.
    for (const dpr of [1, 1.5, 2, 3, 4]) {
      const stick = Math.max(1, Math.floor(dpr));
      for (const spacing of [0.99, 0.8, 0.55, 0.3]) {
        for (const phase of [0, 0.13, 0.37, 0.61, 0.89]) {
          const input: [number, Bar][] = [];
          for (let i = 0; i < 400; i++) input.push([(i + phase) * spacing, bar(i, 1, 2, 0, 1)]);
          const out = run('ohlc', dpr, 1, input);
          // Each stick stands for the bars from its time up to the next stick's.
          for (let k = 0; k < out.length; k++) {
            const centre = Math.round(out[k].x * dpr);
            const end = k + 1 < out.length ? out[k + 1].bar.time : input.length;
            for (let i = out[k].bar.time; i < end; i++) {
              const drift = Math.abs(Math.round(input[i][0] * dpr) - centre);
              expect(drift, `dpr ${dpr} spacing ${spacing} phase ${phase} bar ${i}`).toBeLessThanOrEqual(stick >> 1);
            }
          }
        }
      }
    }
  });

  it('reuses the merged bars from one frame to the next', () => {
    const seen: Bar[][] = [];
    const lod = createLodColumns((_x, b) => seen[seen.length - 1].push(b));
    for (let frame = 0; frame < 2; frame++) {
      seen.push([]);
      lod.begin('ohlc', 1, 1);
      for (let i = 0; i < 40; i++) lod.push(i * 0.25 + frame * 0.1, bar(i, 1, 2 + frame, 0, 1));
      lod.end();
    }
    expect(seen[0].length).toBeGreaterThan(5);
    expect(seen[1].length).toBe(seen[0].length);
    seen[1].forEach((b, i) => expect(b).toBe(seen[0][i]));
    expect(seen[1][0].high).toBe(3);
  });

  it('keeps a line column\'s first, lowest, highest and last value, in order, each once', () => {
    const v = (time: number, c: number): Bar => bar(time, c, c, c, c);
    const out = run('line', 1, 1, [
      [5.0, v(1, 10)], [5.1, v(2, 14)], [5.2, v(3, 8)], [5.3, v(4, 11)], [5.4, v(5, 9)],
      [6.0, v(6, 7)],
      [7.0, v(7, 3)], [7.1, v(8, 3)], [7.2, v(9, 3)],
    ]);
    expect(out.map((o) => o.bar.time)).toEqual([1, 2, 3, 5, 6, 7, 9]);
    // Highest before lowest keeps that order.
    const hl = run('line', 1, 1, [[1.0, v(1, 5)], [1.1, v(2, 3)], [1.2, v(3, 9)], [1.3, v(4, 6)]]);
    expect(hl.map((o) => o.bar.time)).toEqual([1, 2, 3, 4]);
    const lh = run('line', 1, 1, [[1.0, v(1, 5)], [1.1, v(2, 9)], [1.2, v(3, 3)], [1.3, v(4, 6)]]);
    expect(lh.map((o) => o.bar.time)).toEqual([1, 2, 3, 4]);
  });

  it('keeps one whitespace bar where a line breaks, however long the gap', () => {
    const v = (time: number, c: number): Bar => bar(time, c, c, c, c);
    const out = run('line', 1, 1, [
      [1.0, v(1, 10)], [1.2, v(2, 12)], [1.3, v(3, NaN)], [1.4, v(4, 11)],
      [2.0, v(5, NaN)], [3.0, v(6, NaN)], [4.0, v(7, NaN)], [5.0, v(8, 9)],
    ]);
    expect(out.map((o) => o.bar.time)).toEqual([1, 2, 3, 4, 5, 8]);
    expect(Number.isNaN(out[2].bar.close)).toBe(true);
    expect(Number.isNaN(out[4].bar.close)).toBe(true);
  });

  it('keeps an HLC band column\'s first and last bars, its closing extremes, its highest high and lowest low, in order, and a gap once', () => {
    // The close peaks in the middle of the column and the highest high and the
    // lowest low sit on bars whose closes are neither extreme: all six stay.
    const out = run('band', 1, 1, [
      [4.6, bar(1, 10, 11, 9, 10)],
      [4.7, bar(2, 10, 18, 9, 12)],
      [4.8, bar(3, 12, 13, 11, 13)],
      [4.9, bar(4, 13, 13, 2, 11)],
      [5.0, bar(5, 11, 12, 10, 8)],
      [5.1, bar(6, 8, 10, 8, 9)],
      [5.2, bar(7, 9, 10, 8, 9)],
      [5.3, bar(8, NaN, NaN, NaN, NaN)],
      [5.4, bar(9, NaN, NaN, NaN, NaN)],
      [6.0, bar(10, 9, 10, 8, 9)],
    ]);
    expect(out.map((o) => o.bar.time)).toEqual([1, 2, 3, 4, 5, 7, 8, 10]);
    // Real bars at their own x, not a stick on the column.
    expect(out[2].x).toBe(4.8);
    expect(Number.isNaN(out[6].bar.close)).toBe(true);
    // A band column's width is one device pixel at any ratio, like a line's.
    expect(lodColumnWidth(2, 1, 'band')).toBe(1);
  });

  it('keeps a histogram column\'s lowest and highest bars and drops its gaps', () => {
    const v = (time: number, c: number): Bar => bar(time, 0, c, 0, c);
    const out = run('column', 1, 1, [
      [2.0, v(1, 4)], [2.1, v(2, -3)], [2.2, v(3, NaN)], [2.3, v(4, 9)], [2.4, v(5, 1)],
      [3.0, v(6, 2)],
    ]);
    expect(out.map((o) => o.bar.time)).toEqual([2, 4, 6]);
    // A real bar, at its own x, carrying its own colour.
    expect(out[1].x).toBe(2.3);
  });
});

describe('the series pass', () => {
  it('bounds a frame of 200,000 bars by the plot width, by default', () => {
    const bars = walk(200_000);
    const on = rig(bars, { tally: true });
    const plot = on.chart.timeScale.width;
    expect(on.chart.timeScale.barSpacing * 200_000).toBeLessThanOrEqual(plot + 1e-6);
    resetMarks(on.chart);
    on.paint();
    const bounded = marksOf(on.chart);
    // A candle stick and at most two volume columns per device-pixel column,
    // plus the grid, the axes and their labels.
    expect(bounded).toBeLessThanOrEqual(3 * plot + 600);
    expect(bounded).toBeGreaterThan(plot);
    on.chart.destroy();

    const off = rig(bars, { tally: true, conflate: false });
    resetMarks(off.chart);
    off.paint();
    // The opt-out draws every bar: a wick per candle and a column per volume.
    expect(marksOf(off.chart)).toBeGreaterThanOrEqual(400_000);
    off.chart.destroy();
  });

  it('paints the identical op stream with the level of detail on and off above the threshold', () => {
    const bars = walk(3000);
    for (const [dpr, spacings] of [[1, [1, 1.5, 3, 8]], [2, [1, 2.5]], [1.5, [0.7, 1]]] as const) {
      for (const spacing of spacings) {
        const on = rig(bars, { dpr });
        const off = rig(bars, { dpr, conflate: false });
        for (const r of [on, off]) { r.chart.timeScale.setBarSpacing(spacing); r.paint(); }
        for (let p = 0; p < 2; p++) {
          const a = on.backends[p].series.rec.ops;
          const b = off.backends[p].series.rec.ops;
          expect(a.length, `dpr ${dpr} spacing ${spacing} pane ${p}`).toBeGreaterThan(0);
          expect(a, `dpr ${dpr} spacing ${spacing} pane ${p}`).toEqual(b);
          expect(on.backends[p].calls[0].barSpacing).toBe(spacing);
          // The chrome too: base canvas ops, grid and axes and tags included.
          expect((on.chart.panes()[p].base.ctx as unknown as RecordingContext).ops)
            .toEqual((off.chart.panes()[p].base.ctx as unknown as RecordingContext).ops);
        }
        on.chart.destroy();
        off.chart.destroy();
      }
    }
  });

  it('covers every pixel the bars covered, and no other, in each column below the threshold', () => {
    const bars = walk(4000);
    const on = rig(bars);
    const off = rig(bars, { conflate: false });
    for (const r of [on, off]) { r.chart.timeScale.setBarSpacing(0.3); r.paint(); }
    const columns = on.chart.timeScale.width;
    for (let p = 0; p < 2; p++) {
      const lod = on.backends[p].series.rec.ops.filter((op) => op.type === 'fillRect');
      const full = off.backends[p].series.rec.ops.filter((op) => op.type === 'fillRect');
      // Over three bars to a column: one stick per column for the candles,
      // the lowest and highest bar for the volume.
      expect(full.length).toBeGreaterThan(3 * columns);
      expect(lod.length, `pane ${p}`).toBeLessThanOrEqual((p === 0 ? 1 : 2) * (columns + 1));
      expect(coverage(lod), `pane ${p}`).toEqual(coverage(full));
    }
    on.chart.destroy();
    off.chart.destroy();
  });

  it('keeps the envelope at a ratio of two, and sizes merged sticks for their column', () => {
    const bars = walk(4000);
    const on = rig(bars, { dpr: 2 });
    const off = rig(bars, { dpr: 2, conflate: false });
    for (const r of [on, off]) { r.chart.timeScale.setBarSpacing(0.2); r.paint(); }
    const rows = (ops: readonly Op[]): [number, number] => {
      let top = Infinity, bottom = -Infinity;
      for (const op of ops) if (op.type === 'fillRect') { top = Math.min(top, op.args[1]); bottom = Math.max(bottom, op.args[1] + op.args[3]); }
      return [top, bottom];
    };
    const lod = on.backends[0].series.rec.ops;
    expect(rows(lod)).toEqual(rows(off.backends[0].series.rec.ops));
    // Two-pixel sticks tile: every one starts on an even device column.
    const lefts = lod.filter((op) => op.type === 'fillRect').map((op) => op.args[0]);
    expect(lefts.every((x) => x % 2 === 0)).toBe(true);
    expect(new Set(lefts).size).toBe(lefts.length);
    expect(on.backends[0].calls[0].barSpacing).toBe(1);
    // A volume bar is one device pixel at any ratio, so its columns are too:
    // every pixel the bars covered is still covered, none left as a gap.
    const volume = on.backends[1].series.rec.ops;
    const devicePixels = on.chart.timeScale.width * 2;
    expect(volume.filter((op) => op.type === 'fillRect').length).toBeLessThanOrEqual(2 * (devicePixels + 1));
    expect(coverage(volume)).toEqual(coverage(off.backends[1].series.rec.ops));
    on.chart.destroy();
    off.chart.destroy();
  });

  it('honours the factor with wider columns, and the opt-out at any factor', () => {
    const bars = walk(4000);
    const coarse = rig(bars, { conflationFactor: 4 });
    coarse.chart.timeScale.setBarSpacing(2);
    coarse.paint();
    // Two-pixel bars into four-pixel columns: two bars per stick.
    const sticks = coarse.backends[0].calls[0].items;
    expect(sticks.length).toBeLessThanOrEqual(Math.ceil(coarse.chart.timeScale.width / 4) + 1);
    expect(coarse.backends[0].calls[0].barSpacing).toBe(4);
    coarse.chart.destroy();
    const off = rig(bars, { conflationFactor: 4, conflate: false });
    off.chart.timeScale.setBarSpacing(2);
    off.paint();
    expect(off.backends[0].calls[0].items.length).toBeGreaterThan(sticks.length * 1.8);
    off.chart.destroy();
  });
});

describe('the level of detail at the edges', () => {
  it('changes nothing above the threshold at a pixel ratio of 1.25, and covers the same pixels below it', () => {
    const bars = walk(3000);
    // A stick is one device pixel at 1.25, so the threshold is 0.8 CSS px.
    expect(lodActive(0.85, 1.25, lodColumnWidth(1.25))).toBe(false);
    expect(lodActive(0.75, 1.25, lodColumnWidth(1.25))).toBe(true);
    for (const spacing of [0.85, 1, 2.5]) {
      const on = rig(bars, { dpr: 1.25 });
      const off = rig(bars, { dpr: 1.25, conflate: false });
      for (const r of [on, off]) { r.chart.timeScale.setBarSpacing(spacing); r.paint(); }
      for (let p = 0; p < 2; p++) expect(on.backends[p].series.rec.ops, `spacing ${spacing} pane ${p}`).toEqual(off.backends[p].series.rec.ops);
      on.chart.destroy();
      off.chart.destroy();
    }
    const on = rig(bars, { dpr: 1.25 });
    const off = rig(bars, { dpr: 1.25, conflate: false });
    for (const r of [on, off]) { r.chart.timeScale.setBarSpacing(0.3); r.paint(); }
    const candles = on.backends[0].series.rec.ops.filter((op) => op.type === 'fillRect');
    expect(candles.length).toBeLessThan(off.backends[0].series.rec.ops.filter((op) => op.type === 'fillRect').length / 2);
    expect(coverage(candles)).toEqual(coverage(off.backends[0].series.rec.ops));
    on.chart.destroy();
    off.chart.destroy();
  });

  it('keeps every pixel within a pixel of where the bars put it at a ratio of three', () => {
    // A phone's ratio: three-pixel sticks in three-pixel columns. Every pixel
    // the bars paint has a stick pixel in its row at most one column away, and
    // every stick pixel has a bar pixel as near, at spacings either side of
    // one bar to a column.
    const bars = walk(4000);
    const near = (from: Set<string>, to: Set<string>): string[] => {
      const out: string[] = [];
      for (const key of from) {
        const [x, y] = key.split(',').map(Number);
        if (!to.has(`${x},${y}`) && !to.has(`${x - 1},${y}`) && !to.has(`${x + 1},${y}`)) out.push(key);
      }
      return out;
    };
    for (const spacing of [0.99, 0.8, 0.3]) {
      const on = rig(bars, { dpr: 3 });
      const off = rig(bars, { dpr: 3, conflate: false });
      for (const r of [on, off]) { r.chart.timeScale.setBarSpacing(spacing); r.paint(); }
      const lod = coverage(on.backends[0].series.rec.ops), full = coverage(off.backends[0].series.rec.ops);
      expect(on.backends[0].calls[0].items.length).toBeLessThan(off.backends[0].calls[0].items.length);
      expect(near(full, lod).slice(0, 5), `spacing ${spacing}: bar pixels with no stick pixel near`).toEqual([]);
      expect(near(lod, full).slice(0, 5), `spacing ${spacing}: stick pixels with no bar pixel near`).toEqual([]);
      on.chart.destroy();
      off.chart.destroy();
    }
  });

  it('draws an empty series, a single bar and a run of whitespace without a stick to spare', () => {
    const doc = fakeDocument();
    const backends: SeriesOnly[] = [];
    const chart = new Chart(doc.createElement('div'), {
      document: doc, pixelRatio: () => 1, shortcuts: false, timeNavigator: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
      timeScale: { minBarSpacing: 0.0005 },
      renderBackend: () => { const b = new SeriesOnly(); backends.push(b); return b; },
    });
    chart.applySize(1000, 600);
    const bars = walk(5000);
    chart.addSeries('candlestick').setData(bars);
    chart.addSeries('line');
    chart.addSeries('line').setData([bars[2500]]);
    chart.addSeries('histogram').setData(bars.slice(0, 900).map((b) => ({ time: b.time, open: NaN, high: NaN, low: NaN, close: NaN })));
    chart.timeScale.setBarSpacing(0.1);
    chart.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
    const calls = backends[0].calls;
    expect(calls.length).toBe(4);
    expect(calls[0].items.length).toBeGreaterThan(100);
    expect(calls[1].items).toHaveLength(0);
    expect(calls[2].items).toHaveLength(1);
    expect(calls[3].items).toHaveLength(0);
    chart.destroy();
  });

  it('survives the chart being destroyed by a primitive in the middle of a frame', () => {
    const doc = fakeDocument();
    const chart = new Chart(doc.createElement('div'), {
      document: doc, pixelRatio: () => 1, shortcuts: false, timeNavigator: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
      timeScale: { minBarSpacing: 0.0005 },
    });
    chart.applySize(800, 500);
    chart.addSeries('candlestick').setData(walk(4000));
    chart.addSeries('line').setData(walk(4000).map((b) => ({ ...b, close: b.close - 3 })));
    chart.timeScale.setBarSpacing(0.1);
    let armed = false;
    chart.addPrimitive({ zOrder: () => 'bottom', draw: () => { if (armed) { armed = false; chart.destroy(); } } }, 0);
    armed = true;
    expect(() => chart.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full))).not.toThrow();
    expect(armed).toBe(false);
  });
});

describe('an HLC area below the threshold', () => {
  /** The band's fill vertices and the close line's, split out of one series pass. */
  function hlcOps(ops: readonly Op[]): { band: Op[]; close: Op[] } {
    const fill = ops.findIndex((op) => op.type === 'fill');
    return { band: ops.slice(0, fill), close: ops.slice(fill + 1) };
  }

  /** Per device-pixel column: the lowest and highest y of the vertices that land in it. */
  function extremes(ops: readonly Op[]): Map<number, [number, number]> {
    const out = new Map<number, [number, number]>();
    for (const op of ops) {
      if (op.type !== 'moveTo' && op.type !== 'lineTo') continue;
      const [x, y] = op.args;
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      const c = Math.round(x);
      const seen = out.get(c);
      out.set(c, seen === undefined ? [y, y] : [Math.min(seen[0], y), Math.max(seen[1], y)]);
    }
    return out;
  }

  function hlcRig(bars: readonly Bar[], conflate: boolean): { chart: Chart; backend: () => SeriesOnly } {
    const doc = fakeDocument();
    const backends: SeriesOnly[] = [];
    const chart = new Chart(doc.createElement('div'), {
      document: doc, pixelRatio: () => 1, shortcuts: false, timeNavigator: false, conflate,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
      timeScale: { minBarSpacing: 0.0005 },
      renderBackend: () => { const b = new SeriesOnly(); backends.push(b); return b; },
    });
    chart.applySize(1000, 600);
    chart.addSeries('hlc-area').setData(bars as Bar[]);
    chart.timeScale.setBarSpacing(0.045);
    chart.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
    return { chart, backend: () => backends[0] };
  }

  it('keeps every closing peak and trough, the band\'s edges, and a break in the close line at a gap', () => {
    // A stretch with no prices in the middle, as a feed reports a halt.
    const bars = walk(20_000).map((b, i) => (i >= 9000 && i < 10_000 ? { time: b.time } as Bar : b));
    const on = hlcRig(bars, true);
    const off = hlcRig(bars, false);
    const a = hlcOps(on.backend().series.rec.ops), b = hlcOps(off.backend().series.rec.ops);
    // Still reduced: at most six bars to a column, against over twenty to a column drawn in full.
    const columns = on.chart.timeScale.width;
    expect(off.backend().calls[0].items.length).toBeGreaterThan(20 * columns);
    expect(on.backend().calls[0].items.length).toBeLessThanOrEqual(6 * (columns + 1) + 1);
    // The close line reaches the same highest and lowest close in every column
    // as the line through every bar does.
    expect(extremes(a.close)).toEqual(extremes(b.close));
    // The band's top is the column's highest high and its bottom the lowest low.
    const band = (ops: readonly Op[]): string[] => [...extremes(ops)].map(([c, [top, bottom]]) => `${c}:${top}:${bottom}`);
    expect(band(a.band)).toEqual(band(b.band));
    // The close line stops at the gap and starts again after it, as it does in full.
    const pieces = (ops: readonly Op[]): number => ops.filter((op) => op.type === 'moveTo').length;
    expect(pieces(b.close)).toBe(2);
    expect(pieces(a.close)).toBe(pieces(b.close));
    on.chart.destroy();
    off.chart.destroy();
  });
});

describe('a host renderer under a built-in name', () => {
  it('gets every bar, as any custom type does', () => {
    const builtIn = getChartType('candlestick');
    const seen: number[] = [];
    registerChartType('candlestick', { ...builtIn, draw: (...args) => { seen.push(args[1].length); builtIn.draw(...args); } });
    try {
      const bars = walk(4000);
      const r = rig(bars, { conflate: true });
      r.chart.timeScale.setBarSpacing(0.1);
      seen.length = 0;
      r.paint();
      // Every bar in view reaches the host's renderer, not one stick per column.
      expect(seen).toHaveLength(1);
      expect(seen[0]).toBe(bars.length);
      r.chart.destroy();
    } finally {
      registerChartType('candlestick', builtIn);
    }
    // The built-in one, back in place, is reduced again.
    const again = rig(walk(4000), { conflate: true });
    again.chart.timeScale.setBarSpacing(0.1);
    again.paint();
    expect(again.backends[0].calls[0].items.length).toBeLessThanOrEqual(again.chart.timeScale.width + 1);
    again.chart.destroy();
  });
});
