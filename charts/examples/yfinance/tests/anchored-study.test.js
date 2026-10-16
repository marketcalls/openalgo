import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { createChart, getIndicator } from '/dist/openalgo-charts.mjs';
import { DrawingController } from '/dist/openalgo-charts.draw.mjs';
import { fakeDocument, pointer } from '../../../tests/helpers/fake-dom';
import { anchoredGrowthDescriptor, anchoredGrowthSeed, initAnchoredStudy } from '../src/anchored-study.js';

const bars = Array.from({ length: 60 }, (_, i) => {
  const close = 100 + 10 * Math.sin(i / 4);
  return { time: 1_700_000_000 + i * 86400, open: close - 1, high: close + 2, low: close - 2, close };
});

const charts = [];
beforeAll(() => { globalThis.window ??= {}; });
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

/** The built library's chart and drawing controller, as the page builds them. */
function mounted() {
  const document = fakeDocument();
  const el = document.createElement('div');
  const chart = createChart(el, {
    document, pixelRatio: () => 1, shortcuts: false, timeNavigator: false, animZoom: false, animAutoscale: false,
    branding: false, raf: { schedule: () => 0, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(900, 600);
  chart.addSeries('candlestick').setData(bars);
  chart.setVisibleLogicalRange({ from: 0, to: 59 });
  const draw = new DrawingController(chart);
  initAnchoredStudy();
  return { chart, el, draw };
}

describe('the anchored growth sample', () => {
  it('declares its anchor time and price as one point with a handle', () => {
    const [time, price] = anchoredGrowthDescriptor().inputs;
    expect(time).toMatchObject({ key: 'from', type: 'timestamp', pick: true });
    expect(price).toMatchObject({ key: 'price', type: 'price', pick: true, timeKey: 'from', anchor: true });
  });

  it('grows from the anchor bar and draws nothing before it', () => {
    const { path } = anchoredGrowthDescriptor().calc(bars, { from: bars[10].time, price: 100, rate: 1 });
    expect(path.slice(0, 10).every(value => value === null)).toBe(true);
    expect(path[10]).toBe(100);
    expect(path[12]).toBeCloseTo(102.01, 10);
  });

  it('starts a new study two thirds across the view, at that bar\'s close', () => {
    const { chart } = mounted();
    const seed = anchoredGrowthSeed(chart);
    expect(seed).toEqual({ from: bars[39].time, price: bars[39].close });
    expect(getIndicator('anchored-growth-sample').name).toBe('Anchored growth sample');
  });

  it('drags its handle on the chart and takes the drag back with the drawing undo', () => {
    const { chart, el, draw } = mounted();
    const study = chart.addIndicator('anchored-growth-sample', anchoredGrowthSeed(chart));
    chart.exportSVG();
    const before = study.settings();
    const x = chart.timeToCoordinate(before.from), y = chart.priceToCoordinate(before.price, 0);
    const toX = chart.timeToCoordinate(bars[30].time), toY = y - 50;
    el.dispatch('pointermove', pointer('move', x, y, { buttons: 0 }));
    el.dispatch('pointerdown', pointer('down', x, y));
    for (let i = 1; i <= 4; i++) el.dispatch('pointermove', pointer('move', x + ((toX - x) * i) / 4, y + ((toY - y) * i) / 4));
    el.dispatch('pointerup', pointer('up', toX, toY));
    expect(study.settings().from).toBe(bars[30].time);
    expect(study.settings().price).toBeCloseTo(chart.coordinateToPrice(toY, 0), 9);
    expect(draw.undo()).toBe(true);
    expect(study.settings()).toMatchObject({ from: before.from, price: before.price });
  });
});
