/**
 * The chart-wide history: one timeline for studies, their settings, the chart
 * type, price scales, panes and drawings. Each command type is taken back and
 * applied again against a measured chart, interleaved with drawing steps, and
 * checked against what it must never do: roll back price data, fire an alert
 * again, or touch an order.
 */
import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { AlertController } from '../src/alerts/controller';
import { registerIndicator, readChartSettings, applyChartSettings, createLinkGroup } from '../src/index';
import type { LinkChart } from '../src/link/group';
import type { Bar } from '../src/index';
import { fakeDocument } from './helpers/fake-dom';
import { DrawingController } from '../src/draw/index';
import { ChartHistory, type ChartHistoryError } from '../src/widget/history';

const T0 = 1700000000;
beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

const bars = (n: number): Bar[] => Array.from({ length: n }, (_, i) => {
  const c = 100 + Math.sin(i / 4) * 5 + i * 0.1;
  return { time: T0 + i * 60, open: c - 0.5, high: c + 2, low: c - 2, close: c, volume: 10 + i };
});

let failNext = false;
registerIndicator({
  id: 'hist-osc', name: 'History oscillator', placement: 'pane',
  inputs: [
    { key: 'length', type: 'number', label: 'Length', default: 5 },
    { key: 'source', type: 'source', label: 'Source', default: 'close', allowStudyOutputs: true },
  ],
  plots: [{ key: 'value', title: 'Value', type: 'line' }],
  calc: (b) => {
    if (failNext) throw new Error('calculation refused');
    return { value: b.map(x => x.close) };
  },
});
registerIndicator({
  id: 'hist-overlay', name: 'History overlay', placement: 'onchart',
  inputs: [{ key: 'length', type: 'number', label: 'Length', default: 3 }],
  plots: [{ key: 'value', title: 'Value', type: 'line' }],
  calc: (b) => ({ value: b.map(x => x.high) }),
});
registerIndicator({
  id: 'hist-alerting', name: 'History alerting', placement: 'pane',
  inputs: [{ key: 'length', type: 'number', label: 'Length', default: 2 }],
  plots: [{ key: 'value', title: 'Value', type: 'line' }],
  // True on every bar: any evaluation of history would announce each one.
  alerts: [{ id: 'always', title: 'Always', when: () => true }],
  calc: (b) => ({ value: b.map(x => x.close) }),
});
registerIndicator({
  id: 'hist-bands', name: 'History bands', placement: 'onchart',
  inputs: [{ key: 'width', type: 'number', label: 'Width', default: 2 }],
  plots: [{ key: 'upper', title: 'Upper', type: 'line' }, { key: 'lower', title: 'Lower', type: 'line' }],
  calc: (b) => ({ upper: b.map(x => x.high + 1), lower: b.map(x => x.low - 1) }),
});
let asyncWork: Promise<void> = Promise.resolve();
registerIndicator({
  id: 'hist-async', name: 'History async', placement: 'pane',
  inputs: [{ key: 'length', type: 'number', label: 'Length', default: 4 }],
  plots: [{ key: 'value', title: 'Value', type: 'line' }],
  calc: (b, _s, store) => ({ value: b.map(x => (store.ready === true ? x.close : null)) }),
  attach: (ctx) => {
    ctx.setDataStatus?.({ state: 'loading' });
    asyncWork = Promise.resolve().then(() => Promise.resolve()).then(() => {
      if (ctx.signal?.aborted) return;
      ctx.store.ready = true;
      ctx.setDataStatus?.({ state: 'ready' });
      ctx.requestRecompute();
    });
  },
});

const charts: Chart[] = [];
function makeChart(options: Record<string, unknown> = {}): Chart {
  const chart = new Chart(fakeDocument().createElement('div') as unknown as HTMLElement, {
    document: fakeDocument(),
    raf: { schedule: (cb: (t: number) => void) => { cb(0); return 0; } },
    pixelRatio: () => 1, shortcuts: false, ...options,
  });
  chart.applySize(800, 600);
  charts.push(chart);
  return chart;
}
afterEach(() => { failNext = false; for (const chart of charts.splice(0)) if (!chart.isDestroyed) chart.destroy(); });

interface Rig { chart: Chart; draw: DrawingController; history: ChartHistory; errors: ChartHistoryError[] }
function rig(options: Record<string, unknown> = {}): Rig {
  const chart = makeChart(options);
  chart.addSeries('candlestick').setData(bars(80));
  const draw = new DrawingController(chart);
  const errors: ChartHistoryError[] = [];
  const history = new ChartHistory(chart, { draw, onError: e => errors.push(e) });
  return { chart, draw, history, errors };
}

/** The turn an action ran in is over: observed changes are recorded then. */
const settle = (): Promise<void> => new Promise(resolve => setTimeout(resolve, 0));

const studyIds = (chart: Chart): string[] => chart.indicators().map(s => s.id);
const layout = (chart: Chart) => ({
  studies: chart.indicators().map(s => ({ id: s.id, pane: s.paneIndex, settings: s.settings(), visible: s.visible(), scale: s.priceScaleId() })),
  weights: chart.panes().map((_, i) => chart.paneWeight(i)),
  collapsed: chart.panes().map((_, i) => chart.paneCollapsed(i)),
});
const line = (price: number, paneIndex = 0) => ({ tool: 'horizontal-line', paneIndex, points: [{ time: T0 + 10 * 60, price }], style: {} });
/**
 * Each pane's studies in their stacking order, without ids. The order across
 * panes is not a thing the chart lets anyone set; within a pane it is the
 * order the rows and the plots are drawn in.
 */
const stacks = (chart: Chart) => chart.panes().map((_, slot) => chart.indicators().filter(s => s.paneIndex === slot)
  .map(s => ({ indicatorId: s.indicatorId, settings: s.settings(), visible: s.visible(), scale: s.priceScaleId() })));

describe('studies', () => {
  it('takes an added study back and brings it again, settings and pane included', async () => {
    const { chart, history } = rig();
    const before = layout(chart);
    const study = chart.addIndicator('hist-osc', { length: 9 });
    await settle();
    expect(history.canUndo()).toBe(true);
    expect(history.peekUndo()?.changes).toContain('study-add');
    const added = layout(chart);

    expect(history.undo()).toBe(true);
    expect(studyIds(chart)).toEqual([]);
    expect(chart.panes()).toHaveLength(1);
    expect(layout(chart)).toEqual(before);

    expect(history.redo()).toBe(true);
    expect(chart.indicators()).toHaveLength(1);
    expect(chart.indicators()[0].settings()).toEqual(study.settings());
    expect(chart.indicators()[0].paneIndex).toBe(1);
    expect(layout(chart).weights).toEqual(added.weights);
  });

  it('brings a removed study back to its slot, weight, fold, scale, visibility and stack position', async () => {
    const { chart, history } = rig();
    const a = chart.addIndicator('hist-osc', { length: 3 });
    const b = chart.addIndicator('hist-osc', { length: 4 });
    const c = chart.addIndicator('hist-osc', { length: 5 });
    const overlay = chart.addIndicator('hist-overlay', { length: 7 }, { priceScaleId: 'left' });
    const second = chart.addIndicator('hist-overlay', { length: 8 });
    chart.setPaneWeight(2, 0.9);
    chart.setPaneCollapsed(2, true);
    b.setVisible(false);
    await settle();
    history.clear();
    const before = layout(chart);
    const beforeStacks = stacks(chart);

    history.group()();                    // an empty group is no step
    chart.removeIndicator(b.id);          // the pane in the middle goes with it
    chart.removeIndicator(overlay.id);
    await settle();
    expect(chart.panes()).toHaveLength(3);
    expect(history.peekUndo()?.changes).toEqual(['study-remove']);

    expect(history.undo()).toBe(true);
    // Until the chart takes an instance id back, a study returns under a new
    // one; everything else about it is as it was, the row it held included.
    expect(stacks(chart)).toEqual(beforeStacks);
    expect(layout(chart).weights).toEqual(before.weights);
    expect(layout(chart).collapsed).toEqual(before.collapsed);
    const pricePane = chart.indicators().filter(s => s.paneIndex === 0);
    expect(pricePane[0].priceScaleId()).toBe('left');
    expect(pricePane[1].id).toBe(second.id);
    expect(a.paneIndex).toBe(1);
    expect(c.paneIndex).toBe(3);
    expect(history.canUndo()).toBe(false);

    expect(history.redo()).toBe(true);
    expect(chart.indicators()).toHaveLength(3);
    expect(chart.panes()).toHaveLength(3);
    expect(history.undo()).toBe(true);
    expect(stacks(chart)).toEqual(beforeStacks);
    expect(layout(chart).collapsed).toEqual(before.collapsed);
  });

  it('asks the chart for the removed instance id and keeps a dependent reading it', async () => {
    const { chart, history } = rig();
    const source = chart.addIndicator('hist-osc', { length: 3 });
    const reader = chart.addIndicator('hist-osc', { source: { kind: 'indicator', instanceId: source.id, plotKey: 'value' } });
    await settle();
    history.clear();
    const add = vi.spyOn(chart, 'addIndicator');
    chart.removeIndicator(source.id);
    await settle();
    history.undo();
    // The id is asked for, so a chart that can reuse it answers to the same one.
    expect(add.mock.calls[0][2]).toMatchObject({ instanceId: source.id });
    const other = (): ReturnType<Chart['indicators']>[number] => chart.indicators().find(s => s.id !== reader.id)!;
    const readsFrom = (): string => (reader.settings().source as { instanceId: string }).instanceId;
    expect(readsFrom()).toBe(other().id);
    expect(other().paneIndex).toBe(1);
    expect(reader.paneIndex).toBe(2);

    // Removed and brought back again: the reader follows each time.
    history.redo();
    expect(chart.indicators().map(s => s.id)).toEqual([reader.id]);
    history.undo();
    expect(readsFrom()).toBe(other().id);
    expect(other().settings().length).toBe(3);

    // Later steps that name the study reach it under whichever id it answers to.
    other().setSettings({ length: 11 });
    await settle();
    history.undo();
    expect(other().settings().length).toBe(3);
    history.redo();
    expect(other().settings().length).toBe(11);
  });

  it('brings a removed study back under the instance id it had, so an alert keyed to it reaches it again', async () => {
    const { chart, history } = rig();
    const study = chart.addIndicator('hist-osc', { length: 3 });
    const alerts = new AlertController(chart);
    const alert = alerts.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'value', value: 100 } });
    await settle();
    history.clear();
    expect(alerts.availability(alert.id).available).toBe(true);
    chart.removeIndicator(study.id);
    await settle();
    expect(alerts.availability(alert.id).available).toBe(false);
    history.undo();
    expect(studyIds(chart)).toEqual([study.id]);
    expect(alerts.availability(alert.id).available).toBe(true);
    history.redo();
    history.undo();
    expect(studyIds(chart)).toEqual([study.id]);
  });

  it.each([['of another kind', 'hist-overlay'], ['of the same kind', 'hist-osc']] as const)(
    'brings a removed study back under a fresh id when a study %s holds its id by then, and leaves that one to the host', async (_kind, kind) => {
      const { chart, history, errors } = rig();
      const source = chart.addIndicator('hist-osc', { length: 3 });
      const reader = chart.addIndicator('hist-osc', { source: { kind: 'indicator', instanceId: source.id, plotKey: 'value' } });
      await settle();
      history.clear();
      chart.removeIndicator(source.id);
      await settle();
      // The id came free, and the host placed a study of its own under it.
      const holder = history.ignore(() => chart.addIndicator(kind, { length: 7 }, { instanceId: source.id }));
      const holderPane = chart.panes()[holder.paneIndex];
      const add = vi.spyOn(chart, 'addIndicator');

      expect(history.undo()).toBe(true);
      expect(errors).toEqual([]);
      expect(add.mock.calls[0][2]).toMatchObject({ instanceId: source.id });
      const back = (): ReturnType<Chart['indicators']>[number] | undefined =>
        chart.indicators().find(s => s.indicatorId === 'hist-osc' && s !== holder && s !== reader);
      expect(back()?.id).toBeDefined();
      expect(back()!.id).not.toBe(source.id);
      expect(back()!.settings().length).toBe(3);
      expect(back()!.paneIndex).toBe(1);
      expect((reader.settings().source as { instanceId: string }).instanceId).toBe(back()!.id);
      // The host's study keeps the id, its pane and its settings.
      expect(chart.indicators().find(s => s.id === source.id)).toBe(holder);
      expect(chart.panes()[holder.paneIndex]).toBe(holderPane);
      expect(holder.settings().length).toBe(7);

      // From here on each step reaches each study as itself.
      expect(history.redo()).toBe(true);
      expect(back()).toBeUndefined();
      expect(chart.indicators()).toContain(holder);
      expect(history.undo()).toBe(true);
      expect(back()!.settings().length).toBe(3);
      holder.setSettings({ length: 9 });
      await settle();
      back()!.setSettings({ length: 4 });
      await settle();
      expect(history.undo()).toBe(true);
      expect(back()!.settings().length).toBe(3);
      expect(holder.settings().length).toBe(9);
      expect(history.undo()).toBe(true);
      expect(holder.settings().length).toBe(7);
      expect(back()!.settings().length).toBe(3);
      expect(errors).toEqual([]);
    });

  it('leaves a study the host protects under the freed id alone, and keeps every step behind the one that meets it', async () => {
    const { chart, history, errors } = rig();
    const source = chart.addIndicator('hist-osc', { length: 3 });
    await settle();
    history.clear();
    const earlier = chart.addIndicator('hist-overlay', { length: 4 });
    await settle();
    chart.removeIndicator(source.id);
    await settle();
    const holder = history.ignore(() => chart.addIndicator('hist-osc', { length: 7 },
      { instanceId: source.id, policy: { removable: false, movable: false, configurable: false } }));
    const osc = (): ReturnType<Chart['indicators']>[number][] => chart.indicators().filter(s => s.indicatorId === 'hist-osc');

    expect(history.undo()).toBe(true);
    expect(errors).toEqual([]);
    expect(osc()).toHaveLength(2);
    const back = osc().find(s => s !== holder)!;
    expect(back.settings().length).toBe(3);
    expect(holder.id).toBe(source.id);
    expect(holder.settings().length).toBe(7);
    expect(history.canUndo()).toBe(true);
    expect(history.undo()).toBe(true);
    expect(chart.indicators().some(s => s.id === earlier.id)).toBe(false);
    expect(history.redo()).toBe(true);
    expect(history.redo()).toBe(true);
    expect(osc()).toEqual([holder]);
    expect(chart.indicators()).toHaveLength(2);
    expect(errors).toEqual([]);
  });

  it('records study settings, visibility, scale assignment and stacking as steps', async () => {
    const { chart, history } = rig();
    const one = chart.addIndicator('hist-overlay', { length: 3 });
    const two = chart.addIndicator('hist-overlay', { length: 4 });
    await settle();
    history.clear();

    one.setSettings({ length: 12, 'value:color': '#ff0000' });
    await settle();
    two.setVisible(false);
    await settle();
    one.setPriceScale('left');
    await settle();
    chart.reorderIndicator(two.id, -1);
    await settle();
    expect(studyIds(chart)).toEqual([two.id, one.id]);

    expect(history.peekUndo()?.changes).toEqual(['study-order']);
    history.undo();
    expect(studyIds(chart)).toEqual([one.id, two.id]);
    history.undo();
    expect(one.priceScaleId()).toBeNull();
    history.undo();
    expect(two.visible()).toBe(true);
    history.undo();
    expect(one.settings().length).toBe(3);
    expect(one.settings()['value:color']).not.toBe('#ff0000');
    expect(history.canUndo()).toBe(false);

    for (let i = 0; i < 4; i++) expect(history.redo()).toBe(true);
    expect(one.settings()).toMatchObject({ length: 12, 'value:color': '#ff0000' });
    expect(two.visible()).toBe(false);
    expect(one.priceScaleId()).toBe('left');
    expect(studyIds(chart)).toEqual([two.id, one.id]);
  });

  it('moves a study back to the pane it left, recreating the pane it emptied', async () => {
    const { chart, history } = rig();
    const a = chart.addIndicator('hist-osc');
    const b = chart.addIndicator('hist-osc');
    chart.setPaneWeight(2, 0.6);
    await settle();
    history.clear();
    chart.moveIndicator(b.id, 1);
    await settle();
    expect(chart.panes()).toHaveLength(2);
    history.undo();
    expect(chart.panes()).toHaveLength(3);
    expect(b.paneIndex).toBe(2);
    expect(a.paneIndex).toBe(1);
    expect(chart.paneWeight(2)).toBeCloseTo(0.6);
    history.redo();
    expect(b.paneIndex).toBe(1);
    expect(chart.panes()).toHaveLength(2);
  });
});

describe('chart type and price scales', () => {
  it('takes a chart type back without touching the bars, including a bar that arrived since', async () => {
    const { chart, history } = rig();
    const series = chart.primarySeries()!;
    const setData = vi.spyOn(series, 'setData');
    chart.setSeriesType(series, 'line');
    await settle();
    expect(history.peekUndo()?.changes).toEqual(['chart-type']);
    const tick = { ...bars(81)[80] };
    series.update(tick);
    history.undo();
    expect(chart.seriesType(series)).toBe('candlestick');
    expect(series.getData()).toHaveLength(81);
    expect(series.getData()[80]).toMatchObject({ time: tick.time, close: tick.close });
    history.redo();
    expect(chart.seriesType(series)).toBe('line');
    expect(series.getData()).toHaveLength(81);
    expect(setData).not.toHaveBeenCalled();
  });

  it('routes the chart type through the host when it owns it', async () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(40));
    const setChartType = vi.fn((type: string) => chart.setSeriesType(chart.primarySeries()!, type as never));
    const history = new ChartHistory(chart, { setChartType });
    chart.setSeriesType(chart.primarySeries()!, 'area');
    await settle();
    history.undo();
    expect(setChartType).toHaveBeenCalledWith('candlestick');
  });

  it('records scale options, auto-fit and chart settings made in a transaction', async () => {
    const { chart, history } = rig();
    history.transact(() => chart.setPriceAxisOptions(0, 'right', { mode: 'logarithmic', inverted: true }), 'Scale');
    history.transact(() => chart.setPriceAxisAutoFit(0, 'right', false));
    const settings = readChartSettings(chart);
    const key = Object.keys(settings).find(k => k === 'grid.vertLines' || k.endsWith('vertLines'));
    expect(key).toBeDefined();
    history.transact(() => chart.setGridOptions({ vertLines: !settings[key!] }));
    expect(history.peekUndo()?.changes).toEqual(['settings']);

    history.undo();
    expect(readChartSettings(chart)[key!]).toBe(settings[key!]);
    history.undo();
    expect(chart.priceAxisState(0, 'right')?.autoFit).toBe(true);
    // The price pane's own axis, set from its menu: the chart-wide defaults
    // did not move, so it is no chart setting, lone pane or not.
    expect(history.peekUndo()).toEqual({ label: 'Scale', changes: ['axis'] });
    expect(chart.priceScaleDefaults()).toEqual({});
    history.undo();
    expect(chart.priceAxisState(0, 'right')).toMatchObject({ mode: 'linear', inverted: false });
    history.redo();
    expect(chart.priceAxisState(0, 'right')).toMatchObject({ mode: 'logarithmic', inverted: true });
  });

  it('replays one axis inverted from its menu on that axis alone, and a chart-wide invert on every pane', async () => {
    const { chart, history } = rig();
    chart.addIndicator('hist-osc');
    chart.addIndicator('hist-osc');
    await settle();
    history.clear();
    const inverted = (): boolean[] => chart.panes().map((_, i) => chart.priceAxisState(i, 'right')!.inverted);

    history.transact(() => chart.setPriceAxisOptions(0, 'right', { inverted: true }), 'Axis menu');
    expect(inverted()).toEqual([true, false, false]);
    history.undo();
    expect(inverted()).toEqual([false, false, false]);
    history.redo();
    expect(inverted()).toEqual([true, false, false]);
    history.undo();

    history.transact(() => applyChartSettings(chart, { 'scales.inverted': true }), 'Settings');
    expect(inverted()).toEqual([true, true, true]);
    expect(history.peekUndo()?.changes).toEqual(expect.arrayContaining(['settings', 'axis']));
    history.undo();
    expect(inverted()).toEqual([false, false, false]);
    history.redo();
    expect(inverted()).toEqual([true, true, true]);
    // The chart-wide default came back with it: a pane made now is inverted too.
    chart.addIndicator('hist-osc');
    expect(inverted()).toEqual([true, true, true, true]);
  });

  it('records a pane weight and an axis option set outside any transaction, which the chart announces with layout:change', async () => {
    const { chart, history } = rig();
    chart.addIndicator('hist-osc');
    await settle();
    history.clear();
    chart.setPaneWeight(1, 0.6);
    await settle();
    expect(history.peekUndo()?.changes).toEqual(['pane-weight']);
    chart.setPriceAxisOptions(1, 'right', { mode: 'logarithmic', marginTop: 0.2 });
    await settle();
    expect(history.peekUndo()?.changes).toEqual(['axis']);
    // Auto-fit is a view the same event announces, never a step of its own.
    chart.setPriceAxisAutoFit(1, 'right', false);
    await settle();
    expect(history.peekUndo()?.changes).toEqual(['axis']);
    expect(history.undo()).toBe(true);
    expect(chart.priceAxisState(1, 'right')?.mode).toBe('linear');
    expect(chart.panes()[1].scaleFor('right').options.marginTop).toBeCloseTo(0.1);
    expect(history.undo()).toBe(true);
    expect(chart.paneWeight(1)).toBeCloseTo(0.32);
    expect(history.canUndo()).toBe(false);
    expect(history.redo()).toBe(true);
    expect(chart.paneWeight(1)).toBeCloseTo(0.6);
    expect(history.redo()).toBe(true);
    expect(chart.priceAxisState(1, 'right')?.mode).toBe('logarithmic');
  });

  it('replays an axis-menu change on a lone price pane on that axis alone, and a chart-wide default with the axes', async () => {
    const { chart, history } = rig();
    history.clear();
    const heard: unknown[] = [];
    chart.on('style:change', payload => heard.push(payload));
    // From the axis menu: every pane there is moves, but the default a new pane starts from does not.
    history.transact(() => chart.setPriceAxisOptions(0, 'right', { mode: 'logarithmic' }), 'Axis menu');
    expect(history.undo()).toBe(true);
    expect(chart.priceAxisState(0, 'right')?.mode).toBe('linear');
    expect(history.redo()).toBe(true);
    expect(chart.priceAxisState(0, 'right')?.mode).toBe('logarithmic');
    expect(chart.priceScaleDefaults().mode).toBeUndefined();
    expect(heard).toEqual([]);
    chart.addIndicator('hist-osc');
    expect(chart.panes()[1].priceScale.options.mode).toBe('linear');
    await settle();
    history.clear();

    // Chart wide, and outside any transaction: the default goes back with every axis.
    chart.setPriceScaleOptions({ inverted: true });
    await settle();
    const inverted = (): boolean[] => chart.panes().map((_, i) => chart.priceAxisState(i, 'right')!.inverted);
    expect(inverted()).toEqual([true, true]);
    expect(history.peekUndo()?.changes).toEqual(expect.arrayContaining(['settings', 'axis']));
    expect(history.undo()).toBe(true);
    expect(inverted()).toEqual([false, false]);
    expect(chart.priceScaleDefaults().inverted).not.toBe(true);
    expect(history.redo()).toBe(true);
    expect(inverted()).toEqual([true, true]);
    expect(chart.priceScaleDefaults().inverted).toBe(true);
  });

  it('takes back a pinned ratio and both plot margins, each as its own step', async () => {
    const { chart, history } = rig();
    chart.addIndicator('hist-osc');
    await settle();
    history.clear();
    const scale = (slot: number) => chart.panes()[slot].scaleFor('right').options;
    const top = scale(1).marginTop;
    const bottom = scale(1).marginBottom;
    history.transact(() => chart.setPriceAxisLockRatio(0, 'right', true), 'Pin');
    history.transact(() => chart.setPriceAxisOptions(1, 'right', { marginBottom: 0.3 }), 'Bottom');
    history.transact(() => chart.setPriceAxisOptions(1, 'right', { marginTop: 0.25 }), 'Top');
    expect(chart.panes()[0].ratioLocked('right')).toBe(true);

    history.undo();
    expect(scale(1).marginTop).toBeCloseTo(top);
    expect(scale(1).marginBottom).toBeCloseTo(0.3);
    history.undo();
    expect(scale(1).marginBottom).toBeCloseTo(bottom);
    expect(chart.panes()[0].ratioLocked('right')).toBe(true);
    history.undo();
    expect(chart.panes()[0].ratioLocked('right')).toBe(false);
    for (let i = 0; i < 3; i++) history.redo();
    expect(chart.panes()[0].ratioLocked('right')).toBe(true);
    expect(scale(1).marginBottom).toBeCloseTo(0.3);
    expect(scale(1).marginTop).toBeCloseTo(0.25);
  });

  it('takes back a plot moved to another scale, and brings a study back with its plots where they were', async () => {
    const { chart, history } = rig();
    const bands = chart.addIndicator('hist-bands');
    await settle();
    history.clear();
    expect(bands.setPlotPriceScales({ upper: 'left' })).toBe(true);
    await settle();
    expect(history.peekUndo()?.changes).toEqual(['study-scale']);
    history.undo();
    expect(bands.plotPriceScaleIds()).toEqual({});
    history.redo();
    expect(bands.plotPriceScaleIds()).toEqual({ upper: 'left' });

    chart.removeIndicator(bands.id);
    await settle();
    history.undo();
    const back = chart.indicators()[0];
    expect(back.plotPriceScaleIds()).toEqual({ upper: 'left' });
    expect(back.series('upper')?.priceScale()).toBe(chart.panes()[0].scaleFor('left'));
  });

  it('takes back a scale placement and a series scale assignment', async () => {
    const { chart, history } = rig();
    const series = chart.primarySeries()!;
    chart.setSeriesPriceScale(series, 'left');
    await settle();
    expect(history.peekUndo()?.changes).toContain('series-scale');
    chart.setPriceAxisPlacement(0, 'left', 'right', 1);
    await settle();
    expect(chart.priceAxisPlacement(0, 'left')).toEqual({ side: 'right', order: 1 });
    history.undo();
    expect(chart.priceAxisPlacement(0, 'left')?.side).toBe('left');
    history.undo();
    expect(series.priceScale()).toBe(chart.panes()[0].scaleFor('right'));
    history.redo();
    expect(series.priceScale()).toBe(chart.panes()[0].scaleFor('left'));
  });
});

describe('panes', () => {
  it('moves, folds and resizes panes as separate steps and walks them back in order', async () => {
    const { chart, history } = rig();
    const a = chart.addIndicator('hist-osc');
    const b = chart.addIndicator('hist-osc');
    await settle();
    history.clear();
    chart.movePane(1, 1);
    await settle();
    chart.setPaneCollapsed(1, true);
    await settle();
    history.transact(() => chart.setPaneWeight(2, 0.7), 'Resize');
    chart.setPaneWeight(1, 0.4);
    chart.emit('paneResized', { paneIndex: 1 });   // a divider drag ends
    await settle();
    expect(history.peekUndo()?.changes).toEqual(['pane-weight']);

    history.undo();
    expect(chart.paneWeight(1)).toBeCloseTo(0.32);
    history.undo();
    expect(chart.paneWeight(2)).toBeCloseTo(0.32);
    history.undo();
    expect(chart.paneCollapsed(1)).toBe(false);
    history.undo();
    expect([a.paneIndex, b.paneIndex]).toEqual([1, 2]);
    expect(history.canUndo()).toBe(false);
    for (let i = 0; i < 4; i++) history.redo();
    expect([a.paneIndex, b.paneIndex]).toEqual([2, 1]);
    expect(chart.paneCollapsed(1)).toBe(true);
  });

  it('brings back a removed pane with every study and drawing it held', async () => {
    const { chart, draw, history } = rig();
    const a = chart.addIndicator('hist-osc', { length: 6 });
    chart.addIndicator('hist-osc', { length: 7 }, { paneIndex: 1 });
    chart.addIndicator('hist-osc', { length: 8 });
    await settle();
    const marker = draw.add(line(50, 1));
    history.clear();
    chart.removePane(1);
    await settle();
    expect(chart.indicators()).toHaveLength(1);
    expect(draw.get(marker.id)).toBeUndefined();

    history.undo();
    expect(chart.panes()).toHaveLength(3);
    expect(stacks(chart).map(pane => pane.map(s => s.settings.length))).toEqual([[], [6, 7], [8]]);
    expect(draw.get(marker.id)?.paneIndex).toBe(1);
    history.redo();
    expect(chart.panes()).toHaveLength(2);
    expect(draw.get(marker.id)).toBeUndefined();
    expect(chart.indicators().some(s => s.id === a.id)).toBe(false);
  });

  it('brings back a pane that held only drawings, as a step of its own, with its height and place', async () => {
    const { chart, draw, history } = rig();
    const a = chart.addIndicator('hist-osc');
    const b = chart.addIndicator('hist-osc');
    await settle();
    const mark = draw.add(line(50, 1));
    chart.moveIndicator(a.id, 2);          // pane 1 keeps only the drawing
    await settle();
    history.ignore(() => chart.setPaneWeight(1, 0.45));
    // Nothing is plotted there: the range its scale kept from the study is
    // what places the drawing (set here as a painted frame would have).
    const range = { min: 20, max: 80 };
    chart.panes()[1].scaleFor('right').setComputedRange(range);
    history.clear();
    expect(chart.panes()).toHaveLength(3);

    expect(chart.removePane(1)).toBe(true);
    await settle();
    expect(draw.get(mark.id)).toBeUndefined();
    expect(history.peekUndo()?.changes).toEqual(['pane-remove']);
    history.undo();
    expect(chart.panes()).toHaveLength(3);
    expect(draw.get(mark.id)?.paneIndex).toBe(1);
    expect(chart.paneWeight(1)).toBeCloseTo(0.45);
    expect(chart.panes()[1].scaleFor('right').priceRange()).toEqual(range);
    expect([a.paneIndex, b.paneIndex]).toEqual([2, 2]);
    history.redo();
    expect(chart.panes()).toHaveLength(2);
    expect(draw.get(mark.id)).toBeUndefined();
    history.undo();
    expect(draw.get(mark.id)?.paneIndex).toBe(1);
    expect(history.canUndo()).toBe(false);
  });

  it('leaves a pane a host makes for its own primitive or plots a series in to the host', async () => {
    const { chart, history } = rig();
    const visual = { zOrder: () => 'bottom' as const, draw: () => {} };
    chart.addPrimitive(visual, 1);          // a pane with nothing plotted in it, made for the host's primitive
    await settle();
    expect(chart.panes()).toHaveLength(2);
    expect(history.canUndo()).toBe(false);
    expect(history.peekUndo()).toBeNull();
    chart.addIndicator('hist-osc');
    await settle();
    expect(history.peekUndo()?.changes).toEqual(['study-add']);
    expect(history.undo()).toBe(true);
    expect(chart.panes()).toHaveLength(2);
    expect(chart.panes()[1].hasPrimitive(visual)).toBe(true);
    expect(history.canUndo()).toBe(false);
    expect(history.redo()).toBe(true);
    history.clear();
    // Taken away with its primitive, which no undo could give the host back: no step either.
    expect(chart.removePane(1)).toBe(true);
    await settle();
    expect(chart.panes()).toHaveLength(2);
    expect(history.canUndo()).toBe(false);

    // A series a host plots in a pane of its own is price data, which history never takes away.
    chart.addSeries('line', { paneIndex: 2 }).setData(bars(20));
    await settle();
    expect(chart.panes()).toHaveLength(3);
    expect(history.canUndo()).toBe(false);
    chart.addIndicator('hist-osc');
    await settle();
    expect(history.peekUndo()?.changes).toEqual(['study-add']);
    history.undo();
    expect(chart.panes()).toHaveLength(3);
  });

  it('puts a price pane moved below its studies back on top', async () => {
    const { chart, history } = rig({ movablePrimaryPane: true });
    chart.addIndicator('hist-osc');
    await settle();
    history.clear();
    expect(chart.setPrimaryPaneIndex(1)).toBe(true);
    await settle();
    expect(history.peekUndo()?.changes).toContain('pane-order');
    history.undo();
    expect(chart.primaryPaneIndex()).toBe(0);
    history.redo();
    expect(chart.primaryPaneIndex()).toBe(1);
  });
});

describe('one timeline with drawings', () => {
  it('drops every drawing step and orphan once the controller loads another document', async () => {
    const { chart, draw, history } = rig();
    chart.addIndicator('hist-osc');
    await settle();
    draw.add(line(50, 1));
    const kept = draw.add(line(101));
    expect(chart.removePane(1)).toBe(true);
    await settle();
    // Another instrument's drawings, as a host keeping them per instrument loads them.
    draw.fromJSON({ version: 2, drawings: [] });
    expect(history.peekUndo()?.changes).toEqual(['study-remove']);
    expect(history.undo()).toBe(true);
    expect(chart.panes()).toHaveLength(2);
    expect(draw.drawings()).toEqual([]);
    // The study add is still a step; the drawing added before it no longer is.
    expect(history.undo()).toBe(true);
    expect(chart.indicators()).toHaveLength(0);
    expect(history.canUndo()).toBe(false);
    expect(draw.get(kept.id)).toBeUndefined();
  });

  it('interleaves drawing steps with chart steps and walks them in order both ways', async () => {
    const { chart, draw, history } = rig();
    const first = draw.add(line(101));
    const study = chart.addIndicator('hist-osc');
    await settle();
    draw.update(first.id, { style: { color: '#123456' } });
    study.setSettings({ length: 21 });
    await settle();
    expect(history.peekUndo()?.changes).toEqual(['study-settings']);

    history.undo();
    expect(study.settings().length).toBe(5);
    expect(draw.get(first.id)?.style.color).toBe('#123456');
    expect(history.peekUndo()?.changes).toEqual(['drawing']);
    history.undo();
    expect(draw.get(first.id)?.style.color).not.toBe('#123456');
    history.undo();
    expect(chart.indicators()).toHaveLength(0);
    expect(draw.get(first.id)).toBeDefined();
    history.undo();
    expect(draw.drawings()).toHaveLength(0);
    expect(history.canUndo()).toBe(false);

    history.redo();
    expect(draw.drawings()).toHaveLength(1);
    expect(chart.indicators()).toHaveLength(0);
    history.redo();
    expect(chart.indicators()).toHaveLength(1);
    history.redo();
    expect(draw.get(first.id)?.style.color).toBe('#123456');
    history.redo();
    expect(chart.indicators()[0].settings().length).toBe(21);
    expect(history.canRedo()).toBe(false);
  });

  it('invalidates redo on any new action, chart or drawing', async () => {
    const { chart, draw, history } = rig();
    chart.addIndicator('hist-osc');
    await settle();
    history.undo();
    expect(history.canRedo()).toBe(true);
    draw.add(line(99));
    expect(history.canRedo()).toBe(false);
    history.undo();
    expect(history.canRedo()).toBe(true);
    chart.addIndicator('hist-overlay');
    await settle();
    expect(history.canRedo()).toBe(false);
    expect(history.redo()).toBe(false);
  });

  it('follows a host that presses the drawing controller directly', async () => {
    const { chart, draw, history } = rig();
    chart.addIndicator('hist-osc');
    await settle();
    draw.add(line(99));
    draw.undo();
    expect(history.canRedo()).toBe(true);
    history.undo();
    expect(chart.indicators()).toHaveLength(0);
    history.redo();
    history.redo();
    expect(draw.drawings()).toHaveLength(1);
  });

  it('keeps a whole drawing drag as one step, and records a study added while it runs as a step of its own', async () => {
    const { chart, draw, history } = rig();
    const d = draw.add(line(101));
    history.clear();
    const at = (price: number) => ({ id: `draw:${d.id}`, time: T0 + 10 * 60, price, paneIndex: 0 });
    chart.emit('drag', at(101));
    await settle();
    chart.emit('drag', at(103));
    await settle();
    // A chord, or the host, while the pointer is still down; on the price pane, so no pane is announced.
    const study = chart.addIndicator('hist-overlay');
    await settle();
    chart.emit('drag', at(106));
    await settle();
    chart.emit('drag:end', {});
    await settle();
    expect(draw.get(d.id)?.points[0].price).toBeCloseTo(106);

    expect(history.peekUndo()?.changes).toEqual(['drawing']);
    history.undo();
    expect(draw.get(d.id)?.points[0].price).toBeCloseTo(101);
    expect(chart.indicators()).toHaveLength(1);
    expect(history.peekUndo()?.changes).toEqual(['study-add']);
    history.undo();
    expect(chart.indicators().some(s => s.id === study.id)).toBe(false);
    expect(history.canUndo()).toBe(false);
    history.redo();
    history.redo();
    expect(draw.get(d.id)?.points[0].price).toBeCloseTo(106);
  });

  it('skips drawing steps the controller no longer holds', async () => {
    const { chart, draw, history } = rig();
    draw.add(line(99));
    chart.addIndicator('hist-osc');
    await settle();
    draw.fromJSON({ version: 1, drawings: [] });
    expect(history.undo()).toBe(true);
    expect(chart.indicators()).toHaveLength(0);
    expect(history.canUndo()).toBe(false);
    expect(history.undo()).toBe(false);
  });
});

describe('coalescing', () => {
  it('merges a live colour edit into one step, and a cancelled group into none', async () => {
    const { chart, draw, history } = rig();
    const study = chart.addIndicator('hist-osc');
    const d = draw.add(line(100));
    await settle();
    history.clear();
    const color = study.settings()['value:color'];
    const drawn = draw.get(d.id)?.style.color;

    let end = history.group('Colour');
    for (const next of ['#110000', '#220000', '#330000']) {
      study.setSettings({ 'value:color': next });
      await settle();
      draw.update(d.id, { style: { color: next } });
    }
    end();
    expect(history.peekUndo()).toEqual({ label: 'Colour', changes: ['study-settings', 'drawing'] });
    expect(history.undo()).toBe(true);
    expect(study.settings()['value:color']).toBe(color);
    expect(draw.get(d.id)?.style.color).toBe(drawn);
    expect(history.canUndo()).toBe(false);
    expect(history.redo()).toBe(true);
    expect(study.settings()['value:color']).toBe('#330000');
    expect(draw.get(d.id)?.style.color).toBe('#330000');

    const original = study.settings().length;
    end = history.group('Dialog');
    study.setSettings({ length: 30 });
    await settle();
    study.setSettings({ length: original });   // Cancel puts it back
    end();
    expect(history.peekUndo()?.label).toBe('Colour');
    history.undo();
    expect(history.canUndo()).toBe(false);
  });

  it('gives the redo branch back when a group ends as no step', async () => {
    const { chart, history } = rig();
    const study = chart.addIndicator('hist-osc');
    await settle();
    study.setSettings({ length: 8 });
    await settle();
    history.undo();
    expect(history.canRedo()).toBe(true);
    const end = history.group('Dialog');
    study.setSettings({ length: 30 });
    await settle();
    study.setSettings({ length: 5 });   // Cancel puts it back
    await settle();
    end();
    expect(history.canRedo()).toBe(true);
    expect(history.peekUndo()?.changes).toEqual(['study-add']);
    expect(history.redo()).toBe(true);
    expect(study.settings().length).toBe(8);
  });

  it('keeps the oldest step a cancelled group would have pushed past the limit', async () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(40));
    const history = new ChartHistory(chart, { limit: 2 });
    const one = chart.addIndicator('hist-osc');
    await settle();
    chart.addIndicator('hist-osc');
    await settle();
    const end = history.group();
    one.setSettings({ length: 30 });
    await settle();
    one.setSettings({ length: 5 });
    await settle();
    end();
    expect(history.undo()).toBe(true);
    expect(history.undo()).toBe(true);
    expect(chart.indicators()).toHaveLength(0);
  });

  it('leaves a host change made in the middle of a group out of the step', async () => {
    const { chart, history } = rig();
    const study = chart.addIndicator('hist-osc');
    await settle();
    history.clear();
    const end = history.group('Dialog');
    history.transact(() => chart.setPriceAxisOptions(1, 'right', { inverted: true }));
    study.setSettings({ length: 11 });
    await settle();
    // The host's own change while the dialog is open: a scale it owns.
    history.ignore(() => chart.setPriceAxisOptions(1, 'right', { mode: 'percentage' }));
    history.transact(() => chart.setPriceAxisOptions(1, 'right', { marginTop: 0.25 }));
    study.setSettings({ length: 12 });
    await settle();
    end();
    expect(history.undo()).toBe(true);
    expect(study.settings().length).toBe(5);
    expect(chart.priceAxisState(1, 'right')).toMatchObject({ inverted: false, mode: 'percentage' });
    expect(chart.panes()[1].scaleFor('right').options.marginTop).toBeCloseTo(0.1);
    expect(history.redo()).toBe(true);
    expect(study.settings().length).toBe(12);
    expect(chart.priceAxisState(1, 'right')).toMatchObject({ inverted: true, mode: 'percentage' });
  });

  it('walks each stretch of a step from where the stretch before it leaves the chart, so none loses its stacking', async () => {
    const { chart, history, errors } = rig();
    const a = chart.addIndicator('hist-overlay', { length: 1 });
    const b = chart.addIndicator('hist-overlay', { length: 2 });
    await settle();
    history.clear();
    const lengths = (): unknown[] => chart.indicators().map(s => s.settings().length);
    const end = history.group('Session');
    chart.reorderIndicator(b.id, -1);
    await settle();
    // A turn of the host's: what the user does next is a stretch of its own.
    history.ignore(() => {});
    chart.reorderIndicator(b.id, 1);
    a.setSettings({ length: 10 });
    await settle();
    end();
    expect(lengths()).toEqual([10, 2]);
    expect(history.peekUndo()?.changes).toEqual(expect.arrayContaining(['study-order', 'study-settings']));
    // The later stretch leaves the stack as the chart has it now, and the
    // earlier one still has its own reorder to take back after it.
    expect(history.undo()).toBe(true);
    expect(lengths()).toEqual([1, 2]);
    expect(history.redo()).toBe(true);
    expect(lengths()).toEqual([10, 2]);
    expect(history.undo()).toBe(true);
    expect(lengths()).toEqual([1, 2]);
    expect(errors).toEqual([]);
  });

  it('leaves an ignore inside a transaction out of its one step', () => {
    const { chart, draw, history } = rig();
    let host = '';
    history.transact(() => {
      chart.setPriceAxisOptions(0, 'right', { inverted: true });
      history.ignore(() => {
        chart.setPriceAxisOptions(0, 'right', { marginTop: 0.3 });
        host = draw.add(line(100)).id;
      });
      chart.addIndicator('hist-osc');
    }, 'Template');
    expect(history.peekUndo()).toEqual({ label: 'Template', changes: expect.arrayContaining(['axis', 'study-add']) });
    expect(history.peekUndo()?.changes).not.toContain('drawing');
    history.undo();
    expect(chart.indicators()).toHaveLength(0);
    expect(chart.priceAxisState(0, 'right')?.inverted).toBe(false);
    expect(chart.panes()[0].scaleFor('right').options.marginTop).toBeCloseTo(0.3);
    expect(draw.get(host)).toBeDefined();
    expect(history.canUndo()).toBe(false);
    history.redo();
    expect(chart.priceAxisState(0, 'right')?.inverted).toBe(true);
    expect(chart.indicators()).toHaveLength(1);
  });

  it('records a transaction as one step, drawings included, and joins nested ones', () => {
    const { chart, draw, history } = rig();
    history.transact(() => {
      chart.addIndicator('hist-osc');
      history.transact(() => chart.addIndicator('hist-overlay'));
      draw.add(line(100));
    }, 'Template');
    expect(history.peekUndo()).toEqual({ label: 'Template', changes: expect.arrayContaining(['study-add', 'drawing']) });
    history.undo();
    expect(chart.indicators()).toHaveLength(0);
    expect(draw.drawings()).toHaveLength(0);
    expect(history.canUndo()).toBe(false);
    history.redo();
    expect(chart.indicators()).toHaveLength(2);
    expect(draw.drawings()).toHaveLength(1);
  });

  it('keeps a whole divider drag as one step', async () => {
    const { chart, history } = rig();
    chart.addIndicator('hist-osc');
    await settle();
    history.clear();
    for (const w of [0.4, 0.5, 0.6]) chart.setPaneWeight(1, w);
    chart.emit('paneResized', { paneIndex: 0 });
    await settle();
    history.undo();
    expect(chart.paneWeight(1)).toBeCloseTo(0.32);
    expect(history.canUndo()).toBe(false);
  });
});

describe('what history never does', () => {
  it('fires no study alert and replays no trader alert when a step brings a study back', async () => {
    const { chart, history } = rig();
    const alerts = new AlertController(chart);
    alerts.add({ source: { kind: 'price', price: 105 } });
    const fired: unknown[] = [];
    for (const event of ['indicator:alert', 'alert:triggered', 'alert:created', 'alert:removed', 'alerts:restored']) {
      chart.on(event, payload => fired.push([event, payload]));
    }
    const study = chart.addIndicator('hist-alerting');
    await settle();
    chart.removeIndicator(study.id);
    await settle();
    const alertState = JSON.stringify(alerts.list());
    history.undo();
    history.redo();
    history.undo();
    expect(fired).toEqual([]);
    expect(JSON.stringify(alerts.list())).toBe(alertState);
    // The study is live and still judges new bars; only history stays quiet.
    chart.primarySeries()!.update(bars(81)[80]);
    expect(fired.some(entry => (entry as unknown[])[0] === 'indicator:alert')).toBe(true);
  });

  it('fires no trader alert keyed to a study when a step takes the study away and brings it back', async () => {
    const { chart, history } = rig();
    const study = chart.addIndicator('hist-osc');
    const alerts = new AlertController(chart);
    // Every close is above 90, so a check against history would trigger at once.
    alerts.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'value', value: 90 }, condition: 'greaterThan', repeat: 'everyTime' });
    await settle();
    const fired: unknown[] = [];
    for (const event of ['alert:triggered', 'alert:created', 'alert:removed', 'alerts:restored']) chart.on(event, payload => fired.push([event, payload]));
    const state = JSON.stringify(alerts.list());
    chart.removeIndicator(study.id);
    await settle();
    history.undo();
    history.redo();
    history.undo();
    expect(fired).toEqual([]);
    expect(JSON.stringify(alerts.list())).toBe(state);
  });

  it('never writes bars, whatever it takes back', async () => {
    const { chart, draw, history } = rig();
    const series = chart.primarySeries()!;
    const data = series.getData();
    const setData = vi.spyOn(series, 'setData');
    const update = vi.spyOn(series, 'update');
    chart.addIndicator('hist-osc');
    await settle();
    chart.setSeriesType(series, 'bar');
    await settle();
    draw.add(line(100));
    while (history.undo());
    while (history.redo());
    expect(setData).not.toHaveBeenCalled();
    expect(update).not.toHaveBeenCalled();
    expect(series.getData()).toEqual(data);
  });
});

describe('failures', () => {
  it('leaves the history true to the chart when a step cannot be taken back', async () => {
    const { chart, history, errors } = rig();
    chart.addIndicator('hist-overlay');
    await settle();
    const study = chart.addIndicator('hist-osc', { length: 3 });
    await settle();
    chart.removeIndicator(study.id);
    await settle();
    chart.setSeriesType(chart.primarySeries()!, 'line');
    await settle();
    history.undo();                        // the chart type: fine
    failNext = true;                       // the study can no longer be built
    expect(history.undo()).toBe(false);
    expect(errors).toHaveLength(1);
    expect(errors[0].direction).toBe('undo');
    expect(chart.indicators().map(s => s.indicatorId)).toEqual(['hist-overlay']);
    // The steps behind the one that failed describe a chart this one no
    // longer leads back to; the redo branch still does.
    expect(history.canUndo()).toBe(false);
    expect(history.canRedo()).toBe(true);
    failNext = false;
    history.redo();
    expect(chart.seriesType(chart.primarySeries()!)).toBe('line');
  });

  it('rolls back a command that throws and drops it with what was behind it', () => {
    const { chart, history, errors } = rig();
    let value = 0;
    history.transact(() => chart.addIndicator('hist-osc'));
    history.push({ label: 'Host', undo: () => { throw new Error('host refused'); }, redo: () => { value = 1; } });
    expect(history.undo()).toBe(false);
    expect(errors[0]).toMatchObject({ direction: 'undo', step: { label: 'Host', changes: ['command'] } });
    expect(chart.indicators()).toHaveLength(1);
    expect(history.canUndo()).toBe(false);
    expect(value).toBe(0);
  });

  it('undoes and redoes a host command in its place in the timeline', async () => {
    const { chart, history } = rig();
    let type = 'a';
    history.push({ label: 'Type', undo: () => { type = 'a'; }, redo: () => { type = 'b'; } });
    type = 'b';
    chart.addIndicator('hist-osc');
    await settle();
    history.undo();
    expect(type).toBe('b');
    history.undo();
    expect(type).toBe('a');
    history.redo();
    expect(type).toBe('b');
    expect(history.redo()).toBe(true);
    expect(chart.indicators()).toHaveLength(1);
    expect(history.push({ undo: () => false, redo: () => true })).toBeUndefined();
    expect(history.undo()).toBe(false);
  });

  it('keeps a host command whose undo and redo restore the chart, walking it both ways', async () => {
    const { chart, history } = rig();
    chart.addIndicator('hist-osc');
    await settle();
    const before = chart.getState();
    // A restore starts a new timeline, and the command that made it is the one step on it,
    // as an indicator template applied by the widget is.
    chart.restoreState({ ...before, indicators: [] });
    const after = chart.getState();
    history.push({ label: 'Swap', undo: () => { chart.restoreState(before); }, redo: () => { chart.restoreState(after); } });
    // Each press restores the chart, which empties the timeline mid-press; the step still lands.
    expect(history.undo()).toBe(true);
    expect(chart.indicators()).toHaveLength(1);
    expect(history.peekRedo()?.label).toBe('Swap');
    expect(history.redo()).toBe(true);
    expect(chart.indicators()).toHaveLength(0);
    expect(history.peekUndo()?.label).toBe('Swap');
    expect(history.canRedo()).toBe(false);
  });
});

describe('nested callbacks and async work', () => {
  it('records a listener reacting to the user in the same step, and a listener reacting to an undo in none', async () => {
    const { chart, history } = rig();
    const study = chart.addIndicator('hist-osc');
    await settle();
    history.clear();
    let react = true;
    chart.on('indicatorRemoved', () => { if (react) chart.addIndicator('hist-overlay'); });
    chart.removeIndicator(study.id);
    await settle();
    expect(chart.indicators().map(s => s.indicatorId)).toEqual(['hist-overlay']);
    react = false;
    history.undo();
    expect(chart.indicators().map(s => s.indicatorId)).toEqual(['hist-osc']);
    expect(history.canUndo()).toBe(false);

    // A listener that adjusts the chart as a step is applied is part of that step.
    const off = chart.on('objects:change', () => { if (chart.paneWeight(1) !== 0.5) chart.setPaneWeight(1, 0.5); });
    history.redo();
    history.undo();
    off();
    await settle();
    expect(history.canRedo()).toBe(true);
    expect(history.canUndo()).toBe(false);
  });

  it('leaves a drawing a listener makes while an undo is applied out of every step, and loses nothing', async () => {
    const { chart, draw, history } = rig();
    const first = draw.add(line(101));
    chart.addIndicator('hist-osc');
    await settle();
    let made: string | null = null;
    const off = chart.on('indicatorRemoved', () => { if (made === null) made = draw.add(line(102)).id; });
    history.undo();                       // the study goes, and the listener draws
    off();
    expect(made).not.toBeNull();
    expect(history.peekUndo()?.changes).toEqual(['drawing']);
    history.undo();                       // the first line, and nothing else
    expect(draw.get(first.id)).toBeUndefined();
    expect(draw.get(made!)).toBeDefined();
    expect(history.redo()).toBe(true);
    expect(history.redo()).toBe(true);
    expect(draw.get(first.id)).toBeDefined();
    expect(chart.indicators()).toHaveLength(1);
    expect(draw.get(made!)).toBeDefined();
  });

  it('keeps the redo branch when a listener draws while an undo is applied', async () => {
    const { chart, draw, history } = rig();
    chart.addIndicator('hist-osc');
    await settle();
    const mine = draw.add(line(101));
    history.undo();                       // the line waits on the redo branch
    let made: string | null = null;
    const off = chart.on('indicatorRemoved', () => { if (made === null) made = draw.add(line(102)).id; });
    history.undo();                       // the study goes, and the listener draws
    off();
    expect(history.redo()).toBe(true);
    expect(history.redo()).toBe(true);
    expect(draw.get(mine.id)).toBeDefined();
    expect(draw.get(made!)).toBeDefined();
  });

  it('refuses an undo pressed from inside an undo', async () => {
    const { chart, history } = rig();
    chart.addIndicator('hist-osc');
    await settle();
    chart.addIndicator('hist-overlay');
    await settle();
    const inner: boolean[] = [];
    const off = chart.on('indicatorRemoved', () => inner.push(history.undo()));
    history.undo();
    off();
    expect(inner).toEqual([false]);
    expect(chart.indicators().map(s => s.indicatorId)).toEqual(['hist-osc']);
  });

  it('records nothing when a study brought back finishes its asynchronous work', async () => {
    const { chart, history } = rig();
    const study = chart.addIndicator('hist-async');
    await asyncWork;
    await settle();
    history.clear();
    chart.removeIndicator(study.id);
    await settle();
    history.undo();
    expect(history.canRedo()).toBe(true);
    await asyncWork;
    await settle();
    expect(chart.indicators()[0].values().value?.some(v => v !== null)).toBe(true);
    expect(history.canRedo()).toBe(true);
    expect(history.canUndo()).toBe(false);
  });
});

describe('host control', () => {
  it('ignores the host\'s own changes and forgets everything on a restored layout', async () => {
    const { chart, history } = rig();
    history.ignore(() => { chart.addIndicator('hist-osc'); chart.setPaneWeight(1, 0.7); });
    await settle();
    expect(history.canUndo()).toBe(false);
    chart.addIndicator('hist-overlay');
    await settle();
    expect(history.canUndo()).toBe(true);
    const state = chart.getState();
    chart.restoreState(state);
    await settle();
    expect(history.canUndo()).toBe(false);
    expect(history.canRedo()).toBe(false);
  });

  it('records no drawing the host makes inside ignore, keeps the redo branch, and never takes the drawing back', async () => {
    const { chart, draw, history } = rig();
    chart.addIndicator('hist-osc');
    await settle();
    const mine = draw.add(line(101));
    history.undo();
    expect(draw.get(mine.id)).toBeUndefined();
    const host = history.ignore(() => draw.add(line(102)));
    expect(history.peekUndo()?.changes).toEqual(['study-add']);
    expect(history.canRedo()).toBe(true);
    expect(history.redo()).toBe(true);
    expect(draw.get(mine.id)).toBeDefined();
    history.undo();
    history.undo();
    expect(chart.indicators()).toHaveLength(0);
    expect(draw.get(host.id)).toBeDefined();
    expect(history.canUndo()).toBe(false);
  });

  it('records nothing for a command the host pushes inside ignore, alone or inside a transaction', () => {
    const { chart, history } = rig();
    const undo = vi.fn(), redo = vi.fn();
    history.ignore(() => history.push({ label: 'Host', undo, redo }));
    expect(history.canUndo()).toBe(false);
    expect(history.undo()).toBe(false);
    history.transact(() => {
      chart.addIndicator('hist-osc');
      history.ignore(() => history.push({ label: 'Host', undo, redo }));
    }, 'Template');
    expect(history.peekUndo()).toEqual({ label: 'Template', changes: ['study-add'] });
    expect(history.undo()).toBe(true);
    expect(history.redo()).toBe(true);
    expect(undo).not.toHaveBeenCalled();
    expect(redo).not.toHaveBeenCalled();
  });

  it('never presses through a drawing step it does not hold', async () => {
    const { chart, draw, history } = rig();
    const mine = draw.add(line(101));
    // A controller that records inside ignore, the way one that cannot run untracked would.
    vi.spyOn(draw, 'untracked').mockImplementation(fn => fn());
    const host = history.ignore(() => draw.add(line(102)));
    expect(history.peekUndo()?.changes).toEqual(['drawing']);
    expect(history.undo()).toBe(true);
    expect(draw.get(mine.id)).toBeUndefined();
    expect(draw.get(host.id)).toBeDefined();
    expect(history.redo()).toBe(true);
    expect(draw.get(mine.id)).toBeDefined();
    expect(draw.get(host.id)).toBeDefined();
    expect(chart.indicators()).toHaveLength(0);
  });

  it('takes back only the fields a step changed, keeping the host\'s own changes beside them', async () => {
    const { chart, history } = rig();
    const study = chart.addIndicator('hist-osc');
    chart.addIndicator('hist-osc');
    await settle();
    history.clear();
    study.setSettings({ length: 20 });
    await settle();
    history.transact(() => chart.setPaneWeight(1, 0.6));
    history.ignore(() => {
      study.setSettings({ 'value:color': '#00aa00' });
      chart.setPaneCollapsed(1, true);
      chart.setPaneWeight(2, 0.5);
    });
    history.undo();
    expect(chart.paneWeight(1)).toBeCloseTo(0.32);
    expect(chart.paneCollapsed(1)).toBe(true);
    history.undo();
    expect(study.settings()).toMatchObject({ length: 5, 'value:color': '#00aa00' });
    expect(chart.paneWeight(2)).toBeCloseTo(0.5);
  });

  it('keeps the chart steps when a host rebuilds its chart and attaches the new one', async () => {
    const { chart, history } = rig();
    chart.addIndicator('hist-osc', { length: 4 });
    await settle();
    const study = chart.indicators()[0];
    study.setSettings({ length: 8 });
    await settle();
    const state = chart.getState();
    chart.destroy();
    const next = makeChart();
    next.addSeries('line').setData(bars(80));
    next.restoreState(state);
    const draw = new DrawingController(next);
    history.attach(next, draw);
    history.undo();
    expect(next.indicators()[0].settings().length).toBe(4);
    history.undo();
    expect(next.indicators()).toHaveLength(0);
    history.redo();
    expect(next.indicators()).toHaveLength(1);
  });

  it('takes back drawing steps a replaced drawing controller recorded, in their place', async () => {
    const { chart, draw, history } = rig();
    chart.addIndicator('hist-osc');
    await settle();
    const made = draw.add(line(101));
    draw.update(made.id, { style: { color: '#abcdef' } });
    chart.addIndicator('hist-overlay');
    await settle();
    // The host rebuilds: a new chart and a new controller, from the old state.
    const state = chart.getState();
    draw.destroy();
    chart.destroy();
    const next = makeChart();
    next.addSeries('candlestick').setData(bars(80));
    const rebuilt = new DrawingController(next);
    next.restoreState(state);
    history.attach(next, rebuilt);
    expect(rebuilt.get(made.id)?.style.color).toBe('#abcdef');
    expect(rebuilt.canUndo()).toBe(false);

    history.undo();
    expect(next.indicators().map(s => s.indicatorId)).toEqual(['hist-osc']);
    history.undo();
    expect(rebuilt.get(made.id)?.style.color).not.toBe('#abcdef');
    history.undo();
    expect(rebuilt.get(made.id)).toBeUndefined();
    history.undo();
    expect(next.indicators()).toHaveLength(0);
    for (let i = 0; i < 4; i++) expect(history.redo()).toBe(true);
    expect(rebuilt.get(made.id)?.style.color).toBe('#abcdef');
    expect(next.indicators()).toHaveLength(2);
    // A step the new controller records joins the same timeline.
    rebuilt.remove(made.id);
    history.undo();
    expect(rebuilt.get(made.id)).toBeDefined();
  });

  it('follows a new drawing controller attached while the old one is still standing', () => {
    const { chart, draw, history } = rig();
    const made = draw.add(line(101));
    const next = makeChart();
    next.addSeries('candlestick').setData(bars(80));
    const rebuilt = new DrawingController(next);
    next.restoreState(chart.getState());
    history.attach(next, rebuilt);
    expect(history.undo()).toBe(true);
    expect(rebuilt.get(made.id)).toBeUndefined();
    // The old controller is no longer the timeline's to press.
    expect(draw.get(made.id)).toBeDefined();
    expect(history.redo()).toBe(true);
    expect(rebuilt.get(made.id)).toBeDefined();
  });

  it('drops the oldest steps past its limit', async () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(40));
    const draw = new DrawingController(chart);
    const history = new ChartHistory(chart, { draw, limit: 2 });
    for (const price of [1, 2, 3]) draw.add(line(100 + price));
    let n = 0;
    while (history.undo()) n++;
    expect(n).toBe(2);
    expect(draw.drawings()).toHaveLength(1);
  });

  it('notifies subscribers and stops after destroy', async () => {
    const { chart, history } = rig();
    const seen = vi.fn();
    history.subscribe(seen);
    chart.addIndicator('hist-osc');
    await settle();
    expect(seen).toHaveBeenCalled();
    history.destroy();
    seen.mockClear();
    chart.addIndicator('hist-osc');
    await settle();
    expect(seen).not.toHaveBeenCalled();
    expect(history.undo()).toBe(false);
    expect(history.isDestroyed).toBe(true);
  });
});

describe('study policies', () => {
  it('drops a step that would remove a study the host has protected since, and keeps canUndo and canRedo true', async () => {
    const { chart, draw, history, errors } = rig();
    const level = draw.add(line(99));
    const study = chart.addIndicator('hist-osc');
    await settle();
    expect(history.peekUndo()?.changes).toEqual(['study-add']);
    const heard = vi.fn();
    history.subscribe(heard);
    study.setPolicy({ removable: false });
    await settle();
    // Nothing is left of the add that a press may do, and the controls hear so.
    expect(heard).toHaveBeenCalled();
    expect(history.peekUndo()?.changes).toEqual(['drawing']);

    expect(history.undo()).toBe(true);
    expect(chart.indicators()).toEqual([study]);
    expect(draw.get(level.id)).toBeUndefined();
    expect(history.canUndo()).toBe(false);
    expect(errors).toEqual([]);
    // Dropped for good: redo brings back the line and nothing else.
    expect(history.redo()).toBe(true);
    expect(draw.get(level.id)).toBeDefined();
    expect(history.canRedo()).toBe(false);
    expect(chart.indicators()).toEqual([study]);
  });

  it('leaves the settings of a study the host locked since, and walks the rest of the step both ways', async () => {
    const { chart, history, errors } = rig();
    const locked = chart.addIndicator('hist-osc', { length: 3 });
    const free = chart.addIndicator('hist-overlay', { length: 4 });
    await settle();
    history.clear();
    const end = history.group('Both');
    locked.setSettings({ length: 30 });
    free.setSettings({ length: 40 });
    await settle();
    end();
    locked.setSettings({ length: 31 });
    await settle();
    locked.setPolicy({ configurable: false });
    await settle();
    // The step that changed the locked study alone has nothing left to do.
    expect(history.peekUndo()).toEqual({ label: 'Both', changes: ['study-settings'] });
    expect(history.undo()).toBe(true);
    expect(locked.settings().length).toBe(31);
    expect(free.settings().length).toBe(4);
    expect(history.redo()).toBe(true);
    expect(free.settings().length).toBe(40);
    expect(history.canRedo()).toBe(false);
    // Unlocked again, the step reaches it as recorded.
    locked.setPolicy(null);
    await settle();
    expect(history.undo()).toBe(true);
    expect(locked.settings().length).toBe(3);
    expect(errors).toEqual([]);
  });

  it('never moves a study that may not move to another pane or by a call of its own, lets others pass it, and never fails a press over it', async () => {
    const { chart, history, errors } = rig();
    const first = chart.addIndicator('hist-osc');
    const pinned = chart.addIndicator('hist-osc');
    const other = chart.addIndicator('hist-overlay');
    const second = chart.addIndicator('hist-overlay');
    await settle();
    history.clear();
    chart.moveIndicator(pinned.id, first.paneIndex);
    await settle();
    chart.reorderIndicator(pinned.id, -1);
    await settle();
    // A row two studies the host leaves free trade, beside the pinned one.
    chart.reorderIndicator(second.id, -1);
    await settle();
    pinned.setPolicy({ movable: false });
    await settle();
    const rows = (): string[] => chart.indicators().map(s => s.id);
    expect(rows()).toEqual([pinned.id, first.id, second.id, other.id]);
    const reorder = vi.spyOn(chart, 'reorderIndicator');
    const move = vi.spyOn(chart, 'moveIndicator');

    expect(history.peekUndo()?.changes).toEqual(['study-order']);
    expect(history.undo()).toBe(true);
    expect(rows()).toEqual([pinned.id, first.id, other.id, second.id]);
    // The pinned study moved up past the other while it was free: the other
    // moving back up past it puts the stack back, as the chart allows.
    expect(history.peekUndo()?.changes).toEqual(['study-order']);
    expect(history.undo()).toBe(true);
    expect(rows()).toEqual([first.id, pinned.id, other.id, second.id]);
    // The step that took it to another pane leaves nothing to do.
    expect(history.canUndo()).toBe(false);
    expect(history.undo()).toBe(false);
    expect(pinned.paneIndex).toBe(first.paneIndex);
    expect(errors).toEqual([]);
    expect(history.redo()).toBe(true);
    expect(rows()).toEqual([pinned.id, first.id, other.id, second.id]);
    expect(history.redo()).toBe(true);
    expect(rows()).toEqual([pinned.id, first.id, second.id, other.id]);
    expect(history.canRedo()).toBe(false);
    // Never by a call on the pinned study itself.
    expect(reorder.mock.calls.some(([id]) => id === pinned.id)).toBe(false);
    expect(move.mock.calls.some(([id]) => id === pinned.id)).toBe(false);
    expect(errors).toEqual([]);
  });

  it('records a free study moved past one that may not move, and walks it both ways', async () => {
    const { chart, history, errors } = rig();
    const pinned = chart.addIndicator('hist-overlay', { length: 1 }, { policy: { movable: false } });
    const free = chart.addIndicator('hist-overlay', { length: 2 });
    await settle();
    history.clear();
    expect(chart.reorderIndicator(free.id, -1)).toBe(true);
    await settle();
    const rows = (): string[] => chart.indicators().map(s => s.id);
    expect(rows()).toEqual([free.id, pinned.id]);
    expect(history.canUndo()).toBe(true);
    expect(history.peekUndo()?.changes).toEqual(['study-order']);
    expect(history.undo()).toBe(true);
    expect(rows()).toEqual([pinned.id, free.id]);
    expect(history.redo()).toBe(true);
    expect(rows()).toEqual([free.id, pinned.id]);
    expect(errors).toEqual([]);
  });

  it('brings a study removed from above one that may not move back above it', async () => {
    const { chart, history, errors } = rig();
    const top = chart.addIndicator('hist-overlay', { length: 1 });
    chart.addIndicator('hist-overlay', { length: 2 }, { policy: { movable: false } });
    await settle();
    history.clear();
    chart.removeIndicator(top.id);
    await settle();
    const lengths = (): unknown[] => chart.indicators().map(s => s.settings().length);
    expect(history.undo()).toBe(true);
    expect(lengths()).toEqual([1, 2]);
    expect(history.redo()).toBe(true);
    expect(lengths()).toEqual([2]);
    expect(history.undo()).toBe(true);
    expect(lengths()).toEqual([1, 2]);
    expect(errors).toEqual([]);
  });

  it('puts back a stack around a study that may not move without giving it another row', async () => {
    const { chart, history, errors } = rig();
    const top = chart.addIndicator('hist-overlay');
    const pinned = chart.addIndicator('hist-overlay');
    const bottom = chart.addIndicator('hist-overlay');
    await settle();
    history.clear();
    // Top and bottom trade ends, passing the study between them twice.
    chart.reorderIndicator(bottom.id, -1);
    chart.reorderIndicator(bottom.id, -1);
    chart.reorderIndicator(top.id, 1);
    chart.reorderIndicator(top.id, 1);
    await settle();
    pinned.setPolicy({ movable: false });
    await settle();
    const rows = (): string[] => chart.indicators().map(s => s.id);
    expect(rows()).toEqual([bottom.id, pinned.id, top.id]);
    expect(history.undo()).toBe(true);
    expect(rows()).toEqual([top.id, pinned.id, bottom.id]);
    expect(history.redo()).toBe(true);
    expect(rows()).toEqual([bottom.id, pinned.id, top.id]);
    expect(errors).toEqual([]);
  });

  it('records no step for what the host does to a study it protects', async () => {
    const { chart, history } = rig();
    const owned = chart.addIndicator('hist-osc', { length: 3 }, { policy: { configurable: false, removable: false } });
    await settle();
    expect(history.canUndo()).toBe(false);
    owned.setSettings({ length: 8 }, { force: true });
    await settle();
    expect(history.canUndo()).toBe(false);
    chart.addIndicator('hist-overlay');
    await settle();
    expect(history.undo()).toBe(true);
    expect(chart.indicators()).toEqual([owned]);
    expect(owned.settings().length).toBe(8);
    expect(history.canUndo()).toBe(false);
    // Lifted later, the policy still leaves the host's own change where it is.
    owned.setPolicy(null);
    await settle();
    expect(history.canUndo()).toBe(false);
    expect(owned.settings().length).toBe(8);
    // Taken away by the host's hand while protected, it is not the user's to bring back.
    owned.setPolicy({ removable: false });
    await settle();
    chart.removeIndicator(owned.id, { force: true });
    await settle();
    expect(history.canUndo()).toBe(false);
    expect(history.undo()).toBe(false);
    expect(chart.indicators()).toEqual([]);
  });

  it('brings a study back with the restrictions the host had set on it', async () => {
    const { chart, history } = rig();
    const study = chart.addIndicator('hist-osc', { length: 6 }, { policy: { configurable: false, movable: false } });
    await settle();
    history.clear();
    chart.removeIndicator(study.id);
    await settle();
    expect(history.undo()).toBe(true);
    const back = chart.indicators()[0];
    expect(back.id).toBe(study.id);
    expect(back.policy()).toEqual({ configurable: false, movable: false });
    expect(back.setSettings({ length: 9 })).toBe(false);
    expect(history.redo()).toBe(true);
    expect(chart.indicators()).toEqual([]);
  });
});

describe('study policies the host changes later', () => {
  it('brings a study back with the policy its host holds now, never an older one a step captured', async () => {
    const { chart, history, errors } = rig();
    const study = chart.addIndicator('hist-osc', { length: 3 }, { policy: { movable: false } });
    await settle();
    study.setPolicy({ configurable: false });
    await settle();
    expect(history.undo()).toBe(true);
    expect(chart.indicators()).toEqual([]);
    expect(history.redo()).toBe(true);
    const back = (): ReturnType<Chart['indicators']>[number] => chart.indicators()[0];
    expect(back().policy()).toEqual({ configurable: false });
    expect(back().setSettings({ length: 99 })).toBe(false);
    expect(back().settings().length).toBe(3);

    // Removed, brought back, the add taken back and made again: still the host's policy.
    expect(chart.removeIndicator(back().id)).toBe(true);
    await settle();
    expect(history.undo()).toBe(true);
    expect(back().policy()).toEqual({ configurable: false });
    expect(history.undo()).toBe(true);
    expect(chart.indicators()).toEqual([]);
    expect(history.redo()).toBe(true);
    expect(back().policy()).toEqual({ configurable: false });
    expect(back().setSettings({ length: 99 })).toBe(false);
    expect(errors).toEqual([]);
  });

  it('records no step for a forced remove in the same turn the host protected the study', async () => {
    const { chart, history } = rig();
    const study = chart.addIndicator('hist-osc', { length: 3 });
    await settle();
    history.clear();
    // No capture falls between the two: the policy is read off the study that went.
    study.setPolicy({ removable: false });
    expect(chart.removeIndicator(study.id, { force: true })).toBe(true);
    await settle();
    expect(history.canUndo()).toBe(false);
    expect(history.undo()).toBe(false);
    expect(chart.indicators()).toEqual([]);
  });

  it.each([
    ['one it had set a policy on', { movable: false }],
    ['one it had set no policy on', null],
  ] as const)('never brings back a study its host has removed, %s, even through a step that brought it', async (_name, policy) => {
    const { chart, history, errors } = rig();
    const end = history.group('Session');
    const study = chart.addIndicator('hist-osc', { length: 3 });
    await settle();
    history.ignore(() => {
      if (policy !== null) study.setPolicy(policy);
      chart.removeIndicator(study.id);
    });
    chart.addIndicator('hist-overlay', { length: 4 });
    await settle();
    end();
    expect(history.undo()).toBe(true);
    expect(chart.indicators()).toEqual([]);
    expect(history.redo()).toBe(true);
    expect(chart.indicators().map(s => s.indicatorId)).toEqual(['hist-overlay']);
    expect(history.undo()).toBe(true);
    expect(chart.indicators()).toEqual([]);
    expect(errors).toEqual([]);
  });
});

describe('settings the history leaves alone', () => {
  it('does not record a view change: a zoom, an axis drag, a pinned range', async () => {
    const { chart, history } = rig();
    chart.setVisibleLogicalRange({ from: 10, to: 40 });
    chart.panes()[0].priceScale.setAutoScale(false);
    chart.emit('objects:change', {});
    await settle();
    expect(history.canUndo()).toBe(false);
  });
});

describe('linked charts', () => {
  it('sends a linked appearance step back to the charts that followed it, on undo and on redo', async () => {
    const lead = rig();
    const follow = rig();
    lead.chart.addIndicator('hist-osc');
    await settle();
    // The study pane is logarithmic from its own axis menu already, so the
    // chart-wide write moves the price pane alone and is taken back on its axis.
    lead.history.ignore(() => lead.chart.setPriceAxisOptions(1, 'right', { mode: 'logarithmic' }));
    lead.history.clear();
    const links = createLinkGroup({ appearance: true, crosshair: false, viewport: false });
    for (const r of [lead, follow]) {
      links.add(r.chart as unknown as LinkChart, {
        appearance: { read: () => readChartSettings(r.chart), apply: values => r.history.ignore(() => applyChartSettings(r.chart, values)) },
      });
    }
    const mode = (chart: Chart): string | undefined => chart.priceAxisState(0, 'right')?.mode;
    lead.history.transact(() => applyChartSettings(lead.chart, { 'scales.mode': 'logarithmic' }), 'Settings');
    expect(mode(follow.chart)).toBe('logarithmic');
    expect(follow.history.canUndo()).toBe(false);

    lead.history.undo();
    expect(mode(lead.chart)).toBe('linear');
    expect(mode(follow.chart)).toBe('linear');
    lead.history.redo();
    expect(mode(lead.chart)).toBe('logarithmic');
    expect(mode(follow.chart)).toBe('logarithmic');
    expect(follow.history.canUndo()).toBe(false);
    links.destroy();
  });

  it('announces nothing on undo for a step no linked chart heard', async () => {
    const { chart, history } = rig();
    chart.addIndicator('hist-osc');
    await settle();
    history.clear();
    const heard: unknown[] = [];
    chart.on('style:change', payload => heard.push(payload));
    // An axis menu row: the price pane's axis alone, which no linked chart follows.
    history.transact(() => chart.setPriceAxisOptions(0, 'right', { mode: 'logarithmic' }), 'Axis menu');
    history.undo();
    expect(chart.priceAxisState(0, 'right')?.mode).toBe('linear');
    history.redo();
    expect(chart.priceAxisState(0, 'right')?.mode).toBe('logarithmic');
    expect(heard).toEqual([]);
  });
});

registerIndicator({
  id: 'hist-anchored', name: 'History anchored', placement: 'onchart',
  inputs: [
    { key: 'at', type: 'timestamp', label: 'Anchor time', default: T0 + 10 * 60, pick: true },
    { key: 'level', type: 'price', label: 'Anchor price', default: 100, pick: true, timeKey: 'at', anchor: true },
  ],
  plots: [{ key: 'value', title: 'Value', type: 'line' }],
  calc: (b, s) => ({ value: b.map(x => (x.time >= (s.at as number) ? s.level as number : null)) }),
});

describe('study input anchors', () => {
  const anchorOf = (study: { id: string }): string => `input-anchor:${study.id}:level`;
  /** A drag of the anchor handle, pressed and released at two bars. */
  const dragAnchor = (chart: Chart, study: { id: string }, from: { at: number; level: number }, to: { at: number; level: number }): void => {
    const id = anchorOf(study);
    chart.emit('drag:start', { id, time: from.at, price: from.level, paneIndex: 0 });
    chart.emit('drag', { id, time: to.at, price: to.level, paneIndex: 0 });
    chart.emit('drag:end', { id, time: to.at, price: to.level, paneIndex: 0 });
  };

  it('takes back an anchor pick made outside the drawing history first, and never an unrelated drawing for it', async () => {
    const { chart, draw, history } = rig();
    const study = chart.addIndicator('hist-anchored');
    await settle();
    history.clear();
    const level = draw.add(line(97));
    const start = { at: T0 + 10 * 60, level: 100 };
    const dragged = { at: T0 + 20 * 60, level: 104 };
    const picked = { at: T0 + 30 * 60, level: 108 };
    dragAnchor(chart, study, start, dragged);
    expect(study.settings()).toMatchObject(dragged);
    await settle();
    // What a settings dialog's Pick point writes: the settings, not a drag.
    study.setSettings(picked);
    await settle();

    expect(history.undo()).toBe(true);
    expect(study.settings()).toMatchObject(dragged);
    expect(draw.get(level.id)).toBeDefined();
    expect(history.undo()).toBe(true);
    expect(study.settings()).toMatchObject(start);
    expect(draw.get(level.id)).toBeDefined();
    expect(history.undo()).toBe(true);
    expect(draw.get(level.id)).toBeUndefined();
    expect(study.settings()).toMatchObject(start);
    expect(history.canUndo()).toBe(false);
    // The drawing controller held the line's step alone, and a press straight
    // at it after the history walked back finds nothing more to take.
    expect(draw.canUndo()).toBe(false);

    expect(history.redo()).toBe(true);
    expect(draw.get(level.id)).toBeDefined();
    expect(study.settings()).toMatchObject(start);
    expect(history.redo()).toBe(true);
    expect(study.settings()).toMatchObject(dragged);
    expect(history.redo()).toBe(true);
    expect(study.settings()).toMatchObject(picked);
    expect(history.canRedo()).toBe(false);
  });

  it('holds a drag and a moveInputAnchor as one step each, at once, and takes each back exactly once', () => {
    const { chart, draw, history } = rig();
    const study = chart.addIndicator('hist-anchored');
    const start = { at: T0 + 10 * 60, level: 100 };
    const dragged = { at: T0 + 20 * 60, level: 104 };
    // The study came in the same turn: a press on its handle is an action of its own.
    dragAnchor(chart, study, start, dragged);
    // Recorded as the release ends, so a control asking right after sees it.
    expect(history.peekUndo()?.changes).toEqual(['study-settings']);
    expect(draw.moveInputAnchor(study.id, 'level', { time: T0 + 30 * 60, price: 108 })).toBe(true);
    expect(history.peekUndo()?.changes).toEqual(['study-settings']);
    // One owner: the drawing history holds neither move.
    expect(draw.historySteps()).toEqual({ undo: [], redo: [] });
    expect(draw.canUndo()).toBe(false);

    expect(history.undo()).toBe(true);
    expect(study.settings()).toMatchObject(dragged);
    expect(history.undo()).toBe(true);
    expect(study.settings()).toMatchObject(start);
    expect(history.peekUndo()?.changes).toEqual(['study-add']);
    expect(draw.undo()).toBe(false);
    expect(history.redo()).toBe(true);
    expect(history.redo()).toBe(true);
    expect(study.settings()).toMatchObject({ at: T0 + 30 * 60, level: 108 });
    expect(history.canRedo()).toBe(false);
    expect(draw.historySteps()).toEqual({ undo: [], redo: [] });
  });

  it('records a move the host makes inside ignore nowhere, and gives the steps back to the drawing history when it goes', () => {
    const { chart, draw, history } = rig();
    const study = chart.addIndicator('hist-anchored');
    history.clear();
    history.ignore(() => draw.moveInputAnchor(study.id, 'level', { time: T0 + 20 * 60, price: 104 }));
    expect(study.settings()).toMatchObject({ at: T0 + 20 * 60, level: 104 });
    expect(history.canUndo()).toBe(false);
    expect(draw.canUndo()).toBe(false);

    // A controller the history follows takes the steps; the one it left keeps its own again.
    const next = new DrawingController(chart);
    history.attach(chart, next);
    expect(draw.moveInputAnchor(study.id, 'level', { time: T0 + 25 * 60, price: 106 })).toBe(true);
    expect(draw.canUndo()).toBe(true);
    draw.destroy();
    history.destroy();
    expect(next.moveInputAnchor(study.id, 'level', { time: T0 + 30 * 60, price: 108 })).toBe(true);
    expect(next.canUndo()).toBe(true);
    expect(next.undo()).toBe(true);
    expect(study.settings()).toMatchObject({ at: T0 + 25 * 60, level: 106 });
    next.destroy();
  });
});

describe('what the history holds on to', () => {
  interface Held {
    _known: Map<string, object & { id: string }>; _lastNames: Map<string, string>; _hostRemoved: Set<string>; _seen: Set<number>;
    _undo: { changes: { before: { studies: { id: string }[] }; after: { studies: { id: string }[] } }[] }[];
    _redo: Held['_undo'];
  }
  const inside = (history: ChartHistory): Held => history as unknown as Held;
  /** The names the steps on both branches reach. */
  const reached = (history: ChartHistory): Set<string> => {
    const h = inside(history);
    return new Set([...h._undo, ...h._redo].flatMap(entry => entry.changes.flatMap(c => [...c.before.studies, ...c.after.studies].map(s => s.id))));
  };
  const counts = (history: ChartHistory) => {
    const h = inside(history);
    return { studies: h._known.size, ids: h._lastNames.size, hostRemoved: h._hostRemoved.size, panes: h._seen.size };
  };
  /** Every study the history holds is on the chart or named by a step. */
  const bounded = (history: ChartHistory, chart: Chart): void => {
    const names = reached(history);
    const live = new Set<object>(chart.isDestroyed ? [] : chart.indicators());
    for (const [name, study] of inside(history)._known) expect(names.has(name) || live.has(study), `holds ${name}`).toBe(true);
    for (const name of inside(history)._hostRemoved) expect(names.has(name), `host removed ${name}`).toBe(true);
  };

  it('lets go of the studies the host adds and removes inside ignore, which no step names', async () => {
    const { chart, history } = rig();
    for (let i = 0; i < 100; i++) {
      const study = history.ignore(() => chart.addIndicator('hist-osc'));
      history.ignore(() => chart.removeIndicator(study.id));
    }
    // And a pair inside one ignore, which the history may never have seen.
    for (let i = 0; i < 100; i++) history.ignore(() => { chart.removeIndicator(chart.addIndicator('hist-osc').id); });
    await settle();
    expect(history.canUndo()).toBe(false);
    expect(counts(history)).toEqual({ studies: 0, ids: 0, hostRemoved: 0, panes: 1 });
  });

  it('holds no more studies than its limited steps name, and every step still walks', async () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(80));
    const draw = new DrawingController(chart);
    const errors: ChartHistoryError[] = [];
    const history = new ChartHistory(chart, { draw, limit: 10, onError: e => errors.push(e) });
    for (let i = 0; i < 60; i++) {
      const study = chart.addIndicator('hist-osc', { length: i + 1 });
      await settle();
      chart.removeIndicator(study.id);
      await settle();
    }
    // Ten steps: the last five studies, each added and removed.
    expect(counts(history)).toEqual({ studies: 5, ids: 5, hostRemoved: 0, panes: 6 });
    bounded(history, chart);
    const lengths: number[] = [];
    for (let i = 0; i < 10; i++) {
      expect(history.undo(), `undo ${i}`).toBe(true);
      lengths.push(...chart.indicators().map(s => Number(s.settings().length)));
    }
    expect(history.undo()).toBe(false);
    expect(lengths).toEqual([60, 59, 58, 57, 56]);
    for (let i = 0; i < 10; i++) expect(history.redo(), `redo ${i}`).toBe(true);
    expect(chart.indicators()).toEqual([]);
    expect(errors).toEqual([]);
    bounded(history, chart);
  });

  it('lets go of what only the redo branch named once a new step drops it', async () => {
    const { chart, history } = rig();
    for (let i = 0; i < 5; i++) { chart.addIndicator('hist-osc', { length: i + 1 }); await settle(); }
    for (let i = 0; i < 5; i++) history.undo();
    expect(chart.indicators()).toEqual([]);
    // Off the chart, named by the five steps a redo would take.
    expect(counts(history).studies).toBe(5);
    bounded(history, chart);
    chart.addIndicator('hist-overlay');
    await settle();
    expect(history.canRedo()).toBe(false);
    expect(counts(history)).toEqual({ studies: 1, ids: 1, hostRemoved: 0, panes: 1 });
    bounded(history, chart);
    expect(history.undo()).toBe(true);
    expect(history.redo()).toBe(true);
    expect(chart.indicators().map(s => s.indicatorId)).toEqual(['hist-overlay']);
  });

  /** A dialog that previews a change to `study` and is cancelled: a group that ends as no step. */
  const cancelled = async (history: ChartHistory, study: ReturnType<Chart['addIndicator']>): Promise<void> => {
    const end = history.group('Dialog');
    const was = study.settings().length;
    study.setSettings({ length: 9 });
    await settle();
    study.setSettings({ length: was });
    await settle();
    end();
  };

  it('keeps a study only the redo branch a group set aside names until the group ends, policy and all', async () => {
    const { chart, history, errors } = rig();
    const other = chart.addIndicator('hist-overlay', { length: 4 });
    await settle();
    history.clear();
    chart.addIndicator('hist-osc', { length: 3 }, { policy: { movable: false } });
    await settle();
    expect(history.undo()).toBe(true);
    expect(chart.indicators()).toEqual([other]);
    // The group's first change drops the redo branch, and gives it back when it cancels.
    await cancelled(history, other);
    expect(history.redo()).toBe(true);
    expect(chart.indicators().find(s => s.indicatorId === 'hist-osc')?.policy()).toEqual({ movable: false });
    expect(errors).toEqual([]);
  });

  it('keeps a study only the step a group pushed past the limit names until the group ends, policy and all', async () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(80));
    const errors: ChartHistoryError[] = [];
    const history = new ChartHistory(chart, { limit: 1, onError: e => errors.push(e) });
    const other = chart.addIndicator('hist-overlay', { length: 4 });
    const study = chart.addIndicator('hist-osc', { length: 3 }, { policy: { movable: false } });
    await settle();
    history.clear();
    chart.removeIndicator(study.id);
    await settle();
    // The group's first change pushes the remove past the limit, and puts it back when it cancels.
    await cancelled(history, other);
    expect(history.undo()).toBe(true);
    const back = chart.indicators().find(s => s.indicatorId === 'hist-osc');
    expect(back?.id).toBe(study.id);
    expect(back?.policy()).toEqual({ movable: false });
    expect(errors).toEqual([]);
  });

  it('keeps the name a study reading a removed one captures its source by, so no step appears that nobody made', async () => {
    const chart = makeChart();
    chart.addSeries('candlestick').setData(bars(80));
    const history = new ChartHistory(chart, { limit: 1 });
    // A step names a removed study under the id `x`: another study placed under it goes by a name of its own.
    const first = chart.addIndicator('hist-osc', {}, { instanceId: 'x' });
    await settle();
    chart.removeIndicator(first.id);
    await settle();
    const source = history.ignore(() => chart.addIndicator('hist-osc', {}, { instanceId: 'x' }));
    history.ignore(() => chart.addIndicator('hist-osc', { source: { kind: 'indicator', instanceId: 'x', plotKey: 'value' } }));
    // The host takes the source away; the reader still names it, and every capture reads it by that name.
    history.ignore(() => chart.removeIndicator(source.id));
    chart.addIndicator('hist-overlay');
    await settle();
    expect(history.peekUndo()?.changes).toEqual(['study-add']);
  });

  it('keeps nothing of a rebuilt chart, and still brings back a study a step removed there, with its policy', async () => {
    const { chart, history, errors } = rig();
    const kept = chart.addIndicator('hist-overlay', { length: 4 });
    const removed = chart.addIndicator('hist-osc', { length: 3 }, { policy: { movable: false } });
    const dropped = history.ignore(() => chart.addIndicator('hist-alerting'));
    await settle();
    chart.removeIndicator(removed.id);
    await settle();
    const state = chart.getState();
    chart.destroy();
    const next = makeChart();
    next.addSeries('candlestick').setData(bars(80));
    next.restoreState(state);
    // The host leaves one study out of the rebuild.
    next.removeIndicator(next.indicators().find(s => s.indicatorId === 'hist-alerting')!.id);
    history.attach(next, new DrawingController(next));
    const values = [...inside(history)._known.values()];
    for (const old of [kept, removed, dropped]) expect(values).not.toContain(old);
    const live = new Set<object>(next.indicators());
    // What is not on the new chart is held as data, not as a study of the old one.
    for (const value of values) expect(live.has(value) || !('setSettings' in value), 'a study object of the old chart').toBe(true);
    bounded(history, next);
    expect(history.undo()).toBe(true);
    const back = next.indicators().find(s => s.indicatorId === 'hist-osc');
    expect(back?.id).toBe(removed.id);
    expect(back?.policy()).toEqual({ movable: false });
    expect(errors).toEqual([]);
  });
});
