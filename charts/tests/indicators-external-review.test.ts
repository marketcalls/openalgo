import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import { createTier2Indicator, type Tier2Context, type Tier2Descriptor, type Tier2Point } from '../src/indicators/external';
import { fakeDocument } from './helpers/fake-dom';

const bars = (...times: number[]) => times.map(time => ({ time, open: 1, high: 1, low: 1, close: 1 }));
const point = (time: number, v: number): Tier2Point => ({ time, values: { v } });
const settle = async (): Promise<void> => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
const charts: Chart[] = [];
let sequence = 0;
afterEach(() => charts.splice(0).forEach(chart => chart.destroy()));

async function mount(calc?: Tier2Descriptor['calc']) {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, pixelRatio: () => 1, shortcuts: false, raf: { schedule: () => 1, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  chart.setDataContext({ symbol: 'PRIMARY', interval: '1m' });
  const source = chart.addSeries('candlestick');
  source.setData(bars(0, 60, 120));
  const requests: { context: Tier2Context; resolve(value: readonly Tier2Point[]): void }[] = [];
  const id = `external-review-${sequence++}`;
  registerIndicator(createTier2Indicator({
    id, name: 'External review', placement: 'pane', inputs: [],
    plots: [{ key: 'v', type: 'line', title: 'Value' }], calc,
    fetch: context => new Promise(resolve => requests.push({ context, resolve })),
  }));
  const indicator = chart.addIndicator(id);
  requests[0].resolve([point(0, 10), point(60, 20), point(120, 30)]);
  await settle();
  return { chart, source, indicator, requests };
}

describe('native external review regressions', () => {
  it('fetches both new ends after prepend and append were queued behind active history', async () => {
    const h = await mount();
    h.source.update({ ...bars(120)[0], close: 2 });
    h.source.prependData(bars(-60));
    h.source.update(bars(180)[0]);
    expect(h.requests).toHaveLength(2);
    h.requests[1].resolve([point(120, 35)]);
    await settle();
    expect(h.requests[2].context).toMatchObject({ from: -60, to: 0 });
    h.requests[2].resolve([point(-60, 5), point(0, 10)]);
    await settle();
    expect(h.requests).toHaveLength(4);
    expect(h.requests[3].context).toMatchObject({ from: 120, to: 180 });
    h.requests[3].resolve([point(120, 35), point(180, 40)]);
    await settle();
    expect(h.indicator.values().v).toEqual([5, 10, 20, 35, 40]);
    expect(h.requests).toHaveLength(4);
  });

  it('keeps catch-up loading when a public values read recovers calculation over cached data', async () => {
    const h = await mount((_bars, external) => {
      if (external.v.includes(999)) throw new Error('Rejected external value');
      return external;
    });
    h.source.update({ ...bars(120)[0], close: 2 });
    h.source.update({ ...bars(120)[0], close: 3 });
    h.requests[1].resolve([point(120, 999)]);
    await settle();
    expect(h.requests).toHaveLength(3);
    expect(h.indicator.dataStatus()?.state).toBe('loading');
    expect(h.indicator.values().v).toEqual([10, 20, 30]);
    expect(h.indicator.dataStatus()?.state).toBe('loading');
    h.requests[2].resolve([point(120, 40)]);
    await settle();
    expect(h.indicator.values().v).toEqual([10, 20, 40]);
    expect(h.indicator.dataStatus()?.state).toBe('ready');
  });
});
