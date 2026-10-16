import { darkTheme } from '../src/theme';
import { describe, it, expect } from 'vitest';
import { getChartType, registeredChartTypes, type SeriesType, type DrawItem } from '../src/model/chart-type-registry';
import type { Bar } from '../src/model/bar';
import { stepPoints, valuePoints } from '../src/render/line';
import { barGeometry, drawColumns } from '../src/render/bars';
import { makeCtx } from './helpers/fake-ctx';

// Base-tier types (point-figure/kagi register only with the transform tier).
const ALL: SeriesType[] = [
  'candlestick', 'hollow-candle', 'volume-candle', 'bar', 'high-low',
  'line', 'line-markers', 'step', 'area', 'hlc-area', 'baseline', 'column', 'histogram',
];

const bar = (time: number, o: number, h: number, l: number, c: number, v = 100): Bar =>
  ({ time, open: o, high: h, low: l, close: c, volume: v });

const items = (bars: Bar[]): DrawItem[] => bars.map((b, i) => ({ x: 10 + i * 10, bar: b }));
const identityY = (v: number): number => 1000 - v; // higher value, smaller y

describe('chart-type registry', () => {
  it('registers all base-tier chart types', () => {
    const reg = registeredChartTypes();
    for (const t of ALL) expect(reg).toContain(t);
    expect(reg.length).toBe(ALL.length);
  });

  it('throws on an unknown type', () => {
    expect(() => getChartType('nope' as SeriesType)).toThrow();
  });

  it('uses type-appropriate autoscale extents', () => {
    const b = bar(0, 10, 20, 5, 15);
    expect(getChartType('candlestick').extents(b, {})).toEqual({ min: 5, max: 20 }); // high/low
    expect(getChartType('line').extents(b, {})).toEqual({ min: 15, max: 15 }); // close only
    expect(getChartType('column').extents(b, { base: 0 })).toEqual({ min: 0, max: 15 }); // base..close
  });
});

describe('line geometry (pure)', () => {
  it('valuePoints projects close to screen points', () => {
    const pts = valuePoints(items([bar(0, 1, 1, 1, 12), bar(1, 1, 1, 1, 8)]), identityY);
    expect(pts).toEqual([{ x: 10, y: 988 }, { x: 20, y: 992 }]);
  });

  it('stepPoints produces 2N-1 points (HV staircase)', () => {
    const pts = stepPoints([{ x: 0, y: 0 }, { x: 10, y: 5 }, { x: 20, y: 3 }]);
    expect(pts).toHaveLength(5);
    expect(pts[1]).toEqual({ x: 10, y: 0 }); // horizontal first
    expect(pts[2]).toEqual({ x: 10, y: 5 }); // then vertical
  });
});

describe('bar geometry (pure)', () => {
  it('marks up/down and projects O/H/L/C', () => {
    const g = barGeometry({ x: 5, bar: bar(0, 10, 12, 9, 11) }, identityY, 1);
    expect(g.up).toBe(true);
    expect(g.yHigh).toBe(988); // 1000-12
    expect(g.yLow).toBe(991); // 1000-9
  });
});

describe('renderers draw expected primitives (recording context)', () => {
  const bs = 8, dpr = 1;
  const data = items([bar(0, 10, 12, 9, 11), bar(1, 11, 13, 10, 10), bar(2, 10, 11, 8, 9)]);

  it('candlestick fills one body per bar (+ wicks)', () => {
    const { ctx, rec } = makeCtx();
    getChartType('candlestick').draw(ctx, data, identityY, bs, dpr, {}, { plotHeight: 1000, maxVolume: 100, theme: darkTheme });
    // 3 bodies + 3 wicks = 6 fillRects
    expect(rec.count('fillRect')).toBe(6);
  });

  it('hollow candle outlines the up body (strokeRect)', () => {
    const { ctx, rec } = makeCtx();
    getChartType('hollow-candle').draw(ctx, [data[0]], identityY, bs, dpr, {}, { plotHeight: 1000, maxVolume: 100, theme: darkTheme });
    expect(rec.count('strokeRect')).toBeGreaterThanOrEqual(1); // bar 0 is up: hollow
  });

  it('column draws one rect per bar', () => {
    const { ctx, rec } = makeCtx();
    getChartType('column').draw(ctx, data, identityY, bs, dpr, { base: 0 }, { plotHeight: 1000, maxVolume: 100, theme: darkTheme });
    expect(rec.count('fillRect')).toBe(3);
  });

  it('ohlc bar draws 3 rects per bar; high-low draws 1', () => {
    const a = makeCtx();
    getChartType('bar').draw(a.ctx, data, identityY, bs, dpr, {}, { plotHeight: 1000, maxVolume: 100, theme: darkTheme });
    expect(a.rec.count('fillRect')).toBe(9); // 3 bars × (vertical + open tick + close tick)

    const b = makeCtx();
    getChartType('high-low').draw(b.ctx, data, identityY, bs, dpr, {}, { plotHeight: 1000, maxVolume: 100, theme: darkTheme });
    expect(b.rec.count('fillRect')).toBe(3); // vertical only
  });

  it('line strokes a single polyline over N points', () => {
    const { ctx, rec } = makeCtx();
    getChartType('line').draw(ctx, data, identityY, bs, dpr, { color: '#fff' }, { plotHeight: 1000, maxVolume: 100, theme: darkTheme });
    expect(rec.count('moveTo')).toBe(1);
    expect(rec.count('lineTo')).toBe(2); // N-1 segments
    expect(rec.count('stroke')).toBe(1);
  });

  it('line-markers adds a dot per point', () => {
    const { ctx, rec } = makeCtx();
    getChartType('line-markers').draw(ctx, data, identityY, bs, dpr, {}, { plotHeight: 1000, maxVolume: 100, theme: darkTheme });
    expect(rec.count('arc')).toBe(3);
  });

  it('every registered type draws without error', () => {
    for (const t of ALL) {
      const { ctx } = makeCtx();
      expect(() => getChartType(t).draw(ctx, data, identityY, bs, dpr, getChartType(t).defaultStyle, { plotHeight: 1000, maxVolume: 100, theme: darkTheme })).not.toThrow();
    }
  });
});

describe('column per-bar colour', () => {
  it('honours bar.color over the up/down pair, as the histogram renderer does', () => {
    // The indicator registry documents colorBy as supported by both histogram
    // and column. Column ignored it, so every Chop Zone / Awesome Oscillator
    // bar painted one colour regardless of what the descriptor computed.
    const { ctx, rec } = makeCtx();
    const items = [
      { x: 10, bar: { time: 1, open: 0, high: 1, low: 0, close: 1, color: '#123456' } },
      { x: 20, bar: { time: 2, open: 0, high: 1, low: 0, close: 1 } },
    ];
    drawColumns(ctx, items, (v) => 100 - v * 10, 8, 1, { base: 0, upColor: '#aaaaaa' });
    const rects = rec.ops.filter((o) => o.type === 'fillRect');
    expect(rects).toHaveLength(2);
    expect(rects[0].fillStyle).toBe('#123456'); // per-bar colour wins
    expect(rects[1].fillStyle).toBe('#aaaaaa'); // falls back to the up colour
  });
});
