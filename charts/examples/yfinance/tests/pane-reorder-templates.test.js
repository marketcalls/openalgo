import { afterEach, describe, expect, it, vi } from 'vitest';
vi.mock('/dist/openalgo-charts.mjs', () => import('../../../src/index.ts'));
vi.mock('/dist/openalgo-charts.workspace.mjs', () => import('../../../src/workspace/index.ts'));
vi.mock('openalgo-charts', () => import('../../../src/index.ts'));
import { Chart } from '../../../src/index.ts';
import '../../../src/indicators/index.ts';
import { DrawingController } from '../../../src/draw/index.ts';
import { fakeDocument } from '../../../tests/helpers/fake-dom';
import { captureIndicatorTemplate, applyIndicatorTemplate } from '../src/indicator-templates.js';

const charts = [];
afterEach(() => charts.splice(0).forEach(chart => chart.destroy()));
const bars = Array.from({ length: 80 }, (_, i) => {
  const close = 100 + Math.sin(i / 5) * 4;
  return { time: 1700000000 + i * 60, open: close, high: close + 1, low: close - 1, close };
});

/**
 * The host's chart with RSI and MACD panes, and optionally the price pane moved
 * to the bottom. Built with `movablePrimaryPane`, as main.js and split.js build
 * the host's charts.
 */
function mount(studies = ['rsi', 'macd'], bottom = true) {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, pixelRatio: () => 1, shortcuts: false, raf: { schedule: () => 1, cancel: () => {} },
    movablePrimaryPane: true,
  });
  charts.push(chart);
  chart.applySize(800, 500);
  chart.setDataContext({ symbol: 'HOST', interval: '1m' });
  chart.addSeries('candlestick').setData(bars);
  for (const study of studies) chart.addIndicator(study);
  if (bottom) chart.setPrimaryPaneIndex(chart.panes().length - 1);
  const app = { chart, chart2: null, activeIndicators: [] };
  const target = { pane: 1, chart, current: () => true };
  return { app, target, chart };
}

describe('host templates on a chart with its price pane at the bottom', () => {
  it('replaces the studies and keeps the price pane and its drawings at the bottom', () => {
    const donor = mount(['rsi', 'cci'], false);
    const payload = captureIndicatorTemplate(donor.app, donor.target);
    const h = mount();
    const draw = new DrawingController(h.chart);
    const line = draw.add({ tool: 'horizontal-line', paneIndex: 2, style: {}, points: [{ time: bars[10].time, price: 100 }] });
    applyIndicatorTemplate(h.app, h.target, payload, 'replace');
    expect(h.chart.indicators().map(item => [item.indicatorId, item.paneIndex])).toEqual([['rsi', 0], ['cci', 1]]);
    expect(h.chart.primaryPaneIndex()).toBe(2);
    expect(h.chart.panes()[2].series()[0].type).toBe('candlestick');
    expect(draw.get(line.id)?.paneIndex).toBe(2);
    draw.destroy();
  });

  it('captures the same portable template whichever slot the price pane holds', () => {
    const top = mount(['rsi'], false), bottom = mount(['rsi'], true);
    const strip = payload => payload.indicators.map(({ indicatorId, paneIndex }) => [indicatorId, paneIndex]);
    const a = captureIndicatorTemplate(top.app, top.target), b = captureIndicatorTemplate(bottom.app, bottom.target);
    expect(strip(a)).toEqual([['rsi', 1]]);
    expect(strip(b)).toEqual(strip(a));
    expect(b.layout.panes.map(pane => pane.weight)).toEqual(a.layout.panes.map(pane => pane.weight));
  });

  it('puts the price pane back where it was when the chart refuses a template', () => {
    const donor = mount(['rsi'], false);
    const payload = captureIndicatorTemplate(donor.app, donor.target);
    const h = mount();
    const restore = h.chart.restoreState.bind(h.chart);
    let calls = 0;
    // The first restore reports failure after landing; the rollback must bring the old stack back.
    h.chart.restoreState = (state, options) => { const report = restore(state, options); return ++calls === 1 ? { ...report, applied: false, reason: 'refused' } : report; };
    expect(() => applyIndicatorTemplate(h.app, h.target, payload, 'replace')).toThrow(/refused/);
    expect(h.chart.primaryPaneIndex()).toBe(2);
    expect(h.chart.indicators().map(item => [item.indicatorId, item.paneIndex])).toEqual([['rsi', 0], ['macd', 1]]);
  });
});
