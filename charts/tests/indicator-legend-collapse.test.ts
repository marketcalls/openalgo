import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart, type ChartOptions } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import { PaneLegend } from '../src/primitives/pane-legend';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import type { RecordingContext } from './helpers/fake-ctx';

const charts: Chart[] = [];
let serial = 0;
const bars = [10, 20, 30].map((close, index) => ({ time: 1700000000 + index * 60, open: close, high: close, low: close, close }));

function fixture(options: Partial<ChartOptions> = {}) {
  vi.stubGlobal('window', {});
  const document = fakeDocument(), element = document.createElement('div') as unknown as FakeElement;
  const chart = new Chart(element, { document, pixelRatio: () => 1, shortcuts: false,
    timeNavigator: false, branding: false, animZoom: false, animAutoscale: false,
    raf: { schedule: callback => { callback(); return 1; }, cancel() {} }, ...options });
  charts.push(chart); chart.applySize(800, 600);
  const primary = chart.addSeries('line'); primary.setData(bars);
  return { chart, element, primary };
}

function study(chart: Chart, title = 'Study reading', paneIndex = 0) {
  const id = `legend-collapse-${++serial}`, detached = vi.fn(), attached = vi.fn(() => detached);
  const calc = vi.fn((data: typeof bars) => ({ a: data.map(bar => bar.close * 2), b: data.map(bar => bar.close * 3) }));
  registerIndicator({ id, name: title, placement: 'onchart', inputs: [],
    plots: [{ key: 'a', type: 'line', title: 'A' }, { key: 'b', type: 'line', title: 'B' }], calc, attach: attached });
  return { api: chart.addIndicator(id, {}, { paneIndex }), calc, attached, detached, id };
}

function paint(chart: Chart) {
  for (const pane of chart.panes()) (pane.top.ctx as unknown as RecordingContext).ops = [];
  chart.setGridOptions({ vertLines: true });
  return chart.panes().map(pane => (pane.top.ctx as unknown as RecordingContext).ops.filter(op => op.type === 'fillText'));
}

function control(chart: Chart) {
  const rows = paint(chart);
  for (let pane = 0; pane < rows.length; pane++) {
    const text = rows[pane].find(op => op.text?.startsWith('Indicators '));
    if (text) return { pane, x: text.args[0] + 2, y: text.args[1] };
  }
  throw new Error('Indicator count control was not rendered');
}

function tap(element: FakeElement, x: number, y: number, pointerType = 'mouse') {
  element.dispatch('pointerdown', pointer('down', x, y, { pointerType }));
  element.dispatch('pointerup', pointer('up', x, y, { pointerType }));
}

afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); vi.unstubAllGlobals(); });

describe('collapsed study legends', () => {
  it.each([NaN, Infinity, -Infinity])('uses the same finite row fallback for a host icon size of %s', iconSize => {
    const { chart, element } = fixture();
    chart.addPrimitive(new PaneLegend({ id: 'host-invalid-size', title: 'Host', iconSize, actions: [] }));
    study(chart);
    const hit = control(chart);
    expect(Number.isFinite(hit.x) && Number.isFinite(hit.y)).toBe(true);
    expect(hit.y).toBe(33);
    tap(element, hit.x, hit.y);
    expect(chart.indicatorLegendCollapsed()).toBe(true);
    expect(paint(chart)[0].some(op => op.text === 'Host')).toBe(true);
  });

  it('replaces only study rows with one applied-instance count and restores their order', () => {
    const { chart } = fixture();
    const host = new PaneLegend({ id: 'host-symbol', title: 'Host symbol', actions: [] }); host.setValue('OHLC reading');
    chart.addPrimitive(host);
    const first = study(chart, 'First study'), second = study(chart, 'Second study');
    second.api.setVisible(false);
    chart.addSeries('line').setData(bars);
    const before = paint(chart)[0].map(op => op.text);
    expect(before).toContain('Indicators 2');
    expect(before.indexOf('First study')).toBeLessThan(before.indexOf('Second study'));
    expect(first.api.legend()!.hitTest(20, 45)).not.toBeNull();
    const handles = chart.indicators(), objects = vi.fn(); chart.on('objects:change', objects);
    chart.setIndicatorLegendCollapsed(true);
    const collapsed = paint(chart)[0].map(op => op.text);
    expect(collapsed).toContain('Indicators 2');
    expect(collapsed).toContain('Host symbol'); expect(collapsed).toContain('OHLC reading');
    expect(collapsed).not.toContain('First study'); expect(collapsed).not.toContain('Second study');
    expect(chart.indicators()).toEqual(handles);
    expect(first.api.visible()).toBe(true); expect(second.api.visible()).toBe(false);
    expect(first.api.legend()!.hitTest(20, 45)).toBeNull();
    chart.setIndicatorLegendCollapsed(true); expect(objects).toHaveBeenCalledTimes(1);
    chart.setIndicatorLegendCollapsed(false);
    expect(paint(chart)[0].map(op => op.text)).toEqual(before);
  });

  it('starts collapsed, includes duplicate descriptors and hidden studies, and hides the count at zero', () => {
    const { chart } = fixture({ indicatorLegendCollapsed: true });
    expect(paint(chart)[0].some(op => op.text?.startsWith('Indicators '))).toBe(false);
    const first = study(chart), second = chart.addIndicator(first.id); second.setVisible(false);
    expect(paint(chart)[0].map(op => op.text)).toContain('Indicators 2');
    expect(paint(chart)[0].map(op => op.text)).not.toContain('Study reading');
    first.api.remove(); expect(paint(chart)[0].map(op => op.text)).toContain('Indicators 1');
    second.remove(); expect(paint(chart)[0].some(op => op.text?.startsWith('Indicators '))).toBe(false);
    expect(chart.indicatorLegendCollapsed()).toBe(true);
  });

  it('keeps calculations, live values, and attach lifetimes active while collapsed', () => {
    const { chart, primary } = fixture(), entry = study(chart);
    const initial = entry.api.values(), calls = entry.calc.mock.calls.length;
    chart.setIndicatorLegendCollapsed(true);
    expect(entry.api.values()).toEqual(initial); expect(entry.calc).toHaveBeenCalledTimes(calls);
    primary.update({ ...bars[2], close: 40 });
    expect(entry.api.values()).toEqual({ a: [20, 40, 80], b: [30, 60, 120] });
    chart.setIndicatorLegendCollapsed(false);
    expect(paint(chart)[0].map(op => op.text)).toContain('80');
    expect(entry.attached).toHaveBeenCalledTimes(1); expect(entry.detached).not.toHaveBeenCalled();
  });

  it.each(['mouse', 'touch', 'pen'])('toggles without prior hover using %s and swallows placement clicks', type => {
    const { chart, element } = fixture(); study(chart);
    chart.setPlacementMode(true);
    const clicked = vi.fn(); chart.on('click', clicked);
    const point = control(chart);
    tap(element, point.x, point.y, type);
    expect(chart.indicatorLegendCollapsed()).toBe(true);
    tap(element, point.x, point.y, type);
    expect(chart.indicatorLegendCollapsed()).toBe(false);
    expect(clicked).not.toHaveBeenCalled();
  });

  it('consumes a dragged or canceled control press without drawing or moving the viewport', () => {
    const { chart, element } = fixture(); study(chart); chart.setPlacementMode(true);
    const point = control(chart), range = chart.getVisibleLogicalRange(), clicked = vi.fn(); chart.on('click', clicked);
    element.dispatch('pointerdown', pointer('down', point.x, point.y));
    element.dispatch('pointermove', pointer('move', point.x + 80, point.y + 40));
    element.dispatch('pointerup', pointer('up', point.x + 80, point.y + 40));
    expect(clicked).not.toHaveBeenCalled(); expect(chart.getVisibleLogicalRange()).toEqual(range);
    expect(chart.indicatorLegendCollapsed()).toBe(false);
    element.dispatch('pointerdown', pointer('down', point.x, point.y));
    element.dispatch('pointercancel', pointer('up', point.x, point.y));
    expect(chart.indicatorLegendCollapsed()).toBe(false);
  });

  it('never resets the chart or emits a drawing double click over the control', () => {
    const { chart, element, primary } = fixture(); study(chart);
    primary.priceScale().setAutoScale(false); primary.priceScale().setPriceRange({ min: 5, max: 50 });
    const point = control(chart), doubled = vi.fn(); chart.on('dblclick', doubled);
    tap(element, point.x, point.y); tap(element, point.x, point.y);
    element.dispatch('dblclick', { clientX: point.x, clientY: point.y });
    expect(primary.priceScale().autoScale).toBe(false);
    expect(primary.priceScale().priceRange()).toEqual({ min: 5, max: 50 });
    expect(doubled).not.toHaveBeenCalled();
  });

  it('keeps the control available when title and value switches are disabled', () => {
    const { chart, element } = fixture({ indicatorLegendCollapsed: true }); study(chart);
    chart.setStatusLineOptions({ title: false, lastValueLabel: false, chartValues: false });
    const point = control(chart); tap(element, point.x, point.y);
    expect(chart.indicatorLegendCollapsed()).toBe(false);
    expect(paint(chart)[0].map(op => op.text)).toContain('Indicators 1');
  });

  it('moves the single control with the visible top pane and preserves reserved offsets', () => {
    const { chart } = fixture({ indicatorLegendCollapsed: true, legendOffset: { top: 52, left: 40 } });
    study(chart, 'Upper study'); const lower = study(chart, 'Lower study', 1); study(chart, 'Third study', 2);
    expect(control(chart)).toMatchObject({ pane: 0 });
    expect(control(chart).y).toBeGreaterThan(52);
    chart.maximizePane(1);
    expect(control(chart)).toMatchObject({ pane: 1 });
    expect(control(chart).x).toBeGreaterThanOrEqual(40); expect(control(chart).y).toBeGreaterThan(52);
    chart.movePane(1, 1); expect(control(chart).pane).toBe(2);
    lower.api.remove(); expect(control(chart).pane).toBe(0);
    expect(paint(chart).flat().filter(op => op.text === 'Indicators 2')).toHaveLength(1);
  });

  it('keeps the compact control inside narrow plot columns at fractional pixel density', () => {
    const { chart, primary } = fixture({ indicatorLegendCollapsed: true, pixelRatio: () => 1.5, legendOffset: { left: 45 }, legendIconSize: 28 });
    study(chart); chart.addSeries('line', { priceScaleId: 'left' }).setData(bars);
    chart.setPriceAxisPlacement(0, 'left', 'left'); chart.applySize(220, 300);
    const text = paint(chart)[0].find(op => op.text?.startsWith('Indicators '));
    expect(text).toBeDefined();
    const plotWidth = chart.timeScale.width;
    expect(text!.args[0]).toBeGreaterThanOrEqual(0);
    expect(text!.args[0] + text!.text!.length * 6).toBeLessThanOrEqual(plotWidth * 1.5);
    expect(primary.priceScale().height).toBeGreaterThan(100);
  });

  it('exports the count and plots while omitting study names from SVG', () => {
    const { chart } = fixture({ indicatorLegendCollapsed: true }); study(chart, 'Export study title');
    const svg = chart.exportSVG();
    expect(svg).toContain('Indicators 1'); expect(svg).not.toContain('Export study title');
    expect(svg).toContain('<path');
    chart.setIndicatorLegendCollapsed(false);
    expect(chart.exportSVG()).toContain('Export study title');
  });

  it('preserves partial restore preferences and replaces the count with restored applied studies', () => {
    const { chart } = fixture(); const first = study(chart), second = study(chart);
    const saved = chart.getState();
    expect(saved.indicatorLegendCollapsed).toBe(false);
    chart.setIndicatorLegendCollapsed(true);
    chart.restoreState({ version: 1, grid: { vertLines: false } });
    expect(chart.indicatorLegendCollapsed()).toBe(true);
    chart.restoreState({ version: 1, indicatorLegendCollapsed: true, indicators: [saved.indicators![0]] });
    expect(paint(chart)[0].map(op => op.text)).toContain('Indicators 1');
    expect(chart.indicators()[0].id).toBe(first.api.id);
    expect(chart.indicators().some(item => item.id === second.api.id)).toBe(false);
    const roundtrip = JSON.parse(JSON.stringify(chart.getState()));
    chart.setIndicatorLegendCollapsed(false); chart.restoreState(roundtrip);
    expect(chart.indicatorLegendCollapsed()).toBe(true);
    expect(paint(chart)[0].map(op => op.text)).not.toContain('Study reading');
  });

  it('rejects malformed preferences before mutation and preserves newer callback restores', () => {
    const { chart } = fixture(); study(chart);
    const before = chart.getState();
    for (const value of [null, 1, 'true', {}]) {
      expect(chart.restoreState({ version: 1, indicatorLegendCollapsed: value }).applied).toBe(false);
      expect(chart.getState()).toEqual(before);
    }
    const read = vi.fn(() => true);
    expect(chart.restoreState(Object.defineProperty({ version: 1 }, 'indicatorLegendCollapsed', { get: read })).applied).toBe(false);
    expect(read).not.toHaveBeenCalled();
    let nested = false;
    chart.on('objects:change', () => { if (!nested) { nested = true; chart.restoreState({ version: 1, indicatorLegendCollapsed: false }); } });
    chart.restoreState({ version: 1, indicatorLegendCollapsed: true });
    expect(chart.indicatorLegendCollapsed()).toBe(false);
  });

  it('keeps a host row with a study-like id and explicit study row visibility intact', () => {
    const { chart } = fixture(), entry = study(chart);
    chart.addPrimitive(new PaneLegend({ id: 'indicator:host', title: 'Host-owned title', actions: [] }));
    entry.api.legend()!.setOptions({ visible: false, font: 17 });
    chart.setIndicatorLegendCollapsed(true); chart.setIndicatorLegendCollapsed(false);
    const text = paint(chart)[0].map(op => op.text);
    expect(text).toContain('Host-owned title'); expect(text).toContain('Indicators 1');
    expect(text).not.toContain('Study reading');
    expect(entry.api.legend()!.options()).toMatchObject({ visible: false, font: 17 });
    expect(entry.api.legend()!.hitTest(20, 35)).toBeNull();
  });

  it('counts plotless applied studies but never a failed construction', () => {
    const { chart } = fixture({ indicatorLegendCollapsed: true });
    const id = `legend-collapse-empty-${++serial}`;
    registerIndicator({ id, name: 'Plotless study', placement: 'onchart', inputs: [], plots: [], calc: () => ({}) });
    chart.addIndicator(id);
    registerIndicator({ id: `${id}-failed`, name: 'Failed study', placement: 'onchart', inputs: [], plots: [], calc: () => { throw new Error('Unavailable'); } });
    expect(() => chart.addIndicator(`${id}-failed`)).toThrow('Unavailable');
    expect(paint(chart)[0].map(op => op.text)).toContain('Indicators 1');
    expect(chart.indicators()).toHaveLength(1);
  });

  it('continues native live alert delivery while collapsed without alerting on the display toggle', () => {
    const { chart, primary } = fixture();
    const id = `legend-collapse-alert-${++serial}`, alert = vi.fn(); chart.on('indicator:alert', alert);
    registerIndicator({ id, name: 'Active alerts', placement: 'onchart', inputs: [],
      plots: [{ key: 'a', title: 'A', type: 'line' }], calc: data => ({ a: data.map(bar => bar.close) }),
      alerts: [{ id: 'positive', title: 'Positive', frequency: 'everyUpdate', when: () => true, message: 'Live condition' }] });
    chart.addIndicator(id); chart.setIndicatorLegendCollapsed(true);
    expect(alert).not.toHaveBeenCalled();
    primary.update({ ...bars[2], close: 40 }); chart.indicators()[0].values();
    expect(alert).toHaveBeenCalledTimes(1);
  });

  it('completes a clean tap when releasing capture synchronously reports lost capture', () => {
    const { chart, element } = fixture(); study(chart);
    const point = control(chart);
    let reported = false;
    element.releasePointerCapture = () => {
      if (reported) return;
      reported = true;
      element.dispatch('lostpointercapture', pointer('up', point.x, point.y));
    };
    tap(element, point.x, point.y);
    expect(chart.indicatorLegendCollapsed()).toBe(true);
  });

  it('places the toggle and study below a host row with larger buttons and its own top offset', () => {
    const { chart } = fixture();
    chart.addPrimitive(new PaneLegend({ id: 'large-host', title: 'Large host', top: 40, iconSize: 28, actions: [] }));
    study(chart, 'Following study');
    const rows = paint(chart)[0], host = rows.find(op => op.text === 'Large host')!;
    const toggle = rows.find(op => op.text === 'Indicators 1')!, following = rows.find(op => op.text === 'Following study')!;
    expect(toggle.args[1] - 9).toBeGreaterThanOrEqual(host.args[1] + 15);
    expect(following.args[1] - 9).toBeGreaterThanOrEqual(toggle.args[1] + 9);
  });
});
