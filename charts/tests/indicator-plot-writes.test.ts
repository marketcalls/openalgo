/**
 * A study's plots on a live tick: the shared time index is left alone and each
 * plot series takes only the points that moved, while every reader still sees
 * exactly what a whole rewrite would have given it.
 *
 * The reference for "a whole rewrite" is the mapping every recompute used to
 * hand `setData`, written out again below, applied to the study's current
 * values: a plot series must hold that, point for point and key for key.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { DataLayer } from '../src/model/data-layer';
import { exportChartDataCsv } from '../src/model/chart-data-export';
import { getIndicator, registerIndicator, type IndicatorDescriptor, type IndicatorPlot, type IndicatorSettings, type IndicatorValues } from '../src/model/indicator-registry';
import type { IndicatorApi } from '../src/model/indicator-instance';
import type { SeriesApi } from '../src/model/series';
import { toBar, type Bar } from '../src/model/bar';
import { ReplayController } from '../src/replay/controller';
import { addComparison } from '../src/compare/controller';
import { fakeDocument } from './helpers/fake-dom';
import '../src/indicators/index';

/** Ten studies a busy terminal runs, on the price pane and in panes of their own. */
const STUDIES = ['ema', 'bollinger', 'rsi', 'macd', 'volume', 'supertrend', 'adx', 'stochastic', 'vwap', 'atr'];
const STEP = 900;
const T0 = 1_735_689_600;

const cleanup: (() => void)[] = [];
afterEach(() => {
  for (const dispose of cleanup.splice(0).reverse()) dispose();
  vi.restoreAllMocks();
});

/** Deterministic bars, `skip` left out so the history has a hole in it. */
function makeBars(count: number, skip: readonly number[] = []): Bar[] {
  let s = 20260926 >>> 0;
  const rnd = (): number => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0), s / 4294967296);
  const out: Bar[] = [];
  let price = 1000;
  for (let i = 0; i < count; i++) {
    const open = price;
    const close = 1000 + Math.sin(i / 17) * 18 + (rnd() - 0.5) * 6;
    const bar = { time: T0 + i * STEP, open, high: Math.max(open, close) + rnd() * 3, low: Math.min(open, close) - rnd() * 3, close, volume: Math.floor(1000 + rnd() * 9000) };
    if (!skip.includes(i)) out.push(bar);
    price = close;
  }
  return out;
}

/** A chart whose frames run when the test flushes them, the way a browser runs them. */
function setup(data: readonly Bar[]): { chart: Chart; series: SeriesApi; flush: () => void } {
  const doc = fakeDocument();
  const pending = new Map<number, () => void>();
  let handle = 1;
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: (cb) => { pending.set(handle, cb); return handle++; }, cancel: (h) => { pending.delete(h); } },
  });
  cleanup.push(() => chart.destroy());
  chart.applySize(900, 700);
  const flush = (): void => {
    for (let guard = 0; guard < 8 && pending.size > 0; guard++) {
      const batch = [...pending.values()];
      pending.clear();
      for (const cb of batch) cb();
    }
  };
  const series = chart.addSeries('candlestick');
  series.setData(data);
  flush();
  return { chart, series, flush };
}

/** What a recompute used to hand one plot's `setData`, normalised the way `setData` stores it. */
function wholeWrite(plot: IndicatorPlot, values: IndicatorValues, bars: readonly Bar[], settings: IndicatorSettings): Bar[] {
  const n = bars.length;
  const { colorBy, colorParts } = plot;
  if (plot.ohlc !== undefined) {
    const cols = [plot.ohlc.open, plot.ohlc.high, plot.ohlc.low, plot.ohlc.close].map((key) => values[key]);
    return bars.map((source, i) => {
      const close = cols[3][i];
      const value = close === null ? NaN : close;
      const bar: Bar = { time: source.time, open: cols[0][i] ?? NaN, high: cols[1][i] ?? NaN, low: cols[2][i] ?? NaN, close: value };
      if (Number.isFinite(value)) {
        const c = colorBy?.({ value, index: i, values, settings });
        if (c !== undefined) bar.color = c;
        const parts = colorParts?.({ value, index: i, values, settings });
        if (parts !== undefined) {
          if (parts.body !== undefined) bar.color = parts.body;
          if (parts.wick !== undefined) bar.wickColor = parts.wick;
          if (parts.border !== undefined) bar.borderColor = parts.border;
        }
      }
      return bar;
    });
  }
  const col = values[plot.key];
  if (col === undefined) return [];
  const out: { time: number; value: number; color?: string }[] = [];
  for (let i = 0; i < n; i++) {
    const v = col[i];
    const value = v === null || v === undefined ? NaN : v;
    const point: { time: number; value: number; color?: string } = { time: bars[i].time, value };
    if (Number.isFinite(value)) {
      const body = colorParts?.({ value, index: i, values, settings })?.body ?? colorBy?.({ value, index: i, values, settings });
      if (body !== undefined) point.color = body;
    }
    out.push(point);
  }
  return out.map(toBar);
}

function plotsOf(study: IndicatorApi): { plot: IndicatorPlot; api: SeriesApi }[] {
  return getIndicator(study.indicatorId).plots.flatMap((plot) => {
    const api = study.series(plot.key);
    return api === undefined ? [] : [{ plot, api }];
  });
}

/** A second instrument on the same clock, so a comparison overlay rides along through every step. */
const second = (bars: readonly Bar[]): Bar[] => bars.map((b) => ({ ...b, open: b.open * 2, high: b.high * 2, low: b.low * 2, close: b.close * 2 }));

/** Every plot series holds what a whole rewrite of the study's current values gives, keys in the same order. */
function expectWholeWriteContent(chart: Chart, series: SeriesApi, studies: readonly IndicatorApi[]): void {
  const bars = series.getData();
  for (const study of studies) {
    for (const { plot, api } of plotsOf(study)) {
      const expected = wholeWrite(plot, study.values(), bars, study.settings());
      const actual = api.getData();
      expect(actual, `${study.indicatorId}.${plot.key}`).toStrictEqual(expected);
      expect(JSON.stringify(actual), `${study.indicatorId}.${plot.key} key order`).toBe(JSON.stringify(expected));
    }
  }
  expect(chart.dataLayer.length).toBe(new Set(bars.map((b) => b.time)).size);
}

/** Counts what the plot series receive and how often the time index is rebuilt. */
function watch(studies: readonly IndicatorApi[]): { rebuilds: () => number; wholes: () => number; points: () => number } {
  const rebuild = vi.spyOn(DataLayer.prototype as unknown as { _rebuild(): void }, '_rebuild');
  const apis = studies.flatMap((study) => plotsOf(study).map(({ api }) => api));
  const setData = apis.map((api) => vi.spyOn(api, 'setData'));
  const update = apis.map((api) => vi.spyOn(api, 'update'));
  const calls = (spies: readonly { mock: { calls: unknown[] } }[]): number => spies.reduce((sum, spy) => sum + spy.mock.calls.length, 0);
  return { rebuilds: () => rebuild.mock.calls.length, wholes: () => calls(setData), points: () => calls(update) };
}

describe('a live tick leaves the time index alone', () => {
  it('a forming-bar update and an appended bar rebuild nothing and write each plot in place', () => {
    const { chart, series, flush } = setup(makeBars(400));
    const studies = STUDIES.map((id) => chart.addIndicator(id));
    const comparison = addComparison(chart, { symbol: 'SECOND', bars: second(makeBars(401)) });
    flush();
    const plots = studies.reduce((sum, study) => sum + plotsOf(study).length, 0);
    const seen = watch(studies);
    let last = series.getData()[399];

    last = { ...last, close: last.close + 2.5, high: last.high + 2.5 };
    series.update(last);
    flush();
    expect(seen.rebuilds()).toBe(0);
    expect(seen.wholes()).toBe(0);
    expect(seen.points()).toBeLessThanOrEqual(plots * 2);
    expectWholeWriteContent(chart, series, studies);

    last = { time: last.time + STEP, open: last.close, high: last.close + 1, low: last.close - 3, close: last.close - 2, volume: 900 };
    series.update(last);
    flush();
    expect(seen.rebuilds()).toBe(0);
    expect(seen.wholes()).toBe(0);
    expect(series.getData()).toHaveLength(401);
    expectWholeWriteContent(chart, series, studies);
    expect(comparison.barAt(last.time)?.close).toBe(second(makeBars(401))[400].close);
  });

  it('a page of older history rebuilds the index once, for the source, and the plots follow whole', () => {
    const all = makeBars(400);
    const { chart, series, flush } = setup(all.slice(100));
    const studies = STUDIES.map((id) => chart.addIndicator(id));
    flush();
    const seen = watch(studies);
    series.prependData(all.slice(0, 100));
    flush();
    expect(seen.rebuilds()).toBe(1);
    expect(seen.wholes()).toBeGreaterThan(0);
    expect(seen.points()).toBe(0);
    expectWholeWriteContent(chart, series, studies);
  });

  it('a late bar filling a gap in the history rebuilds the index once, and the plots follow whole', () => {
    const hole = 250;
    const { chart, series, flush } = setup(makeBars(400, [hole]));
    const studies = STUDIES.map((id) => chart.addIndicator(id));
    flush();
    const seen = watch(studies);
    series.update(makeBars(400)[hole]);
    flush();
    expect(series.getData()).toHaveLength(400);
    expect(seen.rebuilds()).toBe(1);
    expect(seen.wholes()).toBeGreaterThan(0);
    expectWholeWriteContent(chart, series, studies);
  });
});

describe('every reader sees what a whole rewrite gives it', () => {
  const coloured: IndicatorDescriptor = {
    id: 'plot-writes-coloured', name: 'Coloured', placement: 'pane', inputs: [],
    plots: [
      { key: 'diff', type: 'histogram', title: 'Diff', colorBy: ({ value }) => (value >= 0 ? '#26a69a' : '#ef5350') },
      { key: 'gappy', type: 'line', title: 'Gappy' },
      // Coloured by the bar after it, so the forming bar recolours the one before it.
      { key: 'lead', type: 'line', title: 'Lead', colorBy: ({ index, values }) => ((values.diff[index + 1] ?? 0) >= 0 ? '#1e88e5' : '#fb8c00') },
    ],
    calc: (bars) => ({
      diff: bars.map((b) => b.close - b.open),
      lead: bars.map((b) => b.open),
      // Holes and NaN in the middle of a column are points too.
      gappy: bars.map((b, i) => (i % 7 === 0 ? null : i % 11 === 0 ? NaN : b.close)),
    }),
  };
  const candles: IndicatorDescriptor = {
    id: 'plot-writes-candles', name: 'Candles', placement: 'pane', inputs: [],
    plots: [{
      key: 'c', type: 'candlestick', title: 'Candles',
      ohlc: { open: 'o', high: 'h', low: 'l', close: 'x' },
      colorBy: ({ index, values }) => ((values.x[index] ?? 0) >= (values.o[index] ?? 0) ? '#0a0' : undefined),
      colorParts: ({ value }) => (value > 1000 ? { wick: '#123456' } : { body: '#654321', border: '#abcdef' }),
    }],
    calc: (bars) => ({
      o: bars.map((b) => b.open), h: bars.map((b) => b.high), l: bars.map((b) => b.low),
      x: bars.map((b, i) => (i === 3 ? null : b.close)),
    }),
  };
  // A study that revises all of its past on every bar: nothing can be kept.
  const rebased: IndicatorDescriptor = {
    id: 'plot-writes-rebased', name: 'Rebased', placement: 'pane', inputs: [],
    plots: [{ key: 'r', type: 'line', title: 'Rebased' }],
    calc: (bars) => {
      const last = bars[bars.length - 1]?.close ?? 1;
      return { r: bars.map((b) => b.close / last) };
    },
  };

  it('through ticks, appends, a burst between frames, a correction, new settings and a page of history', () => {
    for (const d of [coloured, candles, rebased]) registerIndicator(d);
    const all = makeBars(460);
    const { chart, series, flush } = setup(all.slice(60, 360));
    const studies = [...STUDIES, coloured.id, candles.id, rebased.id].map((id) => chart.addIndicator(id));
    addComparison(chart, { symbol: 'SECOND', bars: second(all) });
    flush();
    expectWholeWriteContent(chart, series, studies);
    const seen = watch(studies);
    let last = series.getData()[series.getData().length - 1];
    const tick = (close: number): void => {
      last = { ...last, close, high: Math.max(last.high, close), low: Math.min(last.low, close) };
      series.update(last);
    };
    const open = (): void => {
      last = { time: last.time + STEP, open: last.close, high: last.close, low: last.close, close: last.close, volume: 10 };
      series.update(last);
    };
    const csv: string[] = [];
    const steps: (() => void)[] = [
      () => tick(last.close + 4),
      () => tick(last.close - 9),
      () => tick(last.open), // back to where it opened: the body flips colour
      () => open(),
      () => tick(last.close + 1),
      () => { open(); tick(last.close + 3); open(); }, // three writes before one frame
      () => series.update({ ...series.getData()[120], close: series.getData()[120].close + 50 }), // a correction far back
      () => studies[0].setSettings({ length: 21 }),
      () => series.prependData(all.slice(0, 60)),
      () => tick(last.close - 1),
      () => open(),
    ];
    for (const step of steps) {
      step();
      flush();
      expectWholeWriteContent(chart, series, studies);
      csv.push(exportChartDataCsv(chart));
    }
    // The tick steps went in place; history, settings and the correction went whole.
    expect(seen.points()).toBeGreaterThan(0);
    expect(seen.wholes()).toBeGreaterThan(0);

    // The same history loaded at once, with the same settings, reads the same.
    const fresh = setup(series.getData());
    const again = studies.map((study) => fresh.chart.addIndicator(study.indicatorId, study.settings()));
    addComparison(fresh.chart, { symbol: 'SECOND', bars: second(all) });
    fresh.flush();
    for (const [i, study] of studies.entries()) {
      expect(again[i].values(), study.indicatorId).toStrictEqual(study.values());
      for (const { plot, api } of plotsOf(study)) {
        expect(again[i].series(plot.key)!.getData(), `${study.indicatorId}.${plot.key}`).toStrictEqual(api.getData());
      }
    }
    // Instance ids differ between the two charts; every value must not.
    const anonymous = (text: string): string => text.replace(/indicator:[^:,]+:/g, 'indicator:');
    expect(csv[csv.length - 1].split(/\r?\n/)[0]).toContain('comparison:1:SECOND:close');
    expect(anonymous(exportChartDataCsv(fresh.chart))).toBe(anonymous(csv[csv.length - 1]));
  });

  it('through replay: a step forward rebuilds nothing, and every prefix reads as a whole rewrite', () => {
    for (const d of [coloured, candles]) registerIndicator(d);
    const { chart, series, flush } = setup(makeBars(320));
    const studies = [...STUDIES, coloured.id, candles.id].map((id) => chart.addIndicator(id));
    flush();
    const replay = new ReplayController(chart, { startIndex: 200 });
    flush();
    expect(series.getData()).toHaveLength(201);
    expectWholeWriteContent(chart, series, studies);
    const seen = watch(studies);
    for (let i = 0; i < 4; i++) {
      replay.step();
      flush();
      expectWholeWriteContent(chart, series, studies);
    }
    expect(series.getData()).toHaveLength(205);
    expect(seen.rebuilds()).toBe(0);
    expect(seen.wholes()).toBe(0);
    for (const move of [() => replay.stepBack(2), () => replay.seek(260), () => replay.stop()]) {
      move();
      flush();
      expectWholeWriteContent(chart, series, studies);
    }
    expect(series.getData()).toHaveLength(320);
  });

  it('the forming bar is written every time it moves, and when it moves back', () => {
    registerIndicator(coloured);
    const { chart, series, flush } = setup(makeBars(120));
    const study = chart.addIndicator(coloured.id);
    flush();
    const diff = study.series('diff')!;
    const lead = study.series('lead')!;
    let last = series.getData()[119];
    for (const close of [last.open + 5, last.open - 5, last.open + 5, last.open]) {
      last = { ...last, close };
      series.update(last);
      flush();
      const tail = diff.getData()[119];
      expect(tail.close).toBe(close - last.open);
      expect(tail.color).toBe(close - last.open >= 0 ? '#26a69a' : '#ef5350');
      // The bar before keeps its value and takes the forming bar's colour.
      expect(lead.getData()[118]).toMatchObject({ close: series.getData()[118].open, color: close - last.open >= 0 ? '#1e88e5' : '#fb8c00' });
    }
  });

  it('a feed that starts on an empty chart: one bar, then ticks and appends, rebuild nothing once the plots exist', () => {
    registerIndicator(coloured);
    const { chart, series, flush } = setup([]);
    const studies = [...STUDIES, coloured.id].map((id) => chart.addIndicator(id));
    flush();
    expectWholeWriteContent(chart, series, studies);
    const feed = makeBars(6);
    series.update(feed[0]);
    flush();
    // One bar: every plot holds its single point.
    expect(series.getData()).toHaveLength(1);
    expectWholeWriteContent(chart, series, studies);
    const seen = watch(studies);
    let last = feed[0];
    for (const bar of feed.slice(1)) {
      last = { ...last, close: last.close + 1.5, high: last.high + 1.5 };
      series.update(last);
      flush();
      expectWholeWriteContent(chart, series, studies);
      last = bar;
      series.update(last);
      flush();
      expectWholeWriteContent(chart, series, studies);
    }
    expect(series.getData()).toHaveLength(6);
    expect(seen.rebuilds()).toBe(0);
    expect(seen.wholes()).toBe(0);
  });

  it('a chart destroyed from inside a plot write stops the frame cleanly', () => {
    let destroy: (() => void) | null = null;
    registerIndicator({
      ...coloured, id: 'plot-writes-destroys',
      plots: [{ ...coloured.plots[0], colorBy: ({ value, index }) => {
        if (destroy !== null && index === 60) { const run = destroy; destroy = null; run(); }
        return value >= 0 ? '#26a69a' : '#ef5350';
      } }, coloured.plots[1]],
    });
    const { chart, series, flush } = setup(makeBars(120));
    const study = chart.addIndicator('plot-writes-destroys');
    chart.addIndicator('ema');
    flush();
    const last = series.getData()[119];
    series.update({ ...last, close: last.close + 3 });
    const states: string[] = [];
    study.subscribeDataStatus((status) => states.push(status.state));
    destroy = () => chart.destroy();
    // The write in flight lands on a series the teardown already removed; the
    // study is gone by then, so the failure is dropped rather than thrown out
    // of the frame or reported as a study error.
    expect(() => flush()).not.toThrow();
    expect(destroy).toBeNull();
    expect(chart.isDestroyed).toBe(true);
    expect(study.series('diff')).toBeUndefined();
    expect(states).not.toContain('error');
  });

  it('a pass that throws part way leaves the next pass to write the plot whole', () => {
    let fail = false;
    registerIndicator({
      ...coloured, id: 'plot-writes-throws',
      plots: [{ ...coloured.plots[0], colorBy: ({ value, index }) => {
        if (fail && index === 100) throw new Error('colour failed');
        return value >= 0 ? '#26a69a' : '#ef5350';
      } }, coloured.plots[1]],
    });
    const { chart, series, flush } = setup(makeBars(120));
    const study = chart.addIndicator('plot-writes-throws');
    flush();
    const seen = watch([study]);
    let last = series.getData()[119];
    const before = study.series('diff')!.getData()[119];
    fail = true;
    last = { ...last, close: last.close + 7 };
    series.update(last);
    flush();
    // The pass stopped inside the first plot: its series kept the last good pass.
    expect(study.series('diff')!.getData()[119]).toStrictEqual(before);
    fail = false;
    last = { ...last, close: last.close + 1 };
    series.update(last);
    flush();
    expect(seen.wholes()).toBeGreaterThan(0);
    expectWholeWriteContent(chart, series, [study]);
  });
});
