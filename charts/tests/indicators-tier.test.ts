import { describe, it, expect } from 'vitest';
import '../src/indicators/index'; // side effect: registers the built-ins
import {
  registeredIndicators,
  getIndicator,
  hasIndicator,
  indicatorDefaults,
  registerIndicator,
  sourceValue,
  sourceValues,
  INDICATOR_SOURCES,
} from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import { IndicatorInstance, type IndicatorHost } from '../src/model/indicator-instance';
import { BUILTIN_INDICATORS } from '../src/indicators/index';
import { createTier2Indicator, type Tier2Point } from '../src/indicators/external';
import { sma, wma, rma, stdev, highest, lowest } from '../src/indicators/calc';
import { makeCtx } from './helpers/fake-ctx';
import { IndicatorFill } from '../src/primitives/indicator-fill';
import { drawHistogram } from '../src/render/histogram';
import { toBar } from '../src/model/bar';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { DataLayer } from '../src/model/data-layer';
import { darkTheme } from '../src/theme';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';

/** Minimal render context for the fill primitive's geometry. */
function fillRc(): PrimitiveRenderContext {
  const priceScale = new PriceScale();
  priceScale.setHeight(400);
  priceScale.setPriceRange({ min: 0, max: 20 });
  const timeScale = new TimeScale();
  timeScale.setWidth(600);
  return {
    timeScale, priceScale, dataLayer: new DataLayer(), plotWidth: 600, plotHeight: 400,
    priceAxisWidth: 56, dpr: 1, theme: darkTheme,
  };
}
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';
import type { SeriesApi } from '../src/model/series';
import type { PriceLine } from '../src/primitives/price-line';

const bars = (n: number, f: (i: number) => number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = f(i);
    return { time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 100 + i };
  });

const wave = (n = 120): Bar[] => bars(n, (i) => 100 + Math.sin(i / 5) * 10 + i * 0.05);

describe('calc helpers', () => {
  it('sma averages the trailing window and leaves warmup NaN', () => {
    const out = sma([1, 2, 3, 4, 5], 3);
    expect(out.slice(0, 2).every(Number.isNaN)).toBe(true);
    expect(out.slice(2)).toEqual([2, 3, 4]);
  });

  it('wma weights the most recent value highest', () => {
    // (1*1 + 2*2 + 3*3) / 6 = 2.333…
    expect(wma([1, 2, 3], 3)[2]).toBeCloseTo(14 / 6, 10);
  });

  it('rma seeds with the SMA then carries Wilder smoothing', () => {
    const out = rma([2, 4, 6, 8], 2);
    expect(out[1]).toBe(3); // (2+4)/2
    expect(out[2]).toBe((3 * 1 + 6) / 2);
  });

  it('stdev is zero on a flat series', () => {
    expect(stdev([5, 5, 5, 5], 3)[3]).toBe(0);
  });

  it('highest / lowest track the rolling window', () => {
    expect(highest([1, 9, 3, 2], 2)[1]).toBe(9);
    expect(lowest([1, 9, 3, 2], 2)[3]).toBe(2);
  });
});

describe('indicator registry', () => {
  it('registers all 112 built-ins', () => {
    expect(BUILTIN_INDICATORS).toHaveLength(112);
    const ids = registeredIndicators().map((d) => d.id);
    for (const d of BUILTIN_INDICATORS) expect(ids).toContain(d.id);
  });

  it('has no duplicate ids', () => {
    const ids = BUILTIN_INDICATORS.map((d) => d.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('throws a tier-aware message for an unknown id', () => {
    expect(() => getIndicator('nope')).toThrow(/openalgo-charts\/indicators/);
    expect(hasIndicator('nope')).toBe(false);
  });

  it('builds defaults from the declared inputs', () => {
    const d = indicatorDefaults(getIndicator('macd'));
    expect(d).toMatchObject({ fastPeriod: 12, slowPeriod: 26, signalPeriod: 9 });
  });

  it('reads every price source', () => {
    const b: Bar = { time: 1, open: 10, high: 20, low: 0, close: 16, volume: 7 };
    expect(sourceValue(b, 'open')).toBe(10);
    expect(sourceValue(b, 'high')).toBe(20);
    expect(sourceValue(b, 'low')).toBe(0);
    expect(sourceValue(b, 'close')).toBe(16);
    expect(sourceValue(b, 'hl2')).toBe(10);
    expect(sourceValue(b, 'hlc3')).toBe(12);
    expect(sourceValue(b, 'ohlc4')).toBe(11.5);
    expect(sourceValue(b, 'volume')).toBe(7);
    expect(sourceValues([b], 'close')).toEqual([16]);
  });

  it('publishes the canonical source option list for settings UIs', () => {
    expect(INDICATOR_SOURCES.map((s) => s.value)).toContain('hlc3');
  });
});

describe('built-in descriptors', () => {
  const data = wave();

  it('every descriptor returns a full-length column for each declared plot', () => {
    for (const d of BUILTIN_INDICATORS) {
      const values = d.calc(data, indicatorDefaults(d), {});
      for (const plot of d.plots) {
        const col = values[plot.key];
        expect(col, `${d.id}.${plot.key} missing`).toBeDefined();
        expect(col.length, `${d.id}.${plot.key} length`).toBe(data.length);
      }
    }
  });

  it('every descriptor emits only finite numbers or null', () => {
    for (const d of BUILTIN_INDICATORS) {
      const values = d.calc(data, indicatorDefaults(d), {});
      for (const plot of d.plots) {
        for (const v of values[plot.key]) {
          expect(v === null || Number.isFinite(v), `${d.id}.${plot.key} emitted ${v}`).toBe(true);
        }
      }
    }
  });

  it('every descriptor survives empty and single-bar input', () => {
    for (const d of BUILTIN_INDICATORS) {
      for (const input of [[], data.slice(0, 1)]) {
        const values = d.calc(input, indicatorDefaults(d), {});
        for (const plot of d.plots) expect(values[plot.key].length).toBe(input.length);
      }
    }
  });

  it('SMA matches a hand-computed mean', () => {
    const flat = bars(5, (i) => i + 1); // closes 1..5
    const out = getIndicator('sma').calc(flat, { length: 3, source: 'close' }, {});
    expect(out.ma[4]).toBe(4); // (3+4+5)/3
  });

  it('MACD histogram is macd - signal', () => {
    const out = getIndicator('macd').calc(data, indicatorDefaults(getIndicator('macd')), {});
    const i = data.length - 1;
    expect(out.histogram[i]).toBeCloseTo((out.macd[i] as number) - (out.signal[i] as number), 10);
  });

  it('Bollinger bands straddle the basis by stdDev multiples', () => {
    const d = getIndicator('bollinger');
    const out = d.calc(data, { length: 20, stdDev: 2, source: 'close' }, {});
    const i = data.length - 1;
    const basis = out.basis[i] as number;
    expect(out.upper[i] as number).toBeGreaterThan(basis);
    expect(out.lower[i] as number).toBeLessThan(basis);
    expect((out.upper[i] as number) - basis).toBeCloseTo(basis - (out.lower[i] as number), 10);
  });

  it('RSI and Stochastic stay within 0..100 and declare that range', () => {
    for (const id of ['rsi', 'stochastic', 'mfi']) {
      const d = getIndicator(id);
      const out = d.calc(data, indicatorDefaults(d), {});
      for (const plot of d.plots) {
        for (const v of out[plot.key]) {
          if (v === null) continue;
          expect(v).toBeGreaterThanOrEqual(0);
          expect(v).toBeLessThanOrEqual(100);
        }
      }
      expect(d.range?.(indicatorDefaults(d))).toEqual({ min: 0, max: 100 });
    }
  });

  it('ADX +DI/-DI stay within 0..100', () => {
    const d = getIndicator('adx');
    const out = d.calc(data, indicatorDefaults(d), {});
    for (const key of ['plusDi', 'minusDi', 'adx']) {
      for (const v of out[key]) {
        if (v === null) continue;
        expect(v).toBeGreaterThanOrEqual(0);
        expect(v).toBeLessThanOrEqual(100);
      }
    }
  });

  it('OBV adds volume on up closes and subtracts on down closes', () => {
    const seq: Bar[] = [
      { time: 1, open: 10, high: 10, low: 10, close: 10, volume: 5 },
      { time: 2, open: 10, high: 11, low: 10, close: 11, volume: 7 }, // up: +7
      { time: 3, open: 11, high: 11, low: 9, close: 9, volume: 4 },   // down: -4
      { time: 4, open: 9, high: 9, low: 9, close: 9, volume: 9 },     // flat: 0
    ];
    expect(getIndicator('obv').calc(seq, {}, {}).obv).toEqual([0, 7, 3, 3]);
  });

  it('A/D contributes nothing on a doji bar (high === low)', () => {
    const seq: Bar[] = [
      { time: 1, open: 10, high: 10, low: 10, close: 10, volume: 100 }, // doji
      { time: 2, open: 10, high: 12, low: 8, close: 12, volume: 10 },   // full accumulation
    ];
    const out = getIndicator('adl').calc(seq, {}, {}).adl;
    expect(out[0]).toBe(0);
    expect(out[1]).toBe(10);
  });

  it('VWAP resets on a new IST session and is volume-weighted', () => {
    const d = getIndicator('vwap');
    // 2023-11-14 IST 18:00 and 2023-11-15 IST 18:00: different IST days.
    const day1 = 1700000000;
    const seq: Bar[] = [
      { time: day1, open: 100, high: 100, low: 100, close: 100, volume: 10 },
      { time: day1 + 60, open: 200, high: 200, low: 200, close: 200, volume: 10 },
      { time: day1 + 86400, open: 50, high: 50, low: 50, close: 50, volume: 1 },
    ];
    const session = d.calc(seq, { anchor: 'session', source: 'close' }, {}).vwap;
    expect(session[1]).toBeCloseTo(150, 10); // (100*10 + 200*10) / 20
    expect(session[2]).toBeCloseTo(50, 10);  // reset on the new IST day
    const cont = d.calc(seq, { anchor: 'continuous', source: 'close' }, {}).vwap;
    expect(cont[2]).toBeCloseTo((100 * 10 + 200 * 10 + 50) / 21, 10);
  });

  it('Parabolic SAR flips sides and stays near price', () => {
    const trend = bars(60, (i) => 100 + i);
    const out = getIndicator('parabolic-sar').calc(trend, indicatorDefaults(getIndicator('parabolic-sar')), {});
    const last = out.sar[trend.length - 1] as number;
    expect(last).toBeLessThan(trend[trend.length - 1].close); // trailing below an uptrend
  });

  it('Ichimoku displaces the spans forward and the lagging span back', () => {
    const d = getIndicator('ichimoku');
    const out = d.calc(data, { ...indicatorDefaults(d), displacement: 26 }, {});
    // Chikou is the close shifted back, so index i holds the close of i+26.
    expect(out.lagging[0]).toBeCloseTo(data[26].close, 10);
    // Senkou spans are shifted forward, so the first 26 slots are empty.
    expect(out.spanA[0]).toBeNull();
  });
});

function fakeHost(source: Bar[]): {
  host: IndicatorHost; series: Map<string, unknown[]>; removed: string[]; levels: number;
  markers: unknown[][]; markerLayers: number; markersRemoved: number;
  tableLayers: number; tablesRemoved: number; tableRows: unknown[][];
} {
  const series = new Map<string, unknown[]>();
  const removed: string[] = [];
  const markers: unknown[][] = [];
  let n = 0;
  let levels = 0;
  let markerLayers = 0;
  let markersRemoved = 0;
  let tableLayers = 0;
  let tablesRemoved = 0;
  const tableRows: unknown[][] = [];
  const tableLayer = {
    setRows: (r: readonly unknown[]) => { tableRows.push(r.slice()); },
    setOptions: () => {},
  };
  const markerLayer = { setMarkers: (m: readonly unknown[]) => { markers.push(m.slice()); } };
  const host: IndicatorHost = {
    addIndicatorLegend: () => ({ setOptions: () => {}, setValue: () => {}, setValues: () => {} }) as never,
    removeIndicatorLegend: () => {},
    addIndicatorFill: () => {},
    removeIndicatorFill: () => {},
    removeIndicatorMarkers: () => { markersRemoved += 1; },
    addIndicatorTable: () => { tableLayers += 1; return tableLayer as never; },
    removeIndicatorTable: () => { tablesRemoved += 1; },
    legendRowsOn: () => 0,
    addIndicatorSeries: (type): SeriesApi => {
      const key = `${type}-${n++}`;
      series.set(key, []);
      return {
        setData: (d) => { series.set(key, d as unknown[]); },
        prependData: () => {}, update: () => {}, getData: () => [],
        applyOptions: () => {}, remove: () => { removed.push(key); },
        priceScale: () => ({}) as never,
        createMarkers: () => { markerLayers += 1; return markerLayer as never; },
      };
    },
    addIndicatorLevel: (): PriceLine => { levels += 1; return {} as PriceLine; },
    removeIndicatorLevel: () => { levels -= 1; },
    sourceBars: () => source,
    nextPaneIndex: () => 1,
    setPaneRange: () => {},
  };
  return {
    host, series, removed, markers,
    get levels() { return levels; },
    get markerLayers() { return markerLayers; },
    get markersRemoved() { return markersRemoved; },
    get tableLayers() { return tableLayers; },
    get tablesRemoved() { return tablesRemoved; },
    tableRows,
  };
}

describe('IndicatorInstance runtime', () => {

  it('creates one series per plot and fills it on construction', () => {
    const data = wave();
    const h = fakeHost(data);
    const inst = new IndicatorInstance(h.host, getIndicator('macd'));
    expect(h.series.size).toBe(3);
    for (const rows of h.series.values()) expect(rows.length).toBe(data.length);
    expect(inst.paneIndex).toBe(1); // 'pane' placement claims a new pane
  });

  it('places onchart indicators on pane 0', () => {
    const h = fakeHost(wave());
    expect(new IndicatorInstance(h.host, getIndicator('ema')).paneIndex).toBe(0);
  });

  it('setSettings merges, recomputes, and keeps defaults for untouched keys', () => {
    const h = fakeHost(wave());
    const inst = new IndicatorInstance(h.host, getIndicator('rsi'));
    const before = inst.values().rsi[119];
    inst.setSettings({ length: 3 });
    expect(inst.settings()).toMatchObject({ length: 3, source: 'close' });
    expect(inst.values().rsi[119]).not.toBe(before);
  });

  it('switches a plot to another chart type by rebuilding its series', () => {
    // The chart type belongs to the series, not the style bag, so this cannot
    // be an applyOptions: the series has to be rebuilt.
    const h = fakeHost(wave());
    const inst = new IndicatorInstance(h.host, getIndicator('sma'));
    const has = (t: string) => [...h.series.keys()].some((k) => k.startsWith(`${t}-`));
    expect(has('line')).toBe(true);
    inst.setSettings({ 'ma:type': 'histogram' });
    expect(has('histogram')).toBe(true);
    inst.remove();
  });

  it('keeps a plot on its declared type when no override is set', () => {
    const h = fakeHost(wave());
    const inst = new IndicatorInstance(h.host, getIndicator('sma'));
    const has = (t: string) => [...h.series.keys()].some((k) => k.startsWith(`${t}-`));
    expect(has('line')).toBe(true);
    expect(has('histogram')).toBe(false);
    inst.remove();
  });

  it('remove tears down every series and level, and is idempotent', () => {
    const h = fakeHost(wave());
    const inst = new IndicatorInstance(h.host, getIndicator('rsi'));
    expect(h.levels).toBe(3); // OB / 50 / OS
    inst.remove();
    inst.remove();
    expect(h.removed).toHaveLength(1);
    expect(h.levels).toBe(0);
  });

  it('uses calcTail for a tail-only change and matches a full recompute', () => {
    const data = wave(60);
    const h = fakeHost(data);
    let tailCalls = 0;
    const descriptor: IndicatorDescriptor = {
      id: 'test-tail', name: 'Tail', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map((x) => x.close * 2) }),
      calcTail: (b, _s, from) => {
        tailCalls += 1;
        return { v: b.slice(from).map((x) => x.close * 2) };
      },
    };
    const inst = new IndicatorInstance(h.host, descriptor);
    expect(tailCalls).toBe(0); // first pass is a full calc
    data.push({ time: 1700009999, open: 1, high: 1, low: 1, close: 42, volume: 1 });
    inst.recompute();
    expect(tailCalls).toBe(1);
    expect(inst.values().v[data.length - 1]).toBe(84);
    expect(inst.values().v).toEqual(data.map((x) => x.close * 2));
  });

  it('falls back to a full calc when calcTail returns null', () => {
    const data = wave(20);
    const h = fakeHost(data);
    const descriptor: IndicatorDescriptor = {
      id: 'test-null-tail', name: 'NullTail', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      calc: (b) => ({ v: b.map(() => 1) }),
      calcTail: () => null,
    };
    const inst = new IndicatorInstance(h.host, descriptor);
    data.push({ time: 1700009999, open: 1, high: 1, low: 1, close: 1, volume: 1 });
    inst.recompute();
    expect(inst.values().v).toHaveLength(data.length);
    expect(inst.values().v.every((v) => v === 1)).toBe(true);
  });
});

describe('Tier-2 contract', () => {
  const point = (time: number, oi: number): Tier2Point => ({ time, values: { oi } });

  it('aligns external points to bars with last-known-value, never forward-looking', async () => {
    const data = bars(5, () => 100); // times 1700000000 + i*60
    const descriptor = createTier2Indicator({
      id: 'test-oi', name: 'OI', placement: 'pane', inputs: [],
      plots: [{ key: 'oi', type: 'line', title: 'OI' }],
      // A point lands exactly on bar 1 and mid-way between bars 2 and 3.
      fetch: async () => [point(1700000060, 10), point(1700000150, 20)],
    });

    const store: Record<string, unknown> = {};
    let recomputes = 0;
    const detach = descriptor.attach?.({
      settings: () => ({}), bars: () => data,
      requestRecompute: () => { recomputes += 1; }, store,
    });
    await new Promise((r) => setTimeout(r, 0));
    expect(recomputes).toBe(1);

    const out = descriptor.calc(data, {}, store).oi;
    expect(out[0]).toBeNull();  // before the first point
    expect(out[1]).toBe(10);    // exactly on a point
    expect(out[2]).toBe(10);    // carries forward, does NOT look ahead to 20
    expect(out[3]).toBe(20);
    expect(out[4]).toBe(20);
    if (typeof detach === 'function') detach();
  });

  it('does not show previous-symbol data when a new symbol fetch fails', async () => {
    const data = bars(3, () => 100);
    let attempt = 0;
    const descriptor = createTier2Indicator({
      id: 'test-fail', name: 'Fail', placement: 'pane', inputs: [],
      plots: [{ key: 'oi', type: 'line', title: 'OI' }],
      fetch: async () => {
        attempt += 1;
        if (attempt > 1) throw new Error('network');
        return [point(1700000000, 5)];
      },
      refetchOn: ['symbol'],
    });
    const store: Record<string, unknown> = {};
    const ctx = { settings: () => ({ symbol: 'A' }), bars: () => data, requestRecompute: () => {}, store };
    descriptor.attach?.(ctx);
    await new Promise((r) => setTimeout(r, 0));
    expect(descriptor.calc(data, {}, store).oi[0]).toBe(5);

    // Failed history for B must not present A's data as B's values.
    descriptor.attach?.({ ...ctx, settings: () => ({ symbol: 'B' }) });
    await new Promise((r) => setTimeout(r, 0));
    expect(descriptor.calc(data, {}, store).oi).toEqual([null, null, null]);
  });

  it('merges live points in time order and unsubscribes on detach', async () => {
    const data = bars(3, () => 100);
    let unsubscribed = false;
    let push: ((p: Tier2Point) => void) | null = null;
    const descriptor = createTier2Indicator({
      id: 'test-live', name: 'Live', placement: 'pane', inputs: [],
      plots: [{ key: 'oi', type: 'line', title: 'OI' }],
      fetch: async () => [point(1700000000, 1)],
      subscribe: (_ctx, cb) => { push = cb; return () => { unsubscribed = true; }; },
    });
    const store: Record<string, unknown> = {};
    const detach = descriptor.attach?.({
      settings: () => ({}), bars: () => data, requestRecompute: () => {}, store,
    });
    await new Promise((r) => setTimeout(r, 0));
    // Out-of-order arrival still lands in time order.
    (push as unknown as (p: Tier2Point) => void)(point(1700000120, 3));
    (push as unknown as (p: Tier2Point) => void)(point(1700000060, 2));
    expect(descriptor.calc(data, {}, store).oi).toEqual([1, 2, 3]);
    if (typeof detach === 'function') detach();
    expect(unsubscribed).toBe(true);
  });
});

describe('chart.addIndicator integration', () => {
  const makeChart = (): Chart => {
    const chart = new Chart(fakeDocument().createElement('div'), {
      document: fakeDocument(),
      raf: { schedule: () => 0 },
      pixelRatio: () => 1,
      shortcuts: false,
    });
    chart.applySize(800, 600);
    return chart;
  };

  it('adds, lists, and removes an indicator', () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(wave());
    const rsi = chart.addIndicator('rsi');
    expect(chart.indicators()).toHaveLength(1);
    expect(rsi.name).toBe('RSI');
    expect(rsi.values().rsi).toHaveLength(120);
    expect(chart.removeIndicator(rsi.id)).toBe(true);
    expect(chart.indicators()).toHaveLength(0);
    expect(chart.removeIndicator(rsi.id)).toBe(false);
  });

  it('an indicator plot never becomes the primary price series', () => {
    const chart = makeChart();
    const ema = chart.addIndicator('ema'); // added BEFORE any price series
    chart.addSeries('candlestick').setData(wave());
    // The candles drive the legend, so the indicator recomputed off them.
    expect(ema.values().ma.length).toBe(120);
  });

  it('recomputes when the source series updates', () => {
    const chart = makeChart();
    const data = wave(30);
    const price = chart.addSeries('candlestick');
    price.setData(data);
    const sma20 = chart.addIndicator('sma', { length: 5 });
    const before = sma20.values().ma[29];
    price.update({ time: data[29].time + 60, open: 500, high: 500, low: 500, close: 500 });
    expect(sma20.values().ma).toHaveLength(31);
    expect(sma20.values().ma[30]).not.toBe(before);
  });

  it('does not recurse when an indicator writes its own plots', () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(wave(20));
    expect(() => { chart.addIndicator('macd'); chart.addIndicator('bollinger'); }).not.toThrow();
    expect(chart.indicators()).toHaveLength(2);
  });

  it('destroy tears down every indicator', () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(wave(20));
    chart.addIndicator('rsi');
    chart.destroy();
    expect(chart.indicators()).toHaveLength(0);
  });

  it('a custom descriptor registers and runs like a built-in', () => {
    registerIndicator({
      id: 'test-double', name: 'Double', placement: 'onchart',
      inputs: [{ key: 'factor', type: 'number', label: 'Factor', default: 2 }],
      plots: [{ key: 'out', type: 'line', title: 'Double' }],
      calc: (b, s) => ({ out: b.map((x) => x.close * (s.factor as number)) }),
    });
    const chart = makeChart();
    chart.addSeries('candlestick').setData(wave(10));
    const inst = chart.addIndicator('test-double', { factor: 3 });
    expect(inst.values().out[0]).toBeCloseTo(wave(10)[0].close * 3, 10);
  });
});

describe('indicator fills (the Ichimoku cloud)', () => {
  it('ichimoku declares a cloud between the two spans', () => {
    const d = registeredIndicators().find((x) => x.id === 'ichimoku');
    expect(d?.fills?.[0].between).toEqual(['spanA', 'spanB']);
    // Colour-by-settings, so the cloud is restyleable like any plot.
    expect(d?.fills?.[0].colorUpKey).toBe('cloudUpColor');
  });

  it('fills one polygon per constant-sign run, split at the crossing', () => {
    const fill = new IndicatorFill({ colorUp: '#0f0', colorDown: '#f00' });
    // A leads, then B leads: one flip, so two filled runs.
    fill.setPoints([
      { index: 0, a: 10, b: 5 },
      { index: 1, a: 8, b: 6 },
      { index: 2, a: 4, b: 9 },
      { index: 3, a: 2, b: 11 },
    ]);
    const { ctx, rec } = makeCtx();
    fill.draw(ctx, fillRc());
    const fills = rec.ops.filter((o) => o.type === 'fill');
    expect(fills).toHaveLength(2);
    // Both colours used: a single-colour band would hide which side leads.
    const styles = fills.map((o) => o.fillStyle);
    expect(styles).toContain('#0f0');
    expect(styles).toContain('#f00');
  });

  it('breaks the band across a gap instead of bridging it', () => {
    const fill = new IndicatorFill({ colorUp: '#0f0', colorDown: '#f00' });
    // The warmup hole an Ichimoku span always has at the start.
    fill.setPoints([
      { index: 0, a: null, b: null },
      { index: 1, a: 10, b: 5 },
      { index: 2, a: 11, b: 6 },
      { index: 3, a: null, b: null },
      { index: 4, a: 12, b: 7 },
      { index: 5, a: 13, b: 8 },
    ]);
    const { ctx, rec } = makeCtx();
    fill.draw(ctx, fillRc());
    // Two separate runs, not one polygon spanning the hole.
    expect(rec.ops.filter((o) => o.type === 'fill')).toHaveLength(2);
  });

  it('draws nothing for a single point or while hidden', () => {
    const fill = new IndicatorFill({ colorUp: '#0f0', colorDown: '#f00' });
    fill.setPoints([{ index: 0, a: 1, b: 2 }]);
    const a = makeCtx();
    fill.draw(a.ctx, fillRc());
    expect(a.rec.ops.filter((o) => o.type === 'fill')).toHaveLength(0);

    fill.setPoints([{ index: 0, a: 1, b: 2 }, { index: 1, a: 3, b: 4 }]);
    fill.setVisible(false);
    const b = makeCtx();
    fill.draw(b.ctx, fillRc());
    expect(b.rec.ops.filter((o) => o.type === 'fill')).toHaveLength(0);
  });
});

describe('per-bar plot colour', () => {
  it('MACD histogram uses four states, not one colour', () => {
    const d = getIndicator('macd');
    const hist = d.plots.find((p) => p.key === 'histogram');
    expect(hist?.colorBy).toBeTypeOf('function');
    const values = { histogram: [1, 2, 1.5, -0.5, -1.5, -1] } as Record<string, (number | null)[]>;
    const at = (i: number) =>
      hist?.colorBy?.({ value: values.histogram[i] as number, index: i, values, settings: {} });
    // Above zero: building vs fading are different colours.
    expect(at(1)).not.toBe(at(2));
    // Below zero likewise, and neither matches the positive pair.
    expect(at(4)).not.toBe(at(5));
    expect(new Set([at(1), at(2), at(4), at(5)]).size).toBe(4);
  });

  it('a bar carries its colour through toBar to the renderer', () => {
    const bar = toBar({ time: 1, value: 5, color: '#abcdef' });
    expect(bar.color).toBe('#abcdef');
    const { ctx, rec } = makeCtx();
    drawHistogram(ctx, [{ x: 10, bar }], (v) => 100 - v, 8, 1, { color: '#000000', base: 0 });
    // The per-bar colour wins over the style colour.
    const fills = rec.ops.filter((o) => o.type === 'fillRect');
    expect(fills[0]?.fillStyle).toBe('#abcdef');
  });

  it('falls back to the plot colour when a bar has none', () => {
    const { ctx, rec } = makeCtx();
    drawHistogram(ctx, [{ x: 10, bar: toBar({ time: 1, value: 5 }) }], (v) => 100 - v, 8, 1,
      { color: '#123456', base: 0 });
    expect(rec.ops.filter((o) => o.type === 'fillRect')[0]?.fillStyle).toBe('#123456');
  });
});

describe('Williams VIX Fix', () => {
  const d = () => getIndicator('williams-vix-fix');

  it('is registered under the expected id and name', () => {
    // Named like Williams Alligator and Williams Fractals.
    expect(d().name).toBe('Williams VIX Fix');
    expect(d().placement).toBe('pane');
  });

  it('spikes when price falls far below the lookback high', () => {
    // A hard drop on the last bar: wvf measures the low against the highest
    // close, so the spike belongs to the bar that made the low.
    const flat = Array.from({ length: 60 }, (_, i) => ({
      time: 1700000000 + i * 60, open: 100, high: 100, low: 100, close: 100, volume: 1,
    }));
    flat[59] = { ...flat[59], low: 80, close: 82 };
    const out = d().calc(flat, { pd: 22, bbl: 20, mult: 2, lb: 50, ph: 0.85, pl: 1.01 }, {});
    const wvf = out.wvf as (number | null)[];
    expect(wvf[58]).toBeCloseTo(0, 6);
    // low 80 against a highest close of 100 -> 20%.
    expect(wvf[59]).toBeCloseTo(20, 6);
  });

  it('colours the histogram by breakout, not by level', () => {
    const hist = d().plots.find((p) => p.key === 'wvf');
    expect(hist?.colorBy).toBeTypeOf('function');
    const values = {
      wvf: [5, 12], alertUpper: [10, 10], alertHigh: [20, 20],
    } as Record<string, (number | null)[]>;
    const at = (i: number) =>
      hist?.colorBy?.({ value: values.wvf[i] as number, index: i, values, settings: {} });
    // Below the band: normal. Above it: alert, even though 12 < rangeHigh.
    expect(at(0)).toBe('#808080');
    expect(at(1)).toBe('#00ff00');
  });

  it('keeps the colour rule working when the bands are hidden', () => {
    // The reference `sd`/`hp` toggles hide the plots; they must not disable the
    // alert, which is the whole point of the study.
    const bars = wave();
    const out = d().calc(bars, { pd: 22, bbl: 20, mult: 2, lb: 50, ph: 0.85, pl: 1.01, sd: false, hp: false }, {});
    expect((out.upperBand as (number | null)[]).every((v) => v === null)).toBe(true);
    expect((out.alertUpper as (number | null)[]).some((v) => v !== null)).toBe(true);
  });
});

describe('HalfTrend', () => {
  const d = () => getIndicator('halftrend');
  const defaults = () => indicatorDefaults(d());

  it('is registered as an on-chart trend study', () => {
    expect(d().name).toBe('HalfTrend');
    expect(d().placement).toBe('onchart');
    expect(d().category).toBe('Trend');
  });

  it('holds exactly one side of the level per bar', () => {
    const out = d().calc(wave(), defaults(), {});
    const up = out.up as (number | null)[];
    const down = out.down as (number | null)[];
    for (let i = 0; i < up.length; i++) {
      // Never both: the split is what recolours the line at a flip.
      expect(up[i] === null || down[i] === null, `both set at ${i}`).toBe(true);
    }
    // A 120-bar sine crosses often enough that both sides must appear.
    expect(up.some((v) => v !== null)).toBe(true);
    expect(down.some((v) => v !== null)).toBe(true);
  });

  it('never moves the up level down while the uptrend holds', () => {
    const out = d().calc(wave(), defaults(), {});
    const up = out.up as (number | null)[];
    let prev: number | null = null;
    for (let i = 0; i < up.length; i++) {
      const v = up[i];
      if (v === null) { prev = null; continue; } // trend ended, next run restarts
      if (prev !== null) expect(v).toBeGreaterThanOrEqual(prev - 1e-9);
      prev = v;
    }
  });

  it('holds the level flat through noise that does not close beyond the prior bar', () => {
    // A rising staircase whose bars never close below the previous bar's low,
    // so the down-flip can never arm and the level must only ratchet up.
    const rising = bars(80, (i) => 100 + i);
    const out = d().calc(rising, defaults(), {});
    const down = out.down as (number | null)[];
    expect(down.every((v) => v === null)).toBe(true);
  });

  it('brackets the level with the channel at the configured deviation', () => {
    const data = wave();
    const out = d().calc(data, { ...defaults(), channelDeviation: 3, atrPeriod: 14 }, {});
    const level = (i: number): number | null =>
      (out.up as (number | null)[])[i] ?? (out.down as (number | null)[])[i];
    const hi = out.atrHigh as (number | null)[];
    const lo = out.atrLow as (number | null)[];
    let checked = 0;
    for (let i = 0; i < data.length; i++) {
      const l = level(i);
      if (l === null || hi[i] === null || lo[i] === null) continue;
      // Symmetric about the level, and the channel widens with deviation.
      expect(hi[i]! - l).toBeCloseTo(l - lo[i]!, 9);
      expect(hi[i]!).toBeGreaterThan(l);
      checked += 1;
    }
    expect(checked).toBeGreaterThan(0);
  });

  it('hides the channel and the signals when their toggles are off', () => {
    const out = d().calc(wave(), { ...defaults(), showChannels: false, showSignals: false }, {});
    expect((out.atrHigh as (number | null)[]).every((v) => v === null)).toBe(true);
    expect((out.atrLow as (number | null)[]).every((v) => v === null)).toBe(true);
    expect((out.buySignal as (number | null)[]).every((v) => v === null)).toBe(true);
    expect((out.sellSignal as (number | null)[]).every((v) => v === null)).toBe(true);
    // The level itself is not a toggle: it must still be there.
    const up = out.up as (number | null)[];
    const down = out.down as (number | null)[];
    expect(up.some((v) => v !== null) || down.some((v) => v !== null)).toBe(true);
  });

  it('marks a signal only on the bar the trend flips', () => {
    const data = wave();
    const out = d().calc(data, { ...defaults(), atrPeriod: 14 }, {});
    const up = out.up as (number | null)[];
    const down = out.down as (number | null)[];
    const buy = out.buySignal as (number | null)[];
    const sell = out.sellSignal as (number | null)[];
    for (let i = 1; i < data.length; i++) {
      const flippedUp = up[i] !== null && up[i - 1] === null;
      const flippedDown = down[i] !== null && down[i - 1] === null;
      if (buy[i] !== null) expect(flippedUp, `buy at ${i} without an up flip`).toBe(true);
      if (sell[i] !== null) expect(flippedDown, `sell at ${i} without a down flip`).toBe(true);
    }
    expect(buy.some((v) => v !== null) || sell.some((v) => v !== null)).toBe(true);
  });

  it('exposes a restyleable colour key per plot and a ribbon per side', () => {
    const keys = d().plots.map((p) => p.colorKey);
    expect(keys).not.toContain(undefined);
    expect(d().fills?.map((f) => f.between)).toEqual([['up', 'atrLow'], ['down', 'atrHigh']]);
  });
});

describe('indicator signal markers', () => {
  const d = () => getIndicator('halftrend');

  it('HalfTrend labels every flip and nothing else', () => {
    const data = wave();
    const out = d().calc(data, { ...indicatorDefaults(d()), atrPeriod: 14 }, {});
    const markers = d().markers?.({ bars: data, values: out, settings: indicatorDefaults(d()) }) ?? [];
    expect(markers.length).toBeGreaterThan(0);
    const buys = out.buySignal.filter((v) => v !== null).length;
    const sells = out.sellSignal.filter((v) => v !== null).length;
    expect(markers).toHaveLength(buys + sells);
    for (const m of markers) {
      expect(m.position).toBe('atPrice');
      expect(m.text === 'Buy' ? m.shape : 'labelUp').toBe('labelUp');
      expect(m.text === 'Sell' ? m.shape : 'labelDown').toBe('labelDown');
      // Anchored to a real bar time, or SeriesMarkers drops it silently.
      expect(data.some((b) => b.time === m.time)).toBe(true);
    }
  });

  it('the showLabels toggle clears the labels but not the plotted signals', () => {
    const data = wave();
    const s = { ...indicatorDefaults(d()), showLabels: false };
    const out = d().calc(data, s, {});
    expect(d().markers?.({ bars: data, values: out, settings: s })).toEqual([]);
    const any = out.buySignal.some((v) => v !== null) || out.sellSignal.some((v) => v !== null);
    expect(any).toBe(true);
  });

  it('the runtime creates one marker layer and feeds it on recompute', () => {
    const h = fakeHost(wave());
    const inst = new IndicatorInstance(h.host, d());
    expect(h.markerLayers).toBe(1);
    expect(h.markers.length).toBeGreaterThan(0);
    expect(h.markers[h.markers.length - 1].length).toBeGreaterThan(0);
    inst.remove();
    expect(h.markersRemoved).toBe(1);
  });

  it('hiding the indicator clears its markers, showing it restores them', () => {
    const h = fakeHost(wave());
    const inst = new IndicatorInstance(h.host, d());
    inst.setVisible(false);
    expect(h.markers[h.markers.length - 1]).toEqual([]);
    inst.setVisible(true);
    expect(h.markers[h.markers.length - 1].length).toBeGreaterThan(0);
  });

  it('a descriptor with no markers hook never creates a layer', () => {
    const h = fakeHost(wave());
    new IndicatorInstance(h.host, getIndicator('sma'));
    expect(h.markerLayers).toBe(0);
  });
});

describe('restored background fills', () => {
  const data = wave();

  /** Every column key the descriptor's fills name, deduplicated. */
  const fillKeys = (d: IndicatorDescriptor): string[] =>
    [...new Set((d.fills ?? []).flatMap((f) => [f.between[0], f.between[1]]))];

  /** How many shaded regions each restored descriptor should now declare. */
  const expected: readonly (readonly [string, number])[] = [
    ['rsi', 1],
    ['cci', 2], // the level background plus the Bollinger band
    ['mfi', 1],
    ['stochastic', 1],
    ['obv', 1],
  ];

  for (const [id, count] of expected) {
    it(`${id} declares ${count} fill(s), all of them backed by real columns`, () => {
      const d = getIndicator(id);
      expect(d.fills ?? []).toHaveLength(count);
      const out = d.calc(data, indicatorDefaults(d), {});
      for (const key of fillKeys(d)) {
        // A fill naming a column that does not exist draws nothing and throws
        // nothing, so this is the only place the mistake can be caught.
        expect(out[key], `${id} fills between '${key}', which calc never returns`).toBeDefined();
        expect(out[key].length, `${id}.${key} length`).toBe(data.length);
      }
    });
  }

  it('holds the band edges at their level on every bar', () => {
    const levels: readonly (readonly [string, number, number])[] = [
      ['rsi', 70, 30],
      ['mfi', 80, 20],
      ['stochastic', 80, 20],
      ['cci', 100, -100],
    ];
    for (const [id, up, down] of levels) {
      const d = getIndicator(id);
      const out = d.calc(data, indicatorDefaults(d), {});
      expect(out.upperLevel, id).toEqual(new Array(data.length).fill(up));
      expect(out.lowerLevel, id).toEqual(new Array(data.length).fill(down));
    }
  });

  it('shades the pane across the warmup, where the study itself is still empty', () => {
    const mains: readonly (readonly [string, string])[] = [
      ['rsi', 'rsi'], ['mfi', 'mfi'], ['stochastic', 'k'], ['cci', 'cci'],
    ];
    for (const [id, main] of mains) {
      const d = getIndicator(id);
      const out = d.calc(data, indicatorDefaults(d), {});
      const first = out[main].findIndex((v) => v !== null);
      expect(first, `${id} has no warmup gap left to test`).toBeGreaterThan(0);
      for (let i = 0; i < first; i++) {
        expect(out.upperLevel[i], `${id}.upperLevel[${i}]`).not.toBeNull();
        expect(out.lowerLevel[i], `${id}.lowerLevel[${i}]`).not.toBeNull();
      }
    }
  });

  it('moves the RSI band edges with the overbought / oversold inputs', () => {
    const d = getIndicator('rsi');
    const out = d.calc(data, { ...indicatorDefaults(d), overbought: 65, oversold: 35 }, {});
    expect(out.upperLevel.every((v) => v === 65)).toBe(true);
    expect(out.lowerLevel.every((v) => v === 35)).toBe(true);
  });

  it('leaves the Bollinger bands empty unless that smoothing type is picked', () => {
    for (const id of ['cci', 'obv']) {
      const d = getIndicator(id);
      for (const type of ['None', 'SMA', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA']) {
        const off = d.calc(data, { ...indicatorDefaults(d), maType: type }, {});
        expect(off.bbUpper.every((v) => v === null), `${id} ${type} bbUpper`).toBe(true);
        expect(off.bbLower.every((v) => v === null), `${id} ${type} bbLower`).toBe(true);
        // 'None' switches the average off too; every other kernel prints one.
        expect(off.ma.some((v) => v !== null), `${id} ${type} ma`).toBe(type !== 'None');
      }
      const on = d.calc(data, { ...indicatorDefaults(d), maType: 'SMA + Bollinger Bands' }, {});
      expect(on.bbUpper.some((v) => v !== null), `${id} bbUpper on`).toBe(true);
      expect(on.bbLower.some((v) => v !== null), `${id} bbLower on`).toBe(true);
      const i = data.length - 1;
      expect(on.bbUpper[i] as number, `${id} bbUpper straddles`).toBeGreaterThan(on.ma[i] as number);
      expect(on.bbLower[i] as number, `${id} bbLower straddles`).toBeLessThan(on.ma[i] as number);
    }
  });

  it('keeps every new column null-or-finite, never NaN', () => {
    for (const [id] of expected) {
      const d = getIndicator(id);
      const s = { ...indicatorDefaults(d), maType: 'SMA + Bollinger Bands' };
      for (const key of Object.keys(d.calc(data, s, {}))) {
        for (const v of d.calc(data, s, {})[key]) {
          expect(v === null || Number.isFinite(v), `${id}.${key} holds ${String(v)}`).toBe(true);
        }
      }
    }
  });

  it('survives no bars and a single bar', () => {
    for (const [id] of expected) {
      const d = getIndicator(id);
      const s = indicatorDefaults(d);
      for (const key of fillKeys(d)) {
        expect(d.calc([], s, {})[key], `${id}.${key} on no bars`).toEqual([]);
        expect(d.calc(data.slice(0, 1), s, {})[key].length, `${id}.${key} on one bar`).toBe(1);
      }
    }
  });

  it('every built-in fill names a column its own calc returns', () => {
    for (const d of BUILTIN_INDICATORS) {
      const out = d.calc(data, indicatorDefaults(d), {});
      for (const fill of d.fills ?? []) {
        for (const key of fill.between) {
          expect(out[key], `${d.id} fills between '${key}', which calc never returns`).toBeDefined();
          expect(out[key].length, `${d.id}.${key} length`).toBe(data.length);
        }
      }
    }
  });
});
