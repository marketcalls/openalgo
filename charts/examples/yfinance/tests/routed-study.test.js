import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { IndicatorBackground, createChart, getIndicator } from '/dist/openalgo-charts.mjs';
import { fakeDocument, pointer } from '../../../tests/helpers/fake-dom';
import { initRoutedStudy, routedSignalDescriptor } from '../src/routed-study.js';

const bars = Array.from({ length: 60 }, (_, i) => {
  const close = 100 + 10 * Math.sin(i / 4);
  return { time: 1_700_000_000 + i * 86400, open: close - 1, high: close + 2, low: close - 2, close };
});

function outputs(settings) {
  const descriptor = routedSignalDescriptor();
  const values = descriptor.calc(bars, settings);
  return {
    marks: descriptor.markers({ bars, values, settings }),
    shapes: descriptor.draws({ bars, values, settings }),
    shading: descriptor.background({ bars, values, settings }),
  };
}

const charts = [];
beforeAll(() => { globalThis.window ??= {}; });
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

/** A real chart from the built library, painted synchronously into a fake canvas. */
function mounted() {
  const document = fakeDocument();
  const el = document.createElement('div');
  const chart = createChart(el, {
    document, pixelRatio: () => 1, shortcuts: false, timeNavigator: false, animZoom: false, animAutoscale: false,
    raf: { schedule: callback => { callback(); return 1; }, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(900, 600);
  chart.addSeries('candlestick').setData(bars);
  const clicks = [];
  chart.subscribeClick(id => { clicks.push(id); });
  initRoutedStudy();
  const study = chart.addIndicator('routed-signal-sample');
  return { chart, el, clicks, study };
}
const click = (el, x, y) => {
  el.dispatch('pointerdown', pointer('down', x, y));
  el.dispatch('pointerup', pointer('up', x, y));
};
/** Where the chart last drew each Buy or Sell plate on one pane. */
const plates = (chart, paneIndex) => chart.panes()[paneIndex].primitives()
  .flatMap(layer => layer._lastPositions ?? []).filter(mark => mark.id.startsWith('signal:'));
/** The drawing layers on one pane that hold a shape matching `test`. */
const shapesOn = (chart, paneIndex, test) => chart.panes()[paneIndex].primitives()
  .filter(layer => Array.isArray(layer._items) && layer._items.some(test));
/** The colours each shading layer on one pane holds, one list per layer. */
const shadingOn = (chart, paneIndex) => chart.panes()[paneIndex].primitives()
  .filter(layer => layer instanceof IndicatorBackground).map(layer => layer._colors);
const range = shape => shape.id === 'routed-range';
const now = shape => shape.text === 'Now';
/** A point inside the range box, at a candle's own price on the price pane. */
const inRange = chart => {
  const bar = bars[bars.length - 10];
  return [chart.timeToCoordinate(bar.time), chart.priceToCoordinate(bar.close, 0)];
};

describe('routed signal sample', () => {
  it('registers an opt-in pane study under Examples', () => {
    initRoutedStudy();
    expect(getIndicator('routed-signal-sample')).toMatchObject({ category: 'Examples', placement: 'pane' });
  });

  it('sends its plates and range box to the price pane and keeps the rest with the histogram', () => {
    const { marks, shapes } = outputs({ length: 10, onPrice: true });
    const plateMarks = marks.filter(mark => mark.shape === 'labelUp' || mark.shape === 'labelDown');
    const dots = marks.filter(mark => mark.shape === 'circle');
    expect(plateMarks.length).toBeGreaterThan(1);
    expect(plateMarks.every(mark => mark.overlay === true && mark.plot === undefined)).toBe(true);
    expect(dots).toHaveLength(plateMarks.length);
    expect(dots.every(mark => mark.overlay === undefined && mark.plot === undefined)).toBe(true);
    expect(shapes.map(shape => [shape.kind, shape.overlay ?? null, shape.plot ?? null]))
      .toEqual([['box', true, null], ['label', null, 'momentum']]);
  });

  it('shades the candles by momentum, the histogram pane when asked, and nothing when off', () => {
    const [onPrice] = outputs({ length: 10, onPrice: true, shade: 'price' }).shading;
    expect(onPrice.overlay).toBe(true);
    expect(onPrice.plot).toBeUndefined();
    expect(onPrice.colors).toHaveLength(bars.length);
    // Null through the warmup, then one of the two regime colours on every bar.
    expect(onPrice.colors.slice(0, 10).every(color => color === null)).toBe(true);
    expect(new Set(onPrice.colors.slice(10))).toEqual(new Set(['rgba(38, 166, 154, 0.12)', 'rgba(239, 83, 80, 0.12)']));
    const [local] = outputs({ length: 10, onPrice: true, shade: 'study' }).shading;
    expect(local).toEqual({ colors: onPrice.colors });
    expect(outputs({ length: 10, onPrice: true, shade: 'off' }).shading).toEqual([]);
  });

  it('keeps the plates with the histogram when Signals on price is off', () => {
    const { marks } = outputs({ length: 10, onPrice: false });
    expect(marks.length).toBeGreaterThan(0);
    expect(marks.every(mark => mark.overlay === undefined && mark.plot === undefined)).toBe(true);
  });
});

describe('routed signal sample on a mounted chart', () => {
  it('draws the plates and the range box on the candles and the Now label with the histogram', () => {
    const { chart, el, clicks, study } = mounted();
    expect(study.paneIndex).toBe(1);
    const drawn = plates(chart, 0);
    expect(drawn.length).toBeGreaterThan(1);
    expect(plates(chart, 1)).toEqual([]);
    expect(shapesOn(chart, 0, range)).toHaveLength(1);
    expect(shapesOn(chart, 1, range)).toHaveLength(0);
    expect(shapesOn(chart, 1, now)).toHaveLength(1);
    // Each reports its id where it is drawn.
    click(el, drawn[0].x, drawn[0].y);
    click(el, ...inRange(chart));
    expect(clicks).toEqual([drawn[0].id, 'routed-range']);
  });

  it('shades the candles from the study pane, follows Momentum shading and goes with the study', () => {
    const { chart, study } = mounted();
    const [candles] = shadingOn(chart, 0);
    expect(shadingOn(chart, 0)).toHaveLength(1);
    expect(candles.filter(Boolean).length).toBeGreaterThan(40);
    expect(shadingOn(chart, 1)).toEqual([]);
    // Moving the study leaves the shading on the candles.
    expect(chart.moveIndicator(study.id, chart.panes().length)).toBe(true);
    expect(shadingOn(chart, 0)).toHaveLength(1);
    study.setSettings({ shade: 'study' });
    expect(shadingOn(chart, 0)).toEqual([]);
    expect(shadingOn(chart, study.paneIndex)).toEqual([candles]);
    study.setSettings({ shade: 'off' });
    expect(shadingOn(chart, study.paneIndex)).toEqual([[]]);
    study.setSettings({ shade: 'price' });
    expect(shadingOn(chart, 0)).toEqual([candles]);
    study.remove();
    expect(shadingOn(chart, 0)).toEqual([]);
  });

  it('leaves the price axis free to move, and the routed outputs go with the candles', () => {
    const { chart, el, clicks } = mounted();
    expect(chart.movePriceAxis(0, 'right', 'left')).toBe(true);
    expect(chart.panes()[0].usesScale('right')).toBe(false);
    click(el, ...inRange(chart));
    expect(clicks).toEqual(['routed-range']);
    expect(chart.movePriceAxis(0, 'left', 'right')).toBe(true);
    click(el, ...inRange(chart));
    expect(clicks).toEqual(['routed-range', 'routed-range']);
  });

  it('sends the plates back to the histogram with Signals on price off, and clears every target with the study', () => {
    const { chart, study } = mounted();
    study.setSettings({ onPrice: false });
    expect(plates(chart, 0)).toEqual([]);
    expect(plates(chart, 1).length).toBeGreaterThan(1);
    expect(shapesOn(chart, 0, range)).toHaveLength(1);
    study.setVisible(false);
    expect(plates(chart, 1)).toEqual([]);
    study.setVisible(true);
    study.setSettings({ onPrice: true });
    expect(plates(chart, 0).length).toBeGreaterThan(1);
    study.remove();
    expect(plates(chart, 0)).toEqual([]);
    expect(shapesOn(chart, 0, range)).toHaveLength(0);
    expect(chart.panes()).toHaveLength(1);
  });
});
