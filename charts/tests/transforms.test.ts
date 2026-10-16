import { darkTheme } from '../src/theme';
import { describe, it, expect } from 'vitest';
import '../src/transform/index'; // side effect: registers point-figure & kagi renderers
import { runTransform, ensureIncreasingTimes } from '../src/transform/transform';
import { HeikinAshiTransform } from '../src/transform/heikin-ashi';
import { RenkoTransform } from '../src/transform/renko';
import { RangeBarsTransform } from '../src/transform/range-bars';
import { LineBreakTransform } from '../src/transform/line-break';
import { PointFigureTransform, type PointFigureColumn } from '../src/transform/point-figure';
import { KagiTransform } from '../src/transform/kagi';
import { getChartType, type DrawItem } from '../src/model/chart-type-registry';
import type { Bar } from '../src/model/bar';
import { makeCtx } from './helpers/fake-ctx';

let T = 1000;
const closes = (cs: number[]): Bar[] => cs.map((c) => ({ time: T++, open: c, high: c + 0.0, low: c - 0.0, close: c }));
const ohlc = (o: number, h: number, l: number, c: number, t = T++): Bar => ({ time: t, open: o, high: h, low: l, close: c });
const oc = (b: Bar): [number, number] => [b.open, b.close];

describe('ensureIncreasingTimes', () => {
  it('bumps colliding times to keep one logical index per element', () => {
    const out = ensureIncreasingTimes([
      { time: 100, open: 1, high: 1, low: 1, close: 1 },
      { time: 100, open: 2, high: 2, low: 2, close: 2 },
      { time: 100, open: 3, high: 3, low: 3, close: 3 },
    ]);
    expect(out.map((b) => b.time)).toEqual([100, 101, 102]);
  });
});

describe('Heikin Ashi', () => {
  it('applies the HA formula (first bar seeds haOpen)', () => {
    const out = runTransform(new HeikinAshiTransform(), [ohlc(10, 12, 8, 11, 1)]);
    expect(out[0]).toMatchObject({ open: 10.5, close: 10.25, high: 12, low: 8 });
  });
  it('is 1:1 with input bars', () => {
    const bars = [ohlc(10, 12, 8, 11, 1), ohlc(11, 13, 9, 10, 2), ohlc(10, 11, 9, 10, 3)];
    expect(runTransform(new HeikinAshiTransform(), bars)).toHaveLength(3);
  });
});

describe('Renko', () => {
  it('emits one brick per box-size move, with directions', () => {
    T = 1;
    const out = runTransform(new RenkoTransform({ boxSize: 1 }), closes([100, 100.5, 102, 101, 98.5]));
    expect(out).toHaveLength(5); // 2 up, 1 down, 2 down
    expect(out[0].close).toBeGreaterThan(out[0].open); // up brick
    expect(out[2].close).toBeLessThan(out[2].open); // down brick
  });

  it('completed bricks are stable as more data arrives (incremental == batch prefix)', () => {
    T = 1; const prefix = runTransform(new RenkoTransform({ boxSize: 1 }), closes([100, 100.5, 102]));
    T = 1; const full = runTransform(new RenkoTransform({ boxSize: 1 }), closes([100, 100.5, 102, 101, 98.5]));
    expect(prefix.map(oc)).toEqual(full.slice(0, prefix.length).map(oc));
  });
});

describe('Range bars', () => {
  it('completes a bar when high-low reaches the range', () => {
    T = 1;
    const out = runTransform(new RangeBarsTransform({ range: 2 }), closes([10, 11, 12, 9, 9.5]));
    expect(out).toHaveLength(2); // one completed (10->12) + flush of the partial
    expect(out[0].high - out[0].low).toBeGreaterThanOrEqual(2);
  });
});

describe('Line Break', () => {
  it('forms a new line only on a break of the prior N lines', () => {
    T = 1;
    const out = runTransform(new LineBreakTransform({ lines: 3 }), closes([10, 11, 9, 12, 8]));
    expect(out).toHaveLength(4);
  });
});

describe('Point & Figure', () => {
  const cols = (out: Bar[]): PointFigureColumn[] => out as PointFigureColumn[];

  it('emits columns on reversals with X/O direction', () => {
    T = 1;
    const out = runTransform(new PointFigureTransform({ boxSize: 1, reversal: 3 }), closes([100, 101, 102, 103, 99]));
    expect(out).toHaveLength(2); // completed X column + flushed O column
    expect(out[0].close).toBeGreaterThanOrEqual(out[0].open); // X (up)
    expect(out[1].close).toBeLessThan(out[1].open); // O (down)
  });

  it('emits no phantom zero-height column when the first move is down', () => {
    T = 1;
    const out = runTransform(new PointFigureTransform({ boxSize: 1, reversal: 3 }), closes([100, 99, 98, 96, 95]));
    expect(out).toHaveLength(1); // one O column, no leading phantom
    for (const c of out) expect(c.high).toBeGreaterThan(c.low);
    expect(out[0].close).toBeLessThan(out[0].open); // O (down)
  });

  it('never emits a degenerate column in either opening direction', () => {
    for (const series of [[100, 99, 96, 95], [100, 101, 104, 105], [100, 100, 100]]) {
      T = 1;
      const out = runTransform(new PointFigureTransform({ boxSize: 1, reversal: 3 }), closes(series));
      for (const c of cols(out)) {
        expect(c.high).toBeGreaterThan(c.low);
        expect(c.boxes).toBeGreaterThanOrEqual(1);
      }
    }
  });

  // Flat closes, wide intrabar range: 'close' sees nothing, 'hl' builds columns.
  const swings: Bar[] = [
    ohlc(100, 100, 100, 100, 1),
    ohlc(100, 110, 100, 100, 2),
    ohlc(100, 100, 90, 100, 3),
    ohlc(100, 112, 100, 100, 4),
  ];

  it('hl method (default) reads the bar range, not just the close', () => {
    const out = runTransform(new PointFigureTransform({ boxSize: 1, reversal: 3 }), swings);
    expect(out.length).toBeGreaterThan(0);
  });

  it('close method ignores intrabar range', () => {
    const out = runTransform(new PointFigureTransform({ boxSize: 1, reversal: 3, method: 'close' }), swings);
    expect(out).toHaveLength(0);
  });

  it('columns carry the box size and box count they were built with', () => {
    T = 1;
    const out = cols(runTransform(new PointFigureTransform({ boxSize: 1, reversal: 3 }), closes([100, 101, 102, 103, 99])));
    for (const c of out) {
      expect(c.boxSize).toBe(1);
      expect(c.boxes).toBe(Math.round((c.high - c.low) / c.boxSize));
    }
  });

  it('percent mode scales the box with price', () => {
    T = 1;
    const rising: number[] = [];
    for (let i = 0; i < 60; i++) rising.push(100 + i * 8 * (i % 2 === 0 ? 1 : 0.9));
    const out = cols(runTransform(new PointFigureTransform({ mode: 'percent', percent: 2, reversal: 3 }), closes(rising)));
    expect(out.length).toBeGreaterThan(1);
    for (const c of out) expect(c.boxSize).toBeGreaterThan(0);
    expect(out[out.length - 1].boxSize).toBeGreaterThan(out[0].boxSize);
  });

  it('atr mode resolves a positive box per column', () => {
    const bars: Bar[] = [];
    for (let i = 0; i < 80; i++) {
      const base = 100 + Math.sin(i / 3) * 12;
      bars.push(ohlc(base, base + 2, base - 2, base, 1000 + i));
    }
    const out = cols(runTransform(new PointFigureTransform({ mode: 'atr', atrPeriod: 14, reversal: 3 }), bars));
    expect(out.length).toBeGreaterThan(0);
    for (const c of out) {
      expect(c.boxSize).toBeGreaterThan(0);
      expect(Number.isFinite(c.boxSize)).toBe(true);
    }
  });

  it('rejects an unusable box configuration', () => {
    expect(() => new PointFigureTransform({ boxSize: 0 })).toThrow(/boxSize/);
    expect(() => new PointFigureTransform({ mode: 'percent', percent: 0 })).toThrow(/percent/);
  });
});

describe('Kagi', () => {
  it('emits a vertex per reversal and encodes thickness in volume', () => {
    T = 1;
    const out = runTransform(new KagiTransform({ reversal: 2 }), closes([10, 13, 11, 14, 9]));
    expect(out).toHaveLength(4);
    expect(out.map((b) => b.time)).toEqual([...out].map((b) => b.time).sort((a, b) => a - b)); // strictly increasing
    expect([0, 1]).toContain(out[0].volume); // thickness flag
  });
});

describe('Family-B rendering (recording context)', () => {
  const toY = (v: number): number => 1000 - v;
  it('point-figure stacks glyphs (strokes) using boxSize', () => {
    T = 1;
    const cols = runTransform(new PointFigureTransform({ boxSize: 1, reversal: 3 }), closes([100, 101, 102, 103, 99]));
    const items: DrawItem[] = cols.map((b, i) => ({ x: 10 + i * 20, bar: b }));
    const { ctx, rec } = makeCtx();
    getChartType('point-figure').draw(ctx, items, toY, 20, 1, { boxSize: 1, upColor: '#0a0', downColor: '#a00' }, { plotHeight: 1000, maxVolume: 0, theme: darkTheme });
    expect(rec.count('stroke')).toBeGreaterThan(0);
  });

  // Regression: the renderer used to walk rows with `level += box`, so 30 steps
  // of 0.05 landed on 101.49999999999991 and the top glyph was duplicated.
  it('point-figure draws exactly one glyph per box with a fractional box size', () => {
    const column: PointFigureColumn = {
      time: 1, open: 100, close: 101.5, high: 101.5, low: 100, boxSize: 0.05, boxes: 30,
    };
    const { ctx, rec } = makeCtx();
    getChartType('point-figure').draw(ctx, [{ x: 10, bar: column }], toY, 20, 1, {}, { plotHeight: 1000, maxVolume: 0, theme: darkTheme });
    expect(rec.count('stroke')).toBe(30);
  });

  it('point-figure reads the column box size over a mismatched style boxSize', () => {
    const column: PointFigureColumn = {
      time: 1, open: 100, close: 115, high: 115, low: 100, boxSize: 0.5, boxes: 30,
    };
    const { ctx, rec } = makeCtx();
    // style says 5 (wrong); the column says 0.5 and must win.
    getChartType('point-figure').draw(ctx, [{ x: 10, bar: column }], toY, 20, 1, { boxSize: 5 }, { plotHeight: 1000, maxVolume: 0, theme: darkTheme });
    expect(rec.count('stroke')).toBe(30);
  });

  it('point-figure culls glyph rows outside the plot', () => {
    const column: PointFigureColumn = {
      time: 1, open: 100, close: 115, high: 115, low: 100, boxSize: 0.5, boxes: 30,
    };
    const { ctx, rec } = makeCtx();
    // toY = 1000 - v maps the column to y 900..885; a 895px plot clips the lower rows.
    getChartType('point-figure').draw(ctx, [{ x: 10, bar: column }], toY, 20, 1, {}, { plotHeight: 895, maxVolume: 0, theme: darkTheme });
    expect(rec.count('stroke')).toBe(21);
  });

  it('kagi connects vertices with stepped strokes', () => {
    T = 1;
    const verts = runTransform(new KagiTransform({ reversal: 2 }), closes([10, 13, 11, 14, 9]));
    const items: DrawItem[] = verts.map((b, i) => ({ x: 10 + i * 20, bar: b }));
    const { ctx, rec } = makeCtx();
    getChartType('kagi').draw(ctx, items, toY, 20, 1, { thickColor: '#0a0', thinColor: '#a00' }, { plotHeight: 1000, maxVolume: 0, theme: darkTheme });
    expect(rec.count('stroke')).toBe(items.length - 1); // one stepped segment per gap
  });
});
