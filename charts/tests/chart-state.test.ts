import { describe, it, expect } from 'vitest';
import '../src/indicators/index'; // register built-ins so restore can recreate them
import { Chart } from '../src/core/chart';
import { DataLayer } from '../src/model/data-layer';
import { CHART_STATE_VERSION } from '../src/model/chart-state';
import { fakeDocument } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';

const bars = (n: number, step = 60): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = 100 + Math.sin(i / 4) * 5;
    return { time: 1700000000 + i * step, open: c, high: c + 1, low: c - 1, close: c, volume: 10 + i };
  });

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

describe('DataLayer fractional time mapping', () => {
  const layer = (): DataLayer => {
    const d = new DataLayer();
    const id = d.createSeries();
    d.setSeriesData(id, bars(5)); // times 1700000000 + i*60
    return d;
  };

  it('returns exact bar times at whole indices', () => {
    const d = layer();
    expect(d.indexToTimeFloat(0)).toBe(1700000000);
    expect(d.indexToTimeFloat(4)).toBe(1700000240);
  });

  it('interpolates between bars: the positions a gapless axis collapses', () => {
    expect(layer().indexToTimeFloat(1.5)).toBe(1700000090);
  });

  it('extrapolates past both edges at the local bar spacing', () => {
    const d = layer();
    expect(d.indexToTimeFloat(6)).toBe(1700000240 + 2 * 60); // right of the last bar
    expect(d.indexToTimeFloat(-2)).toBe(1700000000 - 2 * 60);
  });

  it('round-trips through timeToIndexFloat', () => {
    const d = layer();
    for (const index of [-3, 0, 1.5, 2, 3.25, 4, 7.5]) {
      expect(d.timeToIndexFloat(d.indexToTimeFloat(index))).toBeCloseTo(index, 9);
    }
  });

  it('degrades safely with no data and with one bar', () => {
    const empty = new DataLayer();
    expect(Number.isNaN(empty.indexToTimeFloat(3))).toBe(true);
    expect(Number.isNaN(empty.timeToIndexFloat(1700000000))).toBe(true);

    const one = new DataLayer();
    one.setSeriesData(one.createSeries(), bars(1));
    expect(one.indexToTimeFloat(5)).toBe(1700000000);
    expect(one.timeToIndexFloat(1700009999)).toBe(0);
  });

  it('handles an irregular (gap-collapsed) time axis', () => {
    const d = new DataLayer();
    const id = d.createSeries();
    // A weekend gap: Fri, Mon, Tue. The collapsed axis has no index inside it.
    d.setSeriesData(id, [
      { time: 1000, open: 1, high: 1, low: 1, close: 1 },
      { time: 300000, open: 1, high: 1, low: 1, close: 1 },
      { time: 386400, open: 1, high: 1, low: 1, close: 1 },
    ]);
    expect(d.indexToTimeFloat(0.5)).toBe((1000 + 300000) / 2);
    expect(d.timeToIndexFloat(300000)).toBe(1);
  });
});

describe('chart.getState / restoreState', () => {
  it('omits cleared optional series styles from its portable snapshot', () => {
    const chart = makeChart();
    const series = chart.addSeries('line', { style: { title: 'Profile', color: '#123456' } });
    series.setData(bars(20));
    series.applyOptions({ title: undefined });
    const state = chart.getState();
    expect(state.series?.[0].style).not.toHaveProperty('title');
    expect(state.series?.[0].style.color).toBe('#123456');
    expect(state).toEqual(JSON.parse(JSON.stringify(state)));
    chart.destroy();
  });

  it('captures a JSON-safe snapshot', () => {
    const chart = makeChart();
    chart.addSeries('candlestick', { style: { upColor: '#123456' } }).setData(bars(50));
    const state = chart.getState();
    // A chart with its price pane on top is written in the oldest shape that
    // describes it, so every reader since the first opens it; version 2 is for
    // a moved price pane only (see primary-pane-reorder.test.ts).
    expect(state.version).toBe(1);
    expect(CHART_STATE_VERSION).toBe(2);
    expect(state).not.toHaveProperty('primaryPane');
    expect(() => JSON.parse(JSON.stringify(state))).not.toThrow();
    expect(state.series?.[0]).toMatchObject({ type: 'candlestick', paneIndex: 0, priceScaleId: 'right' });
    expect(state.series?.[0].style.upColor).toBe('#123456');
    expect(state.panes).toHaveLength(1);
  });

  it('round-trips grid, crosshair mode, and pane price-scale settings', () => {
    const a = makeChart();
    a.addSeries('candlestick').setData(bars(50));
    a.setGridOptions({ vertLines: false, horzLines: true });
    a.applyOptions({ crosshairMode: 'magnet' });
    a.panes()[0].priceScale.setOptions({ mode: 'logarithmic', inverted: true, marginTop: 0.2 });
    a.panes()[0].priceScale.setAutoScale(false);
    a.panes()[0].priceScale.setPriceRange({ min: 90, max: 110 });
    const state = JSON.parse(JSON.stringify(a.getState()));

    const b = makeChart();
    b.addSeries('candlestick').setData(bars(50));
    const report = b.restoreState(state);
    expect(report.applied).toBe(true);
    expect(b.gridOptions()).toEqual({ vertLines: false, horzLines: true });
    const scale = b.panes()[0].priceScale;
    expect(scale.options.mode).toBe('logarithmic');
    expect(scale.options.inverted).toBe(true);
    expect(scale.options.marginTop).toBe(0.2);
    expect(scale.autoScale).toBe(false);
    expect(scale.priceRange()).toEqual({ min: 90, max: 110 });
  });

  it('recreates indicators with their settings and pane', () => {
    const a = makeChart();
    a.addSeries('candlestick').setData(bars(60));
    a.addIndicator('macd', { fastPeriod: 8 });
    a.addIndicator('ema', { length: 55 });
    const state = JSON.parse(JSON.stringify(a.getState()));
    expect(state.indicators).toHaveLength(2);

    const b = makeChart();
    b.addSeries('candlestick').setData(bars(60));
    const report = b.restoreState(state);
    expect(report.indicators).toBe(2);
    expect(b.indicators().map((i) => i.indicatorId)).toEqual(['macd', 'ema']);
    expect(b.indicators()[0].settings().fastPeriod).toBe(8);
    expect(b.indicators()[1].settings().length).toBe(55);
    expect(b.indicators()[0].values().macd).toHaveLength(60);
  });

  it('is idempotent: restoring twice does not duplicate indicators', () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(40));
    chart.addIndicator('rsi');
    const state = JSON.parse(JSON.stringify(chart.getState()));
    chart.restoreState(state);
    chart.restoreState(state);
    expect(chart.indicators()).toHaveLength(1);
  });

  it('reports series descriptors rather than recreating them', () => {
    const a = makeChart();
    a.addSeries('candlestick').setData(bars(30));
    a.addSeries('histogram', { paneIndex: 1 }).setData(bars(30));
    const state = JSON.parse(JSON.stringify(a.getState()));

    const b = makeChart();
    const report = b.restoreState(state);
    expect(report.series).toHaveLength(2);
    expect(report.series[1]).toMatchObject({ type: 'histogram', paneIndex: 1 });
    // The chart has no data for them, so it must not have invented series.
    expect(b.panes()[0].series()).toHaveLength(0);
  });

  it('skips indicators whose tier is not loaded instead of throwing', () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(30));
    const report = chart.restoreState({
      version: CHART_STATE_VERSION,
      indicators: [{ indicatorId: 'not-registered', settings: {}, paneIndex: 1 }],
    });
    expect(report.applied).toBe(true);
    expect(report.indicators).toBe(0);
  });

  it('rejects junk and future versions without throwing', () => {
    const chart = makeChart();
    expect(chart.restoreState(null).applied).toBe(false);
    expect(chart.restoreState('nope').applied).toBe(false);
    expect(chart.restoreState({}).applied).toBe(false);
    const future = chart.restoreState({ version: CHART_STATE_VERSION + 1 });
    expect(future.applied).toBe(false);
    expect(future.reason).toMatch(/newer/);
  });

  it('round-trips the opaque drawings slot untouched', () => {
    const chart = makeChart();
    const payload = { tools: [{ id: 'a', points: [{ time: 1, price: 2 }] }] };
    chart.setDrawingState(payload);
    const state = JSON.parse(JSON.stringify(chart.getState()));
    expect(state.drawings).toEqual(payload);

    const other = makeChart();
    other.restoreState(state);
    expect(other.drawingState()).toEqual(payload);
  });

  it('restores the viewport once data exists', () => {
    const a = makeChart();
    a.addSeries('candlestick').setData(bars(200));
    a.setVisibleLogicalRange({ from: 50, to: 120 });
    const state = JSON.parse(JSON.stringify(a.getState()));

    const b = makeChart();
    b.addSeries('candlestick').setData(bars(200));
    b.restoreState(state);
    const range = b.getVisibleLogicalRange();
    expect(range.to - range.from).toBeCloseTo(70, 6);
  });
});

describe('restoreState never leaves an empty pane', () => {
  // A saved pane exists only to hold an indicator, and restoreState skips an
  // indicator whose tier was never imported. The pane used to survive anyway:
  // still claiming its weight and still drawing a default 0..100 axis, which
  // reads as a large blank region under the chart.
  it('drops a pane whose indicator could not be recreated', () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(60));

    const state = {
      version: 1,
      panes: [
        { weight: 1, priceScale: { marginTop: 0.1, marginBottom: 0.1, autoScale: true } },
        { weight: 2, priceScale: { marginTop: 0.1, marginBottom: 0.1, autoScale: true } },
      ],
      // No such indicator, so restoreState skips it: the same path a state
      // referencing an unloaded tier takes.
      indicators: [{ indicatorId: 'no-such-indicator', settings: {}, paneIndex: 1 }],
      series: [],
    };

    const report = chart.restoreState(state);
    expect(report.applied).toBe(true);
    expect(report.indicators).toBe(0);          // unknown id -> skipped
    expect(chart.panes()).toHaveLength(1);      // ...and its pane went with it
    expect(chart.panes()[0].series().length).toBeGreaterThan(0);
  });

  it('keeps a pane that still holds a series', () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    chart.addSeries('histogram', { paneIndex: 1 })
      .setData([{ time: 1700000000, open: 0, high: 5, low: 0, close: 5 }]);
    expect(chart.panes()).toHaveLength(2);

    chart.restoreState({
      version: 1,
      panes: [
        { weight: 1, priceScale: { marginTop: 0.1, marginBottom: 0.1, autoScale: true } },
        { weight: 2, priceScale: { marginTop: 0.1, marginBottom: 0.1, autoScale: true } },
      ],
      indicators: [],
      series: [],
    });
    // Pane 1 is host-owned, not indicator-owned, so it must survive.
    expect(chart.panes()).toHaveLength(2);
  });
});

describe('an emptied indicator pane never survives', () => {
  // The pruning used to live only in the pane legend's close handler, so the
  // on-chart X cleaned up but `chart.removeIndicator(id)` from a host's own UI
  // did not. The orphan pane then went into getState, and every reload restored
  // a blank region under the chart.
  it('removeIndicator prunes the pane it emptied', () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    // RSI lives in its own pane.
    const rsi = chart.addIndicator('rsi');
    expect(chart.panes().length).toBeGreaterThan(1);
    const pane = rsi.paneIndex;
    expect(pane).toBeGreaterThan(0);

    // The host's own UI calls this directly: it used to leave the pane behind.
    chart.removeIndicator(rsi.id);
    expect(chart.panes()).toHaveLength(1);
  });

  it('keeps the pane when a host series shares it', () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    const rsi = chart.addIndicator('rsi');
    const pane = rsi.paneIndex;
    chart.addSeries('line', { paneIndex: pane })
      .setData([{ time: 1700000000, open: 1, high: 1, low: 1, close: 1 }]);

    chart.removeIndicator(rsi.id);
    // Something the host put there is still in it, so the pane stays.
    expect(chart.panes()).toHaveLength(2);
  });

  it('getState does not persist a pane with nothing in it', () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(40));
    const state = chart.getState() as { panes: unknown[] };
    // One series, one pane: a second entry here is what produced the gap.
    expect(state.panes).toHaveLength(chart.panes().length);
  });
});

describe('maximize bookkeeping survives pane removal', () => {
  // Maximize names a pane rather than rewriting weights, so what has to survive
  // a removal is the index. Left alone it points at whichever pane inherited
  // the slot, and the wrong one fills the chart.
  const threePaneChart = (): ReturnType<typeof makeChart> => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(40));
    chart.addSeries('line', { paneIndex: 1 })
      .setData([{ time: 1700000000, open: 1, high: 1, low: 1, close: 1 }]);
    chart.addSeries('line', { paneIndex: 2 })
      .setData([{ time: 1700000000, open: 2, high: 2, low: 2, close: 2 }]);
    return chart;
  };

  it('leaves the stored weights untouched while maximized', () => {
    const chart = threePaneChart();
    const before = chart.panes().map((p) => p.weight);
    chart.maximizePane(0);
    expect(chart.panes().map((p) => p.weight)).toEqual(before);
    // getState therefore cannot persist a placeholder weight.
    const state = chart.getState() as { panes: { weight: number }[] };
    expect(state.panes.map((p) => p.weight)).toEqual(before);
  });

  it('drops the maximize when the maximized pane is removed', () => {
    const chart = threePaneChart();
    chart.maximizePane(2);
    chart.removePane(2);
    expect(chart.maximizedPane()).toBeNull();
    for (const p of chart.panes()) expect(p.weight).toBeGreaterThan(0.01);
  });

  it('shifts the maximize up when a pane above it is removed', () => {
    const chart = threePaneChart();
    chart.maximizePane(2);
    chart.removePane(1);
    expect(chart.maximizedPane()).toBe(1);
  });
});

describe('drag carries time as well as price', () => {
  it('maps container x to a time on the gapless axis', () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(100));
    // A round-trip through the public coordinate helpers is the contract the
    // drag callback's `time` argument relies on.
    const t = chart.coordinateToTime(400);
    expect(Number.isFinite(t)).toBe(true);
    expect(chart.timeToCoordinate(t)).toBeCloseTo(400, 6);
  });

  it('gives a usable time to the right of the last bar', () => {
    const chart = makeChart();
    const data = bars(100);
    chart.addSeries('candlestick').setData(data);
    const lastX = chart.timeToCoordinate(data[99].time);
    const beyond = chart.coordinateToTime(lastX + 200);
    expect(beyond).toBeGreaterThan(data[99].time);
  });
});
