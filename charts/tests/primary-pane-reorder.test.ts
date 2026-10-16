/**
 * The primary price pane is an identity, not a slot. It is the pane the chart
 * is built with, where a series, a price line, an on-chart study or a
 * comparison lands when nothing names a pane, and it can now sit below the
 * studies as well as above them.
 *
 * Every test runs a measured chart with a synchronous frame, and most of them
 * move the price pane to the bottom of a three-pane stack first: that is the
 * arrangement in which every consumer that still meant "slot zero" when it
 * said "the price pane" lands on a study pane instead, visibly.
 *
 * Moving the price pane is opt-in (`movablePrimaryPane`), so the helpers here
 * turn it on unless a test asks for the default; the default, a price pane
 * pinned at the top exactly as before, has its own block below.
 */
import { describe, it, expect, beforeAll, afterEach } from 'vitest';
import '../src/indicators/index';
import { Chart, type ChartOptions, type ContextMenuEvent } from '../src/core/chart';
import { registerIndicator, type IndicatorDescriptor } from '../src/model/indicator-registry';
import { createRequestedIndicator } from '../src/indicators/requested-indicator';
import { ReplayController } from '../src/replay/controller';
import { AlertController } from '../src/alerts/controller';
import { addComparison } from '../src/compare/controller';
import { createLinkGroup } from '../src/link/index';
import { DrawingController } from '../src/draw/index';
import { DrawingLinkGroup } from '../src/draw/drawing-link';
import { DrawingLayer } from '../src/draw/layer';
import { TimeNavigator } from '../src/primitives/time-navigator';
import { LogoWatermark } from '../src/primitives/watermark';
import { TextWatermark } from '../src/primitives/text-watermark';
import { IndicatorLegendToggle } from '../src/primitives/indicator-legend-toggle';
import { PriceLine } from '../src/primitives/price-line';
import { SeriesMarkers } from '../src/primitives/markers';
import type { IPrimitive } from '../src/primitives/primitive';
import { CHART_STATE_VERSION } from '../src/model/chart-state';
import { readChartSettings } from '../src/model/chart-settings';
import { ChartObjects } from '../src/model/chart-objects';
import { priceDigits } from '../src/widget/statusline';
import { contextMenuEntries, type MenuItem } from '../src/widget/dialogs/context-menu';
import type { WidgetContext } from '../src/widget/context';
import { parseWorkspaceDocument } from '../src/workspace/index';
import { captureIndicatorTemplate, planIndicatorTemplateState } from '../src/workspace/template-layout';
import { planIndicatorTemplate } from '../src/workspace/templates';
import { createWidget, type Widget } from '../src/widget/index';
import { fakeWidgetDocument, fakeContainer, ensureWindowGlobal } from './helpers/fake-dom-widget';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import { workspaceFixture } from './helpers/workspace-fixture';
import type { Bar } from '../src/model/bar';

const W = 800;
const H = 600;

beforeAll(() => {
  // Pointer listeners are wired only when a `window` exists.
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

const charts: Chart[] = [];
const disposers: (() => void)[] = [];
afterEach(() => {
  for (const dispose of disposers.splice(0).reverse()) dispose();
  for (const chart of charts.splice(0)) chart.destroy();
});

const bars = (n: number, from = 0): Bar[] => Array.from({ length: n }, (_, k) => {
  const i = k + from;
  const c = 100 + Math.sin(i / 4) * 5 + i * 0.05;
  return { time: 1700000000 + i * 60, open: c - 0.5, high: c + 1, low: c - 1, close: c, volume: 10 + i };
});

/** A measured chart; `movable` false leaves `movablePrimaryPane` out, the default a host gets. */
function makeChart(options: Partial<ChartOptions> = {}, movable = true): { chart: Chart; el: FakeElement } {
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: (cb: (t: number) => void) => { cb(0); return 1; }, cancel: () => {} },
    ...(movable ? { movablePrimaryPane: true } : {}),
    ...options,
  });
  chart.applySize(W, H);
  charts.push(chart);
  return { chart, el };
}

/** The price pane, an RSI pane and a MACD pane, in the order they were made. */
function stacked(options: Partial<ChartOptions> = {}, movable = true) {
  const made = makeChart(options, movable);
  const price = made.chart.addSeries('candlestick');
  price.setData(bars(120));
  const rsi = made.chart.addIndicator('rsi');
  const macd = made.chart.addIndicator('macd');
  const priceRecord = made.chart.panes()[0].series()[0];
  return { ...made, price, rsi, macd, priceRecord };
}

/** The same stack with the price pane moved to the bottom: RSI, MACD, price. */
function reordered(options: Partial<ChartOptions> = {}) {
  const made = stacked(options);
  expect(made.chart.setPrimaryPaneIndex(2)).toBe(true);
  return made;
}

/** Pane heights as the DOM boxes carry them, which is what hit testing reads. */
const heights = (chart: Chart): number[] =>
  chart.panes().map((pane) => parseFloat(pane.element.style.flex.split(' ')[2]));
const tops = (chart: Chart): number[] => {
  let top = 0;
  return heights(chart).map((h) => { const t = top; top += h; return t; });
};
const holds = (chart: Chart, index: number, type: abstract new (...args: never[]) => unknown): boolean =>
  chart.panes()[index].primitives().some((primitive) => primitive instanceof type);
const firstValues = (values: Record<string, readonly (number | null)[] | undefined>): readonly (number | null)[] =>
  Object.values(values)[0] ?? [];
const tap = (el: FakeElement, x: number, y: number): void => {
  el.dispatch('pointerdown', pointer('down', x, y));
  el.dispatch('pointerup', pointer('up', x, y));
};

let sequence = 0;
function study(patch: Partial<IndicatorDescriptor>): IndicatorDescriptor {
  const descriptor: IndicatorDescriptor = {
    id: `primary-pane-${sequence++}`, name: 'Primary pane probe', placement: 'pane', inputs: [],
    plots: [{ key: 'value', title: 'Value', type: 'line' }],
    calc: (data) => ({ value: data.map((bar) => bar.close) }),
    ...patch,
  };
  registerIndicator(descriptor);
  return descriptor;
}

describe('moving the primary pane', () => {
  it('starts at slot zero and moves below a study with movePane, and a study can displace it back', () => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(60));
    const rsi = chart.addIndicator('rsi');
    const record = chart.panes()[0].series()[0];
    expect(chart.primaryPaneIndex()).toBe(0);
    const moves: unknown[] = [];
    chart.on('paneMoved', (e) => moves.push(e));

    expect(chart.movePane(0, 1)).toBe(true);
    expect(moves).toEqual([{ from: 0, to: 1 }]);
    expect(chart.primaryPaneIndex()).toBe(1);
    expect(chart.panes()[1].series()).toContain(record);
    expect(rsi.paneIndex).toBe(0);

    // The study now above it moves down past it: the price pane is displaced upward.
    expect(chart.movePane(0, 1)).toBe(true);
    expect(chart.primaryPaneIndex()).toBe(0);
    expect(rsi.paneIndex).toBe(1);
  });

  it('walks to any slot one swap at a time through setPrimaryPaneIndex, and refuses what is not a slot', () => {
    const { chart, rsi, macd } = stacked();
    const moves: unknown[] = [];
    chart.on('paneMoved', (e) => moves.push(e));
    expect(chart.setPrimaryPaneIndex(2)).toBe(true);
    // Every step is an ordinary adjacent move, so anything that follows panes by
    // `paneMoved` (drawings, alerts, a host's own bookkeeping) follows this too.
    expect(moves).toEqual([{ from: 0, to: 1 }, { from: 1, to: 2 }]);
    expect([rsi.paneIndex, macd.paneIndex, chart.primaryPaneIndex()]).toEqual([0, 1, 2]);

    expect(chart.setPrimaryPaneIndex(2)).toBe(false);
    for (const bad of [3, -1, 1.5, Number.NaN, '1' as unknown as number]) expect(chart.setPrimaryPaneIndex(bad)).toBe(false);
    expect(moves).toHaveLength(2);

    expect(chart.setPrimaryPaneIndex(0)).toBe(true);
    expect([chart.primaryPaneIndex(), rsi.paneIndex, macd.paneIndex]).toEqual([0, 1, 2]);
  });

  it('keeps the primary pane from being removed wherever it sits, and removes the study pane above it', () => {
    const { chart } = reordered();
    expect(chart.removePane(2)).toBe(false);
    expect(chart.removePane(0)).toBe(true);
    expect(chart.primaryPaneIndex()).toBe(1);
    expect(chart.indicators().map((item) => item.indicatorId)).toEqual(['macd']);
    // Removing the last study pane leaves the price pane alone at the top.
    expect(chart.removePane(0)).toBe(true);
    expect(chart.primaryPaneIndex()).toBe(0);
    expect(chart.panes()).toHaveLength(1);
  });

  it('lays the price pane out at the bottom, where the default coordinate calls find it', () => {
    const { chart } = reordered();
    const h = heights(chart);
    // The last pane below boundaries rounded onto whole pixels (the ratio is 1 here).
    expect(h[2]).toBeCloseTo(H - Math.round(H * 0.64 / 1.64), 6);
    const y = chart.priceToCoordinate(100)!;
    expect(y).toBeGreaterThan(tops(chart)[2]);
    expect(chart.coordinateToPrice(y)).toBeCloseTo(100, 6);
    expect(chart.priceAxisState()?.paneIndex).toBe(2);
    // A second scale on the price pane only, so its axis layout differs from
    // the study pane now at slot 0 and the default is seen to pick it.
    chart.addSeries('line', { priceScaleId: 'left' }).setData(bars(10).map((bar) => ({ time: bar.time, value: bar.close })));
    const own = chart.priceAxisLayout(2);
    expect(own).not.toEqual(chart.priceAxisLayout(0));
    expect(chart.priceAxisLayout()).toEqual(own);
  });
});

describe('a chart that does not opt in keeps the price pane on top, the default', () => {
  const press = (chart: Chart, id: string): boolean =>
    (chart as unknown as { _handleLegendAction(id: string): boolean })._handleLegendAction(id);

  it('reads the option back, off unless the host turns it on', () => {
    expect(makeChart({}, false).chart.movablePrimaryPane()).toBe(false);
    expect(makeChart({ movablePrimaryPane: false }).chart.movablePrimaryPane()).toBe(false);
    expect(makeChart().chart.movablePrimaryPane()).toBe(true);
  });

  it('refuses every move that takes the price pane off the top, and still reorders the studies', () => {
    const { chart, rsi, macd } = stacked({}, false);
    const moves: unknown[] = [];
    chart.on('paneMoved', (e) => moves.push(e));
    expect(chart.movePane(0, 1)).toBe(false);
    expect(chart.movePane(1, -1)).toBe(false);
    expect(chart.setPrimaryPaneIndex(2)).toBe(false);
    expect(chart.setPrimaryPaneIndex(1)).toBe(false);
    expect(moves).toEqual([]);
    expect(chart.primaryPaneIndex()).toBe(0);
    // Study panes still swap among themselves, below the price pane.
    expect(chart.movePane(1, 1)).toBe(true);
    expect([chart.primaryPaneIndex(), rsi.paneIndex, macd.paneIndex]).toEqual([0, 2, 1]);
  });

  it('keeps the up control of the first study pane from displacing it, so an explicit 0 still reads a price', () => {
    const { chart, rsi } = stacked({}, false);
    const y = chart.priceToCoordinate(100, 0)!;
    expect(chart.coordinateToPrice(y, 0)).toBeCloseTo(100, 6);
    expect(press(chart, `indicator:${rsi.id}::up`)).toBe(true);
    expect(rsi.paneIndex).toBe(1);
    expect(chart.primaryPaneIndex()).toBe(0);
    expect(chart.coordinateToPrice(y, 0)).toBeCloseTo(100, 6);
    // The same control on a chart that opted in is how a trader moves it.
    const opted = stacked();
    press(opted.chart, `indicator:${opted.rsi.id}::up`);
    expect([opted.rsi.paneIndex, opted.chart.primaryPaneIndex()]).toEqual([0, 1]);
  });

  it('refuses a saved layout that moved the price pane, before applying anything', () => {
    const saved = JSON.parse(JSON.stringify(reordered().chart.getState()));
    const { chart } = stacked({}, false);
    const report = chart.restoreState({ ...saved, crosshairMode: 'magnet' });
    expect(report.applied).toBe(false);
    expect(report.reason).toMatch(/movablePrimaryPane/);
    expect(chart.crosshairMode()).toBe('normal');
    expect(chart.primaryPaneIndex()).toBe(0);
    expect(chart.indicators().map((item) => [item.indicatorId, item.paneIndex])).toEqual([['rsi', 1], ['macd', 2]]);
    // A version 2 state that keeps the price pane on top is one it can take.
    expect(chart.restoreState({ version: 2, panes: chart.getState().panes, primaryPane: 0 }).applied).toBe(true);
  });
});

describe('the price pane keeps its data through a move', () => {
  it('takes live updates and recomputes its studies', () => {
    const { chart, price, rsi } = reordered();
    const updates: unknown[] = [];
    chart.on('data:update', (e) => updates.push(e));
    const next = { ...bars(1, 120)[0], high: 151, close: 150 };
    price.update(next);
    expect(chart.primaryBars()[chart.primaryBars().length - 1]).toEqual(next);
    expect(updates).toEqual([{ kind: 'update', time: next.time }]);
    chart.indicators();
    expect(firstValues(rsi.values())).toHaveLength(121);
    expect(chart.panes()[2].priceScale.priceRange().max).toBeGreaterThanOrEqual(151);
  });

  it('keeps a history prepend on the price pane and recomputes its studies', () => {
    const { chart, price, rsi, priceRecord } = reordered();
    price.prependData(bars(30, -30));
    expect(chart.primaryBars()).toHaveLength(150);
    expect(chart.panes()[2].series()).toContain(priceRecord);
    chart.indicators();
    expect(firstValues(rsi.values())).toHaveLength(150);
  });

  it('replays the primary series where it now sits', () => {
    const { chart, price, rsi } = reordered();
    const data = chart.primaryBars().slice();
    const replay = new ReplayController(chart, { series: price, bars: data, startIndex: 40 });
    expect(chart.primaryBars()).toHaveLength(41);
    replay.step(5);
    expect(chart.primaryBars()).toHaveLength(46);
    chart.indicators();
    expect(firstValues(rsi.values())).toHaveLength(46);
    replay.stop();
    expect(chart.primaryBars()).toHaveLength(120);
    expect(chart.primaryPaneIndex()).toBe(2);
  });

  it('computes a requested study from provider bars, drawn on the price pane where it sits', async () => {
    const { chart } = makeChart({
      barsProvider: {
        requestBars: async () => bars(120),
        requestSnapshot: async () => {
          const source = bars(120);
          return { bars: source, availableAt: source.map((bar) => bar.time), confirmed: source.map(() => true) };
        },
      },
    });
    chart.setDataContext({ symbol: 'PRIMARY', exchange: 'X', interval: '1m' });
    chart.addSeries('candlestick').setData(bars(120));
    chart.addIndicator('rsi');
    expect(chart.setPrimaryPaneIndex(1)).toBe(true);
    const descriptor = createRequestedIndicator({
      id: `primary-pane-requested-${sequence++}`, name: 'Requested overlay', placement: 'onchart', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'Value' }],
      request: (ctx) => ({ symbol: 'OTHER', interval: '1m', from: 0, to: ctx.bars[ctx.bars.length - 1]?.time ?? 0 }),
      expression: (requested) => ({ v: requested.map((bar) => bar.close) }),
    });
    registerIndicator(descriptor);
    const requested = chart.addIndicator(descriptor.id);
    expect(requested.paneIndex).toBe(1);
    for (let i = 0; i < 12; i++) await Promise.resolve();
    chart.indicators();
    expect(firstValues(requested.values()).some((value) => typeof value === 'number')).toBe(true);
    // The candles and the requested plot share the price pane; the RSI pane above holds only RSI.
    expect(chart.panes()[1].series()).toHaveLength(2);
    expect(chart.panes()[0].series()).toHaveLength(1);
  });
});

describe('price overlays land on the price pane, not on slot zero', () => {
  it('puts an on-chart study, a default series, a price line and event markers on the price pane', () => {
    const { chart } = reordered();
    const ema = chart.addIndicator('ema');
    expect(ema.paneIndex).toBe(2);
    const line = chart.addSeries('line');
    line.setData(bars(10).map((bar) => ({ time: bar.time, value: bar.close })));
    expect(chart.panes()[2].series().length).toBe(3);
    const level = chart.addPriceLine({ price: 101, color: '#888888', id: 'level' });
    expect(chart.panes()[2].primitives()).toContain(level);
    const events = chart.addEventMarkers();
    expect(chart.panes()[2].primitives()).toContain(events);
    // The chart's own strip is born on the price pane even before it has events.
    chart.setEventMarkerOptions({});
    expect(chart.panes()[2].primitives()).toContain(chart.eventMarkers()!);
    chart.setEvents([{ time: bars(1, 5)[0].time, type: 'dividend', label: 'D' }]);
    expect(chart.panes()[2].primitives()).toContain(chart.eventMarkers()!);
    // A bare primitive, the trade layer and a trade host all mean the price pane.
    const bare: IPrimitive = { zOrder: () => 'normal', draw: () => {} };
    chart.addPrimitive(bare);
    expect(chart.panes()[2].primitives()).toContain(bare);
    const lines = (pane: number): number => chart.panes()[pane].primitives().filter((item) => item instanceof PriceLine).length;
    const [studyLines, priceLines] = [lines(0), lines(2)];
    chart.trading.setOrders([{ id: 'o1', type: 'limit', side: 'buy', price: 99, size: 1 }]);
    expect(lines(2)).toBe(priceLines + 1);
    expect(lines(0)).toBe(studyLines);
    const hosted: IPrimitive = { zOrder: () => 'normal', draw: () => {} };
    chart.tradeHost().addPrimitive(hosted);
    expect(chart.panes()[2].primitives()).toContain(hosted);
  });

  it('prunes the study pane at slot zero when its last study goes, and the price pane moves up', () => {
    const { chart, rsi } = reordered();
    rsi.remove();
    expect(chart.panes()).toHaveLength(2);
    expect(chart.primaryPaneIndex()).toBe(1);
    expect(chart.indicators().map((item) => [item.indicatorId, item.paneIndex])).toEqual([['macd', 0]]);
  });

  it('keeps a study that was already on the price pane with it through the move', () => {
    const { chart } = stacked();
    const ema = chart.addIndicator('ema');
    expect(chart.setPrimaryPaneIndex(2)).toBe(true);
    expect(ema.paneIndex).toBe(2);
    expect(ema.legend() && chart.panes()[2].primitives()).toContain(ema.legend());
  });

  it('draws a study plot that forces itself onto the price pane on the price pane', () => {
    const { chart } = reordered();
    const descriptor = study({
      plots: [{ key: 'value', title: 'Value', type: 'line' }, { key: 'band', title: 'Band', type: 'line', overlay: true }],
      calc: (data) => ({ value: data.map(() => 1), band: data.map((bar) => bar.close) }),
    });
    const instance = chart.addIndicator(descriptor.id);
    expect(instance.paneIndex).toBe(3);
    const priceRecords = chart.panes()[2].series().length;
    expect(priceRecords).toBe(2);
    expect(chart.panes()[3].series()).toHaveLength(1);
  });

  it('accepts a band between a price-pane plot and a local plot of an on-chart study on the moved pane', () => {
    const { chart } = reordered();
    const descriptor = study({
      placement: 'onchart',
      plots: [{ key: 'a', title: 'A', type: 'line', overlay: true }, { key: 'b', title: 'B', type: 'line' }],
      fills: [{ between: ['a', 'b'] }],
      calc: (data) => ({ a: data.map((bar) => bar.close + 1), b: data.map((bar) => bar.close - 1) }),
    });
    const instance = chart.addIndicator(descriptor.id, {}, { priceScaleId: 'right' });
    expect(instance.paneIndex).toBe(2);
  });

  it('anchors price-anchored study marks to the candles on the moved pane', () => {
    const { chart } = reordered();
    const descriptor = study({
      placement: 'onchart', markerAnchor: 'price',
      calc: (data) => ({ value: data.map((bar) => bar.close + 20) }),
      markers: ({ bars: data }) => [{ time: data[data.length - 1].time, position: 'aboveBar', shape: 'arrowDown', size: 'small', color: '#f00' }],
    });
    chart.addIndicator(descriptor.id);
    const markers = chart.panes()[2].primitives().filter((item) => item instanceof SeriesMarkers) as SeriesMarkers[];
    expect(markers).toHaveLength(1);
    expect((markers[0] as unknown as { _seriesId: number })._seriesId).toBe(chart.panes()[2].series()[0].dataId);
  });

  it('adds a comparison to the price pane and keeps its handle on it through a move', () => {
    const { chart } = reordered();
    const handle = addComparison(chart, { symbol: 'OTHER', bars: bars(120).map((bar) => ({ ...bar, close: bar.close * 2 })) });
    expect(handle.paneIndex).toBe(2);
    expect(chart.panes()[2].series()).toHaveLength(2);
    expect(chart.panes()[0].series()).toHaveLength(1);
    expect(chart.setPrimaryPaneIndex(0)).toBe(true);
    expect(handle.paneIndex).toBe(0);
    const second = addComparison(chart, { symbol: 'THIRD', bars: bars(120) });
    expect(second.paneIndex).toBe(0);
    handle.remove();
    second.remove();
    expect(chart.panes()[0].series()).toHaveLength(1);
  });
});

describe('primary interactions follow the price pane', () => {
  it('snaps the magnet crosshair on the price pane where it sits', () => {
    const { chart, el } = reordered({ crosshairMode: 'magnet' });
    const top = tops(chart)[2];
    const x = chart.timeToCoordinate(bars(1, 100)[0].time);
    el.dispatch('pointermove', pointer('move', x, top + 5, { buttons: 0 }));
    const cursor = (chart as unknown as { _cursor: { y: number } | null })._cursor!;
    const bar = chart.primaryBars()[100];
    const pane = chart.panes()[2];
    const snapped = [bar.open, bar.high, bar.low, bar.close].map((value) => pane.priceToY(value));
    expect(snapped.some((y) => Math.abs(y - cursor.y) < 1e-6)).toBe(true);
  });

  it('pans the price scale, reads its options and summarises its price from the price pane', () => {
    const { chart, price } = reordered();
    const run = (chart as unknown as { _runShortcut(command: string): boolean })._runShortcut.bind(chart);
    const before = chart.panes()[2].priceScale.priceRange();
    const rsiBefore = chart.panes()[0].priceScale.priceRange();
    expect(run('panUp')).toBe(true);
    expect(chart.panes()[2].priceScale.priceRange()).not.toEqual(before);
    expect(chart.panes()[0].priceScale.priceRange()).toEqual(rsiBefore);

    chart.setPriceAxisOptions(2, 'right', { inverted: true });
    expect(chart.priceScaleOptions().inverted).toBe(true);
    chart.setPriceAxisAutoFit(2, 'right', false);
    chart.setPriceAxisAutoFit(0, 'right', true);
    expect(readChartSettings(chart)['scales.autoScale']).toBe(false);
    // The study pane now at the top is not what the settings dialog describes.
    chart.setPriceAxisAutoFit(2, 'right', true);
    chart.setPriceAxisAutoFit(0, 'right', false);
    expect(readChartSettings(chart)['scales.autoScale']).toBe(true);

    chart.panes()[2].priceScale.setPriceFormatter((value) => `P${value.toFixed(1)}`);
    price.update({ ...bars(1, 120)[0], close: 123.44 });
    const live = (chart as unknown as { _liveRegion: { textContent: string } })._liveRegion;
    expect(live.textContent).toContain('latest price P123.4');
  });

  it('lists a host object that names no pane on the price pane, and prints the status line at its precision', () => {
    const { chart } = reordered();
    const objects = new ChartObjects(chart);
    disposers.push(() => objects.destroy());
    objects.register({ id: 'profile', get: () => ({ kind: 'profile', name: 'Session profile' }) });
    expect(objects.get('custom:profile')?.paneIndex).toBe(2);
    // A four-decimal instrument: the status line agrees with the price axis, not the RSI pane above it.
    chart.setPriceScaleOptions({ minMove: 0.0001 });
    expect(priceDigits(chart)).toBe(4);
  });

  it('hands a study the instrument tick from the price pane where it sits', () => {
    const { chart } = reordered();
    chart.setPriceScaleOptions({ minMove: 0.05 });
    const seen: (number | undefined)[] = [];
    const descriptor = study({ calc: (data, _settings, _store, ctx) => { seen.push(ctx?.tickSize); return { value: data.map((bar) => bar.close) }; } });
    chart.addIndicator(descriptor.id);
    expect(seen[seen.length - 1]).toBe(0.05);
  });

  it('resolves a scale-targeted pick on the price pane where it sits', () => {
    const { chart, el } = reordered();
    const picked: number[] = [];
    chart.beginPick('price', (value) => picked.push(value), { priceScaleId: 'right' });
    // A press on the RSI pane, now at the top, is not a press on the price pane.
    tap(el, 300, tops(chart)[0] + 20);
    expect(picked).toEqual([]);
    const y = tops(chart)[2] + 40;
    tap(el, 300, y);
    expect(picked).toHaveLength(1);
    expect(picked[0]).toBeCloseTo(chart.panes()[2].priceScale.yToPrice(40), 6);
  });
});

describe('drawings, alerts and links follow the price pane', () => {
  it('moves a price-pane drawing with its pane and snaps new anchors on it', () => {
    const { chart } = stacked();
    const draw = new DrawingController(chart, { magnet: 'strong' });
    disposers.push(() => draw.destroy());
    const t = bars(1, 50)[0].time;
    const line = draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: t, price: 100 }] });
    expect(chart.setPrimaryPaneIndex(2)).toBe(true);
    expect(draw.get(line.id)?.paneIndex).toBe(2);
    expect(chart.panes()[2].primitives().some((item) => item instanceof DrawingLayer)).toBe(true);

    const bar = chart.primaryBars()[60];
    chart.emit('crosshair:move', { time: bar.time, price: bar.high + 0.2, paneIndex: 2, bar });
    draw.setTool('horizontal-line');
    chart.emit('click', { id: null, time: bar.time, price: bar.high + 0.2, paneIndex: 2, point: { x: 0, y: 0 } });
    const placed = draw.drawings()[draw.drawings().length - 1];
    expect(placed?.points[0]).toEqual({ time: bar.time, price: bar.high });
    expect(placed?.paneIndex).toBe(2);
  });

  it('keeps price, study and drawing alerts on the price pane where it sits', () => {
    const { chart } = stacked();
    const draw = new DrawingController(chart);
    disposers.push(() => draw.destroy());
    const alerts = new AlertController(chart, { drawings: draw });
    disposers.push(() => alerts.destroy());
    const before = alerts.add({ source: { kind: 'price', price: 100 }, condition: 'crossingUp' });
    expect(chart.setPrimaryPaneIndex(2)).toBe(true);
    const lineOn = (pane: number, id: string): boolean => chart.panes()[pane].primitives()
      .some((item) => item instanceof PriceLine && (item.options() as { id?: string }).id === `alert:${id}:0`);
    expect(lineOn(2, before.id)).toBe(true);
    expect(alerts.availability(before.id)).toMatchObject({ available: true, paneIndex: 2 });

    const after = alerts.add({ source: { kind: 'price', price: 101 }, condition: 'crossingUp' });
    expect(lineOn(2, after.id)).toBe(true);

    const overlay = study({
      plots: [{ key: 'value', title: 'Value', type: 'line' }, { key: 'band', title: 'Band', type: 'line', overlay: true }],
      calc: (data) => ({ value: data.map(() => 1), band: data.map((bar) => bar.close) }),
    });
    const instance = chart.addIndicator(overlay.id);
    const studyAlert = alerts.add({ source: { kind: 'indicator', instanceId: instance.id, plotKey: 'band', value: 100 }, condition: 'crossingUp' });
    expect(alerts.availability(studyAlert.id)).toMatchObject({ available: true, paneIndex: 2 });

    const drawn = draw.add({ tool: 'horizontal-line', paneIndex: 2, style: {}, points: [{ time: bars(1, 10)[0].time, price: 100 }] });
    const drawingAlert = alerts.add({ source: { kind: 'drawing', drawingId: drawn.id }, condition: 'crossingUp' });
    expect(alerts.availability(drawingAlert.id)).toMatchObject({ available: true, paneIndex: 2 });
  });

  it('shares a price-pane drawing between linked charts whose price panes sit at different slots', () => {
    const a = stacked();
    const b = stacked();
    expect(a.chart.setPrimaryPaneIndex(2)).toBe(true);
    const drawA = new DrawingController(a.chart);
    const drawB = new DrawingController(b.chart);
    disposers.push(() => drawA.destroy(), () => drawB.destroy());
    const group = new DrawingLinkGroup({ enabled: true });
    disposers.push(() => group.destroy());
    const identity = { symbol: 'ABC', exchange: 'NSE' };
    group.add(a.chart, drawA, identity);
    group.add(b.chart, drawB, identity);
    const t = bars(1, 30)[0].time;
    drawA.add({ tool: 'horizontal-line', paneIndex: 2, style: {}, points: [{ time: t, price: 101 }] });
    expect(drawB.drawings()).toHaveLength(1);
    expect(drawB.drawings()[0].paneIndex).toBe(0);
    drawB.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: t, price: 102 }] });
    expect(drawA.drawings()).toHaveLength(2);
    expect(drawA.drawings()[1].paneIndex).toBe(2);
    // A study-pane drawing stays local on either chart.
    drawA.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: t, price: 50 }] });
    expect(drawB.drawings()).toHaveLength(2);
  });

  it('pastes a price-pane drawing onto the price pane wherever it now sits, on its own chart and on another', async () => {
    let text = '';
    const port = { writeText: async (value: string) => { text = value; }, readText: async () => text };
    const a = reordered();
    const b = stacked();
    const drawA = new DrawingController(a.chart, { clipboard: port, clipboardFallbackToMemory: false });
    const drawB = new DrawingController(b.chart, { clipboard: port, clipboardFallbackToMemory: false });
    disposers.push(() => drawA.destroy(), () => drawB.destroy());
    const t = bars(1, 30)[0].time;
    const candlesLine = drawA.add({ tool: 'horizontal-line', paneIndex: 2, style: {}, points: [{ time: t, price: 101 }] });
    const rsiLine = drawA.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: t, price: 50 }] });
    expect(await drawA.copy([candlesLine.id, rsiLine.id])).toBe(true);
    // Written price pane first, the way every earlier build wrote a price-pane
    // drawing, so an older reader pastes it beside its own candles too.
    const payload = JSON.parse(text) as Record<string, { drawings: { paneIndex: number }[] }>;
    expect(payload['openalgo-charts/drawings'].drawings.map((d) => d.paneIndex)).toEqual([0, 1]);

    // Onto a chart that keeps its price pane on top, RSI and MACD below it.
    expect((await drawB.paste()).map((d) => d.paneIndex)).toEqual([0, 1]);
    // Onto the same chart after its price pane went back to the top.
    expect(a.chart.setPrimaryPaneIndex(0)).toBe(true);
    expect(drawA.get(candlesLine.id)?.paneIndex).toBe(0);
    expect((await drawA.paste()).map((d) => d.paneIndex)).toEqual([0, 1]);
    // And from a price pane on top to one at the bottom.
    expect(a.chart.setPrimaryPaneIndex(2)).toBe(true);
    const fromB = drawB.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: t, price: 102 }] });
    expect(await drawB.copy(fromB.id)).toBe(true);
    expect((await drawA.paste()).map((d) => d.paneIndex)).toEqual([2]);
  });

  it('folds a study-pane drawing onto the last study pane of a chart with fewer, never onto its price pane', async () => {
    let text = '';
    const port = { writeText: async (value: string) => { text = value; }, readText: async () => text };
    const a = reordered();
    const small = makeChart();
    small.chart.addSeries('candlestick').setData(bars(120));
    small.chart.addIndicator('rsi');
    expect(small.chart.setPrimaryPaneIndex(1)).toBe(true);
    const drawA = new DrawingController(a.chart, { clipboard: port, clipboardFallbackToMemory: false });
    const drawSmall = new DrawingController(small.chart, { clipboard: port, clipboardFallbackToMemory: false });
    disposers.push(() => drawA.destroy(), () => drawSmall.destroy());
    const macdLine = drawA.add({ tool: 'horizontal-line', paneIndex: 1, style: {}, points: [{ time: bars(1, 30)[0].time, price: 0 }] });
    expect(await drawA.copy(macdLine.id)).toBe(true);
    expect((await drawSmall.paste()).map((d) => d.paneIndex)).toEqual([0]);
  });

  it('keeps the linked crosshair on every pane of a chart whose price pane moved', () => {
    const a = stacked();
    const b = stacked();
    expect(b.chart.setPrimaryPaneIndex(2)).toBe(true);
    const group = createLinkGroup({ crosshair: true, viewport: false });
    disposers.push(() => group.destroy());
    group.add(a.chart);
    group.add(b.chart);
    const time = bars(1, 70)[0].time;
    a.el.dispatch('pointermove', pointer('move', a.chart.timeToCoordinate(time), 100, { buttons: 0 }));
    expect(group.crosshairIndex(b.chart)).toBe(70);
    // The leader's price pane is at the bottom of the follower: hovering there leads too.
    b.el.dispatch('pointermove', pointer('move', b.chart.timeToCoordinate(time), tops(b.chart)[2] + 30, { buttons: 0 }));
    expect(group.crosshairIndex(a.chart)).toBe(70);
  });
});

describe('chart furniture follows the price pane', () => {
  it('keeps the time navigator and brand mark on the bottom pane, which is now the price pane', () => {
    const { chart } = stacked();
    expect(holds(chart, 2, TimeNavigator)).toBe(true);
    expect(chart.setPrimaryPaneIndex(2)).toBe(true);
    expect(holds(chart, 2, TimeNavigator)).toBe(true);
    expect(holds(chart, 2, LogoWatermark)).toBe(true);
    expect(chart.setPrimaryPaneIndex(0)).toBe(true);
    expect(holds(chart, 2, TimeNavigator)).toBe(true);
    expect(holds(chart, 0, TimeNavigator)).toBe(false);
  });

  it('puts the background text, the study count and the legend offset on the price pane', () => {
    const { chart, rsi } = reordered({ legendOffset: { top: 40, left: 14 }, watermark: true });
    const ema = chart.addIndicator('ema');
    expect(holds(chart, 2, TextWatermark)).toBe(true);
    expect(holds(chart, 0, TextWatermark)).toBe(false);
    expect(holds(chart, 2, IndicatorLegendToggle)).toBe(true);
    expect(holds(chart, 0, IndicatorLegendToggle)).toBe(false);
    expect(ema.legend()?.options()).toMatchObject({ left: 14 });
    expect(ema.legend()?.options().top).toBeGreaterThanOrEqual(40);
    // The study pane that now sits at the top keeps the default corner.
    expect(rsi.legend()?.options()).toMatchObject({ top: 6, left: 8 });
  });

  it('gives the pane controls to the lead row of the study pane at slot zero and not to the price pane', () => {
    const { chart, rsi } = reordered();
    const ema = chart.addIndicator('ema');
    expect(rsi.legend()?.options().actions).toEqual(expect.arrayContaining(['up', 'down', 'collapse', 'maximize']));
    expect(ema.legend()?.options().actions).not.toContain('collapse');
    expect(ema.legend()?.options().actions).not.toContain('up');
  });
});

describe('collapse and maximize after a reorder', () => {
  it('never collapses the price pane wherever it sits, and folds the study pane at slot zero', () => {
    const { chart } = reordered();
    expect(chart.setPaneCollapsed(2, true)).toBe(false);
    expect(chart.paneCollapsed(2)).toBe(false);
    expect(chart.setPaneCollapsed(0, true)).toBe(true);
    expect(chart.paneCollapsed(0)).toBe(true);
    expect(heights(chart)[0]).toBe(30);
    // The fold is the pane's, so it travels with the pane.
    expect(chart.setPrimaryPaneIndex(0)).toBe(true);
    expect(chart.paneCollapsed(1)).toBe(true);
    expect(chart.paneCollapsed(0)).toBe(false);
  });

  it('maximizes the price pane at the bottom and puts the stack back', () => {
    const { chart } = reordered({ watermark: true });
    chart.addIndicator('ema');
    const before = chart.panes().map((pane) => pane.element.style.flex);
    expect(chart.maximizePane(2)).toBe(true);
    expect(chart.panes()[0].element.style.display).toBe('none');
    expect(chart.panes()[2].element.style.flex).toBe(`0 0 ${H}px`);
    expect(holds(chart, 2, TextWatermark)).toBe(true);
    expect(chart.maximizePane(2)).toBe(true);
    expect(chart.panes().map((pane) => pane.element.style.flex)).toEqual(before);
  });

  it('moves the price-pane furniture to a maximized study pane and back', () => {
    const { chart } = reordered({ watermark: true });
    chart.addIndicator('ema');
    expect(chart.maximizePane(0)).toBe(true);
    expect(holds(chart, 0, TextWatermark)).toBe(true);
    expect(holds(chart, 0, IndicatorLegendToggle)).toBe(true);
    expect(chart.maximizePane(0)).toBe(true);
    expect(holds(chart, 2, TextWatermark)).toBe(true);
    expect(holds(chart, 2, IndicatorLegendToggle)).toBe(true);
  });

  it('keeps a maximize on its pane through a move of the price pane', () => {
    const { chart } = stacked();
    chart.maximizePane(0);
    expect(chart.setPrimaryPaneIndex(2)).toBe(true);
    expect(chart.maximizedPane()).toBe(2);
  });
});

describe('saving and restoring the price pane position', () => {
  it('writes version 2 with the slot only when the price pane has moved', () => {
    const plain = stacked();
    const state = plain.chart.getState();
    expect(state.version).toBe(1);
    expect('primaryPane' in state).toBe(false);
    expect(CHART_STATE_VERSION).toBe(2);

    const { chart } = reordered();
    const moved = chart.getState();
    expect(moved.version).toBe(2);
    expect(moved.primaryPane).toBe(2);
    expect(moved.panes?.map((pane) => pane.weight)).toEqual([0.32, 0.32, 1]);
    expect(moved.series?.map((series) => series.paneIndex)).toEqual(expect.arrayContaining([2]));
  });

  it('restores the arrangement onto a fresh chart', () => {
    const source = reordered();
    source.chart.addIndicator('ema');
    const draw = new DrawingController(source.chart);
    disposers.push(() => draw.destroy());
    draw.add({ tool: 'horizontal-line', paneIndex: 2, style: {}, points: [{ time: bars(1, 20)[0].time, price: 100 }] });
    source.chart.setPaneCollapsed(0, true);
    const saved = JSON.parse(JSON.stringify(source.chart.getState()));

    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(120));
    const target = new DrawingController(chart);
    disposers.push(() => target.destroy());
    const moves: unknown[] = [];
    chart.on('paneMoved', (e) => moves.push(e));
    const report = chart.restoreState(saved);
    expect(report.applied).toBe(true);
    expect(chart.primaryPaneIndex()).toBe(2);
    expect(moves.length).toBeGreaterThan(0);
    expect(chart.indicators().map((item) => [item.indicatorId, item.paneIndex])).toEqual([['rsi', 0], ['macd', 1], ['ema', 2]]);
    expect(chart.panes()[2].series()[0].type).toBe('candlestick');
    expect(chart.paneCollapsed(0)).toBe(true);
    expect(target.drawings()[0].paneIndex).toBe(2);
    expect(chart.panes().map((pane) => pane.weight)).toEqual([0.32, 0.32, 1]);
    expect(JSON.parse(JSON.stringify(chart.getState())).primaryPane).toBe(2);
  });

  it('loads an old document with the price pane at the top, whatever the chart had', () => {
    const old = stacked();
    const document = JSON.parse(JSON.stringify(old.chart.getState()));
    expect(document.version).toBe(1);
    const { chart } = reordered();
    expect(chart.restoreState(document).applied).toBe(true);
    expect(chart.primaryPaneIndex()).toBe(0);
    expect(chart.indicators().map((item) => [item.indicatorId, item.paneIndex])).toEqual([['rsi', 1], ['macd', 2]]);
  });

  it('leaves the price pane where it is when a partial restore names no panes', () => {
    const { chart } = reordered();
    expect(chart.restoreState({ version: 1, crosshairMode: 'magnet' }).applied).toBe(true);
    expect(chart.primaryPaneIndex()).toBe(2);
    const studiesOnly = { version: 1, indicators: chart.getState().indicators };
    expect(chart.restoreState(studiesOnly).applied).toBe(true);
    expect(chart.primaryPaneIndex()).toBe(2);
  });

  it('refuses an impossible slot without applying anything', () => {
    const { chart } = reordered();
    const state = JSON.parse(JSON.stringify(chart.getState()));
    for (const bad of [3, -1, 1.5, '2', null]) {
      const report = chart.restoreState({ ...state, primaryPane: bad, crosshairMode: 'magnet' });
      expect(report.applied, String(bad)).toBe(false);
      expect(chart.crosshairMode()).toBe('normal');
    }
    expect(chart.restoreState({ version: 2, primaryPane: 1 }).applied).toBe(false);
    expect(chart.restoreState({ version: 3 }).applied).toBe(false);
    expect(chart.primaryPaneIndex()).toBe(2);
  });

  it('refuses a price-pane slot in a version 1 state, the way a workspace document does', () => {
    const { chart } = reordered();
    const state = JSON.parse(JSON.stringify(chart.getState()));
    const report = chart.restoreState({ ...state, version: 1, crosshairMode: 'magnet' });
    expect(report.applied).toBe(false);
    expect(report.reason).toMatch(/version 2/);
    expect(chart.crosshairMode()).toBe('normal');
    expect(chart.restoreState({ version: 1, panes: state.panes, primaryPane: 0 }).applied).toBe(false);
    expect(chart.primaryPaneIndex()).toBe(2);
  });

  it('carries the slot through a workspace document and refuses it in an old version', () => {
    const { chart } = reordered();
    const source = workspaceFixture();
    source.panes[0].chart = JSON.parse(JSON.stringify(chart.getState()));
    const parsed = parseWorkspaceDocument(source);
    expect(parsed.panes[0].chart.version).toBe(2);
    expect(parsed.panes[0].chart.primaryPane).toBe(2);
    const legacy = workspaceFixture();
    legacy.panes[0].chart = { ...JSON.parse(JSON.stringify(chart.getState())), version: 1 };
    expect(() => parseWorkspaceDocument(legacy)).toThrow();
    const outside = workspaceFixture();
    outside.panes[0].chart = { ...JSON.parse(JSON.stringify(chart.getState())), primaryPane: 7 };
    expect(() => parseWorkspaceDocument(outside)).toThrow();
  });
});

describe('portable templates', () => {
  it('captures a template in price-pane-first coordinates from a reordered chart', () => {
    const { chart } = reordered();
    chart.addIndicator('ema');
    const template = captureIndicatorTemplate(chart);
    const byId = new Map(template.indicators.map((item) => [item.indicatorId, item.paneIndex]));
    expect(byId.get('ema')).toBe(0);
    expect(byId.get('rsi')).toBe(1);
    expect(byId.get('macd')).toBe(2);
    expect(template.layout?.panes[0].weight).toBe(1);
    expect(template.layout?.plots.filter((plot) => plot.instanceId === template.indicators.find((item) => item.indicatorId === 'ema')?.instanceId)
      .every((plot) => plot.paneIndex === 0)).toBe(true);
  });

  it('applies a captured template to a reordered chart without moving its price pane', () => {
    const donor = stacked();
    donor.chart.addIndicator('ema');
    const template = captureIndicatorTemplate(donor.chart);
    const { chart } = reordered();
    const plan = planIndicatorTemplateState(chart, template, 'replace');
    expect(plan.primaryPane).toBe(2);
    const report = chart.restoreState({ version: 2, indicators: plan.indicators, panes: plan.panes, primaryPane: plan.primaryPane }, plan.restoreOptions);
    expect(report.applied).toBe(true);
    expect(chart.primaryPaneIndex()).toBe(2);
    const placed = chart.indicators().map((item) => [item.indicatorId, item.paneIndex]);
    expect(placed).toEqual(expect.arrayContaining([['ema', 2], ['rsi', 0], ['macd', 1]]));
    expect(chart.panes()[2].series()[0].type).toBe('candlestick');
  });

  it('appends a template after the existing panes and puts its on-chart studies on the price pane', () => {
    const donor = stacked();
    donor.chart.addIndicator('ema');
    const template = captureIndicatorTemplate(donor.chart);
    const { chart } = reordered();
    const plan = planIndicatorTemplateState(chart, template, 'append');
    expect(chart.restoreState({ version: 2, indicators: plan.indicators, panes: plan.panes, primaryPane: plan.primaryPane }, plan.restoreOptions).applied).toBe(true);
    expect(chart.primaryPaneIndex()).toBe(2);
    const added = chart.indicators().slice(2).map((item) => [item.indicatorId, item.paneIndex]);
    expect(added).toEqual([['rsi', 3], ['macd', 4], ['ema', 2]]);
  });

  it('keeps price-pane drawings on the price pane when a replace empties a study pane above it', () => {
    const donor = stacked();
    const template = captureIndicatorTemplate(donor.chart);
    const { chart } = stacked();
    chart.addIndicator('cci');
    expect(chart.setPrimaryPaneIndex(3)).toBe(true);
    const draw = new DrawingController(chart);
    disposers.push(() => draw.destroy());
    const line = draw.add({ tool: 'horizontal-line', paneIndex: 3, style: {}, points: [{ time: bars(1, 20)[0].time, price: 100 }] });
    const before = chart.getState();
    const plan = planIndicatorTemplateState(chart, template, 'replace');
    // The host keeps its drawings through the swap of studies, in the chart's slots as they stood.
    const report = chart.restoreState({ version: 2, indicators: plan.indicators, panes: plan.panes, primaryPane: plan.primaryPane,
      drawings: before.drawings }, plan.restoreOptions);
    expect(report.applied).toBe(true);
    // The emptied CCI pane above the price pane is pruned, and the price pane moves up a slot.
    expect(chart.panes()).toHaveLength(3);
    expect(chart.primaryPaneIndex()).toBe(2);
    expect(draw.get(line.id)?.paneIndex).toBe(2);
  });

  it('hands a draw tier that loads after a pruning restore the drawings in the slots the panes now hold', () => {
    const source = reordered();
    const draw = new DrawingController(source.chart);
    draw.add({ tool: 'horizontal-line', paneIndex: 2, style: {}, points: [{ time: bars(1, 20)[0].time, price: 100 }] });
    const saved = JSON.parse(JSON.stringify(source.chart.getState()));
    draw.destroy();
    // RSI is not registered where the layout is opened, so its pane above the price pane empties and goes.
    saved.indicators = saved.indicators.map((item: { indicatorId: string }) =>
      item.indicatorId === 'rsi' ? { ...item, indicatorId: 'primary-pane-not-registered' } : item);
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(120));
    expect(chart.restoreState(saved).applied).toBe(true);
    expect(chart.panes()).toHaveLength(2);
    expect(chart.primaryPaneIndex()).toBe(1);
    // A move before the tier arrives is carried too.
    expect(chart.setPrimaryPaneIndex(0)).toBe(true);
    const late = new DrawingController(chart);
    disposers.push(() => late.destroy());
    expect(late.drawings().map((d) => d.paneIndex)).toEqual([0]);
    expect(chart.panes()).toHaveLength(2);
  });

  it('does the same for a layout that keeps the price pane on top, on a chart that never opted in', () => {
    const source = stacked({}, false);
    const draw = new DrawingController(source.chart);
    draw.add({ tool: 'horizontal-line', paneIndex: 2, style: {}, points: [{ time: bars(1, 20)[0].time, price: 0 }] });
    draw.add({ tool: 'horizontal-line', paneIndex: 1, style: {}, points: [{ time: bars(1, 20)[0].time, price: 50 }] });
    const saved = JSON.parse(JSON.stringify(source.chart.getState()));
    draw.destroy();
    saved.indicators = saved.indicators.map((item: { indicatorId: string }) =>
      item.indicatorId === 'rsi' ? { ...item, indicatorId: 'primary-pane-not-registered' } : item);
    const { chart } = makeChart({}, false);
    chart.addSeries('candlestick').setData(bars(120));
    expect(chart.restoreState(saved).applied).toBe(true);
    expect(chart.indicators().map((item) => [item.indicatorId, item.paneIndex])).toEqual([['macd', 1]]);
    const late = new DrawingController(chart);
    disposers.push(() => late.destroy());
    // The MACD drawing follows MACD up a slot; the one on the pane that went, goes with it.
    expect(late.drawings().map((d) => [d.paneIndex, d.points[0].price])).toEqual([[1, 0]]);
    expect(chart.panes()).toHaveLength(2);
  });

  it('maps a legacy study list onto the price pane where it sits', () => {
    const planned = planIndicatorTemplate([
      { indicatorId: 'rsi', settings: {}, paneIndex: 0 },
      { indicatorId: 'ema', settings: {}, paneIndex: 1 },
    ], [
      { indicatorId: 'sma', settings: {}, paneIndex: 0 },
      { indicatorId: 'macd', settings: {}, paneIndex: 1 },
    ], 'append', new Set(['rsi', 'ema', 'sma', 'macd']), 2, 1);
    expect(planned.map((item) => [item.indicatorId, item.paneIndex])).toEqual([['rsi', 0], ['ema', 1], ['sma', 1], ['macd', 2]]);
  });
});

describe('the widget pane menu', () => {
  const event = (paneIndex: number, target: ContextMenuEvent['target'] = { kind: 'empty', id: null }): ContextMenuEvent => ({
    paneIndex, point: { x: 400, y: 10 }, price: null, time: null, index: null, preventDefault() {}, target,
  });
  const rows = (chart: Chart, paneIndex: number, target?: ContextMenuEvent['target']): Map<string, MenuItem> => {
    const ctx = { chart, draw: { drawings: () => [] } } as unknown as WidgetContext;
    return new Map(contextMenuEntries(ctx, event(paneIndex, target))
      .filter((entry): entry is MenuItem => !entry.kind || entry.kind === 'item')
      .map((entry) => [entry.id ?? '', entry]));
  };

  it('moves the price pane down and up, greyed at the edges, and never offers to fold it', () => {
    const { chart } = stacked();
    const top = rows(chart, 0);
    expect(top.get('pane-up')).toMatchObject({ label: 'Move pane up', disabled: true });
    expect(top.get('pane-down')).toMatchObject({ label: 'Move pane down' });
    expect(top.get('pane-down')?.disabled).not.toBe(true);
    expect(top.has('pane-collapse')).toBe(false);
    top.get('pane-down')!.run!();
    expect(chart.primaryPaneIndex()).toBe(1);
    rows(chart, 1).get('pane-down')!.run!();
    expect(chart.primaryPaneIndex()).toBe(2);
    const bottom = rows(chart, 2);
    expect(bottom.get('pane-down')).toMatchObject({ disabled: true });
    expect(bottom.has('pane-collapse')).toBe(false);
    // The study pane that is now at the top folds; the time axis is nobody's pane.
    expect(rows(chart, 0).get('pane-collapse')).toMatchObject({ label: 'Collapse pane' });
    expect(rows(chart, 2, { kind: 'time-scale', id: null }).has('pane-up')).toBe(false);
  });

  it('greys the rows that would take a pinned price pane off the top', () => {
    const { chart } = stacked({}, false);
    const top = rows(chart, 0);
    expect(top.get('pane-up')).toMatchObject({ disabled: true });
    expect(top.get('pane-down')).toMatchObject({ disabled: true, note: 'price pane stays on top' });
    const study = rows(chart, 1);
    expect(study.get('pane-up')).toMatchObject({ disabled: true, note: 'price pane stays on top' });
    expect(study.get('pane-down')?.disabled).not.toBe(true);
    study.get('pane-down')!.run!();
    expect(chart.primaryPaneIndex()).toBe(0);
    expect(chart.indicators().map((item) => item.paneIndex)).toEqual([2, 1]);
  });
});

describe('the packaged widget', () => {
  const widgets: Widget[] = [];
  afterEach(() => { for (const widget of widgets.splice(0)) widget.destroy(); });
  const make = (extra: { movablePrimaryPane?: boolean } = {}): Widget => {
    ensureWindowGlobal();
    const document = fakeWidgetDocument();
    const w = createWidget(fakeContainer(document) as unknown as HTMLElement, {
      document: document as unknown as Document, pixelRatio: () => 1,
      rail: false, panels: false, mobile: 'never', animZoom: false, animAutoscale: false,
      raf: { schedule: (cb) => { cb(); return 1; }, cancel() {} },
      ...extra,
    });
    widgets.push(w);
    w.chart.applySize(W, H);
    w.series.setData(bars(120));
    return w;
  };

  it('leaves the option off, as the chart does, and a host turns it on', () => {
    // A host that builds on the widget and passes an explicit 0 for the price
    // (a volume overlay, a coordinate call) keeps working unless it opts in.
    const pinned = make();
    pinned.chart.addIndicator('rsi');
    expect(pinned.chart.movablePrimaryPane()).toBe(false);
    expect(pinned.chart.setPrimaryPaneIndex(1)).toBe(false);
    expect(make({ movablePrimaryPane: false }).chart.movablePrimaryPane()).toBe(false);
    expect(make({ movablePrimaryPane: true }).chart.movablePrimaryPane()).toBe(true);
  });

  it('keeps the up control of the first study pane from moving the price pane of a widget that did not opt in', () => {
    const w = make();
    const rsi = w.chart.addIndicator('rsi');
    const y = w.chart.priceToCoordinate(100, 0)!;
    const press = (id: string): boolean =>
      (w.chart as unknown as { _handleLegendAction(id: string): boolean })._handleLegendAction(id);
    expect(press(`indicator:${rsi.id}::up`)).toBe(true);
    expect(rsi.paneIndex).toBe(1);
    expect(w.chart.primaryPaneIndex()).toBe(0);
    expect(w.chart.coordinateToPrice(y, 0)).toBeCloseTo(100, 6);
    // Nothing moved, so the saved layout is the one every earlier reader opens.
    const saved = JSON.parse(JSON.stringify(w.getState()));
    expect(saved.chart.version).toBe(1);
    expect(saved.chart).not.toHaveProperty('primaryPane');
  });

  it('reports a move of the price pane as a layout change and restores it in another widget', () => {
    const w = make({ movablePrimaryPane: true });
    w.chart.addIndicator('rsi');
    const reasons: string[] = [];
    w.on('layout', (event) => reasons.push((event as { reason: string }).reason));
    expect(w.chart.setPrimaryPaneIndex(1)).toBe(true);
    expect(reasons).toContain('paneMoved');
    const saved = JSON.parse(JSON.stringify(w.getState()));
    expect(saved.chart.version).toBe(2);
    expect(saved.chart.primaryPane).toBe(1);

    // A widget that did not opt in refuses the moved layout rather than lay the
    // price pane's scales on the study pane; one that did restores it.
    const pinned = make();
    expect(pinned.restoreState(saved).applied).toBe(false);
    expect(pinned.chart.primaryPaneIndex()).toBe(0);
    const other = make({ movablePrimaryPane: true });
    expect(other.restoreState(saved).applied).toBe(true);
    expect(other.chart.primaryPaneIndex()).toBe(1);
    expect(other.chart.indicators().map((item) => [item.indicatorId, item.paneIndex])).toEqual([['rsi', 0]]);
    // The widget's own series sits on the price pane, now the bottom one.
    expect(other.chart.panes()[1].scales()).toContain(other.chart.primarySeries()!.priceScale());
    expect(other.chart.panes()[0].scales()).not.toContain(other.chart.primarySeries()!.priceScale());
  });
});

describe('the primitive anchor for the price pane', () => {
  it('re-homes a host primitive anchored to the price pane as it moves', () => {
    const { chart } = stacked();
    const mark: IPrimitive = { zOrder: () => 'top', draw: () => {} };
    chart.addPrimitive(mark, { anchor: 'primary-pane' });
    expect(chart.panes()[0].primitives()).toContain(mark);
    expect(chart.setPrimaryPaneIndex(2)).toBe(true);
    expect(chart.panes()[2].primitives()).toContain(mark);
    expect(chart.panes()[0].primitives()).not.toContain(mark);
  });
});
