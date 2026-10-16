import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import { createTier2Indicator } from '../src/indicators/external';
import { fakeDocument } from './helpers/fake-dom';

const cleanups: (() => void)[] = [];
afterEach(() => cleanups.splice(0).reverse().forEach(fn => fn()));
function mount() {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), { document, raf: { schedule: () => 0 }, shortcuts: false });
  chart.applySize(800, 600);
  cleanups.push(() => chart.destroy());
  return chart;
}
const bar = (time: number) => ({ time, open: 23800, high: 23804, low: 23798, close: 23802 });
const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

describe('explicit chart data context', () => {
  it('keeps OI capability independent of observations and publishes capability-only changes', () => {
    const chart = mount();
    const changes: unknown[] = [];
    chart.on('data:context', context => changes.push(context));
    const price = chart.addSeries('candlestick');
    price.setData([{ ...bar(100), oi: 0 }]);
    expect(chart.hasOpenInterest).toBeUndefined();
    chart.setDataContext({ symbol: 'CONTRACT', hasOpenInterest: true });
    expect(chart.hasOpenInterest).toBe(true);
    price.update(bar(200));
    expect(chart.hasOpenInterest).toBe(true);
    chart.setDataContext({ symbol: 'CONTRACT', hasOpenInterest: false });
    expect(chart.hasOpenInterest).toBe(false);
    chart.setDataContext({ symbol: 'CONTRACT' });
    expect(chart.hasOpenInterest).toBeUndefined();
    expect(changes).toEqual([
      { symbol: 'CONTRACT', hasOpenInterest: true },
      { symbol: 'CONTRACT', hasOpenInterest: false },
      { symbol: 'CONTRACT' },
    ]);
  });

  it('passes the current instrument to external studies and refreshes older ranges', async () => {
    const calls: { symbol?: string; from: number; to: number }[] = [];
    const id = 'context-study';
    registerIndicator(createTier2Indicator({ id, name: 'Context study', placement: 'pane', inputs: [],
      plots: [{ key: 'value', title: 'Value', type: 'line' }],
      fetch: async ctx => {
        calls.push({ symbol: ctx.dataContext?.symbol, from: ctx.from, to: ctx.to });
        return [{ time: ctx.from, values: { value: ctx.dataContext?.symbol === 'NIFTY' ? 100 : 200 } }];
      },
    }));
    const chart = mount();
    chart.setDataContext({ symbol: 'NIFTY', exchange: 'NFO', interval: '1m' });
    const price = chart.addSeries('candlestick');
    price.setData([bar(100), bar(200)]);
    const study = chart.addIndicator(id);
    await settle();
    expect(calls).toContainEqual({ symbol: 'NIFTY', from: 100, to: 200 });
    expect(study.dataStatus()?.state).toBe('ready');
    price.prependData([bar(50)]);
    await settle();
    expect(calls).toContainEqual({ symbol: 'NIFTY', from: 50, to: 100 });
    price.setData([]);
    chart.setDataContext({ symbol: 'BANKNIFTY', exchange: 'NFO', interval: '1m' });
    price.setData([bar(300), bar(400)]);
    await settle();
    expect(calls).toContainEqual({ symbol: 'BANKNIFTY', from: 300, to: 400 });
    expect(chart.getDataContext()?.symbol).toBe('BANKNIFTY');
  });

  it('copies explicit context and does not invent an instrument for raw bars', () => {
    const chart = mount();
    expect(chart.getDataContext()).toBeUndefined();
    const context = { symbol: 'NIFTY', exchange: 'NFO', interval: '1m' };
    chart.setDataContext(context);
    context.symbol = 'changed';
    expect(chart.getDataContext()?.symbol).toBe('NIFTY');
    chart.setDataContext(undefined);
    expect(chart.getDataContext()).toBeUndefined();
  });
});
