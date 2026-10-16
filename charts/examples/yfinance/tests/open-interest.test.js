import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { PaneLegend, darkTheme } from '/dist/openalgo-charts.mjs';
import { makeCtx } from '../../../tests/helpers/fake-ctx';
import { fakeDom } from './helpers.js';
import { initVolume, setLegend } from '../src/volume.js';
import { initCompare } from '../src/compare.js';
import { initStatus } from '../src/status.js';
import { chartSettingUnavailable, initChartSettings } from '../src/chart-settings.js';
import * as context from '../src/expression.js';

let previousDocument;
let app;
beforeEach(() => {
  previousDocument = globalThis.document;
  fakeDom();
  app = {
    req: { symbol: 'CONTRACT', interval: '1m' },
    chart: { hasOpenInterest: true, primaryBars: () => app.currentBars },
    comparisons: [], currentBars: [], idxByTime: new Map(),
    symbolLegend: new PaneLegend({ id: 'price', title: 'Contract', actions: [] }),
  };
  initVolume(app);
  initCompare(app);
  initStatus(app);
  initChartSettings(app);
});
afterEach(() => { globalThis.document = previousDocument; });

function texts() {
  const { ctx, rec } = makeCtx();
  const out = [];
  rec.fillText = text => out.push(text);
  app.symbolLegend.draw(ctx, { dpr: 1, theme: darkTheme, plotWidth: 1200 });
  return out;
}

const bar = { time: 100, open: 100, high: 101, low: 99, close: 100, volume: 20, oi: 0 };

describe('reference-host open interest', () => {
  it('retains same-instrument metadata across rebuilds and marks arithmetic unsupported', () => {
    expect(typeof context.referenceDataContext).toBe('function');
    const previous = { symbol: 'ES=F', interval: '1m', hasOpenInterest: true };
    expect(context.referenceDataContext({ symbol: 'ES=F', interval: '5m' }, previous))
      .toEqual({ symbol: 'ES=F', interval: '5m', hasOpenInterest: true });
    expect(context.referenceDataContext({ symbol: 'AAPL', interval: '5m' }, previous))
      .toEqual({ symbol: 'AAPL', interval: '5m' });
    expect(context.referenceDataContext({ symbol: 'AAPL/MSFT', interval: '5m' }, previous))
      .toEqual({ symbol: 'AAPL/MSFT', interval: '5m', hasOpenInterest: false });
  });

  it('feeds a zero to the OI switch and removes a missing reading from the canvas', () => {
    setLegend(bar);
    expect(texts()).not.toContain('OI');
    app.symbolLegend.setOptions({ statusLine: { openInterest: true } });
    expect(texts()).toContain('OI');
    expect(texts()).toContain('0');
    setLegend({ ...bar, oi: undefined });
    expect(texts()).not.toContain('OI');
    setLegend({ ...bar, oi: 1500 });
    expect(texts()).toContain('1.50K');
  });

  it('suppresses unsupported data and leaves an unknown capability observable', () => {
    app.symbolLegend.setOptions({ statusLine: { openInterest: true } });
    app.chart.hasOpenInterest = false;
    setLegend(bar);
    expect(texts()).not.toContain('OI');
    expect(typeof chartSettingUnavailable('statusLine.openInterest')).toBe('string');
    app.chart.hasOpenInterest = undefined;
    setLegend(bar);
    expect(texts()).toContain('OI');
    expect(chartSettingUnavailable('statusLine.openInterest')).toBeNull();
  });
});
