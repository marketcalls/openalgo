/**
 * Explicit pane and scale targets for a study's background shading.
 *
 * `background` used to shade one layer: the study's own pane, behind its plots.
 * A study in its own pane has regimes to state about the candles too, and a
 * study whose plots sit on two panes has one per plot. The hook can now return
 * a list of targeted columns, each naming the price pane (`overlay: true`) or a
 * declared plot (`plot: key`), and the runtime keeps one owned layer per target
 * that follows moves, scale reassignment, hiding, removal and restore, and
 * stacks predictably with the drawing and marker targets.
 *
 * The first block pins what a descriptor that names no target renders. Its
 * digests were recorded before background targets existed, so any change to
 * the default path fails here rather than in someone's chart.
 */
/// <reference types="vite/client" />
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import type { Pane, PaneRenderContext } from '../src/core/pane';
import { registerIndicator, type IndicatorDescriptor } from '../src/model/indicator-registry';
import { SMA } from '../src/indicators/trend';
import type { IndicatorApi } from '../src/model/indicator-instance';
import type { Bar } from '../src/model/bar';
import type { IPrimitive, PrimitiveRenderContext } from '../src/primitives/primitive';
import { IndicatorBackground } from '../src/primitives/indicator-background';
import { IndicatorDrawings } from '../src/primitives/indicator-draws';
import { makeCtx } from './helpers/fake-ctx';
import { fakeDocument, type FakeElement } from './helpers/fake-dom';
import changelog from '../CHANGELOG.md?raw';
import skillIndicators from '../.github/skills/openalgo-charts/references/indicators.md?raw';
import skillCore from '../.github/skills/openalgo-charts/references/core-api.md?raw';
import skillScales from '../.github/skills/openalgo-charts/references/scales-and-panes.md?raw';
import siteIndicators from '../website/pages/docs/indicators.mdx?raw';
import siteScales from '../website/pages/docs/scales-and-panes.mdx?raw';
import examples from '../website/pages/examples.mdx?raw';

const T0 = 1700000000;
const BARS: Bar[] = Array.from({ length: 40 }, (_, i) => {
  const close = 120 + 10 * Math.sin(i / 5);
  return { time: T0 + i * 60, open: close - 1, high: close + 3, low: close - 3, close };
});

const charts: Chart[] = [];
beforeAll(() => { (globalThis as { window?: unknown }).window ??= {}; });
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

function mount(): Chart {
  const document = fakeDocument();
  const el = document.createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document, pixelRatio: () => 1, shortcuts: false, timeNavigator: false, animZoom: false, animAutoscale: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(BARS);
  return chart;
}

interface ChartInternals {
  _renderContext(showTimeAxis: boolean): PaneRenderContext;
  _bottomPaneIndex(): number;
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
const owned = (study: IndicatorApi): { primitive: IPrimitive; overlay: boolean }[] =>
  (study as unknown as { renderResources(): { primitives: { primitive: IPrimitive; overlay: boolean }[] } }).renderResources().primitives;
/** SHA-256 of the JSON form, through the platform digest so the suite needs no runtime typings. */
const digest = async (value: unknown): Promise<string> => {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(value)));
  return Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('');
};

/** Every study-owned shading layer: its pane, its binding, its placement role and what it paints. */
function shading(chart: Chart, study: IndicatorApi): { pane: number; scale: string | null; overlay: boolean; ops: unknown[] }[] {
  return owned(study).filter(({ primitive }) => primitive instanceof IndicatorBackground).map(({ primitive, overlay }) => {
    const pane = paneOf(chart, primitive);
    return { pane, scale: chart.panes()[pane]?.primitiveScaleId(primitive) ?? null, overlay, ops: paint(chart, pane, primitive) };
  });
}
const placed = (chart: Chart, study: IndicatorApi) => shading(chart, study).map(({ ops: _ops, ...rest }) => rest);

/** Two states and gaps, including a warmup and a hole in the middle of a run. */
const REGIME = (bars: readonly Bar[]): (string | null)[] =>
  bars.map((_, i) => (i < 5 || i % 7 === 5 ? null : i % 7 < 3 ? 'rgba(38,166,154,0.2)' : 'rgba(239,83,80,0.2)'));

const untargetedPane: IndicatorDescriptor = {
  id: 'bg-untargeted-pane', name: 'Untargeted pane', placement: 'pane', inputs: [],
  plots: [{ key: 'osc', type: 'line', title: 'Osc' }, { key: 'alt', type: 'line', title: 'Alt' }],
  calc: bars => ({ osc: bars.map((_, i) => 30 + i), alt: bars.map((_, i) => 60 - i / 2) }),
  background: ({ bars }) => REGIME(bars),
};

const untargetedPrice: IndicatorDescriptor = {
  id: 'bg-untargeted-price', name: 'Untargeted price', placement: 'onchart', inputs: [],
  plots: [{ key: 'mid', type: 'line', title: 'Mid' }],
  calc: bars => ({ mid: bars.map(bar => (bar.open + bar.close) / 2) }),
  background: ({ bars }) => bars.map((_, i) => (i >= 10 && i < 20 ? '#123456' : null)),
};

/** Class names of what the pane draws, in the order it draws them, for the named studies' layers. */
function stackOn(studies: Record<string, IndicatorApi>, pane: Pane): string[] {
  return pane.primitives().flatMap(primitive => {
    const owner = Object.entries(studies).find(([, study]) => owned(study).some(item => item.primitive === primitive))?.[0];
    return owner === undefined ? [] : [`${owner} ${primitive.constructor.name}`];
  });
}

describe('shading that names no target', () => {
  it('keeps one unbound layer in the study pane, painted exactly as before', async () => {
    registerIndicator(untargetedPane);
    registerIndicator(untargetedPrice);
    const chart = mount();
    const pane = chart.addIndicator(untargetedPane.id);
    const price = chart.addIndicator(untargetedPrice.id);
    expect(placed(chart, pane)).toEqual([{ pane: 1, scale: null, overlay: false }]);
    expect(placed(chart, price)).toEqual([{ pane: 0, scale: null, overlay: false }]);
    const ops = [...shading(chart, pane), ...shading(chart, price)].map(layer => layer.ops);
    expect(ops.every(list => list.length > 2)).toBe(true);
    // Re-pinned when pane boundaries moved onto whole device pixels: with that
    // rounding bypassed, this op stream still hashes to the digest pinned before.
    expect(await digest(ops)).toBe('b5ffab1b50bcf7137be8bd8ac95699a8070a11afd41066eac67286a03c0410bf');
  });

  it('stacks behind the study\'s other layers where it always did', () => {
    const id = `bg-untargeted-stack-${seq++}`;
    registerIndicator({
      ...untargetedPane, id,
      draws: ({ bars }) => [{ kind: 'box', from: { time: bars[10].time, price: 40 }, to: { time: bars[20].time, price: 50 }, id: 'zone' }],
      markers: ({ bars }) => [{ time: bars[12].time, position: 'aboveBar', shape: 'circle', size: 'small', color: '#ef5350' }],
    });
    const chart = mount();
    const study = chart.addIndicator(id);
    expect(stackOn({ S: study }, chart.panes()[1])).toEqual([
      'S PaneLegend', 'S SeriesMarkers', 'S IndicatorDrawings', 'S IndicatorBackground',
    ]);
  });

  it('moves with the study, hides in place and goes with it', () => {
    const chart = mount();
    registerIndicator(untargetedPane);
    const study = chart.addIndicator(untargetedPane.id);
    const [layer] = owned(study).filter(({ primitive }) => primitive instanceof IndicatorBackground).map(({ primitive }) => primitive);
    expect(chart.moveIndicator(study.id, 0)).toBe(true);
    expect(placed(chart, study)).toEqual([{ pane: 0, scale: null, overlay: false }]);
    study.setVisible(false);
    expect(shading(chart, study).map(item => item.ops)).toEqual([[]]);
    study.setVisible(true);
    expect(owned(study).some(item => item.primitive === layer)).toBe(true);
    study.remove();
    expect(chart.panes()[0].primitives().some(primitive => primitive instanceof IndicatorBackground)).toBe(false);
  });

  it('renders a list whose one column names no target exactly like the colour list', () => {
    const id = `bg-untargeted-list-${seq++}`;
    registerIndicator({ ...untargetedPane, id, background: ({ bars }) => [{ colors: REGIME(bars) }] });
    registerIndicator(untargetedPane);
    const chart = mount();
    const legacy = chart.addIndicator(untargetedPane.id);
    const listed = chart.addIndicator(id);
    expect(placed(chart, listed)).toEqual([{ pane: listed.paneIndex, scale: null, overlay: false }]);
    expect(shading(chart, listed)[0].ops).toEqual(shading(chart, legacy)[0].ops);
  });
});

let seq = 0;

const OWN = 'rgba(1,2,3,0.25)';
const SENT = 'rgba(4,5,6,0.25)';
type Route = 'none' | 'price' | 'osc' | 'alt' | 'guide';
const ROUTES = (['none', 'price', 'osc', 'alt', 'guide'] as const).map(value => ({ label: value, value }));
const target = (route: Route): { overlay?: boolean; plot?: string } => (route === 'price' ? { overlay: true } : { plot: route });

/** A local oscillator, a second local plot for another axis, and a guide on the candles. */
const PLOTS: IndicatorDescriptor['plots'] = [
  { key: 'osc', type: 'line', title: 'Osc' },
  { key: 'alt', type: 'line', title: 'Alt' },
  { key: 'guide', type: 'line', title: 'Guide', overlay: true },
];
const CALC: IndicatorDescriptor['calc'] = bars => ({
  osc: bars.map((_, i) => 30 + i), alt: bars.map((_, i) => 500 + i), guide: bars.map(bar => bar.close),
});
const own = (bars: readonly Bar[]): (string | null)[] => bars.map((_, i) => (i < 10 ? OWN : null));
const sent = (bars: readonly Bar[]): (string | null)[] => bars.map((_, i) => (i >= 20 && i < 30 ? SENT : null));

/** Shades its own pane, and sends a second column wherever the Shade input says. */
function routedShade(): string {
  const id = `bg-routed-${seq++}`;
  registerIndicator({
    id, name: 'Routed shading', placement: 'pane', plots: PLOTS, calc: CALC,
    inputs: [{ key: 'shade', type: 'select', label: 'Shade', default: 'price', options: ROUTES }],
    background: ({ bars, settings }) => {
      const route = settings.shade as Route;
      return [{ colors: own(bars) }, ...(route === 'none' ? [] : [{ colors: sent(bars), ...target(route) }])];
    },
  });
  return id;
}

const layersOf = (study: IndicatorApi): IPrimitive[] =>
  owned(study).filter(({ primitive }) => primitive instanceof IndicatorBackground).map(({ primitive }) => primitive);
const shadingOn = (chart: Chart, paneIndex: number): IPrimitive[] =>
  chart.panes()[paneIndex].primitives().filter(primitive => primitive instanceof IndicatorBackground);
const allShading = (chart: Chart): number => chart.panes().reduce((sum, _, i) => sum + shadingOn(chart, i).length, 0);
/** The colours one layer fills with, in paint order. */
const fills = (ops: unknown[]): string[] => (ops as { type: string; fillStyle?: string }[])
  .filter(op => op.type === 'fillRect').map(op => op.fillStyle!);
const bound = (chart: Chart, study: IndicatorApi): string[] => placed(chart, study).map(layer => `${layer.pane}:${layer.scale}`);
/** A list with holes at every index `entries` leaves out, the shape a list built by index has. */
const holed = (length: number, entries: Record<number, unknown>): unknown[] => Object.assign(new Array<unknown>(length), entries);

describe('shading targets', () => {
  it('sends a price-pane column to the price pane, bound to no axis, and keeps its own column in the study pane', () => {
    const chart = mount();
    const study = chart.addIndicator(routedShade());
    expect(placed(chart, study)).toEqual([
      { pane: 1, scale: null, overlay: false },
      { pane: 0, scale: null, overlay: true },
    ]);
    expect(shading(chart, study).map(layer => [...new Set(fills(layer.ops))])).toEqual([[OWN], [SENT]]);
    // The whole height of the price pane, over the ten bars it names.
    const [, price] = shading(chart, study);
    const rects = (price.ops as { type: string; args: number[] }[]).filter(op => op.type === 'fillRect');
    const height = (chart.panes()[0] as unknown as { _layout(ctx: PaneRenderContext): { plotHeight: number } })
      ._layout((chart as unknown as ChartInternals)._renderContext(false)).plotHeight;
    expect(rects).toHaveLength(1);
    expect(rects[0].args[3]).toBe(height);
    expect(chart.panes()[0].usesScale('left')).toBe(false);
  });

  it('binds a plot target to that plot pane and effective scale', () => {
    const id = routedShade();
    const chart = mount();
    const alt = chart.addIndicator(id, { shade: 'alt' }, { plotPriceScaleIds: { alt: 'left' } });
    const guide = chart.addIndicator(id, { shade: 'guide' }, { plotPriceScaleIds: { guide: 'overlay:guide' } });
    expect(placed(chart, alt)).toEqual([
      { pane: alt.paneIndex, scale: null, overlay: false },
      { pane: alt.paneIndex, scale: 'left', overlay: false },
    ]);
    expect(placed(chart, guide)).toEqual([
      { pane: guide.paneIndex, scale: null, overlay: false },
      { pane: 0, scale: 'overlay:guide', overlay: true },
    ]);
  });

  it('follows plot and whole-study scale reassignment, and holds no axis the plot has left', () => {
    const id = routedShade();
    const chart = mount();
    const study = chart.addIndicator(id, { shade: 'alt' });
    const guide = chart.addIndicator(id, { shade: 'guide' });
    const pane = chart.panes()[study.paneIndex];
    expect(study.setPlotPriceScales({ alt: 'left' })).toBe(true);
    expect(bound(chart, study)).toEqual([`${study.paneIndex}:null`, `${study.paneIndex}:left`]);
    expect(pane.usesScale('left')).toBe(true);
    // Back on the oscillator's axis, the left column has nothing left to label.
    expect(study.setPlotPriceScales({ alt: null })).toBe(true);
    expect(bound(chart, study)).toEqual([`${study.paneIndex}:null`, `${study.paneIndex}:right`]);
    expect(pane.usesScale('left')).toBe(false);
    expect(study.setPriceScale('left')).toBe(true);
    expect(bound(chart, study)).toEqual([`${study.paneIndex}:null`, `${study.paneIndex}:left`]);
    expect(pane.usesScale('right')).toBe(false);
    expect(guide.setPriceScale('left')).toBe(true);
    expect(bound(chart, guide)).toEqual([`${guide.paneIndex}:null`, '0:right']);
    study.setSettings({ shade: 'price' });
    expect(bound(chart, study)).toEqual([`${study.paneIndex}:null`, '0:null']);
    expect(study.setPriceScale(null)).toBe(true);
    expect(bound(chart, study)).toEqual([`${study.paneIndex}:null`, '0:null']);
  });

  it('moves a column between targets when settings change and releases the layer it left', () => {
    const chart = mount();
    const study = chart.addIndicator(routedShade());
    const [local] = layersOf(study);
    study.setSettings({ shade: 'alt' });
    expect(placed(chart, study)).toEqual([
      { pane: 1, scale: null, overlay: false },
      { pane: 1, scale: 'right', overlay: false },
    ]);
    expect(shadingOn(chart, 0)).toHaveLength(0);
    study.setSettings({ shade: 'none' });
    expect(placed(chart, study)).toEqual([{ pane: 1, scale: null, overlay: false }]);
    expect(layersOf(study)).toEqual([local]);
    expect(allShading(chart)).toBe(1);
    study.setSettings({ shade: 'price' });
    expect(shadingOn(chart, 0)).toHaveLength(1);
  });

  it('hides and shows every shading layer with the study, keeping the layers', () => {
    const chart = mount();
    const study = chart.addIndicator(routedShade(), { shade: 'price' });
    const kept = layersOf(study);
    const painted = () => shading(chart, study).map(layer => layer.ops.length > 2);
    expect(painted()).toEqual([true, true]);
    study.setVisible(false);
    expect(painted()).toEqual([false, false]);
    study.setVisible(true);
    expect(painted()).toEqual([true, true]);
    expect(layersOf(study)).toEqual(kept);
  });

  it('makes a target layer hidden when the study is hidden, and shows it with the study', () => {
    const chart = mount();
    const study = chart.addIndicator(routedShade(), { shade: 'none' });
    study.setVisible(false);
    // A pass while hidden routes a column somewhere new: its layer must not paint yet.
    study.setSettings({ shade: 'price' });
    expect(placed(chart, study)).toEqual([
      { pane: 1, scale: null, overlay: false },
      { pane: 0, scale: null, overlay: true },
    ]);
    expect(shading(chart, study).map(layer => fills(layer.ops))).toEqual([[], []]);
    study.setVisible(true);
    expect(shading(chart, study).map(layer => [...new Set(fills(layer.ops))])).toEqual([[OWN], [SENT]]);
  });

  it('keeps price-pane shading on the price pane through moves and releases it with the study or its pane', () => {
    const id = routedShade();
    const chart = mount();
    const study = chart.addIndicator(id, { shade: 'price' });
    const other = chart.addIndicator(id, { shade: 'alt' });
    expect(chart.moveIndicator(other.id, chart.panes().length)).toBe(true);
    expect(placed(chart, other).map(layer => layer.pane)).toEqual([other.paneIndex, other.paneIndex]);
    expect(chart.moveIndicator(study.id, other.paneIndex)).toBe(true);
    expect(placed(chart, study).map(layer => layer.pane)).toEqual([other.paneIndex, 0]);
    expect(shadingOn(chart, 0)).toHaveLength(1);
    const guide = chart.addIndicator(id, { shade: 'guide' });
    expect(chart.moveIndicator(guide.id, other.paneIndex)).toBe(true);
    expect(placed(chart, guide).map(layer => layer.pane)).toEqual([other.paneIndex, 0]);
    const removable = chart.addIndicator(id, { shade: 'price' });
    expect(shadingOn(chart, 0)).toHaveLength(3);
    expect(chart.removePane(removable.paneIndex)).toBe(true);
    expect(shadingOn(chart, 0)).toHaveLength(2);
    study.remove();
    guide.remove();
    expect(shadingOn(chart, 0)).toHaveLength(0);
    other.remove();
    expect(allShading(chart)).toBe(0);
  });

  it('stays on the price pane when a chart that allows it moves the price pane below its studies', () => {
    const document = fakeDocument();
    const chart = new Chart(document.createElement('div') as unknown as FakeElement, {
      document, pixelRatio: () => 1, shortcuts: false, timeNavigator: false, animZoom: false, animAutoscale: false,
      movablePrimaryPane: true, raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    });
    charts.push(chart);
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData(BARS);
    const study = chart.addIndicator(routedShade(), { shade: 'price' });
    expect(chart.setPrimaryPaneIndex(1)).toBe(true);
    expect(placed(chart, study)).toEqual([
      { pane: study.paneIndex, scale: null, overlay: false },
      { pane: chart.primaryPaneIndex(), scale: null, overlay: true },
    ]);
    expect(chart.primaryPaneIndex()).toBe(1);
    // A layer made after the move lands where the price pane went.
    const later = chart.addIndicator(routedShade(), { shade: 'price' });
    expect(placed(chart, later)[1].pane).toBe(chart.primaryPaneIndex());
  });

  it('restores routed shading from saved state with its bindings', () => {
    const id = routedShade();
    const chart = mount();
    chart.addIndicator(id, { shade: 'price' });
    chart.addIndicator(id, { shade: 'alt' }, { plotPriceScaleIds: { alt: 'left' } });
    const state = JSON.parse(JSON.stringify(chart.getState()));
    expect(chart.restoreState(state)).toMatchObject({ applied: true, indicators: 2 });
    const [price, alt] = chart.indicators();
    expect(placed(chart, price)).toEqual([
      { pane: price.paneIndex, scale: null, overlay: false },
      { pane: 0, scale: null, overlay: true },
    ]);
    expect(placed(chart, alt)).toEqual([
      { pane: alt.paneIndex, scale: null, overlay: false },
      { pane: alt.paneIndex, scale: 'left', overlay: false },
    ]);
    expect(allShading(chart)).toBe(4);
  });

  it('gives each instance and each chart layers of their own', () => {
    const id = routedShade();
    const one = mount();
    const two = mount();
    const first = one.addIndicator(id, { shade: 'price' });
    const second = one.addIndicator(id, { shade: 'price' });
    const elsewhere = two.addIndicator(id, { shade: 'price' });
    const kept = [layersOf(second), layersOf(elsewhere)];
    expect(shadingOn(one, 0)).toHaveLength(2);
    first.setSettings({ shade: 'none' });
    expect(shadingOn(one, 0)).toEqual([kept[0][1]]);
    first.remove();
    expect([layersOf(second), layersOf(elsewhere)]).toEqual(kept);
    expect(shadingOn(two, 0)).toEqual([kept[1][1]]);
  });

  it('creates a target layer only once its column has entries, and keeps it through a pass that shades nothing', () => {
    const id = `bg-lazy-${seq++}`;
    let columns: (bars: readonly Bar[]) => unknown[] = () => [{ colors: [], overlay: true }];
    registerIndicator({ id, name: 'Lazy', placement: 'pane', plots: PLOTS, calc: CALC, inputs: [], background: ({ bars }) => columns(bars) as never });
    const chart = mount();
    const study = chart.addIndicator(id);
    expect(layersOf(study)).toHaveLength(0);
    columns = bars => [{ colors: sent(bars), overlay: true }];
    study.setSettings({});
    chart.primarySeries()!.update({ time: T0 + 40 * 60, open: 120, high: 123, low: 117, close: 121 });
    chart.indicators();
    const [layer] = layersOf(study);
    expect(placed(chart, study)).toEqual([{ pane: 0, scale: null, overlay: true }]);
    columns = bars => [{ colors: bars.map(() => null), overlay: true }];
    chart.primarySeries()!.update({ time: T0 + 41 * 60, open: 120, high: 123, low: 117, close: 121 });
    chart.indicators();
    expect(layersOf(study)).toEqual([layer]);
    expect(fills(shading(chart, study)[0].ops)).toEqual([]);
    columns = () => [{ colors: [], overlay: true }];
    chart.primarySeries()!.update({ time: T0 + 42 * 60, open: 120, high: 123, low: 117, close: 121 });
    chart.indicators();
    expect(layersOf(study)).toEqual([layer]);
    // An empty list returns no target at all, which releases it.
    columns = () => [];
    chart.primarySeries()!.update({ time: T0 + 43 * 60, open: 120, high: 123, low: 117, close: 121 });
    chart.indicators();
    expect(layersOf(study)).toHaveLength(0);
    expect(allShading(chart)).toBe(0);
  });

  it.each([
    ['an unknown plot', [{ colors: ['#fff'], plot: 'missing' }], /declared plot or the price pane/],
    ['a plot and the price pane at once', [{ colors: ['#fff'], plot: 'alt', overlay: true }], /declared plot or the price pane/],
    ['the price pane twice', [{ colors: ['#fff'], overlay: true }, { colors: ['#000'], overlay: true }], /one column per target/],
    ['one plot twice', [{ colors: ['#fff'], plot: 'alt' }, { colors: ['#000'], plot: 'alt' }], /one column per target/],
    ['two columns with no target', [{ colors: ['#fff'] }, { colors: ['#000'] }], /one column per target/],
    ['a column without colours', [{ overlay: true }], /colours or a list of columns/],
    ['colours mixed with columns', ['#fff', { colors: ['#000'], overlay: true }], /colours or a list of columns/],
    // Holes are what `every` and `some` skip, so the check has to visit every index.
    ['a hole before a column', holed(2, { 1: { colors: ['#fff'], overlay: true } }), /colours or a list of columns/],
    ['a hole between columns', holed(3, { 0: { colors: ['#fff'] }, 2: { colors: ['#000'], overlay: true } }), /colours or a list of columns/],
  ])('rejects %s before any shading layer changes', (_, bad, message) => {
    const id = `bg-invalid-${seq++}`;
    registerIndicator({
      id, name: 'Invalid', placement: 'pane', plots: PLOTS, calc: CALC,
      inputs: [{ key: 'bad', type: 'boolean', label: 'Bad', default: true }],
      background: ({ bars, settings }) => (settings.bad === true ? bad : [{ colors: own(bars) }, { colors: sent(bars), overlay: true }]) as never,
    });
    const chart = mount();
    expect(() => chart.addIndicator(id)).toThrow(message);
    expect(chart.panes()).toHaveLength(1);
    expect(allShading(chart)).toBe(0);
    const study = chart.addIndicator(id, { bad: false });
    const before = shading(chart, study);
    const layers = layersOf(study);
    study.setSettings({ bad: true });
    expect(study.dataStatus()?.state).toBe('error');
    expect(layersOf(study)).toEqual(layers);
    expect(shading(chart, study)).toEqual(before);
  });

  it('keeps the outputs synced before a rejected shading target and holds back the ones after it', () => {
    const id = `bg-partial-${seq++}`;
    registerIndicator({
      id, name: 'Partial pass', placement: 'pane', plots: PLOTS, inputs: [{ key: 'bad', type: 'boolean', label: 'Bad', default: false }],
      calc: (bars, settings) => ({ ...CALC(bars, settings, {}), osc: bars.map(() => (settings.bad === true ? 2 : 1)) }),
      draws: ({ bars, settings }) => [{ kind: 'box', from: { time: bars[10].time, price: 40 }, to: { time: bars[20].time, price: 35 },
        id: settings.bad === true ? 'next' : 'plain' }],
      background: ({ bars, settings }) => [{ colors: own(bars) }, { colors: sent(bars), ...(settings.bad === true ? { plot: 'missing' } : { overlay: true }) }],
      barColors: ({ bars, settings }) => bars.map(() => (settings.bad === true ? '#ff0000' : '#00ff00')),
    });
    const chart = mount();
    const study = chart.addIndicator(id);
    const before = shading(chart, study);
    const shapes = (): (string | undefined)[] => owned(study).filter(({ primitive }) => primitive instanceof IndicatorDrawings)
      .flatMap(({ primitive }) => (primitive as unknown as { _items: { id?: string }[] })._items.map(item => item.id));
    expect(shapes()).toEqual(['plain']);
    study.setSettings({ bad: true });
    expect(study.dataStatus()?.state).toBe('error');
    expect(shading(chart, study)).toEqual(before);
    // What the documented pass order syncs before shading is applied and not rolled back...
    expect(study.values().osc[0]).toBe(2);
    expect(shapes()).toEqual(['next']);
    // ...and the bar colours, synced after it, wait for a pass that succeeds.
    expect(chart.primarySeries()!.getData()[0].color).toBe('#00ff00');
  });

  it('clears routed shading while a study it reads is unavailable', () => {
    registerIndicator(SMA);
    const id = `bg-consumer-${seq++}`;
    registerIndicator({
      ...SMA, id, name: 'Routed consumer', placement: 'pane',
      background: ({ bars }) => [{ colors: sent(bars), overlay: true }, { colors: own(bars), plot: 'ma' }],
    });
    const chart = mount();
    const producer = chart.addIndicator('sma', { length: 2 });
    const consumer = chart.addIndicator(id, { length: 2, source: { kind: 'indicator', instanceId: producer.id, plotKey: 'ma' } });
    expect(placed(chart, consumer)).toEqual([
      { pane: 0, scale: null, overlay: true },
      { pane: consumer.paneIndex, scale: 'right', overlay: false },
    ]);
    producer.remove();
    consumer.values();
    expect(consumer.dataStatus()?.state).toBe('error');
    expect(shading(chart, consumer).map(layer => fills(layer.ops))).toEqual([[], []]);
  });
});

describe('shading stacked with the other targets', () => {
  it('follows the study\'s marks and shapes: its own column, then the price pane, then the plots', () => {
    const id = `bg-order-${seq++}`;
    registerIndicator({
      id, name: 'Every output', placement: 'onchart', plots: PLOTS, calc: CALC, inputs: [],
      markers: ({ bars }) => [
        { time: bars[5].time, position: 'aboveBar', shape: 'circle', size: 'small', color: '#888888' },
        { time: bars[15].time, position: 'atPrice', price: 118, shape: 'circle', size: 'small', color: '#26a69a', plot: 'guide' },
      ],
      draws: ({ bars }) => [
        { kind: 'box', from: { time: bars[2].time, price: 124 }, to: { time: bars[8].time, price: 112 }, id: 'own' },
        { kind: 'box', from: { time: bars[10].time, price: 124 }, to: { time: bars[20].time, price: 112 }, id: 'price', overlay: true },
      ],
      // Returned plot first, price pane last: the layers still stack in target order.
      background: ({ bars }) => [{ colors: sent(bars), plot: 'guide' }, { colors: own(bars) }, { colors: sent(bars), overlay: true }],
    });
    const chart = mount();
    const study = chart.addIndicator(id);
    const kinds = owned(study).filter(({ primitive }) => !['PaneLegend', 'LineSeries'].includes(primitive.constructor.name))
      .map(({ primitive, overlay }) => `${primitive.constructor.name}${overlay ? ' overlay' : ''}`);
    expect(kinds).toEqual([
      'SeriesMarkers', 'SeriesMarkers overlay', 'IndicatorDrawings', 'IndicatorDrawings overlay',
      'IndicatorBackground', 'IndicatorBackground overlay', 'IndicatorBackground overlay',
    ]);
    expect(placed(chart, study)).toEqual([
      { pane: 0, scale: null, overlay: false },
      { pane: 0, scale: null, overlay: true },
      { pane: 0, scale: 'right', overlay: true },
    ]);
    // All of it on one pane, drawn in that order; shading paints behind the series whatever its slot.
    expect(stackOn({ S: study }, chart.panes()[0]).filter(layer => !layer.endsWith('PaneLegend'))).toEqual([
      'S SeriesMarkers', 'S SeriesMarkers', 'S IndicatorDrawings', 'S IndicatorDrawings',
      'S IndicatorBackground', 'S IndicatorBackground', 'S IndicatorBackground',
    ]);
    expect(chart.panes()[0].primitives().filter(primitive => primitive instanceof IndicatorBackground).every(primitive => primitive.zOrder() === 'bottom')).toBe(true);
  });

  it('keeps study order on the price pane when a live pass sends a column there for the first time', () => {
    const make = (name: string, from: number): string => {
      const id = `bg-late-${name}-${seq++}`;
      registerIndicator({
        id, name, placement: 'pane', plots: PLOTS, calc: CALC, inputs: [],
        background: ({ bars }) => (bars.length >= from ? [{ colors: sent(bars), overlay: true }] : []),
      });
      return id;
    };
    const chart = mount();
    const studies = { A: chart.addIndicator(make('A', 41)), B: chart.addIndicator(make('B', 0)) };
    expect(stackOn(studies, chart.panes()[0])).toEqual(['B IndicatorBackground']);
    chart.primarySeries()!.update({ time: T0 + 40 * 60, open: 120, high: 123, low: 117, close: 121 });
    chart.indicators();
    // A was added first, so its column paints first and B's covers it where they overlap.
    expect(stackOn(studies, chart.panes()[0])).toEqual(['A IndicatorBackground', 'B IndicatorBackground']);
    expect(chart.indicators().map(study => study.id)).toEqual([studies.A.id, studies.B.id]);
  });

  it('leaves an untargeted study\'s late shading where it lands when a routed study restacks on the same pass', () => {
    const untargeted = (from: number): string => {
      const id = `bg-untargeted-beside-${seq++}`;
      registerIndicator({ ...untargetedPrice, id, background: context => (context.bars.length >= from ? untargetedPrice.background!(context) : []) });
      return id;
    };
    const routed = `bg-routed-beside-${seq++}`;
    registerIndicator({
      id: routed, name: 'Routed late', placement: 'pane', plots: PLOTS, calc: CALC, inputs: [],
      background: ({ bars }) => (bars.length > 40 ? [{ colors: sent(bars), overlay: true }] : []),
    });
    const run = (withRouted: boolean): string[] => {
      const chart = mount();
      const studies: Record<string, IndicatorApi> = { U: chart.addIndicator(untargeted(41)), V: chart.addIndicator(untargeted(0)) };
      if (withRouted) studies.R = chart.addIndicator(routed);
      chart.primarySeries()!.update({ time: T0 + 40 * 60, open: 120, high: 123, low: 117, close: 121 });
      chart.indicators();
      return stackOn(studies, chart.panes()[0]);
    };
    // What an untargeted study has always done: its late layer lands on top of the pane.
    const base = run(false);
    expect(base).toEqual(['U PaneLegend', 'V PaneLegend', 'V IndicatorBackground', 'U IndicatorBackground']);
    expect(run(true)).toEqual([...base, 'R IndicatorBackground']);
  });
});

describe('the documented background targets', () => {
  // The changelog heading the list form is described under: Unreleased until a release names it.
  const release = changelog.split(/\n## /).find(entry => entry.includes('IndicatorBackgroundSpec'))?.split('\n')[0] ?? '';
  const marker = release === 'Unreleased' ? 'unreleased' : release;
  const anchor = `background-targets-${marker.replace(/[^0-9a-z]/g, '')}`;
  const docs = { skillIndicators, skillCore, skillScales, siteIndicators, siteScales, examples };

  it('mark their section with the release that ships them, and unreleased until one does', () => {
    expect(release).not.toBe('');
    for (const text of [skillIndicators, siteIndicators]) expect(text).toContain(`\n### Background targets (${marker})\n`);
  });

  it('send every page that mentions the list form to that section by the anchor it has', () => {
    for (const [name, text] of Object.entries(docs)) {
      const links = text.match(/#background-targets[\w-]*/g) ?? [];
      expect(links.length, name).toBeGreaterThan(0);
      expect(links.filter(link => link !== `#${anchor}`), name).toEqual([]);
    }
  });
});
