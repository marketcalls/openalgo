import { afterEach, describe, expect, it } from 'vitest';
import '../src/indicators/index';
import { AlertController } from '../src/alerts/controller';
import { Chart } from '../src/core/chart';
import { ChartObjects } from '../src/model/chart-objects';
import { DrawingController } from '../src/draw/index';
import { plotStyleKeys, registerIndicator } from '../src/model/indicator-registry';
import { PriceLine } from '../src/primitives/price-line';
import { fakeDocument } from './helpers/fake-dom';
const charts: Chart[] = [];
function makeChart() {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), { document, pixelRatio: () => 1, shortcuts: false, raf: { schedule: () => 0 } });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(Array.from({ length: 50 }, (_, i) => ({ time: 1700000000 + i * 60, open: 10 + i, high: 12 + i, low: 9 + i, close: 11 + i, volume: 100 })));
  charts.push(chart);
  return chart;
}
afterEach(() => { charts.splice(0).forEach(chart => chart.destroy()); });
describe('object organization', () => {
  it('moves the same study, series handles, levels and legend, then updates and removes on the new pane', () => {
    const chart = makeChart();
    const study = chart.addIndicator('rsi');
    const target = chart.addIndicator('macd');
    const sourcePane = chart.panes()[study.paneIndex];
    const records = [...sourcePane.series()];
    const visuals = [...sourcePane.primitives()];
    expect(typeof chart.moveIndicator).toBe('function');
    expect(chart.moveIndicator(study.id, target.paneIndex)).toBe(true);
    expect(chart.indicators().find(item => item.id === study.id)).toBe(study);
    expect(study.paneIndex).toBe(target.paneIndex);
    expect(chart.panes()[study.paneIndex].series()).toEqual(expect.arrayContaining(records));
    expect(chart.panes()[study.paneIndex].primitives()).toEqual(expect.arrayContaining(visuals));
    study.setSettings({ period: 7 });
    study.remove();
    expect(chart.panes()[target.paneIndex].series().some(record => records.includes(record))).toBe(false);
    expect(chart.indicators()).toEqual([target]);
  });
  it('moves attach-hook primitives while preserving forced price overlays', () => {
    const attached = new PriceLine({ id: 'attached', price: 20, color: '#112233' });
    registerIndicator({ id: 'organize-fixture', name: 'Organization fixture', placement: 'pane', inputs: [],
      plots: [{ key: 'value', title: 'Value', type: 'line' }, { key: 'price', title: 'Price', type: 'line', overlay: true }],
      calc: bars => ({ value: bars.map(b => b.close), price: bars.map(b => b.close) }),
      attach: ctx => { ctx.addPrimitive?.(attached); return () => ctx.removePrimitive?.(attached); },
    });
    const chart = makeChart();
    const study = chart.addIndicator('organize-fixture');
    chart.addIndicator('rsi');
    const priceRecords = [...chart.panes()[0].series()];
    expect(typeof chart.moveIndicator).toBe('function');
    chart.moveIndicator(study.id, 2);
    expect(chart.panes()[study.paneIndex].hasPrimitive(attached)).toBe(true);
    expect(chart.panes()[0].series()).toEqual(priceRecords);
    const saved = chart.getState();
    expect(saved.indicators?.find(item => item.instanceId === study.id)?.paneIndex).toBe(study.paneIndex);
  });
  it('reorders the actual series and primitive stack and saves the new instance order', () => {
    const chart = makeChart();
    const first = chart.addIndicator('sma');
    const second = chart.addIndicator('ema');
    const before = [...chart.panes()[0].series()];
    expect(typeof chart.reorderIndicator).toBe('function');
    expect(chart.reorderIndicator(second.id, -1)).toBe(true);
    expect(chart.indicators()).toEqual([second, first]);
    expect(chart.panes()[0].series()).toEqual([before[0], before[2], before[1]]);
    expect(chart.panes()[0].primitives().indexOf(second.legend()!)).toBeLessThan(chart.panes()[0].primitives().indexOf(first.legend()!));
    expect(chart.getState().indicators?.map(item => item.instanceId)).toEqual([second.id, first.id]);
  });
  it('groups drawings, applies shared actions and restores only valid unique members', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const one = draw.add({ tool: 'trend-line', points: [{ time: 1700000000, price: 10 }], paneIndex: 0, style: {} });
    const two = draw.add({ tool: 'trend-line', points: [{ time: 1700000060, price: 11 }], paneIndex: 0, style: {} });
    expect(typeof draw.createGroup).toBe('function');
    const group = draw.createGroup('Levels', [one.id, two.id])!;
    const objects = new ChartObjects(chart, { drawings: draw });
    expect(objects.select('group:' + group.id)).toBe(true);
    expect(draw.selection()).toEqual([one.id, two.id]);
    objects.setVisible('group:' + group.id, false);
    objects.setLocked('group:' + group.id, true);
    expect(draw.drawings().every(d => d.visible === false && d.locked)).toBe(true);
    const saved = draw.toJSON();
    saved.groups![0].members.push('missing', one.id);
    draw.fromJSON(saved);
    expect(draw.groups()).toEqual([{ id: group.id, name: 'Levels', members: [one.id, two.id] }]);
    expect(chart.getState().drawings).toEqual(draw.toJSON());
    objects.remove('group:' + group.id);
    expect(draw.drawings()).toHaveLength(0);
    expect(draw.groups()).toHaveLength(0);
  });
  it('reorders actual drawings within their renderer band and follows pane renumbering', () => {
    const chart = makeChart();
    chart.addIndicator('rsi');
    chart.addIndicator('macd');
    const draw = new DrawingController(chart);
    const one = draw.add({ tool: 'trend-line', points: [{ time: 1700000000, price: 10 }], paneIndex: 2, style: {} });
    const two = draw.add({ tool: 'trend-line', points: [{ time: 1700000060, price: 11 }], paneIndex: 2, style: {} });
    draw.setZIndex(one.id, 7);
    expect(typeof draw.reorder).toBe('function');
    expect(draw.reorder(one.id, -1)).toBe(true);
    expect([...draw.drawings()].sort((a, b) => a.zIndex - b.zIndex).map(d => d.id)).toEqual([one.id, two.id]);
    chart.removePane(1);
    expect(draw.get(one.id)?.paneIndex).toBe(1);
    expect(chart.panes()).toHaveLength(2);
    draw.destroy();
  });
});

it('restores group membership when undoing grouped removal or regrouping', () => {
  const chart = makeChart();
  const draw = new DrawingController(chart);
  const one = draw.add({ tool: 'trend-line', points: [{ time: 1700000000, price: 10 }], paneIndex: 0, style: {} });
  const two = draw.add({ tool: 'trend-line', points: [{ time: 1700000060, price: 11 }], paneIndex: 0, style: {} });
  const group = draw.createGroup('Levels', [one.id, two.id])!;
  draw.removeGroup(group.id, true);
  draw.undo();
  expect(draw.groups()).toEqual([group]);
  expect(draw.drawings().map(d => d.id)).toEqual([one.id, two.id]);
  draw.undo();
  expect(draw.groups()).toHaveLength(0);
  draw.redo();
  expect(draw.groups()).toEqual([group]);
});
it('keeps drawing history attached to panes after a pane is removed', () => {
  const chart = makeChart();
  chart.addIndicator('rsi'); chart.addIndicator('macd');
  const draw = new DrawingController(chart);
  const drawing = draw.add({ tool: 'trend-line', points: [{ time: 1700000000, price: 10 }], paneIndex: 2, style: {} });
  draw.update(drawing.id, { visible: false });
  draw.remove(drawing.id);
  chart.removePane(1);
  draw.undo();
  expect(draw.get(drawing.id)?.paneIndex).toBe(1);
  expect(chart.panes()).toHaveLength(2);
});
it('preserves explicit plot format on movement and does not apply a study range to shared price data', () => {
  registerIndicator({ id: 'organized-format', name: 'Formatted', placement: 'pane', inputs: [],
    plots: [{ key: 'v', title: 'Value', type: 'line', priceFormat: { type: 'custom', formatter: value => 'Q' + value } }],
    calc: bars => ({ v: bars.map(bar => bar.close) }) });
  const chart = makeChart();
  const custom = chart.addIndicator('organized-format');
  const target = chart.panes().length;
  chart.moveIndicator(custom.id, target);
  expect(chart.panes()[custom.paneIndex].priceScale.format(12)).toBe('Q12');
  const rsi = chart.addIndicator('rsi');
  chart.moveIndicator(rsi.id, 0);
  rsi.setSettings({ period: 7 });
  expect(chart.panes()[0].priceScale.fixedRange).toBeNull();
});

it('keeps alert references available and rehomes alert visuals without leaving an empty study pane', () => {
  const chart = makeChart();
  const study = chart.addIndicator('rsi');
  const target = chart.addIndicator('macd');
  const alerts = new AlertController(chart);
  const alert = alerts.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'rsi', value: 40 } });
  chart.moveIndicator(study.id, target.paneIndex);
  expect(alerts.list()[0].source).toEqual(alert.source);
  expect(alerts.availability(alert.id)).toMatchObject({ available: true, paneIndex: study.paneIndex });
  expect(chart.panes()).toHaveLength(2);
  expect(chart.panes()[study.paneIndex].primitives().some(item => item instanceof PriceLine && item.options().id === `alert:${alert.id}:0`)).toBe(true);
});
it('ignores malformed group records and drops duplicate membership deterministically', () => {
  const chart = makeChart(); const draw = new DrawingController(chart);
  const one = draw.add({ tool: 'trend-line', points: [{ time: 1, price: 10 }], paneIndex: 0, style: {} });
  const two = draw.add({ tool: 'trend-line', points: [{ time: 2, price: 11 }], paneIndex: 0, style: {} });
  draw.fromJSON({ ...draw.toJSON(), groups: [null, { id: 'bad', name: 1, members: [one.id] },
    { id: 'one', name: ' First ', members: [one.id, one.id, null, 'stale'] },
    { id: 'two', name: 'Second', members: [one.id, two.id] },
    { id: 'one', name: 'Duplicate id', members: [two.id] }] });
  expect(draw.groups()).toEqual([{ id: 'one', name: 'First', members: [one.id] }, { id: 'two', name: 'Second', members: [two.id] }]);
});

it('reorders the visible candle color contributions immediately', () => {
  for (const [id, color] of [['order-red', '#ff0000'], ['order-green', '#00ff00']]) registerIndicator({
    id, name: id, placement: 'onchart', inputs: [], plots: [{ key: 'v', title: 'Value', type: 'line' }],
    calc: bars => ({ v: bars.map(bar => bar.close) }), barColors: ({ bars }) => bars.map(() => color),
  });
  const chart = makeChart();
  chart.addIndicator('order-red'); const green = chart.addIndicator('order-green');
  expect(chart.primaryBars()[0].color).toBe('#00ff00');
  chart.reorderIndicator(green.id, -1);
  expect(chart.primaryBars()[0].color).toBe('#ff0000');
});

it('moves every study-owned visual and keeps attach-hook lifetime and series handles stable', () => {
  let attachments = 0; let detachments = 0;
  registerIndicator({ id: 'all-owned-visuals', name: 'Owned visuals', placement: 'pane', inputs: [],
    plots: [{ key: 'a', title: 'A', type: 'line' }, { key: 'b', title: 'B', type: 'line' }],
    fills: [{ between: ['a', 'b'] }], levels: () => [{ price: 20, color: '#333333' }],
    calc: bars => ({ a: bars.map(bar => bar.high), b: bars.map(bar => bar.low) }),
    markers: ({ bars }) => [{ time: bars[0].time, position: 'aboveBar', shape: 'circle', size: 'small', color: '#ff0000' }],
    table: () => ({ rows: [[{ text: 'Value' }]] }),
    draws: ({ bars }) => [{ kind: 'line', from: { time: bars[0].time, price: 10 }, to: { time: bars[1].time, price: 12 } }],
    background: ({ bars }) => bars.map(() => '#112233'),
    attach: ctx => { attachments++; const line = new PriceLine({ id: 'owned-hook', price: 18, color: '#000000' }); ctx.addPrimitive?.(line); return () => { detachments++; ctx.removePrimitive?.(line); }; },
  });
  const chart = makeChart(); const study = chart.addIndicator('all-owned-visuals');
  const api = study.series('a'); const original = chart.panes()[study.paneIndex].primitives().filter(item => ['IndicatorFill', 'PaneLegend', 'PriceLine', 'SeriesMarkers', 'ChartTable', 'IndicatorDrawings', 'IndicatorBackground'].includes(item.constructor.name));
  expect(original.length).toBe(8);
  chart.moveIndicator(study.id, chart.panes().length);
  expect(study.series('a')).toBe(api);
  expect(chart.panes()[study.paneIndex].primitives()).toEqual(expect.arrayContaining(original));
  expect(attachments).toBe(1); expect(detachments).toBe(0);
  study.remove(); expect(detachments).toBe(1);
});
it('updates pane-level legend controls when a study changes its pane role', () => {
  const chart = makeChart(); const study = chart.addIndicator('sma');
  expect(study.legend()?.options().actions).not.toContain('maximize');
  chart.moveIndicator(study.id, 1);
  expect(study.legend()?.options().actions).toContain('maximize');
  chart.moveIndicator(study.id, 0);
  expect(study.legend()?.options().actions).not.toContain('maximize');
});

it('prunes a vacated bottom pane while retaining chart-anchored furniture', () => {
  const chart = makeChart(); const target = chart.addIndicator('rsi'); const study = chart.addIndicator('macd');
  chart.moveIndicator(study.id, target.paneIndex);
  expect(chart.panes()).toHaveLength(2);
  expect(study.paneIndex).toBe(target.paneIndex);
});

it('preserves study stacking after settings replace plots and owned visuals', () => {
  const plot = { key: 'a', title: 'A', type: 'line' as const };
  registerIndicator({ id: 'restyled-stack', name: 'Restyled stack', placement: 'onchart',
    inputs: [{ key: 'level', label: 'Level', type: 'number', default: 20 }],
    plots: [plot, { key: 'b', title: 'B', type: 'line' }],
    fills: [{ between: ['a', 'b'] }],
    levels: ctx => [{ price: Number(ctx.settings?.level), color: '#333333' }],
    calc: bars => ({ a: bars.map(bar => bar.high), b: bars.map(bar => bar.low) }),
    markers: ({ bars }) => [{ time: bars[0].time, position: 'aboveBar', shape: 'circle', size: 'small', color: '#ff0000' }],
    table: () => ({ rows: [[{ text: 'Value' }]] }),
    attach: ctx => {
      const line = new PriceLine({ id: 'restyled-hook', price: 18, color: '#000000' });
      ctx.addPrimitive?.(line);
      return () => ctx.removePrimitive?.(line);
    },
  });
  const chart = makeChart();
  const first = chart.addIndicator('restyled-stack');
  const pane = chart.panes()[0];
  const firstSeries = [...pane.series()].slice(1);
  const firstVisuals = new Set(pane.primitives().filter(item => ['IndicatorFill', 'PaneLegend', 'PriceLine', 'SeriesMarkers', 'ChartTable'].includes(item.constructor.name)));
  const second = chart.addIndicator('restyled-stack');
  chart.reorderIndicator(second.id, -1);
  second.setSettings({ [plotStyleKeys(plot).type]: 'area', level: 30 });

  expect(chart.indicators()).toEqual([second, first]);
  expect(pane.series().slice(-firstSeries.length)).toEqual(firstSeries);
  const orderedVisuals = pane.primitives().filter(item => ['IndicatorFill', 'PaneLegend', 'PriceLine', 'SeriesMarkers', 'ChartTable'].includes(item.constructor.name));
  expect(orderedVisuals.map(item => firstVisuals.has(item) ? 'first' : 'second')).toEqual([
    'second', 'second', 'second', 'second', 'second', 'second',
    'first', 'first', 'first', 'first', 'first', 'first',
  ]);
  expect(chart.getState().indicators?.map(item => item.instanceId)).toEqual([second.id, first.id]);
});
