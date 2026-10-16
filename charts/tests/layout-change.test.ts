/**
 * Two reads a chart-wide undo history, or a host that saves its layout, needs
 * from the core:
 *
 * - `layout:change`, after the setters that change what `getState` saves and
 *   used to say nothing, so a change made outside a recorded step is heard
 *   when it happens rather than folded into whatever is recorded next;
 * - `priceScaleDefaults()`, the chart-wide price-scale defaults, which are not
 *   the price pane's own scale once that axis is changed from its own menu.
 */
import { describe, expect, it } from 'vitest';
import '../src/indicators/index';
import { Chart, type LayoutChangeEvent } from '../src/core/chart';
import type { Bar } from '../src/model/bar';
import { fakeDocument } from './helpers/fake-dom';

const bars = (n: number): Bar[] => Array.from({ length: n }, (_, i) => {
  const c = 100 + Math.sin(i / 4) * 5;
  return { time: 1_700_000_000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 10 + i };
});

function makeChart(options: ConstructorParameters<typeof Chart>[1] = {}): { chart: Chart; heard: string[] } {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false, raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} }, ...options,
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(bars(80));
  chart.addIndicator('rsi');
  const heard: string[] = [];
  chart.on('layout:change', payload => heard.push((payload as LayoutChangeEvent).setter));
  return { chart, heard };
}

describe('layout:change', () => {
  it('follows each setter that changes the saved layout, once, named after it', () => {
    const { chart, heard } = makeChart();
    const calls: [string, () => unknown][] = [
      ['setPaneWeight', () => chart.setPaneWeight(1, 0.5)],
      ['setPriceAxisOptions', () => chart.setPriceAxisOptions(0, 'right', { inverted: true })],
      ['setPriceAxisAutoFit', () => chart.setPriceAxisAutoFit(0, 'right', false)],
      ['setPriceAxisLockRatio', () => chart.setPriceAxisLockRatio(0, 'right', true)],
      ['setPriceScaleOptions', () => chart.setPriceScaleOptions({ mode: 'logarithmic' })],
      ['setAutoScale', () => chart.setAutoScale(true)],
      ['setGridOptions', () => chart.setGridOptions({ vertLines: false })],
      ['setCanvasOptions', () => chart.setCanvasOptions({ crosshair: { color: '#123456' } })],
      ['setStatusLineOptions', () => chart.setStatusLineOptions({ volume: false })],
      ['setWatermarkOptions', () => chart.setWatermarkOptions({ visible: true, text: 'NIFTY' })],
      ['setTradingSettings', () => chart.setTradingSettings({ longColor: '#00aa00' })],
      ['setAxisChromeOptions', () => chart.setAxisChromeOptions({ barCountdown: true })],
      ['setEventOptions', () => chart.setEventOptions({ dividend: false })],
      ['applyOptions', () => chart.applyOptions({ crosshairSnapToBar: true })],
      ['setNavigationOptions', () => chart.setNavigationOptions({ mousePan: 'horizontal' })],
    ];
    for (const [setter, call] of calls) {
      heard.length = 0;
      call();
      expect(heard, setter).toEqual([setter]);
    }
  });

  it('follows the magnet shortcut, which changes the crosshair mode getState saves', () => {
    const { chart, heard } = makeChart();
    const run = (chart as unknown as { _runShortcut(command: string): boolean })._runShortcut.bind(chart);
    expect(run('toggleCrosshairMagnet')).toBe(true);
    expect(chart.getState().crosshairMode).toBe('magnet');
    expect(heard).toEqual(['applyOptions']);
  });

  it('keeps objects:change for the pan and zoom switches beside layout:change', () => {
    const { chart, heard } = makeChart();
    let objects = 0;
    chart.on('objects:change', () => { objects++; });
    chart.setNavigationOptions({ panEnabled: false });
    expect(objects).toBe(1);
    expect(heard).toEqual(['setNavigationOptions']);
  });

  it('is one event for a setter that sets others on its way', () => {
    const { chart, heard } = makeChart();
    // The canvas block sets the grid and the chart-wide margins through their own setters.
    chart.setCanvasOptions({ grid: { horzLines: false }, margins: { top: 12, bottom: 8 } });
    expect(heard).toEqual(['setCanvasOptions']);
    heard.length = 0;
    chart.applyOptions({ grid: { vertLines: false }, canvas: { scales: { fontSize: 12 } }, priceScale: { inverted: true } });
    expect(heard).toEqual(['applyOptions']);
  });

  it('fires after the change is in place, so a listener reads the new value', () => {
    const { chart } = makeChart();
    let seen: boolean | undefined;
    chart.on('layout:change', () => { seen = chart.gridOptions().vertLines; });
    chart.setGridOptions({ vertLines: false });
    expect(seen).toBe(false);
  });

  it('stays quiet for a call that names no pane the chart has', () => {
    const { chart, heard } = makeChart();
    chart.setPaneWeight(9, 2);
    chart.setPriceAxisOptions(9, 'right', { inverted: true });
    chart.setPriceAxisAutoFit(9, 'right', true);
    chart.setPriceAxisLockRatio(9, 'right', true);
    expect(heard).toEqual([]);
    // The same calls on a pane the chart has are heard, once each, so the
    // silence above is the pane check and not an event that never fires.
    chart.setPaneWeight(1, 0.6);
    chart.setPriceAxisAutoFit(1, 'right', false);
    expect(heard).toEqual(['setPaneWeight', 'setPriceAxisAutoFit']);
  });

  it('stays quiet through a restore, which announces itself', () => {
    const { chart, heard } = makeChart();
    chart.setGridOptions({ vertLines: false });
    chart.setPaneWeight(1, 0.6);
    const saved = chart.getState();
    const seen: string[] = [];
    chart.on('state:restore:start', () => seen.push('start'));
    chart.on('state:restore:end', () => seen.push('end'));
    heard.length = 0;
    expect(chart.restoreState(saved).applied).toBe(true);
    expect(heard).toEqual([]);
    expect(seen).toEqual(['start', 'end']);
    // And a setter after it is heard again.
    chart.setGridOptions({ vertLines: true });
    expect(heard).toEqual(['setGridOptions']);
  });
});

describe('priceScaleDefaults', () => {
  it('reads the chart-wide defaults, which a change to one axis leaves alone', () => {
    const { chart } = makeChart();
    expect(chart.priceScaleDefaults()).toEqual({});
    chart.setPriceScaleOptions({ mode: 'logarithmic' });
    expect(chart.priceScaleDefaults()).toEqual({ mode: 'logarithmic' });
    // From the axis menu: the price pane's own scale moves, the default does not.
    chart.setPriceAxisOptions(0, 'right', { mode: 'percentage' });
    expect(chart.priceScaleOptions().mode).toBe('percentage');
    expect(chart.priceScaleDefaults().mode).toBe('logarithmic');
    // A pane added now starts from the defaults, not from the price pane.
    chart.addIndicator('macd');
    const added = chart.panes()[chart.panes().length - 1];
    expect(added.priceScale.options.mode).toBe('logarithmic');
  });

  it('includes what construction and the canvas margins set, and hands back a copy', () => {
    const { chart } = makeChart({ priceScale: { inverted: true } });
    chart.setCanvasOptions({ margins: { top: 10, bottom: 20 } });
    const defaults = chart.priceScaleDefaults();
    expect(defaults.inverted).toBe(true);
    expect(defaults.marginTop).toBeCloseTo(0.1, 9);
    expect(defaults.marginBottom).toBeCloseTo(0.2, 9);
    defaults.inverted = false;
    expect(chart.priceScaleDefaults().inverted).toBe(true);
  });
});
