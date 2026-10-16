// The demo's timeline against real charts from the built library: steps kept
// across the rebuild a load or a type switch makes, the type switch itself as
// a command, the demo's own changes left out, and the drawing controller's
// own history as the fallback before a chart has a timeline.
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { applyChartSettings, createChart, createLinkGroup, registerIndicator } from '/dist/openalgo-charts.mjs';
import { DrawingController } from '/dist/openalgo-charts.draw.mjs';
import { fakeDocument } from '../../../tests/helpers/fake-dom';
import {
  initHistory, attachHistory, historyFor, historyPress, historyReady, withoutHistory, asStep, historyGroup, recordChartType,
} from '../src/history.js';
import { initSplit, joinLink } from '../src/split.js';

const bars = Array.from({ length: 60 }, (_, i) => {
  const close = 100 + 10 * Math.sin(i / 4);
  return { time: 1_700_000_000 + i * 86400, open: close - 1, high: close + 2, low: close - 2, close, volume: 100 };
});

beforeAll(() => {
  globalThis.window ??= {};
  registerIndicator({
    id: 'demo-history-study', name: 'Demo history study', placement: 'pane',
    inputs: [{ key: 'length', type: 'number', label: 'Length', default: 5 }],
    plots: [{ key: 'value', title: 'Value', type: 'line' }],
    calc: b => ({ value: b.map(x => x.close) }),
  });
});
const charts = [];
afterEach(() => { for (const chart of charts.splice(0)) if (!chart.isDestroyed) chart.destroy(); });

function build(type = 'candlestick', state) {
  const chart = createChart(fakeDocument().createElement('div'), {
    document: fakeDocument(), pixelRatio: () => 1, shortcuts: false, timeNavigator: false,
    raf: { schedule: callback => { callback(); return 1; }, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(900, 600);
  chart.addSeries(type).setData(bars);
  const draw = new DrawingController(chart);
  if (state) chart.restoreState({ ...state, series: [] });
  return { chart, draw };
}
const settle = () => new Promise(resolve => setTimeout(resolve, 0));

function demo() {
  const app = { focusPane: 1, afterHistory: vi.fn() };
  initHistory(app);
  Object.assign(app, build());
  attachHistory(1);
  return app;
}

describe('the demo timeline', () => {
  it('keeps its steps through the rebuild a load or a type switch makes', async () => {
    const app = demo();
    const study = app.chart.addIndicator('demo-history-study');
    await settle();
    study.setSettings({ length: 9 });
    await settle();
    const history = historyFor(1);

    // The demo throws the chart away and builds another from its state.
    const state = app.chart.getState();
    app.chart.destroy();
    Object.assign(app, build('line', state));
    attachHistory(1);
    expect(historyFor(1)).toBe(history);
    expect(historyReady('undo')).toBe(true);

    expect(historyPress('undo')).toBe(true);
    expect(app.chart.indicators()[0].settings().length).toBe(5);
    expect(app.afterHistory).toHaveBeenCalledWith(1);
    historyPress('undo');
    expect(app.chart.indicators()).toHaveLength(0);
    historyPress('redo');
    expect(app.chart.indicators()).toHaveLength(1);
  });

  it('records a type switch as a command that rebuilds with the type it replaced', async () => {
    const app = demo();
    let shown = 'candlestick';
    const show = type => {
      shown = type.chartType;
      const state = app.chart.getState();
      app.chart.destroy();
      Object.assign(app, build(type.chartType, state));
      attachHistory(1);
    };
    show({ chartType: 'line', transforms: {} });
    recordChartType(1, { chartType: 'candlestick', transforms: {} }, { chartType: 'line', transforms: {} }, show);
    recordChartType(1, { chartType: 'line', transforms: {} }, { chartType: 'line', transforms: {} }, show);   // no switch, no step
    app.chart.addIndicator('demo-history-study');
    await settle();

    historyPress('undo');
    expect(app.chart.indicators()).toHaveLength(0);
    historyPress('undo');
    expect(shown).toBe('candlestick');
    expect(app.chart.seriesType(app.chart.primarySeries())).toBe('candlestick');
    expect(historyReady('undo')).toBe(false);
    historyPress('redo');
    expect(shown).toBe('line');
    historyPress('redo');
    expect(app.chart.indicators()).toHaveLength(1);
  });

  it('records new transform options as a step of their own, and the same options as none', () => {
    const app = demo();
    const shown = [];
    const quarter = { 'point-figure': { mode: 'percent', percent: 0.25, reversal: 3, method: 'hl' } };
    const pf = transforms => ({ chartType: 't:point-figure', transforms });
    const apply = type => shown.push(type.transforms);
    // The defaults spelled out are the defaults: nothing changed, no step.
    recordChartType(1, pf({}), pf({ 'point-figure': { mode: 'atr', atrMultiplier: 1, atrPeriod: 14, reversal: 3, method: 'hl' } }), apply);
    expect(historyReady('undo')).toBe(false);
    recordChartType(1, pf({}), pf(quarter), apply, 'Point and figure settings');
    expect(historyFor(1).peekUndo().label).toBe('Point and figure settings');
    historyPress('undo');
    historyPress('redo');
    expect(shown).toEqual([{}, quarter]);
  });

  it('keeps the demo\'s own changes out, and records a scale change and a settings session as steps', async () => {
    const app = demo();
    withoutHistory(1, () => app.chart.setPriceAxisOptions(0, 'right', { mode: 'percentage' }));
    await settle();
    expect(historyReady('undo')).toBe(false);
    asStep(1, () => app.chart.setPriceAxisOptions(0, 'right', { inverted: true }), 'Price scale');
    // One axis inverted from its menu: the chart-wide defaults stay, so it is
    // an axis field alone and never a chart setting.
    expect(historyFor(1).peekUndo()).toEqual({ label: 'Price scale', changes: ['axis'] });
    expect(app.chart.priceScaleDefaults().inverted).toBeUndefined();
    const end = historyGroup(1, 'Chart settings');
    asStep(1, () => app.chart.setGridOptions({ vertLines: false }));
    asStep(1, () => app.chart.setGridOptions({ vertLines: true }));
    end();
    expect(historyFor(1).peekUndo()?.label).toBe('Price scale');
    historyPress('undo');
    expect(app.chart.priceAxisState(0, 'right')).toMatchObject({ inverted: false, mode: 'percentage' });
  });

  it('walks the drawing controller\'s own history before a chart has a timeline', () => {
    const app = { focusPane: 1 };
    initHistory(app);
    Object.assign(app, build());
    app.draw.add({ tool: 'horizontal-line', paneIndex: 0, points: [{ time: bars[5].time, price: 100 }], style: {} });
    expect(historyFor(1)).toBeNull();
    expect(historyReady('undo')).toBe(true);
    expect(historyPress('undo')).toBe(true);
    expect(app.draw.drawings()).toHaveLength(0);
  });

  it('acts on the focused chart', async () => {
    const app = demo();
    Object.assign(app, { chart2: build().chart });
    app.draw2 = new DrawingController(app.chart2);
    attachHistory(2);
    app.chart2.addIndicator('demo-history-study');
    await settle();
    app.focusPane = 2;
    expect(historyReady('undo')).toBe(true);
    expect(historyReady('undo', 1)).toBe(false);
    historyPress('undo');
    expect(app.chart2.indicators()).toHaveLength(0);
  });

  it('applies a linked appearance change to the other chart outside its timeline, and walks it back on both', async () => {
    // The split view's divider asks the page for its bar; nothing else here needs a document.
    vi.stubGlobal('document', { getElementById: () => ({ addEventListener() {} }) });
    try {
      const app = demo();
      Object.assign(app, { chart2: build().chart });
      app.draw2 = new DrawingController(app.chart2);
      attachHistory(2);
      initSplit(app);
      app.linkGroup = createLinkGroup({ appearance: true, crosshair: false, viewport: false });
      Object.assign(app, { req: { symbol: 'AAA', interval: '1d' }, p2: { symbol: 'BBB', interval: '1d' } });
      joinLink();
      const mode = chart => chart.priceAxisState(0, 'right')?.mode;

      historyFor(1).transact(() => applyChartSettings(app.chart, { 'scales.mode': 'logarithmic' }), 'Chart settings');
      expect(mode(app.chart2)).toBe('logarithmic');
      expect(historyReady('undo', 2)).toBe(false);
      app.chart2.addIndicator('demo-history-study');
      await settle();
      expect(historyFor(2).peekUndo()?.changes).toEqual(['study-add']);
      historyPress('undo', 2);
      expect([mode(app.chart), mode(app.chart2)]).toEqual(['logarithmic', 'logarithmic']);
      historyPress('undo', 1);
      expect([mode(app.chart), mode(app.chart2)]).toEqual(['linear', 'linear']);
      historyPress('redo', 1);
      expect([mode(app.chart), mode(app.chart2)]).toEqual(['logarithmic', 'logarithmic']);
      app.linkGroup.destroy();
      app.drawingLinkGroup.destroy();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
