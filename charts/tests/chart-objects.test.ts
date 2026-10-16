import { afterEach, describe, expect, it } from 'vitest';
import '../src/indicators/index';
import { Chart } from '../src/core/chart';
import { ChartObjects } from '../src/model/chart-objects';
import { DrawingController } from '../src/draw/index';
import { getIndicator, plotStyleKeys, registerIndicator } from '../src/model/indicator-registry';
import { PriceLine } from '../src/primitives/price-line';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
const makeChart = (): Chart => {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: () => 0 },
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(Array.from({ length: 60 }, (_, i) => ({
    time: 1700000000 + i * 60, open: 23800 + i, high: 23804 + i,
    low: 23798 + i, close: 23802 + i, volume: 650,
  })));
  charts.push(chart);
  return chart;
};
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

describe('drawing row names', () => {
  it('names a drawing by the host when it can, else from the tool id', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const line = draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [{ time: 1700000000, price: 23800 }, { time: 1700000600, price: 23810 }] });
    const named = new ChartObjects(chart, { drawings: draw, drawingName: tool => (tool === 'trend-line' ? 'Trend Line' : tool) });
    const plain = new ChartObjects(chart, { drawings: draw });
    expect(named.get('drawing:' + line.id)?.name).toBe('Trend Line');
    expect(plain.get('drawing:' + line.id)?.name).toBe('Trend line');
    named.destroy();
    plain.destroy();
    draw.destroy();
  });
});

describe('object lifecycle and persistence', () => {
  it('hides reference levels and keeps a hidden indicator hidden when its plot type changes', () => {
    const chart = makeChart();
    const indicator = chart.addIndicator('rsi');
    const pane = chart.panes()[indicator.paneIndex];
    const levels = () => pane.primitives().filter(primitive => primitive instanceof PriceLine);
    expect(levels().length).toBeGreaterThan(0);
    const objects = new ChartObjects(chart);
    objects.setVisible('indicator:' + indicator.id, false);
    expect(levels()).toHaveLength(0);
    const key = plotStyleKeys(getIndicator('rsi').plots[0]).type;
    indicator.setSettings({ [key]: 'histogram' });
    expect(pane.series().every(series => series.style.visible === false)).toBe(true);
    expect(levels()).toHaveLength(0);
    objects.setVisible('indicator:' + indicator.id, true);
    expect(levels().length).toBeGreaterThan(0);
    expect(pane.series().every(series => series.style.visible !== false)).toBe(true);
  });

  it('keeps a hidden indicator hidden after a JSON layout round trip', () => {
    const chart = makeChart();
    chart.addIndicator('rsi').setVisible(false);
    const saved = JSON.parse(JSON.stringify(chart.getState()));
    chart.restoreState(saved);
    expect(chart.indicators()).toHaveLength(1);
    expect(chart.indicators()[0].visible()).toBe(false);
    expect(chart.indicators()[0].legend()?.options().hidden).toBe(true);
  });

  it('removes a directly disposed indicator from inventory and frees its pane', () => {
    const chart = makeChart();
    const first = chart.addIndicator('rsi');
    const second = chart.addIndicator('macd');
    first.remove();
    expect(chart.indicators().map(i => i.id)).toEqual([second.id]);
    expect(chart.panes()).toHaveLength(2);
    expect(second.paneIndex).toBe(1);
    expect(chart.getState().indicators?.map(i => i.indicatorId)).toEqual(['macd']);
    second.remove();
    expect(chart.panes()).toHaveLength(1);
  });

  it('restores legacy indicator state without a visibility field as visible', () => {
    const chart = makeChart();
    chart.restoreState({ version: 1, indicators: [{ indicatorId: 'rsi', settings: {}, paneIndex: 1 }] });
    expect(chart.indicators()[0].visible()).toBe(true);
  });
});

describe('shared object inventory', () => {
  it('delivers changes to every observer when one reads the inventory in its callback', () => {
    const chart = makeChart();
    const objects = new ChartObjects(chart);
    objects.subscribe(() => { objects.get('source:primary'); objects.refresh(); });
    let rows = objects.list();
    objects.subscribe(next => { rows = next; });
    chart.addIndicator('rsi');
    expect(rows.filter(row => row.kind === 'indicator')).toHaveLength(1);
  });

  it('enables drawing focus after data arrives without requiring an explicit refresh', () => {
    const chart = makeChart();
    const bars = chart.primarySeries()!.getData();
    chart.primarySeries()!.setData([]);
    const draw = new DrawingController(chart);
    const drawing = draw.add({ tool: 'trend-line', paneIndex: 0, style: {},
      points: [{ time: 1700000060, price: 23800 }] });
    const objects = new ChartObjects(chart, { drawings: draw });
    let canFocus = false;
    objects.subscribe(rows => { canFocus = rows.find(row => row.kind === 'drawing')!.capabilities.focus; });
    expect(canFocus).toBe(false);
    chart.primarySeries()!.setData(bars);
    expect(canFocus).toBe(true);
    expect(objects.get('drawing:' + drawing.id)).toBeDefined();
    draw.destroy();
  });

  it('finishes removal when an external indicator cleanup throws', () => {
    registerIndicator({ id: 'objects-throwing-cleanup', name: 'Cleanup test', placement: 'pane', inputs: [],
      plots: [{ key: 'value', title: 'Value', type: 'line' }], calc: () => ({ value: [] }),
      attach: () => () => { throw new Error('Host cleanup failed'); },
    });
    const chart = makeChart();
    const indicator = chart.addIndicator('objects-throwing-cleanup');
    const objects = new ChartObjects(chart);
    objects.remove('indicator:' + indicator.id);
    expect(chart.indicators()).toHaveLength(0);
    expect(chart.panes()).toHaveLength(1);
  });

  it('notifies observers when the host hides or replaces the primary series', () => {
    const chart = makeChart();
    const objects = new ChartObjects(chart);
    let rows = objects.list();
    objects.subscribe(next => { rows = next; });
    chart.primarySeries()!.applyOptions({ visible: false });
    expect(rows[0].visible).toBe(false);
    chart.primarySeries()!.remove();
    expect(rows).toEqual([]);
    chart.addSeries('line');
    expect(rows[0].kind).toBe('source');
  });

  it('clears an indicator selection immediately when the canvas selects a drawing', () => {
    const chart = makeChart();
    const indicator = chart.addIndicator('rsi');
    const draw = new DrawingController(chart);
    const drawing = draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [] });
    const objects = new ChartObjects(chart, { drawings: draw });
    let rows = objects.list();
    objects.subscribe(next => { rows = next; });
    objects.select('indicator:' + indicator.id);
    draw.select(drawing.id);
    expect(rows.filter(row => row.selected).map(row => row.id)).toEqual(['drawing:' + drawing.id]);
    draw.destroy();
  });

  it('protects the primary source and distinguishes repeated indicator instances', () => {
    const chart = makeChart();
    chart.setDataContext({ symbol: 'NIFTY', exchange: 'NFO', interval: '5m' });
    const a = chart.addIndicator('rsi');
    const b = chart.addIndicator('rsi');
    const objects = new ChartObjects(chart);
    const source = objects.list().find(o => o.kind === 'source')!;
    expect(source.name).toContain('NIFTY');
    expect(objects.remove(source.id)).toBe(false);
    expect(objects.setVisible(source.id, false)).toBe(false);
    expect(chart.primarySeries()?.getData()).toHaveLength(60);
    expect(objects.list().filter(o => o.kind === 'indicator').map(o => o.sourceId)).toEqual([a.id, b.id]);
    objects.remove('indicator:' + a.id);
    expect(objects.list().filter(o => o.kind === 'indicator').map(o => o.sourceId)).toEqual([b.id]);
  });

  it('observes external mutations and clears selection after direct removal', () => {
    const chart = makeChart();
    const objects = new ChartObjects(chart);
    let visible: boolean | undefined;
    let names: string[] = [];
    objects.subscribe(rows => {
      names = rows.filter(o => o.kind === 'indicator').map(o => o.sourceId);
      visible = rows.find(o => o.kind === 'indicator')?.visible;
    });
    const indicator = chart.addIndicator('rsi');
    expect(names).toEqual([indicator.id]);
    objects.select('indicator:' + indicator.id);
    indicator.setVisible(false);
    expect(visible).toBe(false);
    indicator.remove();
    expect(names).toEqual([]);
    expect(objects.list().some(o => o.selected)).toBe(false);
  });

  it('shares drawing selection, visibility, locking and undo with the real controller', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const objects = new ChartObjects(chart, { drawings: draw });
    const drawing = draw.add({ tool: 'trend-line', paneIndex: 0,
      points: [{ time: 1700000060, price: 23800 }, { time: 1700000300, price: 23810 }], style: {} });
    const id = 'drawing:' + drawing.id;
    let selected = false;
    objects.subscribe(rows => { selected = rows.find(o => o.id === id)?.selected ?? false; });
    draw.select(drawing.id);
    expect(selected).toBe(true);
    expect(objects.setLocked(id, true)).toBe(true);
    expect(draw.get(drawing.id)?.locked).toBe(true);
    expect(objects.setVisible(id, false)).toBe(true);
    expect(draw.get(drawing.id)?.visible).toBe(false);
    draw.undo();
    expect(objects.get(id)?.visible).toBe(true);
    expect(objects.remove(id)).toBe(true);
    expect(draw.get(drawing.id)).toBeUndefined();
    draw.undo();
    expect(objects.get(id)?.locked).toBe(true);
    draw.destroy();
  });

  it('focuses future anchors and their price on a primary left axis', () => {
    const chart = makeChart();
    chart.movePriceAxis(0, 'right', 'left');
    chart.setVisibleLogicalRange({ from: 0, to: 30 });
    const draw = new DrawingController(chart);
    const drawing = draw.add({ tool: 'trend-line', paneIndex: 0, style: {},
      points: [{ time: 1700000000 + 80 * 60, price: 25000 }, { time: 1700000000 + 85 * 60, price: 25010 }] });
    const objects = new ChartObjects(chart, { drawings: draw });
    expect(objects.focus('drawing:' + drawing.id)).toBe(true);
    const view = chart.getVisibleLogicalRange();
    expect(view.from).toBeLessThan(80);
    expect(view.to).toBeGreaterThan(85);
    const range = chart.panes()[0].readoutScale().priceRange();
    expect(range.min).toBeLessThan(25000);
    expect(range.max).toBeGreaterThan(25010);
    expect(draw.get(drawing.id)?.points).toEqual(drawing.points);
    draw.destroy();
  });

  it('offers settings only with a host editor and passes the current selected instance', () => {
    const chart = makeChart();
    const indicator = chart.addIndicator('rsi');
    const id = 'indicator:' + indicator.id;
    const without = new ChartObjects(chart);
    expect(without.openSettings(id)).toBe(false);
    const edited: string[] = [];
    const objects = new ChartObjects(chart, { onSettings: row => { edited.push(row.sourceId); } });
    expect(objects.openSettings(id)).toBe(true);
    expect(edited).toEqual([indicator.id]);
    indicator.remove();
    expect(objects.openSettings(id)).toBe(false);
  });

  it('uses explicit profile capabilities and idempotent provider cleanup', () => {
    const chart = makeChart();
    const objects = new ChartObjects(chart);
    let visible = true;
    let changed = () => {};
    let listeners = 0;
    const off = objects.register({ id: 'session-profile',
      get: () => ({ kind: 'profile', name: 'Session volume', paneIndex: 0, visible }),
      subscribe: cb => { changed = cb; listeners++; return () => { listeners--; }; },
      setVisible: on => { visible = on; changed(); },
    });
    const profile = objects.list().find(o => o.kind === 'profile')!;
    expect(objects.setVisible(profile.id, false)).toBe(true);
    expect(visible).toBe(false);
    expect(objects.remove(profile.id)).toBe(false);
    expect(objects.setLocked(profile.id, true)).toBe(false);
    expect(objects.get(profile.id)?.visible).toBe(false);
    off(); off();
    expect(listeners).toBe(0);
    expect(objects.get(profile.id)).toBeUndefined();
    objects.register({ id: 'session-profile', get: () => ({ kind: 'profile', name: 'Replacement' }) });
    off();
    expect(objects.get(profile.id)?.name).toBe('Replacement');
  });

  it('withdraws a provider from observers when its synchronous subscription fails', () => {
    const objects = new ChartObjects(makeChart());
    let rows = objects.list();
    objects.subscribe(next => { rows = next; });
    expect(() => objects.register({ id: 'failed', get: () => ({ kind: 'profile', name: 'Failed' }),
      subscribe: notify => { notify(); throw new Error('Subscription failed'); },
    })).toThrow('Subscription failed');
    expect(rows.some(row => row.id === 'custom:failed')).toBe(false);
  });

  it('isolates duplicate provider IDs and cannot replace the protected source', () => {
    const objects = new ChartObjects(makeChart());
    objects.register({ id: 'source:primary', get: () => ({ kind: 'profile', name: 'Custom' }), remove: () => {} });
    expect(objects.get('source:primary')?.kind).toBe('source');
    expect(objects.remove('source:primary')).toBe(false);
    expect(() => objects.register({ id: 'source:primary', get: () => null })).toThrow();
  });

  it('exposes immutable snapshots and detaches providers when the chart is destroyed', () => {
    const chart = makeChart();
    const objects = new ChartObjects(chart);
    let listeners = 0;
    objects.register({ id: 'test', get: () => ({ kind: 'profile', name: 'Profile' }),
      subscribe: () => { listeners++; return () => { listeners--; }; } });
    const row = objects.list()[0];
    expect(Reflect.set(row, 'name', 'Corrupted')).toBe(false);
    expect(Reflect.set(row.capabilities, 'remove', true)).toBe(false);
    chart.destroy();
    expect(listeners).toBe(0);
    expect(objects.list()).toEqual([]);
    expect(objects.remove(row.id)).toBe(false);
    objects.destroy();
  });

  it('removing an external study stops its subscription and does not affect another study', () => {
    let active = 0;
    registerIndicator({ id: 'objects-external-test', name: 'External test', placement: 'pane', inputs: [],
      plots: [{ key: 'value', title: 'Value', type: 'line' }], calc: () => ({ value: [] }),
      attach: ctx => { active++; ctx.setDataStatus?.({ state: 'unsupported' }); return () => { active--; }; },
    });
    const chart = makeChart();
    const a = chart.addIndicator('objects-external-test');
    const b = chart.addIndicator('objects-external-test');
    const objects = new ChartObjects(chart);
    expect(objects.get('indicator:' + a.id)?.dataStatus?.state).toBe('unsupported');
    expect(active).toBe(2);
    objects.remove('indicator:' + a.id);
    expect(active).toBe(1);
    expect(objects.get('indicator:' + b.id)?.paneIndex).toBe(1);
    chart.destroy();
    expect(active).toBe(0);
  });
});
