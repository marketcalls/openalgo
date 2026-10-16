/**
 * Tier-2 as a combiner (2.4.0): a descriptor may name extra external columns
 * to align (`series`) and a `calc` that folds them into the chart's own bars,
 * so a relative strength or a beta can be computed from a benchmark the host
 * serves through `requestBars`. Without either, the wrapper returns exactly
 * the aligned plot columns it always did.
 */
import { describe, it, expect } from 'vitest';
import { Chart } from '../src/core/chart';
import { createTier2Indicator, type Tier2Context, type Tier2Point } from '../src/indicators/external';
import { IndicatorInstance, type IndicatorHost } from '../src/model/indicator-instance';
import { registerIndicator, type IndicatorBarsRequest, type IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import type { SeriesApi } from '../src/model/series';
import { fakeDocument } from './helpers/fake-dom';

const bars = (...closes: number[]): Bar[] =>
  closes.map((close, i) => ({ time: 100 + i, open: close, high: close, low: close, close }));

function host(source: Bar[], requestBars?: IndicatorHost['requestBars']): IndicatorHost {
  return {
    addIndicatorLegend: () => ({ setOptions: () => {}, setValues: () => {} }) as never,
    removeIndicatorLegend: () => {},
    legendRowsOn: () => 0,
    addIndicatorSeries: (): SeriesApi => ({
      setData: () => {}, prependData: () => {}, update: () => {}, getData: () => [],
      applyOptions: () => {}, remove: () => {}, priceScale: () => ({}) as never,
      createMarkers: () => ({ setMarkers: () => {} }) as never,
    }),
    addIndicatorLevel: () => ({}) as never,
    removeIndicatorLevel: () => {},
    addIndicatorFill: () => {},
    removeIndicatorFill: () => {},
    removeIndicatorMarkers: () => {},
    addIndicatorTable: () => ({ setRows: () => {}, setOptions: () => {} }) as never,
    removeIndicatorTable: () => {},
    sourceBars: () => source,
    nextPaneIndex: () => 1,
    setPaneRange: () => {},
    requestBars,
  };
}

describe('Tier-2 calc and extra series', () => {
  it('aligns the named extra column and hands it to calc alongside the bars', async () => {
    const data = bars(10, 20, 30, 40);
    const store: Record<string, unknown> = {};
    let resolve!: (p: readonly Tier2Point[]) => void;
    const d = createTier2Indicator({
      id: 'ext-ratio', name: 'Ratio', placement: 'pane', inputs: [],
      plots: [{ key: 'ratio', type: 'line', title: 'Ratio' }],
      series: ['bench'],
      fetch: () => new Promise((r) => { resolve = r; }),
      calc: (b, external) => ({
        ratio: b.map((bar, i) => {
          const bench = external.bench[i];
          return bench === null || bench === 0 ? null : bar.close / bench;
        }),
      }),
    });
    let recomputes = 0;
    d.attach!({ settings: () => ({}), bars: () => data, store, requestRecompute: () => { recomputes += 1; } });
    // Nothing fetched yet: the aligned benchmark is all null, so the ratio is too.
    expect(d.calc(data, {}, store).ratio).toEqual([null, null, null, null]);
    resolve([{ time: 100, values: { bench: 2 } }, { time: 102, values: { bench: 4 } }]);
    await Promise.resolve();
    expect(recomputes).toBe(1);
    // Last-known-value alignment: 2 until bar 102, then 4.
    expect(d.calc(data, {}, store).ratio).toEqual([5, 10, 7.5, 10]);
    // The extra column is not a plot, so it is not in the result.
    expect(Object.keys(d.calc(data, {}, store))).toEqual(['ratio']);
  });

  it('returns the aligned plot columns unchanged when no calc is declared', async () => {
    const data = bars(1, 1, 1);
    const store: Record<string, unknown> = {};
    const d = createTier2Indicator({
      id: 'ext-plain', name: 'Plain', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      fetch: async () => [{ time: 101, values: { v: 7 } }],
    });
    d.attach!({ settings: () => ({}), bars: () => data, store, requestRecompute: () => {} });
    await Promise.resolve();
    await Promise.resolve();
    expect(d.calc(data, {}, store).v).toEqual([null, 7, 7]);
  });

  it('passes the host bar provider through to fetch', async () => {
    const data = bars(10, 20);
    const store: Record<string, unknown> = {};
    const asked: IndicatorBarsRequest[] = [];
    let ctxSeen: Tier2Context | null = null;
    const d = createTier2Indicator({
      id: 'ext-bench', name: 'Bench', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'v' }],
      fetch: async (c) => {
        ctxSeen = c;
        const b = await c.requestBars!({ symbol: 'SPY', interval: '1m', from: c.from, to: c.to });
        return b.map((x) => ({ time: x.time, values: { v: x.close } }));
      },
    });
    d.attach!({
      settings: () => ({}), bars: () => data, store, requestRecompute: () => {},
      requestBars: async (r) => { asked.push(r); return bars(3, 4); },
    });
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    expect(asked).toEqual([{ symbol: 'SPY', interval: '1m', from: 100, to: 101 }]);
    expect(ctxSeen).not.toBeNull();
    expect(d.calc(data, {}, store).v).toEqual([3, 4]);
  });
});

describe('requestBars on the attach context', () => {
  const D: IndicatorDescriptor = {
    id: 'rb-probe', name: 'Probe', placement: 'pane', inputs: [],
    plots: [{ key: 'v', type: 'line', title: 'v' }],
    calc: (b) => ({ v: b.map((x) => x.close) }),
    attach: (ctx) => {
      (ctx.store as { probe?: typeof ctx.requestBars }).probe = ctx.requestBars;
    },
  };

  it('rejects with a clear message when the host has no provider', async () => {
    const inst = new IndicatorInstance(host(bars(1, 2)), D);
    const probe = (inst as unknown as { _store: { probe: NonNullable<typeof D.attach> } })._store.probe as unknown as
      (r: IndicatorBarsRequest) => Promise<readonly Bar[]>;
    await expect(probe({ symbol: 'X', interval: '1m', from: 0, to: 1 })).rejects.toThrow(/no bars provider/);
  });

  it('forwards to the host provider with the instance lifetime as the signal', async () => {
    const seen: IndicatorBarsRequest[] = [];
    const inst = new IndicatorInstance(host(bars(1, 2), async (r) => { seen.push(r); return bars(9); }), D);
    const probe = (inst as unknown as { _store: { probe: (r: IndicatorBarsRequest) => Promise<readonly Bar[]> } })._store.probe;
    const out = await probe({ symbol: 'X', exchange: 'NSE', interval: '5m', from: 0, to: 1 });
    expect(out.map((b) => b.close)).toEqual([9]);
    expect(seen[0].signal).toBeInstanceOf(AbortSignal);
    expect(seen[0].signal?.aborted).toBe(false);
    inst.remove();
    expect(seen[0].signal?.aborted).toBe(true);
  });

  it('is served by chart.setBarsProvider, read at request time', async () => {
    registerIndicator(D);
    const doc = fakeDocument();
    const chart = new Chart(doc.createElement('div'), {
      document: doc, pixelRatio: () => 1, shortcuts: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    });
    chart.applySize(400, 300);
    chart.addSeries('candlestick').setData(bars(1, 2, 3));
    expect(chart.hasBarsProvider()).toBe(false);
    const inst = chart.addIndicator('rb-probe');
    const probe = (inst as unknown as { _store: { probe: (r: IndicatorBarsRequest) => Promise<readonly Bar[]> } })._store.probe;
    await expect(probe({ symbol: 'X', interval: '1m', from: 0, to: 1 })).rejects.toThrow(/setBarsProvider/);
    const asked: IndicatorBarsRequest[] = [];
    chart.setBarsProvider(async (r) => { asked.push(r); return bars(42); });
    expect(chart.hasBarsProvider()).toBe(true);
    // The indicator was added before the provider existed and is still served.
    const out = await probe({ symbol: 'X', interval: '1m', from: 0, to: 1 });
    expect(out[0].close).toBe(42);
    expect(asked[0].symbol).toBe('X');
    chart.setBarsProvider(null);
    await expect(probe({ symbol: 'X', interval: '1m', from: 0, to: 1 })).rejects.toThrow(/no bars provider/);
  });
});
