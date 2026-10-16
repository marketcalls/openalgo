/**
 * `chart.plotRect(paneIndex)`: where a pane's plot is in container px. Each
 * figure is checked against what the chart itself uses to paint and to map
 * prices, never against a restatement of the layout arithmetic, so the test
 * fails if the accessor and the renderer ever disagree.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import type { IPrimitive, PrimitiveRenderContext } from '../src/primitives/primitive';
import { fakeDocument } from './helpers/fake-dom';

const T0 = 1700000000;
const charts: Chart[] = [];
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

function makeChart(width = 800, height = 600) {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false, timeNavigator: false,
    raf: { schedule: callback => { callback(); return 1; }, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(width, height);
  const series = chart.addSeries('candlestick');
  series.setData(Array.from({ length: 60 }, (_, i) => ({ time: T0 + i * 60, open: 100, high: 102, low: 98, close: 101 })));
  // A left axis column, so the plot does not start at the container's edge.
  chart.addSeries('line', { priceScaleId: 'left' }).setData(Array.from({ length: 60 }, (_, i) => ({ time: T0 + i * 60, value: 5 + i })));
  registerIndicator({ id: 'plot-rect-study', name: 'Reading', placement: 'pane', inputs: [],
    plots: [{ key: 'v', title: 'Reading', type: 'line' }], calc: bars => ({ v: bars.map(() => 30) }) });
  chart.addIndicator('plot-rect-study');
  return chart;
}

/** What a primitive on the pane is handed to paint with. */
function paintedPlot(chart: Chart, paneIndex: number): { width: number; height: number } {
  let seen: PrimitiveRenderContext | null = null;
  const probe: IPrimitive = { zOrder: () => 'top', draw: (_ctx, rc) => { seen = rc; } };
  chart.addPrimitive(probe, paneIndex);
  chart.exportSVG();
  chart.removePrimitive(probe);
  expect(seen).not.toBeNull();
  const rc = seen as unknown as PrimitiveRenderContext;
  return { width: rc.plotWidth, height: rc.plotHeight };
}

describe('chart.plotRect', () => {
  it('matches the plot the panes paint into and the prices they map', () => {
    const chart = makeChart();
    expect(chart.panes()).toHaveLength(2);
    let top = 0;
    for (const index of [0, 1]) {
      const rect = chart.plotRect(index)!;
      expect(rect).not.toBeNull();
      // The left column is chart wide: a pane with no left scale still starts its plot after it.
      const left = Math.max(...[0, 1].flatMap(i => chart.priceAxisLayout(i)).filter(slot => slot.side === 'left').map(slot => slot.x + slot.width));
      expect(left).toBeGreaterThan(0);
      expect(rect.left).toBe(left);
      // The price a pane maps at its own top is the price the container maps at the rect's top.
      const pane = chart.panes()[index];
      expect(chart.priceToCoordinate(pane.yToPrice(0), index)).toBeCloseTo(rect.top, 6);
      expect(rect.top).toBeGreaterThanOrEqual(top);
      top = rect.top + rect.height;
      expect({ width: rect.width, height: rect.height }).toEqual(paintedPlot(chart, index));
      expect(rect.width).toBe(chart.timeScale.width);
      expect(rect.height).toBe(pane.priceScale.height);
    }
    // The lower pane stops above the time axis strip.
    expect(top).toBeLessThan(600);
  });

  it('follows a resize and a new pane weight', () => {
    const chart = makeChart();
    const before = chart.plotRect(0)!;
    chart.applySize(1000, 700);
    chart.setPaneWeight(1, 3);
    chart.exportSVG();
    const after = chart.plotRect(0)!;
    expect(after.width).toBe(before.width + 200);
    expect(after.height).toBe(chart.panes()[0].priceScale.height);
    expect(chart.plotRect(1)!.top).toBeCloseTo(after.top + after.height, 6);
  });

  it('answers null where a pane has no plot on screen', () => {
    const chart = makeChart();
    for (const index of [-1, 2, 0.5, Number.NaN]) expect(chart.plotRect(index)).toBeNull();
    expect(chart.setPaneCollapsed(1, true)).toBe(true);
    expect(chart.plotRect(1)).toBeNull();
    expect(chart.plotRect(0)).not.toBeNull();
    chart.setPaneCollapsed(1, false);
    chart.maximizePane(1);
    expect(chart.plotRect(0)).toBeNull();
    expect(chart.plotRect(1)!.top).toBe(0);
    expect(chart.plotRect(1)).toMatchObject(paintedPlot(chart, 1));
  });
});
