import { describe, it, expect } from 'vitest';
import { darkTheme, lightTheme, type ChartTheme } from '../src/theme';
import { getChartType, type DrawItem, type SeriesRenderContext } from '../src/model/chart-type-registry';
import { verticalGradient, withAlpha as fromModule } from '../src/render/gradient';
import { withAlpha, fromGradient } from '../src/index';
import type { Bar } from '../src/model/bar';
import { makeCtx } from './helpers/fake-ctx';

const bar = (t: number, o: number, h: number, l: number, c: number): Bar => ({ time: t, open: o, high: h, low: l, close: c, volume: 100 });
const data: DrawItem[] = [bar(0, 10, 12, 9, 11), bar(1, 11, 13, 10, 12)].map((b, i) => ({ x: 10 + i * 10, bar: b }));
const toY = (v: number): number => 1000 - v;
const rc = (theme: ChartTheme): SeriesRenderContext => ({ plotHeight: 1000, maxVolume: 100, theme });

describe('theme presets', () => {
  it('expose a complete palette', () => {
    const keys: (keyof ChartTheme)[] = ['background', 'grid', 'upColor', 'downColor', 'lineColor', 'areaTopColor', 'buy', 'sell', 'crosshair'];
    for (const k of keys) {
      expect(typeof darkTheme[k]).toBe('string');
      expect(typeof lightTheme[k]).toBe('string');
    }
    expect(darkTheme.background).not.toBe(lightTheme.background);
  });
});

describe('theme drives series colors', () => {
  it('candlestick uses the theme up color for an up candle body', () => {
    const customUp = '#123456';
    const theme: ChartTheme = { ...darkTheme, upColor: customUp };
    const { ctx, rec } = makeCtx();
    getChartType('candlestick').draw(ctx, [data[0]], toY, 8, 1, {}, rc(theme));
    // an up candle (close>open): at least one fillRect uses the themed up color
    expect(rec.ops.some((o) => o.type === 'fillRect' && o.fillStyle === customUp)).toBe(true);
  });

  it('a per-series style overrides the theme', () => {
    const { ctx, rec } = makeCtx();
    getChartType('candlestick').draw(ctx, [data[0]], toY, 8, 1, { upColor: '#abcdef' }, rc(darkTheme));
    expect(rec.ops.some((o) => o.type === 'fillRect' && o.fillStyle === '#abcdef')).toBe(true);
  });
});

describe('gradient fills', () => {
  it('verticalGradient creates and caches a gradient per context', () => {
    const { ctx, rec } = makeCtx();
    const g1 = verticalGradient(ctx, 400, '#fff', '#0000');
    const g2 = verticalGradient(ctx, 400, '#fff', '#0000'); // same key: cached
    expect(g1).toBe(g2);
    expect(rec.count('createLinearGradient')).toBe(1); // only created once
  });

  it('area renderer fills with a linear gradient', () => {
    const { ctx, rec } = makeCtx();
    getChartType('area').draw(ctx, data, toY, 8, 1, {}, rc(darkTheme));
    expect(rec.count('createLinearGradient')).toBeGreaterThanOrEqual(1);
  });

  it('baseline renderer clips and fills two gradient regions', () => {
    const { ctx, rec } = makeCtx();
    getChartType('baseline').draw(ctx, data, toY, 8, 1, { baseValue: 11 }, rc(darkTheme));
    expect(rec.count('clip')).toBeGreaterThanOrEqual(2); // above + below base
  });
});

// ---------------------------------------------------------------------------
// The colour helpers an indicator author reaches for. Imported from the package
// entry rather than the module, because being reachable is half the feature: a
// helper only `src/render/gradient.ts` can see leaves every descriptor
// hand-rolling its own rgba string, which is what these replace.
// ---------------------------------------------------------------------------

describe('colour helpers', () => {
  it('re-exports withAlpha from one import path', () => {
    expect(fromModule).toBe(withAlpha);
    expect(withAlpha('#ff0000', 0.5)).toBe('rgba(255,0,0,0.5)');
    expect(withAlpha('#abc', 1)).toBe('rgba(170,187,204,1)');
    expect(withAlpha('not a colour', 0.5)).toBe('not a colour');
  });

  it('blends the endpoints by where the value sits in the range', () => {
    expect(fromGradient(0, 0, 10, '#000000', '#ffffff')).toBe('rgba(0,0,0,1)');
    expect(fromGradient(5, 0, 10, '#000000', '#ffffff')).toBe('rgba(128,128,128,1)');
    expect(fromGradient(10, 0, 10, '#000000', '#ffffff')).toBe('rgba(255,255,255,1)');
  });

  it('clamps outside the range instead of running past the endpoints', () => {
    expect(fromGradient(-40, 0, 10, '#000000', '#ffffff')).toBe('rgba(0,0,0,1)');
    expect(fromGradient(999, 0, 10, '#000000', '#ffffff')).toBe('rgba(255,255,255,1)');
  });

  it('lands a not-available value on the low colour, never on NaN', () => {
    // Canvas ignores an unparseable fillStyle and silently keeps the previous
    // one, so an rgba(NaN,...) would paint the neighbouring bar's colour rather
    // than fail where it could be seen.
    const c = fromGradient(NaN, 0, 10, '#000000', '#ffffff');
    expect(c).toBe('rgba(0,0,0,1)');
    expect(c).not.toContain('NaN');
  });

  it('survives a zero-width and a descending range', () => {
    expect(fromGradient(5, 5, 5, '#000000', '#ffffff')).toBe('rgba(0,0,0,1)');
    expect(fromGradient(6, 5, 5, '#000000', '#ffffff')).toBe('rgba(255,255,255,1)');
    // min above max reads as an inverted scale, which is how a descending
    // measure (a rank, a drawdown) states itself.
    expect(fromGradient(2, 10, 0, '#000000', '#ffffff')).toBe('rgba(204,204,204,1)');
  });

  it('blends alpha as well as colour, from any notation the engine parses', () => {
    expect(fromGradient(0.5, 0, 1, '#00000000', '#ffffffff')).toBe('rgba(128,128,128,0.5)');
    expect(fromGradient(0.5, 0, 1, 'rgb(0,0,0)', 'rgba(255,255,255,0.5)')).toBe('rgba(128,128,128,0.75)');
    expect(fromGradient(0.5, 0, 1, '#f00', '#00f')).toBe('rgba(128,0,128,1)');
  });

  it('falls back to the low colour when an endpoint cannot be parsed', () => {
    expect(fromGradient(0.5, 0, 1, 'not a colour', '#ffffff')).toBe('not a colour');
  });
});
