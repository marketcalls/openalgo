import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import { SMA } from '../src/indicators/trend';
import { fakeDocument } from './helpers/fake-dom';

registerIndicator(SMA);
const charts: Chart[] = [];
afterEach(() => charts.splice(0).forEach(chart => chart.destroy()));
function mount() {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: () => 1, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(800, 500);
  const source = chart.addSeries('line');
  source.setData([1, 3, 5, 7].map((value, index) => ({ time: index * 60, value })));
  return chart;
}
const reference = (instanceId: string) => ({ kind: 'indicator' as const, instanceId, plotKey: 'ma' });

describe('saved study dependency graphs', () => {
  it('restores reversed display order without temporary unavailable calculations', () => {
    const chart = mount();
    const status: unknown[] = [];
    chart.on('indicator:data-status', event => status.push(event));
    const state = chart.getState();
    state.indicators = [
      { indicatorId: 'sma', instanceId: 'consumer', settings: { length: 2, source: reference('producer') }, paneIndex: 0 },
      { indicatorId: 'sma', instanceId: 'producer', settings: { length: 2 }, paneIndex: 0 },
    ];
    expect(chart.restoreState(state).applied).toBe(true);
    expect(status).toEqual([]);
    expect(chart.indicators().map(item => item.id)).toEqual(['consumer', 'producer']);
    expect(chart.indicators()[0].values().ma).toEqual([null, null, 3, 5]);
    expect(chart.getState().indicators?.[0].studyInputs).toEqual(['source']);
  });

  it('rejects the complete cycle before publishing restore events or replacing resources', () => {
    const chart = mount();
    const original = chart.addIndicator('sma', { length: 2 });
    const baseline = chart.getState();
    let starts = 0;
    chart.on('state:restore:start', () => starts++);
    const state = { ...baseline, grid: { vertLines: false, horzLines: false }, indicators: [
      { indicatorId: 'sma', instanceId: 'first', settings: { source: reference('second') }, paneIndex: 0 },
      { indicatorId: 'sma', instanceId: 'second', settings: { source: reference('first') }, paneIndex: 0 },
    ] };
    expect(chart.restoreState(state).applied).toBe(false);
    expect(starts).toBe(0);
    expect(chart.indicators()).toEqual([original]);
    expect(chart.getState()).toEqual(baseline);
  });

  it('keeps a skipped descriptor reference unavailable through a save and reload', () => {
    const chart = mount();
    const state = chart.getState();
    state.indicators = [
      { indicatorId: 'sma', instanceId: 'consumer', settings: { length: 2, source: reference('absent') }, paneIndex: 0 },
      { indicatorId: 'missing-descriptor', instanceId: 'absent', settings: {}, paneIndex: 1 },
    ];
    expect(chart.restoreState(state).applied).toBe(true);
    const consumer = chart.indicators()[0];
    expect(consumer.settings().source).toEqual(reference('absent'));
    expect(consumer.values().ma).toEqual([null, null, null, null]);
    expect(consumer.dataStatus()?.state).toBe('error');
    const saved = chart.getState();
    expect(saved.indicators?.[0].studyInputs).toEqual(['source']);
    expect(chart.restoreState(JSON.parse(JSON.stringify(saved))).applied).toBe(true);
    expect(chart.indicators()[0].dataStatus()?.state).toBe('error');
  });
});
