/**
 * Explicit pane and scale targets for a study's drawings and markers.
 *
 * A study that lives in its own pane used to have one drawing layer and one
 * marker layer, both in that pane on its first plot's scale. A zone that
 * belongs on the candles, or a signal measured against a second plot on
 * another axis, had nowhere to go. A drawing or marker can now name the price
 * pane (`overlay: true`) or a declared plot (`plot: key`), and the runtime
 * keeps one owned layer per target that follows moves, scale reassignment,
 * hiding, removal and restore.
 *
 * The first block pins what a descriptor that names no target renders. Its
 * digests were recorded before targets existed, so any change to the default
 * path fails here rather than in someone's chart.
 */
/// <reference types="vite/client" />
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { InvalidationLevel } from '../src/core/invalidate-mask';
import type { Pane, PaneRenderContext } from '../src/core/pane';
import { registerIndicator, type IndicatorDescriptor } from '../src/model/indicator-registry';
import { SMA } from '../src/indicators/trend';
import type { IndicatorApi } from '../src/model/indicator-instance';
import type { Bar } from '../src/model/bar';
import type { IPrimitive, PrimitiveRenderContext } from '../src/primitives/primitive';
import { IndicatorDrawings } from '../src/primitives/indicator-draws';
import { SeriesMarkers, effectiveMarkerPx } from '../src/primitives/markers';
import type { SeriesApi } from '../src/model/series';
import { makeCtx } from './helpers/fake-ctx';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import siteIndicators from '../website/pages/docs/indicators.mdx?raw';
import skillIndicators from '../.github/skills/openalgo-charts/references/indicators.md?raw';

const T0 = 1700000000;
const BARS: Bar[] = Array.from({ length: 40 }, (_, i) => {
  const close = 120 + 10 * Math.sin(i / 5);
  return { time: T0 + i * 60, open: close - 1, high: close + 3, low: close - 3, close };
});

const charts: Chart[] = [];
beforeAll(() => { (globalThis as { window?: unknown }).window ??= {}; });
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

function mount(candles: { priceScaleId?: 'left' | 'right' } = {}): { chart: Chart; el: FakeElement } {
  const document = fakeDocument();
  const el = document.createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document, pixelRatio: () => 1, shortcuts: false, timeNavigator: false, animZoom: false, animAutoscale: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  chart.addSeries('candlestick', candles).setData(BARS);
  return { chart, el };
}

interface ChartInternals {
  _renderContext(showTimeAxis: boolean): PaneRenderContext;
  _bottomPaneIndex(): number;
  _paneLayout(): { top: number; height: number }[];
}
interface PaneInternals {
  _primitiveContext(ctx: PaneRenderContext): PrimitiveRenderContext;
  _boundPrimitiveContext(p: IPrimitive, context: PrimitiveRenderContext, ctx: PaneRenderContext): PrimitiveRenderContext;
}

/** Paint one primitive the way its pane would, into a recorder, and return the ops. */
function paint(chart: Chart, paneIndex: number, primitive: IPrimitive): unknown[] {
  const internals = chart as unknown as ChartInternals;
  const pane = chart.panes()[paneIndex] as unknown as PaneInternals;
  const ctx = internals._renderContext(paneIndex === internals._bottomPaneIndex());
  const rc = pane._boundPrimitiveContext(primitive, pane._primitiveContext(ctx), ctx);
  const { ctx: canvas, rec } = makeCtx();
  primitive.draw?.(canvas, rc);
  return rec.ops;
}

const paneOf = (chart: Chart, primitive: IPrimitive): number => chart.panes().findIndex(pane => pane.hasPrimitive(primitive));
const layers = <T>(pane: Pane, type: new (...args: never[]) => T): T[] =>
  pane.primitives().filter((p): p is T & IPrimitive => p instanceof type) as T[];
/** SHA-256 of the JSON form, through the platform digest so the suite needs no runtime typings. */
const digest = async (value: unknown): Promise<string> => {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(value)));
  return Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('');
};

/** Every study-owned drawing and marker layer: its pane, its binding and what it paints. */
function ownedLayers(chart: Chart, study: IndicatorApi): { kind: string; pane: number; scale: string | null; overlay: boolean; ops: unknown[] }[] {
  const resources = (study as unknown as { renderResources(): { primitives: { primitive: IPrimitive; overlay: boolean }[] } }).renderResources();
  return resources.primitives
    .filter(({ primitive }) => primitive instanceof IndicatorDrawings || primitive instanceof SeriesMarkers)
    .map(({ primitive, overlay }) => {
      const pane = paneOf(chart, primitive);
      return {
        kind: primitive.constructor.name, pane, overlay,
        scale: chart.panes()[pane].primitiveScaleId(primitive), ops: paint(chart, pane, primitive),
      };
    });
}

const untargetedPane: IndicatorDescriptor = {
  id: 'targets-untargeted-pane', name: 'Untargeted pane', placement: 'pane', inputs: [],
  plots: [{ key: 'osc', type: 'line', title: 'Osc' }, { key: 'alt', type: 'line', title: 'Alt' }],
  calc: bars => ({ osc: bars.map((_, i) => 30 + i), alt: bars.map((_, i) => 60 - i / 2) }),
  draws: ({ bars }) => [
    { kind: 'line', from: { time: bars[2].time, price: 32 }, to: { time: bars[30].time, price: 60 }, color: '#4f8cff', lineStyle: 'dashed' },
    { kind: 'box', from: { time: bars[10].time, price: 40 }, to: { time: bars[20].time, price: 50 }, fillColor: '#26a69a', text: 'Zone', id: 'zone' },
    { kind: 'label', at: { time: bars[25].time, price: 55 }, text: 'Two\nrows', color: '#ef5350', align: 'left' },
    { kind: 'polyline', points: [{ time: bars[5].time, price: 35 }, { time: bars[15].time, price: 45 }, { time: bars[25].time, price: 40 }], closed: true, fillColor: '#ffa726' },
  ],
  markers: ({ bars }) => [
    { time: bars[12].time, position: 'aboveBar', shape: 'arrowDown', size: 'small', color: '#ef5350', text: 'Hi' },
    { time: bars[18].time, position: 'belowBar', shape: 'labelUp', size: 'medium', color: '#26a69a', text: 'Buy', id: 'buy' },
    { time: bars[24].time, position: 'atPrice', price: 50, shape: 'circle', size: 'tiny', color: '#4f8cff' },
  ],
};

const untargetedPrice: IndicatorDescriptor = {
  id: 'targets-untargeted-price', name: 'Untargeted price', placement: 'onchart', markerAnchor: 'price', inputs: [],
  plots: [{ key: 'mid', type: 'line', title: 'Mid' }],
  calc: bars => ({ mid: bars.map(bar => (bar.open + bar.close) / 2) }),
  draws: ({ bars }) => [
    { kind: 'box', from: { time: bars[8].time, price: 125 }, to: { time: bars[16].time, price: 115 }, color: '#ef5350', text: 'Supply\n125' },
  ],
  markers: ({ bars }) => [
    { time: bars[9].time, position: 'belowBar', shape: 'labelUp', size: 'small', color: '#26a69a', text: 'Up' },
    { time: bars[21].time, position: 'aboveBar', shape: 'labelDown', size: 'small', color: '#ef5350', text: 'Down' },
  ],
};

describe('descriptors that name no target', () => {
  it('keep one drawing layer and one marker layer, bound and painted exactly as before', async () => {
    registerIndicator(untargetedPane);
    registerIndicator(untargetedPrice);
    const { chart } = mount();
    const pane = chart.addIndicator(untargetedPane.id);
    const price = chart.addIndicator(untargetedPrice.id);
    const paneLayers = ownedLayers(chart, pane);
    const priceLayers = ownedLayers(chart, price);
    expect(paneLayers.map(({ ops: _ops, ...rest }) => rest)).toEqual([
      { kind: 'SeriesMarkers', pane: 1, overlay: false, scale: null },
      { kind: 'IndicatorDrawings', pane: 1, overlay: false, scale: 'right' },
    ]);
    expect(priceLayers.map(({ ops: _ops, ...rest }) => rest)).toEqual([
      { kind: 'SeriesMarkers', pane: 0, overlay: true, scale: null },
      { kind: 'IndicatorDrawings', pane: 0, overlay: false, scale: 'right' },
    ]);
    expect(paneLayers.every(layer => layer.ops.length > 0) && priceLayers.every(layer => layer.ops.length > 0)).toBe(true);
    // Re-pinned when pane boundaries moved onto whole device pixels: with that
    // rounding bypassed, these op streams still hash to the digests pinned before.
    expect(await digest(paneLayers.map(layer => layer.ops))).toBe('fa75466e0876a1a537e6859d4bf8f96a02ee4be5671ae9a3d2fd16c9de6d8723');
    expect(await digest(priceLayers.map(layer => layer.ops))).toBe('e6737b9553bd21ee5cfe92260aa35ea63819a5146141eb449efbf061918bf833');
  });

  it('leave a layer first made on a live pass above the studies after it, and restack nothing', () => {
    const make = (name: string, from: number): string => {
      const id = `targets-untargeted-late-${name}-${seq++}`;
      registerIndicator({
        ...untargetedPrice, id, name,
        draws: context => (context.bars.length >= from ? untargetedPrice.draws!(context) : []),
        markers: context => (context.bars.length >= from ? untargetedPrice.markers!(context) : []),
      });
      return id;
    };
    const { chart } = mount();
    const studies = { A: chart.addIndicator(make('A', 41)), B: chart.addIndicator(make('B', 0)) };
    expect(stack(chart, studies, 0)).toEqual(['B marks', 'B shapes']);
    tick(chart, 40);
    expect(stack(chart, studies, 0)).toEqual(['B marks', 'B shapes', 'A marks', 'A shapes']);
  });
});

type Route = 'study' | 'price' | 'alt' | 'guide';
const ROUTES = (['study', 'price', 'alt', 'guide'] as const).map(value => ({ label: value, value }));
/** Where a routed output goes: nowhere special, the price pane, or a named plot. */
const target = (route: Route): { overlay?: boolean; plot?: string } =>
  route === 'price' ? { overlay: true } : route === 'study' ? {} : { plot: route };

/** A local oscillator, a second local plot for another axis, and a guide on the candles. */
const PLOTS: IndicatorDescriptor['plots'] = [
  { key: 'osc', type: 'line', title: 'Osc' },
  { key: 'alt', type: 'line', title: 'Alt' },
  { key: 'guide', type: 'line', title: 'Guide', overlay: true },
];
const CALC: IndicatorDescriptor['calc'] = bars => ({
  osc: bars.map((_, i) => 30 + i), alt: bars.map((_, i) => 500 + i), guide: bars.map(bar => bar.close),
});

let seq = 0;
function routedDraws(): string {
  const id = `targets-draws-${seq++}`;
  registerIndicator({
    id, name: 'Routed drawings', placement: 'pane', plots: PLOTS, calc: CALC,
    inputs: [{ key: 'zone', type: 'select', label: 'Zone', default: 'price', options: ROUTES }],
    draws: ({ bars, settings }) => {
      const route = settings.zone as Route;
      const [lo, hi] = route === 'alt' ? [510, 520] : route === 'study' ? [40, 50] : [112, 124];
      return [
        { kind: 'line', from: { time: bars[2].time, price: 32 }, to: { time: bars[30].time, price: 60 }, id: 'ray' } as never,
        { kind: 'box', from: { time: bars[10].time, price: hi }, to: { time: bars[20].time, price: lo },
          fillColor: '#26a69a', id: 'zone', ...target(route) } as never,
      ];
    },
  });
  return id;
}

const owned = (study: IndicatorApi): { primitive: IPrimitive; overlay: boolean }[] =>
  (study as unknown as { renderResources(): { primitives: { primitive: IPrimitive; overlay: boolean }[] } }).renderResources().primitives;
const drawingObjects = (study: IndicatorApi): IPrimitive[] =>
  owned(study).filter(({ primitive }) => primitive instanceof IndicatorDrawings).map(({ primitive }) => primitive);
/** The study's drawing layers: pane, binding, placement role and which shapes each holds. */
function drawLayers(chart: Chart, study: IndicatorApi): { pane: number; scale: string | null; overlay: boolean; ids: (string | undefined)[] }[] {
  return owned(study).filter(({ primitive }) => primitive instanceof IndicatorDrawings).map(({ primitive, overlay }) => {
    const pane = paneOf(chart, primitive);
    return {
      pane, scale: chart.panes()[pane]?.primitiveScaleId(primitive) ?? null, overlay,
      ids: (primitive as unknown as { _items: { id?: string }[] })._items.map(item => item.id),
    };
  });
}
const drawingsOn = (chart: Chart, paneIndex: number): IPrimitive[] =>
  layers(chart.panes()[paneIndex], IndicatorDrawings) as unknown as IPrimitive[];
const allDrawings = (chart: Chart): number => chart.panes().reduce((sum, _, i) => sum + drawingsOn(chart, i).length, 0);
const click = (el: FakeElement, x: number, y: number): void => {
  el.dispatch('pointerdown', pointer('down', x, y));
  el.dispatch('pointerup', pointer('up', x, y));
};
const paneTop = (chart: Chart, paneIndex: number): number => (chart as unknown as ChartInternals)._paneLayout()[paneIndex].top;
/**
 * The drawing and marker layers of the named studies on one pane, in the order
 * the pane draws them, each with its owner, its kind and the ids it holds.
 */
function stack(chart: Chart, studies: Record<string, IndicatorApi>, paneIndex: number): string[] {
  return chart.panes()[paneIndex].primitives().flatMap(primitive => {
    const owner = Object.entries(studies).find(([, study]) => owned(study).some(item => item.primitive === primitive))?.[0];
    const items = primitive instanceof SeriesMarkers ? (primitive as unknown as { _markers: { id?: string }[] })._markers
      : primitive instanceof IndicatorDrawings ? (primitive as unknown as { _items: { id?: string }[] })._items : undefined;
    if (owner === undefined || items === undefined) return [];
    const ids = items.flatMap(item => (item.id === undefined ? [] : [item.id])).join(',');
    return [`${owner} ${primitive instanceof SeriesMarkers ? 'marks' : 'shapes'}${ids ? ` ${ids}` : ''}`];
  });
}
/** Append one bar the way a live feed does, then let every study catch up. */
function tick(chart: Chart, i: number): void {
  chart.primarySeries()!.update({ time: T0 + i * 60, open: 120, high: 123, low: 117, close: 121 });
  chart.indicators();
}

describe('drawing targets', () => {
  it('sends a price-pane drawing to pane zero, bound to no axis, and keeps the rest in the study pane', () => {
    const { chart } = mount();
    const study = chart.addIndicator(routedDraws());
    expect(drawLayers(chart, study)).toEqual([
      { pane: 1, scale: 'right', overlay: false, ids: ['ray'] },
      { pane: 0, scale: null, overlay: true, ids: ['zone'] },
    ]);
  });

  it('binds a plot target to that plot pane and effective scale, beside differently bound layers', () => {
    const id = routedDraws();
    const { chart } = mount();
    const alt = chart.addIndicator(id, { zone: 'alt' }, { plotPriceScaleIds: { alt: 'left' } });
    const guide = chart.addIndicator(id, { zone: 'guide' }, { plotPriceScaleIds: { guide: 'overlay:guide' } });
    expect(drawLayers(chart, alt)).toEqual([
      { pane: alt.paneIndex, scale: 'right', overlay: false, ids: ['ray'] },
      { pane: alt.paneIndex, scale: 'left', overlay: false, ids: ['zone'] },
    ]);
    expect(drawLayers(chart, guide)).toEqual([
      { pane: guide.paneIndex, scale: 'right', overlay: false, ids: ['ray'] },
      { pane: 0, scale: 'overlay:guide', overlay: true, ids: ['zone'] },
    ]);
  });

  it('follows plot and whole-study scale reassignment without moving price-pane layers', () => {
    const id = routedDraws();
    const { chart } = mount();
    const study = chart.addIndicator(id, { zone: 'alt' });
    const guide = chart.addIndicator(id, { zone: 'guide' });
    const bound = (item: IndicatorApi) => drawLayers(chart, item).map(layer => `${layer.pane}:${layer.scale}`);
    expect(study.setPlotPriceScales({ alt: 'overlay:alt' })).toBe(true);
    expect(bound(study)).toEqual([`${study.paneIndex}:right`, `${study.paneIndex}:overlay:alt`]);
    expect(study.setPlotPriceScales({ alt: null })).toBe(true);
    expect(bound(study)).toEqual([`${study.paneIndex}:right`, `${study.paneIndex}:right`]);
    expect(study.setPriceScale('left')).toBe(true);
    expect(bound(study)).toEqual([`${study.paneIndex}:left`, `${study.paneIndex}:left`]);
    expect(guide.setPriceScale('left')).toBe(true);
    expect(bound(guide)).toEqual([`${guide.paneIndex}:left`, '0:right']);
    study.setSettings({ zone: 'price' });
    expect(bound(study)).toEqual([`${study.paneIndex}:left`, '0:null']);
    expect(study.setPriceScale(null)).toBe(true);
    expect(bound(study)).toEqual([`${study.paneIndex}:right`, '0:null']);
  });

  it('moves a shape between targets when settings change and releases the layer it left', () => {
    const { chart } = mount();
    const study = chart.addIndicator(routedDraws());
    const [local] = drawingObjects(study);
    study.setSettings({ zone: 'alt' });
    expect(drawLayers(chart, study)).toEqual([
      { pane: 1, scale: 'right', overlay: false, ids: ['ray'] },
      { pane: 1, scale: 'right', overlay: false, ids: ['zone'] },
    ]);
    expect(drawingsOn(chart, 0)).toHaveLength(0);
    study.setSettings({ zone: 'study' });
    expect(drawLayers(chart, study)).toEqual([{ pane: 1, scale: 'right', overlay: false, ids: ['ray', 'zone'] }]);
    expect(drawingObjects(study)).toEqual([local]);
    expect(allDrawings(chart)).toBe(1);
  });

  it('hides and shows every target layer with the study', () => {
    const { chart } = mount();
    const study = chart.addIndicator(routedDraws(), { zone: 'price' });
    const painted = () => ownedLayers(chart, study).filter(layer => layer.kind === 'IndicatorDrawings').map(layer => layer.ops.length > 0);
    expect(painted()).toEqual([true, true]);
    study.setVisible(false);
    expect(painted()).toEqual([false, false]);
    study.setVisible(true);
    expect(painted()).toEqual([true, true]);
  });

  it('makes a target layer hidden when the study is hidden, and shows it with the study', () => {
    const { chart } = mount();
    const study = chart.addIndicator(routedDraws(), { zone: 'study' });
    study.setVisible(false);
    // A pass while hidden routes a shape somewhere new: its layer must not paint yet.
    study.setSettings({ zone: 'price' });
    expect(drawLayers(chart, study)).toEqual([
      { pane: 1, scale: 'right', overlay: false, ids: ['ray'] },
      { pane: 0, scale: null, overlay: true, ids: ['zone'] },
    ]);
    const painted = () => ownedLayers(chart, study).filter(layer => layer.kind === 'IndicatorDrawings').map(layer => layer.ops.length > 0);
    expect(painted()).toEqual([false, false]);
    study.setVisible(true);
    expect(painted()).toEqual([true, true]);
  });

  it('keeps price-pane layers on pane zero through moves and releases them with the study or its pane', () => {
    const id = routedDraws();
    const { chart } = mount();
    const study = chart.addIndicator(id, { zone: 'price' });
    const other = chart.addIndicator(id, { zone: 'alt' });
    expect(chart.moveIndicator(other.id, chart.panes().length)).toBe(true);
    expect(drawLayers(chart, other).map(layer => layer.pane)).toEqual([other.paneIndex, other.paneIndex]);
    expect(chart.moveIndicator(study.id, other.paneIndex)).toBe(true);
    expect(drawLayers(chart, study).map(layer => layer.pane)).toEqual([other.paneIndex, 0]);
    expect(drawingsOn(chart, 0)).toHaveLength(1);
    const removable = chart.addIndicator(id, { zone: 'price' });
    expect(drawingsOn(chart, 0)).toHaveLength(2);
    expect(chart.removePane(removable.paneIndex)).toBe(true);
    expect(drawingsOn(chart, 0)).toHaveLength(1);
    study.remove();
    expect(drawingsOn(chart, 0)).toHaveLength(0);
    other.remove();
    expect(allDrawings(chart)).toBe(0);
  });

  it('reports clicks on a routed box where it is drawn: on pane zero and on its plot scale', () => {
    const { chart, el } = mount();
    const clicks: string[] = [];
    chart.subscribeClick(id => { clicks.push(id); });
    const study = chart.addIndicator(routedDraws(), { zone: 'price' });
    click(el, chart.timeToCoordinate(BARS[15].time), chart.priceToCoordinate(118, 0)!);
    expect(clicks).toEqual(['zone']);
    study.setSettings({ zone: 'alt' });
    expect(study.setPlotPriceScales({ alt: 'left' })).toBe(true);
    const y = paneTop(chart, study.paneIndex) + chart.panes()[study.paneIndex].scaleFor('left').priceToY(515);
    click(el, chart.timeToCoordinate(BARS[15].time), y);
    expect(clicks).toEqual(['zone', 'zone']);
  });

  it('restores routed layers from saved state with their bindings', () => {
    const id = routedDraws();
    const { chart } = mount();
    chart.addIndicator(id, { zone: 'price' });
    chart.addIndicator(id, { zone: 'alt' }, { plotPriceScaleIds: { alt: 'left' } });
    const state = JSON.parse(JSON.stringify(chart.getState()));
    expect(chart.restoreState(state)).toMatchObject({ applied: true, indicators: 2 });
    const [price, alt] = chart.indicators();
    expect(drawLayers(chart, price)).toEqual([
      { pane: price.paneIndex, scale: 'right', overlay: false, ids: ['ray'] },
      { pane: 0, scale: null, overlay: true, ids: ['zone'] },
    ]);
    expect(drawLayers(chart, alt)).toEqual([
      { pane: alt.paneIndex, scale: 'right', overlay: false, ids: ['ray'] },
      { pane: alt.paneIndex, scale: 'left', overlay: false, ids: ['zone'] },
    ]);
    expect(allDrawings(chart)).toBe(4);
  });

  it('gives each instance and each target a layer of its own', () => {
    const id = routedDraws();
    const { chart } = mount();
    const first = chart.addIndicator(id, { zone: 'price' });
    const second = chart.addIndicator(id, { zone: 'price' });
    const kept = drawingObjects(second);
    expect(drawingsOn(chart, 0)).toHaveLength(2);
    first.setSettings({ zone: 'study' });
    expect(drawingsOn(chart, 0)).toEqual([kept[1]]);
    first.remove();
    expect(drawingObjects(second)).toEqual(kept);
    expect(drawLayers(chart, second).map(layer => layer.ids)).toEqual([['ray'], ['zone']]);
  });

  it.each([{ plot: 'missing' }, { plot: 'alt', overlay: true }])('rejects the target %j before changing any layer', bad => {
    const id = `targets-invalid-draws-${seq++}`;
    registerIndicator({
      id, name: 'Invalid', placement: 'pane', plots: PLOTS, calc: CALC,
      inputs: [{ key: 'bad', type: 'boolean', label: 'Bad', default: true }],
      draws: ({ bars, settings }) => [{ kind: 'line', from: { time: bars[1].time, price: 110 }, to: { time: bars[9].time, price: 120 },
        ...(settings.bad === true ? bad : { overlay: true }) } as never],
    });
    const { chart } = mount();
    expect(() => chart.addIndicator(id)).toThrow(/declared plot or the price pane/);
    expect(chart.panes()).toHaveLength(1);
    expect(allDrawings(chart)).toBe(0);
    const study = chart.addIndicator(id, { bad: false });
    const before = drawLayers(chart, study);
    study.setSettings({ bad: true });
    expect(study.dataStatus()?.state).toBe('error');
    expect(drawLayers(chart, study)).toEqual(before);
  });
});

function routedMarks(placement: 'pane' | 'onchart' = 'pane'): string {
  const id = `targets-marks-${seq++}`;
  registerIndicator({
    id, name: 'Routed markers', placement, plots: PLOTS, calc: CALC,
    inputs: [{ key: 'mark', type: 'select', label: 'Mark', default: 'price', options: ROUTES }],
    markers: ({ bars, settings }) => {
      const route = settings.mark as Route;
      return [
        { time: bars[5].time, position: 'atPrice', price: 35, shape: 'circle', size: 'small', color: '#888888', id: 'plain' },
        route === 'price'
          ? { time: bars[15].time, position: 'belowBar', shape: 'circle', size: 'big', color: '#26a69a', id: 'sig', overlay: true }
          : { time: bars[15].time, position: 'atPrice', price: route === 'alt' ? 515 : route === 'study' ? 45 : 118,
            shape: 'circle', size: 'big', color: '#26a69a', id: 'sig', ...target(route) },
      ] as never;
    },
  });
  return id;
}

/** Which series a marker layer was created on: the candles, or one of the study's plots. */
function seriesName(chart: Chart, study: IndicatorApi, layer: IPrimitive): string {
  const records = (chart as unknown as { _seriesRecords: Map<SeriesApi, { dataId: number }> })._seriesRecords;
  const id = (layer as unknown as { _seriesId: number })._seriesId;
  if (records.get(chart.primarySeries()!)?.dataId === id) return 'primary';
  return ['osc', 'alt', 'guide'].find(key => records.get(study.series(key)!)?.dataId === id) ?? 'none';
}
const markerObjects = (study: IndicatorApi): IPrimitive[] =>
  owned(study).filter(({ primitive }) => primitive instanceof SeriesMarkers).map(({ primitive }) => primitive);
function markerLayers(chart: Chart, study: IndicatorApi): { pane: number; overlay: boolean; series: string; ids: (string | undefined)[] }[] {
  return owned(study).filter(({ primitive }) => primitive instanceof SeriesMarkers).map(({ primitive, overlay }) => ({
    pane: paneOf(chart, primitive), overlay, series: seriesName(chart, study, primitive),
    ids: (primitive as unknown as { _markers: { id?: string }[] })._markers.map(marker => marker.id),
  }));
}
const markersOn = (chart: Chart, paneIndex: number): IPrimitive[] =>
  layers(chart.panes()[paneIndex], SeriesMarkers) as unknown as IPrimitive[];
const allMarkers = (chart: Chart): number => chart.panes().reduce((sum, _, i) => sum + markersOn(chart, i).length, 0);

describe('marker targets', () => {
  it('measures a price-pane group against the candles and keeps untargeted marks on the first plot', () => {
    const { chart, el } = mount();
    const clicks: string[] = [];
    chart.subscribeClick(id => { clicks.push(id); });
    const study = chart.addIndicator(routedMarks());
    expect(markerLayers(chart, study)).toEqual([
      { pane: 1, overlay: false, series: 'osc', ids: ['plain'] },
      { pane: 0, overlay: true, series: 'primary', ids: ['sig'] },
    ]);
    // Below the candle's own low, not below the oscillator in another pane.
    const px = effectiveMarkerPx('big', chart.timeScale.barSpacing);
    click(el, chart.timeToCoordinate(BARS[15].time), chart.priceToCoordinate(BARS[15].low, 0)! + px);
    expect(clicks).toEqual(['sig']);
    // The same group from a study on the price pane whose own marks anchor to its plot.
    const onchart = chart.addIndicator(routedMarks('onchart'));
    expect(markerLayers(chart, onchart)).toEqual([
      { pane: 0, overlay: false, series: 'osc', ids: ['plain'] },
      { pane: 0, overlay: true, series: 'primary', ids: ['sig'] },
    ]);
  });

  it('anchors a named plot group to that plot series, pane and scale', () => {
    const id = routedMarks();
    const { chart, el } = mount();
    const clicks: string[] = [];
    chart.subscribeClick(item => { clicks.push(item); });
    const alt = chart.addIndicator(id, { mark: 'alt' }, { plotPriceScaleIds: { alt: 'left' } });
    const guide = chart.addIndicator(id, { mark: 'guide' });
    expect(markerLayers(chart, alt)).toEqual([
      { pane: alt.paneIndex, overlay: false, series: 'osc', ids: ['plain'] },
      { pane: alt.paneIndex, overlay: false, series: 'alt', ids: ['sig'] },
    ]);
    expect(markerLayers(chart, guide)).toEqual([
      { pane: guide.paneIndex, overlay: false, series: 'osc', ids: ['plain'] },
      { pane: 0, overlay: true, series: 'guide', ids: ['sig'] },
    ]);
    const y = paneTop(chart, alt.paneIndex) + chart.panes()[alt.paneIndex].scaleFor('left').priceToY(515);
    click(el, chart.timeToCoordinate(BARS[15].time), y);
    expect(clicks).toEqual(['sig']);
  });

  it('follows a scale reassignment of the plot it names', () => {
    const { chart, el } = mount();
    const clicks: string[] = [];
    chart.subscribeClick(item => { clicks.push(item); });
    const study = chart.addIndicator(routedMarks(), { mark: 'alt' });
    const pane = chart.panes()[study.paneIndex];
    const drawnAt = () => (markerObjects(study)[1] as unknown as { _lastPositions: { y: number }[] })._lastPositions[0].y;
    expect(study.setPlotPriceScales({ alt: 'left' })).toBe(true);
    const left = pane.scaleFor('left').priceToY(515);
    expect(drawnAt()).toBeCloseTo(left, 6);
    click(el, chart.timeToCoordinate(BARS[15].time), paneTop(chart, study.paneIndex) + left);
    expect(clicks).toEqual(['sig']);
    // Sharing the oscillator's axis stretches the range, so the same value sits elsewhere.
    expect(study.setPlotPriceScales({ alt: null })).toBe(true);
    const right = pane.scaleFor('right').priceToY(515);
    expect(Math.abs(right - left)).toBeGreaterThan(20);
    expect(drawnAt()).toBeCloseTo(right, 6);
    expect(markerLayers(chart, study).map(layer => layer.series)).toEqual(['osc', 'alt']);
  });

  it('moves marks between groups when settings change and releases the layer they left', () => {
    const { chart } = mount();
    const study = chart.addIndicator(routedMarks());
    const [local] = markerObjects(study);
    study.setSettings({ mark: 'alt' });
    expect(markerLayers(chart, study)).toEqual([
      { pane: 1, overlay: false, series: 'osc', ids: ['plain'] },
      { pane: 1, overlay: false, series: 'alt', ids: ['sig'] },
    ]);
    expect(markersOn(chart, 0)).toHaveLength(0);
    study.setSettings({ mark: 'study' });
    expect(markerLayers(chart, study)).toEqual([{ pane: 1, overlay: false, series: 'osc', ids: ['plain', 'sig'] }]);
    expect(markerObjects(study)).toEqual([local]);
    expect(allMarkers(chart)).toBe(1);
  });

  it('clears every group while hidden and fills the same layers when shown', () => {
    const { chart } = mount();
    const study = chart.addIndicator(routedMarks());
    const kept = markerObjects(study);
    study.setVisible(false);
    expect(markerLayers(chart, study).map(layer => layer.ids)).toEqual([[], []]);
    expect(markerObjects(study)).toEqual(kept);
    study.setVisible(true);
    expect(markerLayers(chart, study).map(layer => layer.ids)).toEqual([['plain'], ['sig']]);
    expect(markerObjects(study)).toEqual(kept);
  });

  it('keeps price-pane groups on pane zero through moves and releases them with the study or its pane', () => {
    const id = routedMarks();
    const { chart } = mount();
    const study = chart.addIndicator(id);
    const other = chart.addIndicator(id, { mark: 'alt' });
    expect(chart.moveIndicator(other.id, chart.panes().length)).toBe(true);
    expect(markerLayers(chart, other).map(layer => layer.pane)).toEqual([other.paneIndex, other.paneIndex]);
    expect(chart.moveIndicator(study.id, other.paneIndex)).toBe(true);
    expect(markerLayers(chart, study).map(layer => layer.pane)).toEqual([other.paneIndex, 0]);
    const removable = chart.addIndicator(id);
    expect(markersOn(chart, 0)).toHaveLength(2);
    expect(chart.removePane(removable.paneIndex)).toBe(true);
    expect(markersOn(chart, 0)).toHaveLength(1);
    study.remove();
    expect(markersOn(chart, 0)).toHaveLength(0);
    other.remove();
    expect(allMarkers(chart)).toBe(0);
  });

  it('restores routed marker groups from saved state', () => {
    const id = routedMarks();
    const { chart } = mount();
    chart.addIndicator(id);
    chart.addIndicator(id, { mark: 'alt' }, { plotPriceScaleIds: { alt: 'left' } });
    const state = JSON.parse(JSON.stringify(chart.getState()));
    expect(chart.restoreState(state)).toMatchObject({ applied: true, indicators: 2 });
    const [price, alt] = chart.indicators();
    expect(markerLayers(chart, price)).toEqual([
      { pane: price.paneIndex, overlay: false, series: 'osc', ids: ['plain'] },
      { pane: 0, overlay: true, series: 'primary', ids: ['sig'] },
    ]);
    expect(markerLayers(chart, alt)).toEqual([
      { pane: alt.paneIndex, overlay: false, series: 'osc', ids: ['plain'] },
      { pane: alt.paneIndex, overlay: false, series: 'alt', ids: ['sig'] },
    ]);
    expect(alt.plotPriceScaleId('alt')).toBe('left');
    expect(allMarkers(chart)).toBe(4);
  });

  it('gives each instance its own marker layers', () => {
    const id = routedMarks();
    const { chart } = mount();
    const first = chart.addIndicator(id);
    const second = chart.addIndicator(id);
    const kept = markerObjects(second);
    expect(markersOn(chart, 0)).toHaveLength(2);
    first.setSettings({ mark: 'study' });
    expect(markersOn(chart, 0)).toEqual([kept[1]]);
    first.remove();
    expect(markerObjects(second)).toEqual(kept);
    expect(markerLayers(chart, second).map(layer => layer.ids)).toEqual([['plain'], ['sig']]);
  });

  it('waits for candles before drawing a price-pane group', () => {
    const id = `targets-late-${seq++}`;
    registerIndicator({
      id, name: 'Late candles', placement: 'pane', plots: PLOTS, calc: CALC, inputs: [],
      markers: ({ bars }) => bars.length < 5 ? [] : [{ time: bars[4].time, position: 'aboveBar', shape: 'circle', size: 'small',
        color: '#ef5350', id: 'late', overlay: true } as never],
    });
    const document = fakeDocument();
    const chart = new Chart(document.createElement('div') as unknown as FakeElement, {
      document, pixelRatio: () => 1, shortcuts: false, timeNavigator: false, animZoom: false, animAutoscale: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    });
    charts.push(chart);
    chart.applySize(800, 600);
    const study = chart.addIndicator(id);
    expect(markerObjects(study)).toHaveLength(0);
    chart.addSeries('candlestick').setData(BARS);
    study.values();
    expect(markerLayers(chart, study)).toEqual([{ pane: 0, overlay: true, series: 'primary', ids: ['late'] }]);
  });

  it('keeps two charts sharing one descriptor independent of each other', () => {
    const marks = routedMarks();
    const draws = routedDraws();
    const one = mount().chart;
    const two = mount().chart;
    const a = one.addIndicator(marks);
    const b = two.addIndicator(marks);
    const c = one.addIndicator(draws);
    const d = two.addIndicator(draws);
    const keptMarks = markerObjects(b);
    const keptDraws = drawingObjects(d);
    expect(markersOn(two, 0)).toEqual([keptMarks[1]]);
    expect(drawingsOn(two, 0)).toEqual([keptDraws[1]]);
    a.remove();
    c.remove();
    expect(markersOn(one, 0)).toHaveLength(0);
    expect(drawingsOn(one, 0)).toHaveLength(0);
    expect(markerObjects(b)).toEqual(keptMarks);
    expect(drawingObjects(d)).toEqual(keptDraws);
    expect(markerLayers(two, b).map(layer => layer.ids)).toEqual([['plain'], ['sig']]);
    expect(drawLayers(two, d).map(layer => layer.ids)).toEqual([['ray'], ['zone']]);
  });

  it.each([{ plot: 'missing' }, { plot: 'alt', overlay: true }])('rejects the marker target %j before changing any layer', bad => {
    const id = `targets-invalid-marks-${seq++}`;
    registerIndicator({
      id, name: 'Invalid', placement: 'pane', plots: PLOTS, calc: CALC,
      inputs: [{ key: 'bad', type: 'boolean', label: 'Bad', default: true }],
      markers: ({ bars, settings }) => [{ time: bars[3].time, position: 'aboveBar', shape: 'circle', size: 'small', color: '#ef5350',
        ...(settings.bad === true ? bad : { overlay: true }) } as never],
    });
    const { chart } = mount();
    expect(() => chart.addIndicator(id)).toThrow(/declared plot or the price pane/);
    expect(chart.panes()).toHaveLength(1);
    expect(allMarkers(chart)).toBe(0);
    const study = chart.addIndicator(id, { bad: false });
    const before = markerLayers(chart, study);
    study.setSettings({ bad: true });
    expect(study.dataStatus()?.state).toBe('error');
    expect(markerLayers(chart, study)).toEqual(before);
  });

  it('stacks marks sent to the candles with the study\'s own marks there, and splits them when the study moves', () => {
    const id = `targets-shared-anchor-${seq++}`;
    registerIndicator({
      id, name: 'Shared anchor', placement: 'onchart', markerAnchor: 'price', inputs: [],
      plots: [{ key: 'osc', type: 'line', title: 'Osc' }],
      calc: bars => ({ osc: bars.map(bar => bar.close) }),
      markers: ({ bars }) => [
        { time: bars[15].time, position: 'belowBar', shape: 'circle', size: 'small', color: '#26a69a', id: 'own' },
        { time: bars[15].time, position: 'belowBar', shape: 'circle', size: 'small', color: '#ef5350', id: 'sent', overlay: true },
        { time: bars[20].time, position: 'belowBar', shape: 'circle', size: 'small', color: '#26a69a', id: 'later' },
      ] as never,
    });
    const { chart } = mount();
    const study = chart.addIndicator(id);
    expect(markerLayers(chart, study)).toEqual([{ pane: 0, overlay: true, series: 'primary', ids: ['own', 'sent', 'later'] }]);
    // One under the other at the shared bar, rather than one on top of the other.
    const [layer] = markerObjects(study);
    paint(chart, 0, layer);
    const at = Object.fromEntries((layer as unknown as { _lastPositions: { id: string; y: number }[] })._lastPositions
      .map(({ id: mark, y }) => [mark, y]));
    expect(at.sent - at.own).toBeCloseTo(effectiveMarkerPx('small', chart.timeScale.barSpacing) + 4, 6);
    // In a pane of its own the study's marks anchor to its plot, so the sent mark
    // gets a group on the candles, and rejoins them when the study comes back.
    expect(chart.moveIndicator(study.id, 1)).toBe(true);
    expect(markerLayers(chart, study)).toEqual([
      { pane: 1, overlay: false, series: 'osc', ids: ['own', 'later'] },
      { pane: 0, overlay: true, series: 'primary', ids: ['sent'] },
    ]);
    expect(chart.moveIndicator(study.id, 0)).toBe(true);
    expect(markerLayers(chart, study)).toEqual([{ pane: 0, overlay: true, series: 'primary', ids: ['own', 'sent', 'later'] }]);
    expect(allMarkers(chart)).toBe(1);
  });

  it('keeps marks that name the plot the study\'s own marks anchor to in that one layer', () => {
    const id = `targets-first-plot-${seq++}`;
    registerIndicator({
      id, name: 'First plot', placement: 'pane', plots: PLOTS, calc: CALC, inputs: [],
      markers: ({ bars }) => [
        { time: bars[15].time, position: 'aboveBar', shape: 'circle', size: 'small', color: '#26a69a', id: 'named', plot: 'osc' },
        { time: bars[15].time, position: 'aboveBar', shape: 'circle', size: 'small', color: '#888888', id: 'other', plot: 'alt' },
        { time: bars[15].time, position: 'aboveBar', shape: 'circle', size: 'small', color: '#ef5350', id: 'own' },
      ] as never,
    });
    const { chart } = mount();
    const study = chart.addIndicator(id);
    // In the order returned, so the named mark sits nearest the bar and the study's own one above it.
    expect(markerLayers(chart, study)).toEqual([
      { pane: 1, overlay: false, series: 'osc', ids: ['named', 'own'] },
      { pane: 1, overlay: false, series: 'alt', ids: ['other'] },
    ]);
    expect(allMarkers(chart)).toBe(2);
  });

  it.each([
    ['declared first', ['guide', 'band', 'osc', 'alt']],
    ['declared later', ['osc', 'alt', 'guide', 'band']],
  ])('puts a mark naming a plot with a gap on the candle only when that plot is on the price pane, %s', (_, order) => {
    // Every plot has a gap at one bar, and one mark there names each plot.
    const gap = 15;
    const onPrice = new Set(['guide', 'band']);
    const holed = (column: number[]): (number | null)[] => column.map((value, i) => (i === gap ? null : value));
    const id = `targets-named-gap-${seq++}`;
    registerIndicator({
      id, name: 'Named gap', placement: 'pane', inputs: [],
      plots: order.map(key => ({ key, type: 'line' as const, title: key, ...(onPrice.has(key) ? { overlay: true } : {}) })),
      calc: bars => Object.fromEntries(order.map(key => [key, holed(bars.map(bar => bar.close))])),
      markers: ({ bars }) => order.map(key => ({ time: bars[gap].time, position: 'belowBar', shape: 'circle', size: 'small',
        color: '#26a69a', id: key, plot: key })) as never,
    });
    const { chart } = mount();
    const study = chart.addIndicator(id);
    const drawn = (): string[] => {
      const under = chart.panes()[0].scaleFor('right').priceToY(BARS[gap].low) + effectiveMarkerPx('small', chart.timeScale.barSpacing);
      return markerObjects(study).flatMap(layer => {
        paint(chart, paneOf(chart, layer), layer);
        return (layer as unknown as { _lastPositions: { id: string; y: number }[] })._lastPositions
          .map(({ id: mark, y }) => (Math.abs(y - under) < 1e-6 ? mark : `${mark} elsewhere`));
      }).sort();
    };
    expect(drawn()).toEqual(['band', 'guide']);
    expect(chart.moveIndicator(study.id, 0)).toBe(true);
    expect(drawn()).toEqual(['alt', 'band', 'guide', 'osc']);
    expect(chart.moveIndicator(study.id, chart.panes().length)).toBe(true);
    expect(drawn()).toEqual(['band', 'guide']);
  });
});

describe('price-pane drawings on the instrument scale', () => {
  /** Only local plots, so nothing but the routed box can occupy an axis on the price pane. */
  const localOnly = (): string => {
    const id = `targets-local-only-${seq++}`;
    registerIndicator({
      id, name: 'Local plots only', placement: 'pane', plots: PLOTS.slice(0, 2), calc: CALC, inputs: [],
      draws: ({ bars }) => [{ kind: 'box', from: { time: bars[10].time, price: 124 }, to: { time: bars[20].time, price: 112 },
        fillColor: '#26a69a', id: 'zone', overlay: true } as never],
    });
    return id;
  };
  const clicks = (chart: Chart): string[] => {
    const seen: string[] = [];
    chart.subscribeClick(id => { seen.push(id); });
    return seen;
  };
  const onCandles = (chart: Chart, el: FakeElement): void =>
    click(el, chart.timeToCoordinate(BARS[15].time), chart.priceToCoordinate(118, 0)!);

  it.each([
    ['moved to the left axis', () => { const mounted = mount(); expect(mounted.chart.movePriceAxis(0, 'right', 'left')).toBe(true); return mounted; }],
    ['added on the left scale', () => mount({ priceScaleId: 'left' })],
  ])('draws on the candles when they are %s, without reserving the right axis', (_, setup) => {
    const { chart, el } = setup();
    const seen = clicks(chart);
    const study = chart.addIndicator(localOnly());
    expect(drawLayers(chart, study)).toEqual([{ pane: 0, scale: null, overlay: true, ids: ['zone'] }]);
    expect(chart.panes()[0].usesScale('right')).toBe(false);
    onCandles(chart, el);
    expect(seen).toEqual(['zone']);
    // The candles can go back, and the shape goes with them.
    expect(chart.movePriceAxis(0, 'left', 'right')).toBe(true);
    onCandles(chart, el);
    expect(seen).toEqual(['zone', 'zone']);
  });

  it('leaves the price axis free to move and travels with the candles', () => {
    const { chart, el } = mount();
    const seen = clicks(chart);
    chart.addIndicator(localOnly());
    expect(chart.movePriceAxis(0, 'right', 'left')).toBe(true);
    expect(chart.panes()[0].usesScale('right')).toBe(false);
    onCandles(chart, el);
    expect(seen).toEqual(['zone']);
  });

  it('measures on the price pane itself, not across panes, when the candles live on another pane', () => {
    const document = fakeDocument();
    const el = document.createElement('div') as unknown as FakeElement;
    const chart = new Chart(el, {
      document, pixelRatio: () => 1, shortcuts: false, timeNavigator: false, animZoom: false, animAutoscale: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    });
    charts.push(chart);
    chart.applySize(800, 600);
    chart.addSeries('candlestick', { paneIndex: 1 }).setData(BARS);
    const seen = clicks(chart);
    // The guide puts a price on pane zero, which is where the price-pane box goes.
    const id = `targets-candles-elsewhere-${seq++}`;
    registerIndicator({
      id, name: 'Candles elsewhere', placement: 'pane', plots: PLOTS, calc: CALC, inputs: [],
      draws: ({ bars }) => [{ kind: 'box', from: { time: bars[10].time, price: 124 }, to: { time: bars[20].time, price: 112 },
        fillColor: '#26a69a', id: 'zone', overlay: true } as never],
    });
    const study = chart.addIndicator(id);
    expect(drawLayers(chart, study)).toEqual([{ pane: 0, scale: null, overlay: true, ids: ['zone'] }]);
    const own = chart.panes()[0].readoutScale().priceToY(118);
    expect(Math.abs(own - chart.primarySeries()!.priceScale().priceToY(118))).toBeGreaterThan(20);
    click(el, chart.timeToCoordinate(BARS[15].time), paneTop(chart, 0) + own);
    expect(seen).toEqual(['zone']);
  });

  it('follows the candles onto another scale set on the series itself', () => {
    const { chart, el } = mount();
    const seen = clicks(chart);
    chart.addIndicator(localOnly());
    expect(chart.setSeriesPriceScale(chart.primarySeries()!, 'overlay:candles')).toBe(true);
    // Squeezed into the lower half, so the scale it left no longer agrees with it.
    chart.primarySeries()!.priceScale().setOptions({ marginTop: 0.85 });
    chart.invalidate(mask => mask.invalidateGlobal(InvalidationLevel.Full));
    expect(Math.abs(chart.priceToCoordinate(118, 0)! - chart.panes()[0].scaleFor('right').priceToY(118))).toBeGreaterThan(50);
    onCandles(chart, el);
    expect(seen).toEqual(['zone']);
  });
});

/** Which of the named studies owns each primitive, in the order the pane draws them. */
function owners(studies: Record<string, IndicatorApi>, primitives: IPrimitive[]): (string | undefined)[] {
  return primitives.map(primitive => Object.entries(studies).find(([, study]) => owned(study).some(item => item.primitive === primitive))?.[0]);
}

describe('routed layer lifecycle', () => {
  it('keeps study order on the price pane when a live pass routes to a target again or for the first time', () => {
    const make = (name: string, routes: (count: number) => boolean): string => {
      const id = `targets-order-${name}-${seq++}`;
      registerIndicator({
        id, name, placement: 'pane', plots: PLOTS, calc: CALC, inputs: [],
        draws: ({ bars }) => routes(bars.length) ? [{ kind: 'box', from: { time: bars[10].time, price: 124 },
          to: { time: bars[20].time, price: 112 }, overlay: true } as never] : [],
        markers: ({ bars }) => routes(bars.length) ? [{ time: bars[15].time, position: 'belowBar', shape: 'circle',
          size: 'small', color: '#26a69a', overlay: true } as never] : [],
      });
      return id;
    };
    const { chart } = mount();
    const studies = {
      A: chart.addIndicator(make('A', count => count !== 41)),
      B: chart.addIndicator(make('B', () => true)),
      C: chart.addIndicator(make('C', count => count >= 42)),
    };
    const order = () => [owners(studies, drawingsOn(chart, 0)), owners(studies, markersOn(chart, 0))];
    expect(order()).toEqual([['A', 'B'], ['A', 'B']]);
    const live = (i: number) => {
      chart.primarySeries()!.update({ time: T0 + i * 60, open: 120, high: 123, low: 117, close: 121 });
      studies.A.values();
    };
    live(40);
    expect(order()).toEqual([['B'], ['B']]);
    live(41);
    expect(order()).toEqual([['A', 'B', 'C'], ['A', 'B', 'C']]);
    expect(chart.indicators().map(study => study.id)).toEqual([studies.A.id, studies.B.id, studies.C.id]);
  });

  it('moves a price-pane group to replacement candles and releases the one on the old series', () => {
    const id = `targets-replaced-${seq++}`;
    registerIndicator({
      id, name: 'Replaced candles', placement: 'pane', plots: PLOTS, calc: CALC, inputs: [],
      // A fixed time, so the group is still returned while the chart has no candles.
      markers: () => [{ time: BARS[15].time, position: 'belowBar', shape: 'circle', size: 'small', color: '#26a69a',
        id: 'sig', overlay: true } as never],
    });
    const { chart } = mount();
    const study = chart.addIndicator(id);
    const [old] = markerObjects(study);
    chart.primarySeries()!.remove();
    study.values();
    chart.addSeries('candlestick').setData(BARS);
    study.values();
    expect(markerLayers(chart, study)).toEqual([{ pane: 0, overlay: true, series: 'primary', ids: ['sig'] }]);
    expect(markerObjects(study)).not.toContain(old);
    expect(markersOn(chart, 0)).toHaveLength(1);
  });

  it('checks the style of every routed drawing before the study layer changes', () => {
    const id = `targets-style-draws-${seq++}`;
    registerIndicator({
      id, name: 'Styled drawings', placement: 'pane', plots: PLOTS, calc: CALC,
      inputs: [{ key: 'bad', type: 'boolean', label: 'Bad', default: false }],
      draws: ({ bars, settings }) => [
        { kind: 'line', from: { time: bars[2].time, price: 32 }, to: { time: bars[30].time, price: 60 }, id: settings.bad ? 'next' : 'ray' },
        { kind: 'box', from: { time: bars[10].time, price: 124 }, to: { time: bars[20].time, price: 112 }, text: 'Zone', id: 'zone',
          overlay: true, ...(settings.bad === true ? { verticalAlign: 'sideways' } : {}) },
      ] as never,
    });
    const { chart } = mount();
    const study = chart.addIndicator(id);
    const before = drawLayers(chart, study);
    expect(before.map(layer => layer.ids)).toEqual([['ray'], ['zone']]);
    study.setSettings({ bad: true });
    expect(study.dataStatus()?.state).toBe('error');
    expect(drawLayers(chart, study)).toEqual(before);
  });

  it('checks the style of every routed mark before the study layer changes', () => {
    const id = `targets-style-marks-${seq++}`;
    registerIndicator({
      id, name: 'Styled marks', placement: 'pane', plots: PLOTS, calc: CALC,
      inputs: [{ key: 'bad', type: 'boolean', label: 'Bad', default: false }],
      markers: ({ bars, settings }) => [
        { time: bars[5].time, position: 'atPrice', price: 35, shape: 'circle', size: 'small', color: '#888888', id: settings.bad ? 'next' : 'plain' },
        { time: bars[15].time, position: 'belowBar', shape: 'labelUp', size: 'small', color: '#26a69a', text: 'Up', id: 'sig',
          overlay: true, ...(settings.bad === true ? { textColor: '' } : {}) },
      ] as never,
    });
    const { chart } = mount();
    const study = chart.addIndicator(id);
    const before = markerLayers(chart, study);
    expect(before.map(layer => layer.ids)).toEqual([['plain'], ['sig']]);
    study.setSettings({ bad: true });
    expect(study.dataStatus()?.state).toBe('error');
    expect(markerLayers(chart, study)).toEqual(before);
  });

  it('clears routed layers while a study it reads is unavailable', () => {
    registerIndicator(SMA);
    const id = `targets-consumer-${seq++}`;
    registerIndicator({
      ...SMA, id, name: 'Routed consumer', placement: 'pane',
      draws: ({ bars }) => [
        { kind: 'box', from: { time: bars[10].time, price: 124 }, to: { time: bars[20].time, price: 112 }, id: 'zone', overlay: true },
        { kind: 'label', at: { time: bars[25].time, price: 120 }, text: 'MA', id: 'tag', plot: 'ma' },
      ] as never,
      markers: ({ bars }) => [{ time: bars[15].time, position: 'belowBar', shape: 'circle', size: 'small', color: '#26a69a',
        id: 'sig', overlay: true } as never],
    });
    const { chart } = mount();
    const producer = chart.addIndicator('sma', { length: 2 });
    const consumer = chart.addIndicator(id, { length: 2, source: { kind: 'indicator', instanceId: producer.id, plotKey: 'ma' } });
    expect(drawLayers(chart, consumer).map(layer => layer.ids)).toEqual([['zone'], ['tag']]);
    expect(markerLayers(chart, consumer).map(layer => layer.ids)).toEqual([['sig']]);
    producer.remove();
    consumer.values();
    expect(consumer.dataStatus()?.state).toBe('error');
    expect(drawLayers(chart, consumer).map(layer => layer.ids)).toEqual([[], []]);
    expect(markerLayers(chart, consumer).map(layer => layer.ids)).toEqual([[]]);
    expect(ownedLayers(chart, consumer).every(layer => layer.ops.length === 0)).toBe(true);
  });

  it('keeps the outputs synced before a rejected drawing target and leaves every drawing layer as it was', () => {
    const id = `targets-partial-${seq++}`;
    registerIndicator({
      id, name: 'Partial pass', placement: 'pane', plots: PLOTS, inputs: [{ key: 'bad', type: 'boolean', label: 'Bad', default: false }],
      calc: (bars, settings) => ({ ...CALC(bars, settings, {}), osc: bars.map(() => (settings.bad === true ? 2 : 1)) }),
      markers: ({ bars, settings }) => [{ time: bars[5].time, position: 'atPrice', price: 35, shape: 'circle', size: 'small',
        color: '#888888', id: settings.bad === true ? 'next' : 'plain' }],
      draws: ({ bars, settings }) => [{ kind: 'box', from: { time: bars[10].time, price: 124 }, to: { time: bars[20].time, price: 112 },
        id: 'zone', ...(settings.bad === true ? { plot: 'missing' } : { overlay: true }) } as never],
    });
    const { chart } = mount();
    const study = chart.addIndicator(id);
    const before = drawLayers(chart, study);
    study.setSettings({ bad: true });
    expect(study.dataStatus()?.state).toBe('error');
    expect(drawLayers(chart, study)).toEqual(before);
    // Earlier outputs of the same pass are not rolled back.
    expect(study.values().osc[0]).toBe(2);
    expect(markerLayers(chart, study).map(layer => layer.ids)).toEqual([['next']]);
  });

  it('holds back the bar colours of a settings change whose drawing target is rejected', () => {
    const id = `targets-settings-colours-${seq++}`;
    registerIndicator({
      id, name: 'Coloured settings', placement: 'pane', plots: PLOTS, calc: CALC,
      inputs: [{ key: 'bad', type: 'boolean', label: 'Bad', default: false }],
      barColors: ({ bars, settings }) => bars.map(() => (settings.bad === true ? '#ff0000' : '#00ff00')),
      draws: ({ bars, settings }) => [{ kind: 'box', from: { time: bars[10].time, price: 124 }, to: { time: bars[20].time, price: 112 },
        ...(settings.bad === true ? { plot: 'missing' } : { overlay: true }) } as never],
    });
    const { chart } = mount();
    const study = chart.addIndicator(id);
    expect(chart.primarySeries()!.getData()[0].color).toBe('#00ff00');
    // The settings path reorders every study's resources after its pass, which must not run the colours of a failed one.
    study.setSettings({ bad: true });
    expect(study.dataStatus()?.state).toBe('error');
    expect(chart.primarySeries()!.getData()[0].color).toBe('#00ff00');
    expect(chart.moveIndicator(study.id, chart.panes().length)).toBe(true);
    expect(chart.primarySeries()!.getData()[0].color).toBe('#00ff00');
  });

  it('keeps a study\'s marks under its shapes on the candles when a later study restacks the pane', () => {
    // The reference sample's shape: plates and a range box on the candles from the first pass.
    const sample = `targets-sample-${seq++}`;
    registerIndicator({
      id: sample, name: 'Sample', placement: 'pane', plots: PLOTS, calc: CALC, inputs: [],
      markers: ({ bars }) => [{ time: bars[15].time, position: 'belowBar', shape: 'labelUp', size: 'small', color: '#26a69a',
        text: 'Buy', id: 'buy', overlay: true } as never],
      draws: ({ bars }) => [{ kind: 'box', from: { time: bars[10].time, price: 124 }, to: { time: bars[20].time, price: 112 },
        id: 'range', overlay: true } as never],
    });
    const late = `targets-late-box-${seq++}`;
    registerIndicator({
      id: late, name: 'Late box', placement: 'pane', plots: PLOTS, calc: CALC, inputs: [],
      draws: ({ bars }) => (bars.length > 40 ? [{ kind: 'box', from: { time: bars[25].time, price: 124 },
        to: { time: bars[30].time, price: 112 }, id: 'late', overlay: true } as never] : []),
    });
    const { chart } = mount();
    const studies = { A: chart.addIndicator(sample), B: chart.addIndicator(late) };
    expect(stack(chart, studies, 0)).toEqual(['A marks buy', 'A shapes range']);
    tick(chart, 40);
    expect(stack(chart, studies, 0)).toEqual(['A marks buy', 'A shapes range', 'B shapes late']);
  });

  it('leaves an untargeted study\'s late layers where they land when a routed study restacks on the same pass', () => {
    const untargeted = (from: number): string => {
      const id = `targets-untargeted-beside-${seq++}`;
      registerIndicator({
        ...untargetedPrice, id,
        draws: context => (context.bars.length >= from ? untargetedPrice.draws!(context) : []),
        markers: context => (context.bars.length >= from ? untargetedPrice.markers!(context) : []),
        tables: ({ bars }) => (bars.length >= from ? [{ id: 'grid', rows: [[{ text: 'Grid' }]] }] : []),
      });
      return id;
    };
    const routed = `targets-routed-beside-${seq++}`;
    registerIndicator({
      id: routed, name: 'Routed late', placement: 'pane', plots: PLOTS, calc: CALC, inputs: [],
      markers: ({ bars }) => (bars.length > 40 ? [{ time: bars[15].time, position: 'belowBar', shape: 'circle', size: 'small',
        color: '#26a69a', overlay: true } as never] : []),
      draws: ({ bars }) => (bars.length > 40 ? [{ kind: 'box', from: { time: bars[10].time, price: 124 },
        to: { time: bars[20].time, price: 112 }, overlay: true } as never] : []),
    });
    // Everything the named studies own on the price pane, in the order it is drawn.
    const drawn = (chart: Chart, studies: Record<string, IndicatorApi>): string[] => chart.panes()[0].primitives().flatMap(primitive => {
      const [owner] = owners(studies, [primitive]);
      return owner === undefined ? [] : [`${owner} ${primitive.constructor.name}`];
    });
    // U first draws on a live pass, V on its first pass; R, when present, routes on the same live pass as U.
    const run = (withRouted: boolean): string[] => {
      const { chart } = mount();
      const studies: Record<string, IndicatorApi> = { U: chart.addIndicator(untargeted(41)), V: chart.addIndicator(untargeted(0)) };
      if (withRouted) studies.R = chart.addIndicator(routed);
      tick(chart, 40);
      return drawn(chart, studies);
    };
    // What an untargeted study has always done: its late layers land on top of the pane.
    const base = run(false);
    expect(base).toEqual([
      'U PaneLegend', 'V PaneLegend', 'V SeriesMarkers', 'V ChartTable', 'V IndicatorDrawings',
      'U SeriesMarkers', 'U ChartTable', 'U IndicatorDrawings',
    ]);
    const beside = run(true);
    expect(beside.filter(layer => !layer.startsWith('R '))).toEqual(base);
    expect(beside).toEqual([...base, 'R SeriesMarkers', 'R IndicatorDrawings']);
  });

  it('puts a released target back where the first pass stacked it, whatever order the outputs came in', () => {
    const id = `targets-recreated-${seq++}`;
    // The guide comes first in each list, and the price pane is left out of one pass only.
    const onPrice = (count: number): boolean => count !== 41;
    registerIndicator({
      id, name: 'Recreated', placement: 'pane', plots: PLOTS, calc: CALC, inputs: [],
      markers: ({ bars }) => [
        { time: bars[12].time, position: 'atPrice', price: 118, shape: 'circle', size: 'small', color: '#888888', id: 'g', plot: 'guide' },
        ...(onPrice(bars.length) ? [{ time: bars[15].time, position: 'belowBar', shape: 'circle', size: 'small', color: '#26a69a',
          id: 'p', overlay: true }] : []),
      ] as never,
      draws: ({ bars }) => [
        { kind: 'box', from: { time: bars[2].time, price: 124 }, to: { time: bars[8].time, price: 112 }, id: 'g', plot: 'guide' },
        ...(onPrice(bars.length) ? [{ kind: 'box', from: { time: bars[10].time, price: 124 }, to: { time: bars[20].time, price: 112 },
          id: 'p', overlay: true }] : []),
      ] as never,
    });
    const { chart } = mount();
    const studies = { S: chart.addIndicator(id) };
    const first = stack(chart, studies, 0);
    expect(first).toEqual(['S marks p', 'S marks g', 'S shapes p', 'S shapes g']);
    tick(chart, 40);
    expect(stack(chart, studies, 0)).toEqual(['S marks g', 'S shapes g']);
    tick(chart, 41);
    expect(stack(chart, studies, 0)).toEqual(first);
  });

  it('publishes no bar colours from a pass that creates a routed layer and then fails', () => {
    const id = `targets-colours-${seq++}`;
    registerIndicator({
      id, name: 'Coloured', placement: 'pane', plots: PLOTS, calc: CALC, inputs: [],
      barColors: ({ bars }) => bars.map(() => (bars.length > 40 ? '#ff0000' : '#00ff00')),
      markers: ({ bars }) => (bars.length > 40 ? [{ time: bars[15].time, position: 'belowBar', shape: 'circle', size: 'small',
        color: '#26a69a', overlay: true } as never] : []),
      draws: ({ bars }) => [{ kind: 'box', from: { time: bars[10].time, price: 124 }, to: { time: bars[20].time, price: 112 },
        ...(bars.length > 40 ? { plot: 'missing' } : { overlay: true }) } as never],
    });
    const { chart } = mount();
    const study = chart.addIndicator(id);
    expect(chart.primarySeries()!.getData()[0].color).toBe('#00ff00');
    tick(chart, 40);
    expect(study.dataStatus()?.state).toBe('error');
    // The group was made before the pass failed; the colours still wait for a pass that succeeds.
    expect(markerLayers(chart, study)).toEqual([{ pane: 0, overlay: true, series: 'primary', ids: [undefined] }]);
    expect(chart.primarySeries()!.getData()[0].color).toBe('#00ff00');
  });

  it('runs no other study\'s bar colours in the middle of a pass that creates a routed layer', () => {
    const routed = `targets-routed-late-${seq++}`;
    registerIndicator({
      id: routed, name: 'Routed late', placement: 'pane', plots: PLOTS, calc: CALC, inputs: [],
      markers: ({ bars }) => (bars.length > 40 ? [{ time: bars[15].time, position: 'belowBar', shape: 'circle', size: 'small',
        color: '#26a69a', overlay: true } as never] : []),
    });
    const strict = `targets-strict-colours-${seq++}`;
    const handed: number[] = [];
    registerIndicator({
      id: strict, name: 'Strict colours', placement: 'onchart', plots: [{ key: 'x', type: 'line', title: 'X' }], inputs: [],
      calc: bars => ({ x: bars.map(bar => bar.close) }),
      // A hook entitled to assume that its values describe the bars it is handed.
      barColors: ({ bars, values }) => {
        if (values.x.length !== bars.length) throw new Error('stale values');
        handed.push(bars.length);
        return bars.map(() => null);
      },
    });
    const { chart } = mount();
    const first = chart.addIndicator(routed);
    chart.addIndicator(strict);
    handed.length = 0;
    tick(chart, 40);
    expect(first.dataStatus()?.state).not.toBe('error');
    expect(markerLayers(chart, first)).toEqual([{ pane: 0, overlay: true, series: 'primary', ids: [undefined] }]);
    expect(handed).toEqual([41]);
  });

  it('lets the study order decide the bar colours again once a routed restack is over', () => {
    const late = `targets-restack-then-reorder-${seq++}`;
    registerIndicator({
      id: late, name: 'Routed late', placement: 'pane', plots: PLOTS, calc: CALC, inputs: [],
      markers: ({ bars }) => (bars.length > 40 ? [{ time: bars[15].time, position: 'belowBar', shape: 'circle', size: 'small',
        color: '#26a69a', overlay: true } as never] : []),
    });
    const painter = (color: string): string => {
      const id = `targets-painter-${seq++}`;
      registerIndicator({
        id, name: `Paints ${color}`, placement: 'onchart', plots: [{ key: 'x', type: 'line', title: 'X' }], inputs: [],
        calc: bars => ({ x: bars.map(bar => bar.close) }), barColors: ({ bars }) => bars.map(() => color),
      });
      return id;
    };
    const { chart } = mount();
    const routed = chart.addIndicator(late);
    const red = chart.addIndicator(painter('#ff0000'));
    chart.addIndicator(painter('#0000ff'));
    const colour = (): string | undefined => chart.primarySeries()!.getData()[0].color;
    expect(colour()).toBe('#0000ff');
    tick(chart, 40);
    expect(markerLayers(chart, routed)).toHaveLength(1);
    // The later study wins the candles, so moving red last hands them to red.
    expect(chart.reorderIndicator(red.id, 1)).toBe(true);
    expect(colour()).toBe('#ff0000');
  });
});

describe('the documented scale callback of a drawing layer', () => {
  it('says the same in the website and the skills reference: the layer stays on the pane it was added to', () => {
    // The paragraph or bullet that hands a layer one series' scale, with its line breaks folded.
    const said = (text: string): string =>
      text.split(/\n\s*\n|\n(?=- )/).find(block => block.includes('() => series.priceScale()'))?.replace(/\s+/g, ' ') ?? '';
    for (const text of [siteIndicators, skillIndicators]) {
      expect(said(text)).toContain('to follow one series on that series\' own pane');
      expect(said(text)).not.toContain('wherever the series goes');
    }
  });
});
