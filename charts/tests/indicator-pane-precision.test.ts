/**
 * An indicator's own pane is not quoted in the instrument's tick.
 *
 * Reported from a live terminal. The host hands the chart the symbol's tick
 * size, `setPriceScaleOptions({ minMove: 0.10 })`, and every pane on the chart
 * took it: `PriceScale.precision` answered one decimal everywhere, so a William
 * VIX Fix sitting at 0.61 was labelled "0.6" on its own axis and the RSI beside
 * it read "70.0, 50.0, 30.0".
 *
 * A tick size is a property of the *instrument*, not of an axis. An RSI is a
 * dimensionless 0..100 oscillator and a VIX Fix is a percentage; neither trades
 * in paise, so 0.10 is not a coarse answer for their axes but an answer to a
 * different question. A pane that plots one has to infer its precision from the
 * range it covers, which is what `precision()` already does when `minMove` is 0.
 *
 * It costs more than a tidy label. A study whose whole signal lives in the
 * second decimal is drawn correctly and then labelled wrongly: the gridline at
 * 0.25 was printed as "0.3", so the number beside the line is not the number
 * the line is at, and the legend rounds along with the axis.
 */
import { describe, it, expect } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import { precisionForStep } from '../src/scale/ticks';
import { fakeDocument } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';

/** The instrument's tick, the number the host actually pushes down. */
const TICK = 0.1;

/**
 * A chart that paints synchronously, so the autoscale pass has run and every
 * scale is measured by the time a call returns. A chart without `applySize` and
 * a real frame sits on the 0..1 placeholder, where every precision assertion
 * would compare one placeholder against another.
 */
function makeChart(): Chart {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc,
    pixelRatio: () => 1,
    shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 600);
  return chart;
}

const bars = (n: number): Bar[] =>
  Array.from({ length: n }, (_, i) => ({
    time: 1735689600 + i * 60,
    open: 1339.5 + i, high: 1340.2 + i, low: 1339.1 + i, close: 1339.7 + i,
  }));

/** The reported chart: candles on pane 0, the tick not yet pushed down. */
function priced(): Chart {
  const chart = makeChart();
  chart.addSeries('candlestick').setData(bars(30));
  return chart;
}

/**
 * A study on its own pane whose values run 0.30..1.30, the band a VIX Fix
 * occupies. The span is what decides the inferred precision, so it is chosen
 * rather than incidental: 1.0 of range plus the default 10% margins is 1.25,
 * and 1.25/100 implies two decimals.
 */
registerIndicator({
  id: 'pane-precision-vix', name: 'VIX Fix (test)', placement: 'pane', inputs: [],
  plots: [{ key: 'v', type: 'line', title: 'VIX' }],
  calc: (b) => ({ v: b.map((_, i) => 0.3 + i / (b.length - 1)) }),
});

/** An oscillator that declares its band, the way the built-in RSI does. */
registerIndicator({
  id: 'pane-precision-rsi', name: 'RSI (test)', placement: 'pane', inputs: [],
  plots: [{ key: 'v', type: 'line', title: 'RSI' }],
  range: () => ({ min: 0, max: 100 }),
  calc: (b) => ({ v: b.map((_, i) => 30 + (i % 40)) }),
});

/** A cumulative study running to millions, where a decimal is not information. */
registerIndicator({
  id: 'pane-precision-obv', name: 'OBV (test)', placement: 'pane', inputs: [],
  plots: [{ key: 'v', type: 'line', title: 'OBV' }],
  calc: (b) => ({ v: b.map((_, i) => 1_000_000 + i * 5_000) }),
});

/** Records what `calc` was told the instrument's tick is. */
let calcTick: number | undefined;
registerIndicator({
  id: 'pane-precision-calc-tick', name: 'Calc Tick (test)', placement: 'pane', inputs: [],
  plots: [{ key: 'v', type: 'line', title: 'v' }],
  calc: (b, _s, _store, ctx) => { calcTick = ctx?.tickSize; return { v: b.map(() => 1) }; },
});

describe('the instrument tick stops at the panes that quote the instrument', () => {
  it('does not follow the host onto a study pane that already exists', () => {
    // The reported order: the study is on the chart, then the symbol loads and
    // the host pushes its tick down chart-wide.
    const chart = priced();
    const vix = chart.addIndicator('pane-precision-vix');
    chart.setPriceScaleOptions({ minMove: TICK });

    const scale = chart.panes()[vix.paneIndex].priceScale;
    expect(scale.options.minMove).toBe(0);
    // The reported symptom, in the form a trader reads it.
    expect(scale.format(0.61)).toBe('0.61');
    // And the axis strip's own text, as close to the pixels as a unit test
    // gets: `drawPriceAxis` prints `format(t)` for every `ticks(n)`. Under the
    // instrument's tick this ladder read "0.3, 0.5, 0.8, 1.0, 1.3", which is
    // not merely coarse: the gridlines sit at 0.25 and 0.75, so two of those
    // five labels named a price the line beside them was not drawn at.
    expect(scale.ticks(6).map((t) => scale.format(t)))
      .toEqual(['0.25', '0.50', '0.75', '1.00', '1.25']);
    // The precision is the pane's own range talking, not a floor that happens
    // to be two: the band it covers is what sets it.
    const { min, max } = scale.priceRange();
    expect(scale.precision()).toBe(precisionForStep((max - min) / 100));
  });

  it('is not inherited by a study pane made after the tick was set', () => {
    // The other order, and the one that reaches a different line of code: the
    // pane is built after `minMove` is already held as a chart-wide default.
    const chart = priced();
    chart.setPriceScaleOptions({ minMove: TICK });
    const vix = chart.addIndicator('pane-precision-vix');

    const scale = chart.panes()[vix.paneIndex].priceScale;
    expect(scale.options.minMove).toBe(0);
    expect(scale.format(0.61)).toBe('0.61');
  });

  it('holds a bounded oscillator to two decimals rather than whole points', () => {
    const chart = priced();
    chart.setPriceScaleOptions({ minMove: TICK });
    const rsi = chart.addIndicator('pane-precision-rsi');

    const scale = chart.panes()[rsi.paneIndex].priceScale;
    // Dropping the tick is only half of it. A 0..100 band implies a step of one
    // whole point, so the span alone would label the ladder "70" and round a
    // reading of 62.24 to "62" -- past the part a trader comparing it to the 70
    // level is looking at. Two decimals is the floor, the same one the percent
    // branch of `precision()` has always settled on for the same reason.
    expect([scale.format(70), scale.format(50), scale.format(30)])
      .toEqual(['70.00', '50.00', '30.00']);
    expect(scale.format(62.2449)).toBe('62.24');
  });

  it('lifts the floor where a decimal is no longer information', () => {
    // An on-balance-volume runs to millions. "1234567.00" says nothing the
    // integer did not, and costs the axis the width those digits need.
    const chart = priced();
    chart.setPriceScaleOptions({ minMove: TICK });
    const obv = chart.addIndicator('pane-precision-obv');

    const scale = chart.panes()[obv.paneIndex].priceScale;
    expect(scale.format(1234567)).toBe('1234567');
  });
});

describe('the panes that do quote it keep it', () => {
  it('keeps the tick on the price pane, which is the whole point of sending it', () => {
    const chart = priced();
    chart.addIndicator('pane-precision-vix');
    chart.setPriceScaleOptions({ minMove: TICK });

    const scale = chart.panes()[0].priceScale;
    expect(scale.options.minMove).toBe(TICK);
    expect(scale.format(1339.7)).toBe('1339.7');
  });

  it('reaches the price pane left axis and its hidden overlay scale', () => {
    // Both still quote the instrument: a second scale on the price pane is a
    // second reading of the same prices, not a different unit.
    const chart = priced();
    chart.addSeries('line', { priceScaleId: 'left' }).setData(bars(30));
    chart.addSeries('histogram', { priceScaleId: '' }).setData(bars(30));
    chart.addIndicator('pane-precision-vix');
    chart.setPriceScaleOptions({ minMove: TICK }, 'all');

    const pane = chart.panes()[0];
    expect(pane.scales().map((s) => s.options.minMove)).toEqual([TICK, TICK, TICK]);
    // ... while the study pane the same sweep passed over is still untouched.
    expect(chart.panes()[1].priceScale.options.minMove).toBe(0);
  });

  it('follows a second symbol onto a pane of its own', () => {
    // A comparison instrument is a price, so its pane is promoted the moment
    // the host plots it and gets the tick it would have had before the fix.
    const chart = priced();
    chart.setPriceScaleOptions({ minMove: TICK });
    chart.addSeries('line', { paneIndex: 1 }).setData(bars(30));

    expect(chart.panes()[1].priceScale.options.minMove).toBe(TICK);
  });

  it('obeys a host that names one study axis outright', () => {
    // The escape hatch, and the reason the filter lives in the chart-wide
    // setter alone: naming a pane and a scale is the caller saying what that
    // axis quotes, and it is not second-guessed.
    const chart = priced();
    const vix = chart.addIndicator('pane-precision-vix');
    chart.setPriceScaleOptions({ minMove: TICK });
    chart.setPriceAxisOptions(vix.paneIndex, 'right', { minMove: 0.25 });

    expect(chart.panes()[vix.paneIndex].priceScale.options.minMove).toBe(0.25);
  });
});

describe('the instrument tick still reaches what is computed from the instrument', () => {
  it('hands a study on its own pane the price pane tick to calculate with', () => {
    // `calc` runs on the instrument's bars whatever pane it draws in, so a
    // descriptor sizing something in ticks must not lose the tick to the fix.
    const chart = priced();
    chart.setPriceScaleOptions({ minMove: TICK });
    calcTick = undefined;
    chart.addIndicator('pane-precision-calc-tick');

    expect(calcTick).toBe(TICK);
  });
});

describe('a saved layout does not carry the defect back in', () => {
  it('drops a broadcast tick from a study pane on restore, and keeps the price pane one', () => {
    // A workspace saved by a build that had the defect records the instrument's
    // tick on every pane. Restoring it faithfully would re-create the wrong
    // precision on a pane the chart-wide setter no longer reaches to correct.
    const source = priced();
    const vix = source.addIndicator('pane-precision-vix');
    source.setPriceScaleOptions({ minMove: TICK });
    const state = source.getState();
    for (const pane of state.panes ?? []) {
      delete pane.priceScale.minPrecision;
      delete pane.priceScale.fixedRange;
    }
    const saved = state.panes?.[vix.paneIndex];
    expect(saved).toBeDefined();
    if (saved) saved.priceScale.minMove = TICK; // what the old build wrote

    const restored = priced();
    restored.restoreState(state);

    expect(restored.panes()[0].priceScale.options.minMove).toBe(TICK);
    expect(restored.panes()[vix.paneIndex].priceScale.options.minMove).toBe(0);
  });
});
