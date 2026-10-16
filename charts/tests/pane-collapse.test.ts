/**
 * Pane collapse: a lower pane folds to a header strip and keeps everything it
 * holds. The strip is layout, not state, so expanding brings back exactly the
 * height the pane had, and a saved layout reopens folded the same way.
 *
 * Every test runs a measured chart with a synchronous frame, and drives the
 * real pointer handlers, because the defects this guards against (a drawing
 * selectable through a strip, a ladder grabbed on a pane with no ladder) only
 * show up on the input path.
 */
import { describe, it, expect, beforeAll, afterEach } from 'vitest';
import '../src/indicators/index';
import { Chart, type ChartOptions, type ContextMenuEvent, type CrosshairMoveEvent, type ChartClickEvent } from '../src/core/chart';
import { InvalidationLevel } from '../src/core/invalidate-mask';
import { parsePaneState } from '../src/model/chart-state';
import { ChartObjects } from '../src/model/chart-objects';
import { DrawingController } from '../src/draw/index';
import { LogoWatermark } from '../src/primitives/watermark';
import { TimeNavigator } from '../src/primitives/time-navigator';
import { PaneLegend } from '../src/primitives/pane-legend';
import type { IPrimitive, PrimitiveRenderContext } from '../src/primitives/primitive';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { DataLayer } from '../src/model/data-layer';
import { darkTheme } from '../src/theme';
import { parseWorkspaceDocument } from '../src/workspace/index';
import { contextMenuEntries, type MenuItem } from '../src/widget/dialogs/context-menu';
import type { WidgetContext } from '../src/widget/context';
import { createWidget, type Widget } from '../src/widget/index';
import { fakeWidgetDocument, fakeContainer, ensureWindowGlobal } from './helpers/fake-dom-widget';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import { makeCtx, type RecordingContext } from './helpers/fake-ctx';
import { workspaceFixture } from './helpers/workspace-fixture';
import type { Bar } from '../src/model/bar';

const W = 800;
const H = 600;
/** The default 18 px legend row with its 6 px inset above and below. */
const STRIP = 30;
const TIME_AXIS = 22;

beforeAll(() => {
  // Pointer listeners are wired only when a `window` exists.
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

const charts: Chart[] = [];
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

const bars = (n: number, from = 0): Bar[] => Array.from({ length: n }, (_, k) => {
  const i = k + from;
  const c = 100 + Math.sin(i / 4) * 5 + i * 0.05;
  return { time: 1700000000 + i * 60, open: c - 0.5, high: c + 1, low: c - 1, close: c, volume: 10 + i };
});

function makeChart(options: Partial<ChartOptions> = {}): { chart: Chart; el: FakeElement } {
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: (cb: (t: number) => void) => { cb(0); return 1; }, cancel: () => {} },
    ...options,
  });
  chart.applySize(W, H);
  charts.push(chart);
  return { chart, el };
}

/** The price pane, an RSI pane and a MACD pane: weights 1, 0.32 and 0.32. */
function stacked(options: Partial<ChartOptions> = {}) {
  const made = makeChart(options);
  const price = made.chart.addSeries('candlestick');
  price.setData(bars(120));
  const rsi = made.chart.addIndicator('rsi');
  const macd = made.chart.addIndicator('macd');
  return { ...made, price, rsi, macd };
}

/** Pane heights as the DOM boxes carry them, which is what hit testing reads. */
const heights = (chart: Chart): number[] =>
  chart.panes().map((pane) => parseFloat(pane.element.style.flex.split(' ')[2]));
const tops = (chart: Chart): number[] => {
  let top = 0;
  return heights(chart).map((h) => { const t = top; top += h; return t; });
};
const sum = (values: number[]): number => values.reduce((a, b) => a + b, 0);
/**
 * Heights once every boundary between panes is moved onto a whole pixel, as
 * the chart lays panes out at a pixel ratio of 1. The outer edge stays put.
 */
const onPixels = (shares: number[]): number[] => {
  let top = 0, running = 0;
  return shares.map((share, i) => {
    running += share;
    const bottom = i === shares.length - 1 ? running : Math.round(running);
    const height = bottom - top;
    top = bottom;
    return height;
  });
};
const expectHeights = (actual: number[], expected: number[]): void => {
  expect(actual).toHaveLength(expected.length);
  actual.forEach((h, i) => expect(h, `pane ${i}`).toBeCloseTo(expected[i], 9));
};
const last = <T>(values: readonly T[]): T | undefined => values[values.length - 1];
const fullFrame = (chart: Chart): void => chart.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
const recorder = (ctx: CanvasRenderingContext2D): RecordingContext => ctx as unknown as RecordingContext;
const press = (el: FakeElement, x: number, y: number, toX = x, toY = y): void => {
  el.dispatch('pointerdown', pointer('down', x, y));
  if (toX !== x || toY !== y) el.dispatch('pointermove', pointer('move', toX, toY));
  el.dispatch('pointerup', pointer('up', toX, toY));
};
const hover = (el: FakeElement, x: number, y: number): void => el.dispatch('pointermove', pointer('move', x, y, { buttons: 0 }));
const touch = (el: FakeElement, type: 'down' | 'move' | 'up', id: number, x: number, y: number): void =>
  el.dispatch(`pointer${type}`, pointer(type, x, y, { pointerType: 'touch', pointerId: id }));
const paneHolds = (chart: Chart, index: number, type: abstract new (...args: never[]) => unknown): boolean =>
  chart.panes()[index].primitives().some((primitive) => primitive instanceof type);
/** Where one of a row's controls sits, in container px, once the row has painted its buttons. */
const rowControl = (chart: Chart, legend: PaneLegend, pane: number, action: string): { x: number; y: number } => {
  const buttons = (legend as unknown as { _buttons: { id: string; x: number; y: number }[] })._buttons;
  const button = buttons.find((b) => b.id.endsWith('::' + action));
  expect(button).toBeDefined();
  return { x: button!.x + 8, y: tops(chart)[pane] + button!.y + 8 };
};
/** Hover the row so its buttons appear, then press one of them: the collapse control unless told otherwise. */
const pressControl = (chart: Chart, el: FakeElement, legend: PaneLegend, pane: number, action = 'collapse'): void => {
  hover(el, 20, tops(chart)[pane] + 15);
  const first = rowControl(chart, legend, pane, action);
  hover(el, first.x, first.y);
  const { x, y } = rowControl(chart, legend, pane, action);
  hover(el, x, y);
  press(el, x, y);
};
const texts = (ctx: CanvasRenderingContext2D): string[] =>
  recorder(ctx).ops.filter((op) => op.type === 'fillText').map((op) => String(op.text));

describe('collapsing a pane', () => {
  it('lays it out as a header strip and gives its height to the open panes', () => {
    const { chart } = stacked();
    const events: unknown[] = [];
    chart.on('paneCollapsed', (e) => events.push(e));
    expect(chart.setPaneCollapsed(1, true)).toBe(true);
    expect(chart.paneCollapsed(1)).toBe(true);
    expect(events).toEqual([{ paneIndex: 1, collapsed: true }]);
    const h = heights(chart);
    expect(h[1]).toBe(STRIP);
    expectHeights(h, onPixels([(H - STRIP) / 1.32, STRIP, ((H - STRIP) * 0.32) / 1.32]));
    expect(sum(h)).toBeCloseTo(H, 9);
    // The strip is layout: the weight it will expand back to is untouched.
    expect(chart.paneWeight(1)).toBe(0.32);
  });

  it('expands back to exactly the height it had', () => {
    const { chart } = stacked();
    chart.setPaneWeight(1, 0.5);
    const before = chart.panes().map((pane) => pane.element.style.flex);
    chart.setPaneCollapsed(1, true);
    expect(heights(chart)[1]).toBe(STRIP);
    const events: unknown[] = [];
    chart.on('paneCollapsed', (e) => events.push(e));
    expect(chart.setPaneCollapsed(1, false)).toBe(true);
    expect(events).toEqual([{ paneIndex: 1, collapsed: false }]);
    expect(chart.panes().map((pane) => pane.element.style.flex)).toEqual(before);
    expect(chart.paneWeight(1)).toBe(0.5);
  });

  it('keeps pane 0 open and refuses what it cannot do', () => {
    const { chart } = stacked();
    let fired = 0;
    chart.on('paneCollapsed', () => { fired++; });
    expect(chart.setPaneCollapsed(0, true)).toBe(false);
    expect(chart.setPaneCollapsed(3, true)).toBe(false);
    expect(chart.setPaneCollapsed(-1, true)).toBe(false);
    expect(chart.setPaneCollapsed(1, 'yes' as unknown as boolean)).toBe(false);
    expect(chart.setPaneCollapsed(1, false)).toBe(false);
    expect(chart.setPaneCollapsed(1, true)).toBe(true);
    expect(chart.setPaneCollapsed(1, true)).toBe(false);
    expect(fired).toBe(1);
    expect(chart.paneCollapsed(0)).toBe(false);
    expect(chart.paneCollapsed(9)).toBe(false);
  });

  it('stores a weight set while collapsed and uses it on expand', () => {
    const { chart } = stacked();
    chart.setPaneCollapsed(1, true);
    const folded = heights(chart);
    chart.setPaneWeight(1, 0.64);
    expect(heights(chart)).toEqual(folded);
    chart.setPaneCollapsed(1, false);
    const total = 1 + 0.64 + 0.32;
    expectHeights(heights(chart), onPixels([H / total, (H * 0.64) / total, (H * 0.32) / total]));
  });
});

describe('the strip height', () => {
  it('is one legend row, and follows the legend icon size', () => {
    const { chart } = stacked();
    chart.setPaneCollapsed(1, true);
    chart.setLegendIconSize(28);
    // A 28 px button needs a 30 px row, plus the same 6 px inset either side.
    expect(heights(chart)[1]).toBe(42);
    expect(sum(heights(chart))).toBeCloseTo(H, 9);
  });
});

describe('what a collapsed pane keeps', () => {
  it('keeps taking data and recomputing its studies', () => {
    const { chart, price, rsi } = stacked();
    chart.setPaneCollapsed(1, true);
    const before = rsi.values().rsi.length;
    const last = bars(1, 120)[0];
    price.update({ ...last, close: last.close + 8, high: last.close + 9 });
    chart.indicators();
    const after = rsi.values().rsi;
    expect(after).toHaveLength(before + 1);
    expect(after[after.length - 1]).toBeGreaterThan(50);
    // Open again, the scale is measured for the full pane with the new values in it.
    chart.setPaneCollapsed(1, false);
    const scale = chart.panes()[1].priceScale;
    expect(scale.height).toBeCloseTo(onPixels([H / 1.64, (H * 0.32) / 1.64, (H * 0.32) / 1.64])[1], 9);
    expect(scale.priceRange().max).toBeGreaterThanOrEqual(after[after.length - 1] as number);
  });

  it('neither paints nor hit-tests what the pane holds until it expands', () => {
    const { chart, el } = stacked();
    let painted = 0;
    const probe: IPrimitive = {
      zOrder: () => 'normal',
      draw: () => { painted++; },
      hitTest: () => ({ externalId: 'probe', zOrder: 'normal', distance: 0 }),
    };
    chart.addPrimitive(probe, 1);
    const hovered: unknown[] = [];
    chart.on('hover', (e) => hovered.push((e as { id: string | null }).id));

    chart.setPaneCollapsed(1, true);
    painted = 0;
    fullFrame(chart);
    expect(painted).toBe(0);
    hover(el, 600, tops(chart)[1] + 15);
    expect(hovered).not.toContain('probe');
    const clicks: ChartClickEvent[] = [];
    chart.on('click', (e) => clicks.push(e as ChartClickEvent));
    press(el, 600, tops(chart)[1] + 15);
    expect(last(clicks)).toMatchObject({ id: null, paneIndex: 1, price: null });

    chart.setPaneCollapsed(1, false);
    expect(painted).toBeGreaterThan(0);
    hover(el, 600, tops(chart)[1] + 40);
    expect(hovered).toContain('probe');
  });

  it('keeps a drawing on the pane, out of reach while collapsed', () => {
    const { chart, el } = stacked();
    const draw = new DrawingController(chart);
    const line = draw.add({ tool: 'horizontal-line', paneIndex: 1, style: {}, points: [{ time: bars(1, 60)[0].time, price: 50 }] });
    const at = (): number => tops(chart)[1] + chart.panes()[1].priceToY(50);

    press(el, 500, at());
    expect(draw.selection()).toEqual([line.id]);
    draw.select(null);

    chart.setPaneCollapsed(1, true);
    expect(at() - tops(chart)[1]).toBeLessThan(STRIP);
    press(el, 500, at());
    expect(draw.selection()).toEqual([]);
    // Placing a tool on the strip places nothing: there is no price there.
    draw.setTool('horizontal-line');
    press(el, 500, tops(chart)[1] + 12);
    draw.setTool(null);
    expect(draw.drawings()).toHaveLength(1);
    expect(draw.get(line.id)?.points).toEqual(line.points);

    chart.setPaneCollapsed(1, false);
    press(el, 500, at());
    expect(draw.selection()).toEqual([line.id]);
    draw.destroy();
  });

  it('keeps the first legend row in the strip, with the control that expands it', () => {
    const { chart, el, rsi } = stacked();
    const legend = rsi.legend()!;
    expect(legend.options().actions).toContain('collapse');
    chart.setPaneCollapsed(1, true);
    expect(legend.options().collapsed).toBe(true);

    const top = recorder(chart.panes()[1].top.ctx);
    top.ops.length = 0;
    fullFrame(chart);
    expect(top.ops.some((op) => op.type === 'fillText' && op.text === 'RSI')).toBe(true);

    // The row's readings follow the crosshair, so the buttons settle once the
    // pointer is over them: find the control, move onto it, and find it again.
    const control = (): { x: number; y: number } => {
      const buttons = (legend as unknown as { _buttons: { id: string; x: number; y: number }[] })._buttons;
      const button = buttons.find((b) => b.id.endsWith('::collapse'));
      expect(button).toBeDefined();
      return { x: button!.x + 8, y: tops(chart)[1] + button!.y + 8 };
    };
    hover(el, 20, tops(chart)[1] + 15);
    hover(el, control().x, control().y);
    const { x, y } = control();
    hover(el, x, y);
    press(el, x, y);
    expect(chart.paneCollapsed(1)).toBe(false);
    expect(legend.options().collapsed).toBe(false);
  });

  it('draws no plot and no price ladder on a strip, and routes no axis gesture to it', () => {
    const { chart, el } = stacked();
    chart.setPaneCollapsed(1, true);
    expect(chart.priceAxisLayout(1)).toEqual([]);
    expect(chart.priceAxisLayout(2)).not.toEqual([]);

    const strip = recorder(chart.panes()[1].base.ctx);
    const open = recorder(chart.panes()[2].base.ctx);
    strip.ops.length = 0;
    open.ops.length = 0;
    fullFrame(chart);
    // No ladder labels, and no strokes at all: no series, grid or level lines.
    expect(strip.ops.filter((op) => op.type === 'fillText')).toEqual([]);
    expect(strip.ops.filter((op) => op.type === 'stroke')).toEqual([]);
    expect(open.ops.filter((op) => op.type === 'fillText').length).toBeGreaterThan(0);
    expect(open.ops.filter((op) => op.type === 'stroke').length).toBeGreaterThan(0);

    const scale = chart.panes()[1].priceScale;
    const range = scale.priceRange();
    const auto = scale.autoScale;
    const y = tops(chart)[1] + 10;
    press(el, W - 20, y, W - 20, y + 15);
    expect(scale.autoScale).toBe(auto);
    expect(scale.priceRange()).toEqual(range);
  });

  it('reports no price and no series for pointer events over a strip', () => {
    const { chart, el, rsi } = stacked();
    chart.setPaneCollapsed(1, true);
    const y = tops(chart)[1] + 15;
    // Right on the RSI line as the strip's scale would place it, clear of the
    // legend row: an open pane reports the study there.
    const x = 600;
    const value = rsi.values().rsi[Math.round(chart.timeScale.xToIndex(x))] as number;
    const onLine = tops(chart)[1] + chart.panes()[1].priceScale.priceToY(value);
    expect(onLine - tops(chart)[1]).toBeLessThan(STRIP);

    const menus: ContextMenuEvent[] = [];
    chart.on('contextmenu', (e) => menus.push(e as ContextMenuEvent));
    for (const [px, py] of [[x, onLine], [W - 20, y]]) {
      el.dispatch('contextmenu', { clientX: px, clientY: py, defaultPrevented: false, preventDefault() {} });
    }
    expect(menus.map((e) => [e.paneIndex, e.price, e.target.kind])).toEqual([[1, null, 'empty'], [1, null, 'empty']]);

    const moves: CrosshairMoveEvent[] = [];
    chart.on('crosshair:move', (e) => moves.push(e as CrosshairMoveEvent));
    const stripTop = recorder(chart.panes()[1].top.ctx);
    const openTop = recorder(chart.panes()[2].top.ctx);
    stripTop.ops.length = 0;
    openTop.ops.length = 0;
    hover(el, 500, y);
    expect(last(moves)).toMatchObject({ paneIndex: 1, price: null });
    expect(last(moves)?.time).not.toBeNull();
    // The crosshair's dashed lines cross the open panes, never the strip.
    expect(stripTop.ops.some((op) => op.type === 'setLineDash')).toBe(false);
    expect(openTop.ops.some((op) => op.type === 'setLineDash')).toBe(true);

    // A drag that starts on the strip pans time only; its scale stays where it was.
    const scale = chart.panes()[1].priceScale;
    const range = scale.priceRange();
    const view = chart.getVisibleLogicalRange();
    press(el, 500, y - 5, 470, y + 10);
    expect(chart.getVisibleLogicalRange()).not.toEqual(view);
    expect(scale.priceRange()).toEqual(range);
  });

  it('pans time but leaves a strip scale alone under a two-finger drag', () => {
    const { chart, el } = stacked();
    chart.setPaneCollapsed(1, true);
    const scale = chart.panes()[1].priceScale;
    const range = { ...scale.priceRange() };
    const auto = scale.autoScale;
    const view = chart.getVisibleLogicalRange();
    const y = tops(chart)[1] + 12;
    touch(el, 'down', 1, 400, y);
    touch(el, 'down', 2, 600, y);
    touch(el, 'move', 1, 360, y + 10);
    touch(el, 'move', 2, 560, y + 10);
    touch(el, 'up', 1, 360, y + 10);
    touch(el, 'up', 2, 560, y + 10);
    expect(chart.getVisibleLogicalRange()).not.toEqual(view);
    expect(scale.autoScale).toBe(auto);
    expect(scale.priceRange()).toEqual(range);
  });

  it('maps no price to or from a strip, the way its pointer events report none', () => {
    const { chart } = stacked();
    const open = { toY: chart.priceToCoordinate(50, 1), toPrice: chart.coordinateToPrice(tops(chart)[1] + 40, 1) };
    expect(open.toY).not.toBeNull();
    expect(open.toPrice).not.toBeNull();
    chart.setPaneCollapsed(1, true);
    expect(chart.priceToCoordinate(50, 1)).toBeNull();
    expect(chart.coordinateToPrice(tops(chart)[1] + 10, 1)).toBeNull();
    // The panes that are still open map as before.
    expect(chart.priceToCoordinate(100, 0)).not.toBeNull();
    expect(chart.coordinateToPrice(tops(chart)[2] + 40, 2)).not.toBeNull();
    // Maximized, the pane is whole again and so is its mapping.
    chart.maximizePane(1);
    expect(chart.priceToCoordinate(50, 1)).not.toBeNull();
    chart.maximizePane(1);
    chart.setPaneCollapsed(1, false);
    expect(chart.priceToCoordinate(50, 1)).toBeCloseTo(open.toY!, 9);
  });

  it('nudges no drawing on a strip by a screen distance the strip cannot show', () => {
    const { chart } = stacked();
    const draw = new DrawingController(chart);
    const line = draw.add({ tool: 'horizontal-line', paneIndex: 1, style: {}, points: [{ time: bars(1, 60)[0].time, price: 50 }] });
    chart.setPaneCollapsed(1, true);
    // Ten strip pixels are a third of a 30 px scale: a jump nobody would see.
    draw.nudge([line.id], 0, 10);
    expect(draw.get(line.id)?.points[0].price).toBe(50);
    chart.setPaneCollapsed(1, false);
    draw.nudge([line.id], 0, 10);
    expect(draw.get(line.id)?.points[0].price).toBeLessThan(50);
    draw.destroy();
  });
});

describe('collapsing the bottom pane', () => {
  it('keeps the time axis at the foot of the chart, under the strip', () => {
    const { chart, el } = stacked();
    chart.setPaneCollapsed(2, true);
    const h = heights(chart);
    expect(h[2]).toBe(STRIP + TIME_AXIS);
    expect(sum(h)).toBeCloseTo(H, 9);
    expect(chart.panes()[2].priceScale.height).toBe(STRIP);

    const base = recorder(chart.panes()[2].base.ctx);
    base.ops.length = 0;
    fullFrame(chart);
    const labels = base.ops.filter((op) => op.type === 'fillText');
    expect(labels.length).toBeGreaterThan(0);
    expect(labels.every((op) => op.args[1] >= STRIP)).toBe(true);

    const spacing = chart.timeScale.barSpacing;
    press(el, 300, H - 8, 360, H - 8);
    expect(chart.timeScale.barSpacing).not.toBe(spacing);
  });

  it('moves the chart furniture onto the lowest open pane and back', () => {
    const { chart } = stacked();
    const holds = (index: number, type: abstract new (...args: never[]) => unknown): boolean =>
      chart.panes()[index].primitives().some((primitive) => primitive instanceof type);
    expect(holds(2, LogoWatermark)).toBe(true);
    chart.setPaneCollapsed(2, true);
    expect(holds(1, LogoWatermark)).toBe(true);
    expect(holds(1, TimeNavigator)).toBe(true);
    expect(holds(2, LogoWatermark)).toBe(false);
    expect(holds(2, TimeNavigator)).toBe(false);
    chart.setPaneCollapsed(2, false);
    expect(holds(2, LogoWatermark)).toBe(true);
    expect(holds(2, TimeNavigator)).toBe(true);
  });

  it('reveals the navigator from the lowest open pane, where it now sits', () => {
    const { chart, el } = stacked({ timeNavigator: { fadeSeconds: 0 } });
    chart.setPaneCollapsed(2, true);
    const nav = chart.panes()[1].primitives().find((p) => p instanceof TimeNavigator) as TimeNavigator;
    expect(nav).toBeDefined();
    // The band just above the pane's foot, where the controls fade in.
    const x = chart.timeScale.width / 2;
    const y = heights(chart)[1] - 23;
    hover(el, x, tops(chart)[1] + y);
    fullFrame(chart);
    expect(nav.hitTest(x, y)?.externalId).toMatch(/^timenav::/);
  });
});

describe('collapse and maximize', () => {
  it('shows a maximized strip at full size and folds it again on restore', () => {
    const { chart, el } = stacked();
    chart.setPaneCollapsed(1, true);
    chart.maximizePane(1);
    expect(heights(chart)[1]).toBe(H);
    expect(chart.paneCollapsed(1)).toBe(true);
    const moves: CrosshairMoveEvent[] = [];
    chart.on('crosshair:move', (e) => moves.push(e as CrosshairMoveEvent));
    hover(el, 400, 300);
    expect(last(moves)?.paneIndex).toBe(1);
    expect(last(moves)?.price).not.toBeNull();
    chart.maximizePane(1);
    expect(chart.maximizedPane()).toBeNull();
    expect(heights(chart)[1]).toBe(STRIP);
  });

  it('hides a strip behind another maximized pane and brings it back folded', () => {
    const { chart } = stacked();
    chart.setPaneCollapsed(1, true);
    chart.maximizePane(2);
    expect(chart.panes()[1].element.style.display).toBe('none');
    expect(heights(chart)[2]).toBe(H);
    chart.maximizePane(2);
    expect(chart.panes()[1].element.style.display).toBe('');
    expect(heights(chart)[1]).toBe(STRIP);
  });

  it('ends a maximize when the maximized pane is collapsed', () => {
    const { chart } = stacked();
    const maximized: unknown[] = [];
    chart.on('paneMaximized', (e) => maximized.push(e));
    chart.maximizePane(1);
    expect(chart.setPaneCollapsed(1, true)).toBe(true);
    expect(chart.maximizedPane()).toBeNull();
    expect(last(maximized)).toEqual({ paneIndex: null });
    expect(chart.panes()[0].element.style.display).toBe('');
    expect(heights(chart)[1]).toBe(STRIP);
  });

  it('offers no divider while a pane is maximized', () => {
    const { chart, el } = stacked();
    chart.maximizePane(1);
    const before = chart.panes().map((pane) => pane.weight);
    press(el, 400, 1, 400, 80);
    expect(chart.panes().map((pane) => pane.weight)).toEqual(before);
  });
});

describe('resizing around a strip', () => {
  it('keeps the strip height when the chart resizes', () => {
    const { chart } = stacked();
    chart.setPaneCollapsed(1, true);
    chart.applySize(W, 900);
    const h = heights(chart);
    expect(h[1]).toBe(STRIP);
    expectHeights(h, onPixels([(900 - STRIP) / 1.32, STRIP, ((900 - STRIP) * 0.32) / 1.32]));
    expect(sum(h)).toBeCloseTo(900, 9);
    expect(chart.panes().map((pane) => pane.weight)).toEqual([1, 0.32, 0.32]);
  });

  it('never lays strips out taller than the chart', () => {
    const { chart } = stacked();
    chart.setPaneCollapsed(1, true);
    chart.setPaneCollapsed(2, true);
    chart.applySize(W, 60);
    const h = heights(chart);
    expect(h.every((value) => Number.isFinite(value) && value >= 0)).toBe(true);
    expect(sum(h)).toBeCloseTo(60, 9);
  });

  it('moves height between the open panes either side of a strip', () => {
    const { chart, el } = stacked();
    chart.setPaneCollapsed(1, true);
    const before = chart.panes().map((pane) => pane.weight);
    const was = heights(chart);
    const boundary = tops(chart)[1];
    press(el, 400, boundary, 400, boundary + 40);
    const after = chart.panes().map((pane) => pane.weight);
    expect(after[1]).toBe(before[1]);
    expect(after[0]).toBeGreaterThan(before[0]);
    expect(after[2]).toBeLessThan(before[2]);
    expect(after[0] + after[2]).toBeCloseTo(before[0] + before[2], 9);
    expect(heights(chart)[1]).toBe(STRIP);
    expect(heights(chart)[0]).toBeCloseTo(was[0] + 40, 9);
  });

  it('offers no divider above a bottom strip with no open pane below it', () => {
    const { chart, el } = stacked();
    chart.setPaneCollapsed(2, true);
    const before = chart.panes().map((pane) => pane.weight);
    const boundary = tops(chart)[2];
    press(el, 400, boundary, 400, boundary - 40);
    expect(chart.panes().map((pane) => pane.weight)).toEqual(before);
  });
});

describe('removing and moving strips', () => {
  it('drops a collapsed pane and leaves every other pane its own state', () => {
    const { chart } = stacked();
    chart.addIndicator('cci');
    chart.setPaneCollapsed(1, true);
    chart.setPaneCollapsed(3, true);
    expect(chart.removePane(1)).toBe(true);
    expect([1, 2].map((i) => chart.paneCollapsed(i))).toEqual([false, true]);
    const h = heights(chart);
    expect(h[2]).toBe(STRIP + TIME_AXIS);
    expect(sum(h)).toBeCloseTo(H, 9);
    // The navigator sat on the pane that just moved up a slot. Looking it up by
    // its old slot missed it and attached it a second time.
    const navigators = chart.panes().flatMap((pane) => pane.primitives().filter((p) => p instanceof TimeNavigator));
    expect(navigators).toHaveLength(1);
    expect(chart.panes()[1].primitives()).toContain(navigators[0]);
  });

  it('leaves no collapse behind when the study on a strip is removed', () => {
    const { chart, rsi } = stacked();
    chart.setPaneCollapsed(1, true);
    chart.removeIndicator(rsi.id);
    expect(chart.panes()).toHaveLength(2);
    expect(chart.paneCollapsed(1)).toBe(false);
    const next = chart.addIndicator('rsi');
    expect(chart.paneCollapsed(next.paneIndex)).toBe(false);
    expect(heights(chart)[next.paneIndex]).toBeGreaterThan(STRIP + TIME_AXIS);
  });

  it('follows its pane through a move', () => {
    const { chart } = stacked();
    chart.setPaneCollapsed(1, true);
    expect(chart.movePane(1, 1)).toBe(true);
    expect(chart.paneCollapsed(1)).toBe(false);
    expect(chart.paneCollapsed(2)).toBe(true);
    expect(heights(chart)[2]).toBe(STRIP + TIME_AXIS);
  });
});

describe('the row a strip shows', () => {
  /** RSI and CCI sharing pane 1, with MACD on pane 2 below them. */
  const shared = () => {
    const made = stacked();
    const cci = made.chart.addIndicator('cci', {}, { paneIndex: 1 });
    return { ...made, cci };
  };
  const rowOf = (legend: PaneLegend): number | undefined => legend.options().row;
  const actionsOf = (study: { legend(): PaneLegend | null }): readonly string[] | undefined => study.legend()!.options().actions;
  /** A study row's own buttons, and the same row when it leads a lower pane. */
  const OWN_ROW = ['hide', 'settings', 'close'];
  const LEAD_ROW = ['hide', 'settings', 'up', 'down', 'collapse', 'maximize', 'close'];

  it.each([false, true])('keeps the way back when the first study is closed from the strip (compact legends %s)', (compact) => {
    const { chart, el, rsi, cci } = shared();
    if (compact) chart.setIndicatorLegendCollapsed(true);
    chart.setPaneCollapsed(1, true);
    pressControl(chart, el, rsi.legend()!, 1, 'close');
    const ids = chart.indicators().map((study) => study.id);
    expect(ids).not.toContain(rsi.id);
    expect(ids).toContain(cci.id);
    expect(chart.paneCollapsed(1)).toBe(true);
    // The surviving row is now the strip's only row, and it has to open it.
    pressControl(chart, el, cci.legend()!, 1);
    expect(chart.paneCollapsed(1)).toBe(false);
  });

  it('gives the new first row of an open pane the pane controls, and a fold leaves them as they are', () => {
    const { chart, el, rsi, cci } = shared();
    expect(actionsOf(cci)).toEqual(OWN_ROW);
    pressControl(chart, el, rsi.legend()!, 1, 'close');
    expect(chart.indicators().map((study) => study.id)).not.toContain(rsi.id);
    expect(chart.paneCollapsed(1)).toBe(false);
    // The pane is open and the surviving row now leads it, so it carries all
    // four pane controls, not only its own hide, settings and close.
    expect(actionsOf(cci)).toEqual(LEAD_ROW);
    pressControl(chart, el, cci.legend()!, 1);
    expect(chart.paneCollapsed(1)).toBe(true);
    expect(actionsOf(cci)).toEqual(LEAD_ROW);
    pressControl(chart, el, cci.legend()!, 1);
    expect(chart.paneCollapsed(1)).toBe(false);
    expect(actionsOf(cci)).toEqual(LEAD_ROW);
    pressControl(chart, el, cci.legend()!, 1, 'maximize');
    expect(chart.maximizedPane()).toBe(1);
  });

  it.each([false, true])('gives a study added below a host row the pane controls (folded %s)', (folded) => {
    const { chart } = makeChart();
    chart.addSeries('candlestick').setData(bars(120));
    chart.addSeries('line', { paneIndex: 1 }).setData(bars(120).map((bar) => ({ time: bar.time, value: bar.close })));
    const host = new PaneLegend({ id: 'host', title: 'Host', actions: [] });
    chart.addPrimitive(host, 1);
    if (folded) chart.setPaneCollapsed(1, true);
    const cci = chart.addIndicator('cci', {}, { paneIndex: 1 });
    const rsi = chart.addIndicator('rsi', {}, { paneIndex: 1 });
    expect([actionsOf(cci), actionsOf(rsi)]).toEqual([LEAD_ROW, OWN_ROW]);
    // The host keeps its row as it made it.
    expect(host.options().actions).toEqual([]);
    chart.removeIndicator(cci.id);
    expect(actionsOf(rsi)).toEqual(LEAD_ROW);
  });

  it.each([false, true])('moves the pane controls with the first study row of each pane (folded %s)', (folded) => {
    const { chart, rsi, cci, macd } = shared();
    if (folded) { chart.setPaneCollapsed(1, true); chart.setPaneCollapsed(2, true); }
    // RSI keeps its place ahead of MACD in the stacking order, so it leads the
    // pane it moves to, and CCI is left leading the pane it moved from.
    expect(chart.moveIndicator(rsi.id, macd.paneIndex)).toBe(true);
    expect([actionsOf(cci), actionsOf(rsi), actionsOf(macd)]).toEqual([LEAD_ROW, LEAD_ROW, OWN_ROW]);
    expect(chart.reorderIndicator(macd.id, -1)).toBe(true);
    expect([actionsOf(macd), actionsOf(rsi)]).toEqual([LEAD_ROW, OWN_ROW]);
    expect(chart.moveIndicator(macd.id, chart.panes().length)).toBe(true);
    expect([actionsOf(rsi), actionsOf(macd)]).toEqual([LEAD_ROW, LEAD_ROW]);
    expect(chart.moveIndicator(cci.id, rsi.paneIndex)).toBe(true);
    expect([actionsOf(rsi), actionsOf(cci), actionsOf(macd)]).toEqual([LEAD_ROW, OWN_ROW, LEAD_ROW]);
    expect(chart.panes()).toHaveLength(3);
  });

  it('gives the strip its control when a restored layout folds the pane', () => {
    const { chart, el, rsi, cci } = shared();
    chart.removeIndicator(rsi.id);
    const state = JSON.parse(JSON.stringify(chart.getState()));
    state.panes[1].collapsed = true;
    expect(chart.restoreState({ version: state.version, panes: state.panes }).applied).toBe(true);
    expect(chart.indicators().map((study) => study.id)).toContain(cci.id);
    expect(chart.paneCollapsed(1)).toBe(true);
    pressControl(chart, el, cci.legend()!, 1);
    expect(chart.paneCollapsed(1)).toBe(false);
  });

  it.each([false, true])('leads with the first study row above a row the host placed first (compact legends %s)', (compact) => {
    const { chart, el } = makeChart();
    chart.addSeries('candlestick').setData(bars(120));
    chart.addSeries('line', { paneIndex: 1 }).setData(bars(120).map((bar) => ({ time: bar.time, value: bar.close })));
    const host = new PaneLegend({ id: 'host', title: 'Host', actions: [] });
    chart.addPrimitive(host, 1);
    const cci = chart.addIndicator('cci', {}, { paneIndex: 1 });
    chart.addIndicator('macd');
    if (compact) chart.setIndicatorLegendCollapsed(true);
    // An open pane keeps the order the rows were added in.
    expect([rowOf(host), rowOf(cci.legend()!)]).toEqual([0, 1]);

    chart.setPaneCollapsed(1, true);
    expect([rowOf(host), rowOf(cci.legend()!)]).toEqual([1, 0]);
    const strip = chart.panes()[1].top.ctx;
    recorder(strip).ops.length = 0;
    fullFrame(chart);
    expect(texts(strip)).toContain('CCI');
    expect(texts(strip)).not.toContain('Host');
    // Maximized, the pane shows whole, its rows in the order they were added
    // (with the study toggle's row reserved between them, as on any top pane).
    chart.maximizePane(1);
    expect(rowOf(host)).toBe(0);
    expect(rowOf(cci.legend()!)).toBeGreaterThan(0);
    recorder(strip).ops.length = 0;
    fullFrame(chart);
    expect(texts(strip)).toContain('Host');
    chart.maximizePane(1);
    expect([rowOf(host), rowOf(cci.legend()!)]).toEqual([1, 0]);
    pressControl(chart, el, cci.legend()!, 1);
    expect(chart.paneCollapsed(1)).toBe(false);
    expect([rowOf(host), rowOf(cci.legend()!)]).toEqual([0, 1]);
    recorder(strip).ops.length = 0;
    fullFrame(chart);
    expect(texts(strip)).toContain('Host');
  });

  it('draws and answers only its one row', () => {
    const { chart, el, cci } = shared();
    chart.setPaneCollapsed(1, true);
    const strip = chart.panes()[1].top.ctx;
    recorder(strip).ops.length = 0;
    fullFrame(chart);
    expect(texts(strip)).toContain('RSI');
    // The second row starts inside the strip's lower inset, so drawing it
    // would leave the tops of its letters along the strip's bottom edge.
    expect(texts(strip)).not.toContain('CCI');
    const hovered: (string | null)[] = [];
    chart.on('hover', (e) => hovered.push((e as { id: string | null }).id));
    const clicks: ChartClickEvent[] = [];
    chart.on('click', (e) => clicks.push(e as ChartClickEvent));
    // Just above the divider grab, where the second row begins.
    const band = (): number => tops(chart)[1] + STRIP - 5;
    hover(el, 20, band());
    press(el, 20, band());
    expect(hovered.some((id) => id?.includes(cci.id))).toBe(false);
    expect(last(clicks)).toMatchObject({ id: null, paneIndex: 1 });

    chart.setPaneCollapsed(1, false);
    recorder(strip).ops.length = 0;
    fullFrame(chart);
    expect(texts(strip)).toContain('CCI');
    hover(el, 20, band());
    expect(last(hovered)).toContain(cci.id);
  });
});

describe('saving and restoring collapse', () => {
  const scale = { marginTop: 0.1, marginBottom: 0.1, minMove: 0, mode: 'linear', inverted: false, autoScale: true };

  it('saves the flag on the pane and restores the same layout', () => {
    const a = stacked();
    a.chart.setPaneWeight(2, 0.5);
    a.chart.setPaneCollapsed(2, true);
    const state = JSON.parse(JSON.stringify(a.chart.getState()));
    expect(state.panes.map((pane: { collapsed?: boolean }) => pane.collapsed)).toEqual([undefined, undefined, true]);

    const b = makeChart();
    b.chart.addSeries('candlestick').setData(bars(120));
    expect(b.chart.restoreState(state).applied).toBe(true);
    expect([0, 1, 2].map((i) => b.chart.paneCollapsed(i))).toEqual([false, false, true]);
    expect(b.chart.panes().map((pane) => pane.element.style.flex)).toEqual(a.chart.panes().map((pane) => pane.element.style.flex));
    b.chart.setPaneCollapsed(2, false);
    expect(b.chart.paneWeight(2)).toBe(0.5);
  });

  it('opens a pane when the restored layout does not say it is collapsed', () => {
    const { chart } = stacked();
    const plain = JSON.parse(JSON.stringify(chart.getState()));
    chart.setPaneCollapsed(1, true);
    expect(chart.restoreState(plain).applied).toBe(true);
    expect(chart.paneCollapsed(1)).toBe(false);
  });

  it('moves the chart furniture off a strip the saved layout folds', () => {
    const a = stacked();
    a.chart.setPaneCollapsed(2, true);
    const state = JSON.parse(JSON.stringify(a.chart.getState()));
    const fresh = makeChart();
    fresh.chart.addSeries('candlestick').setData(bars(120));
    const same = stacked();
    for (const { chart } of [fresh, same]) {
      expect(chart.restoreState(state).applied).toBe(true);
      expect(chart.paneCollapsed(2)).toBe(true);
      expect(paneHolds(chart, 1, LogoWatermark)).toBe(true);
      expect(paneHolds(chart, 2, LogoWatermark)).toBe(false);
      expect(paneHolds(chart, 1, TimeNavigator)).toBe(true);
    }
  });

  it('opens a pane the restored layout does not list, so a new study never lands folded', () => {
    const { chart } = stacked();
    chart.setPaneCollapsed(1, true);
    chart.setPaneCollapsed(2, true);
    const state = JSON.parse(JSON.stringify(chart.getState()));
    const cci = [{ indicatorId: 'cci', settings: {}, paneIndex: 1 }];
    // A template applied in replace mode keeps only the price pane's layout.
    expect(chart.restoreState({ version: state.version, indicators: cci, panes: state.panes.slice(0, 1) }).applied).toBe(true);
    expect(chart.indicators().map((study) => study.indicatorId)).toEqual(['cci']);
    expect(chart.paneCollapsed(1)).toBe(false);
    expect(heights(chart)[1]).toBeGreaterThan(STRIP + TIME_AXIS);

    // Studies rebuilt with no layout at all open their panes the same way.
    chart.setPaneCollapsed(1, true);
    expect(chart.restoreState({ version: state.version, indicators: cci }).applied).toBe(true);
    expect(chart.paneCollapsed(1)).toBe(false);
  });

  it('keeps a fold through a restore that touches neither panes nor studies', () => {
    const { chart } = stacked();
    chart.setPaneCollapsed(1, true);
    expect(chart.restoreState({ version: 1, crosshairMode: 'magnet' }).applied).toBe(true);
    expect(chart.paneCollapsed(1)).toBe(true);
  });

  it('keeps pane 0 open whatever a saved layout claims', () => {
    const { chart } = stacked();
    const state = JSON.parse(JSON.stringify(chart.getState()));
    state.panes[0].collapsed = true;
    expect(chart.restoreState(state).applied).toBe(true);
    expect(chart.paneCollapsed(0)).toBe(false);
  });

  it('validates the saved flag', () => {
    expect(parsePaneState({ weight: 1, priceScale: scale, collapsed: true }).collapsed).toBe(true);
    expect('collapsed' in parsePaneState({ weight: 1, priceScale: scale })).toBe(false);
    for (const bad of [1, 'true', null, {}]) {
      expect(() => parsePaneState({ weight: 1, priceScale: scale, collapsed: bad })).toThrow();
    }
  });

  it('carries the flag through a workspace document', () => {
    const source = workspaceFixture();
    const panes = [{ weight: 1, priceScale: scale }, { weight: 0.3, priceScale: scale, collapsed: true }];
    const input = { ...source, panes: source.panes.map((pane) => ({ ...pane, chart: { ...pane.chart, panes } })) };
    expect(parseWorkspaceDocument(input).panes[0].chart.panes?.map((pane) => pane.collapsed === true)).toEqual([false, true]);
  });
});

describe('study legend collapse is a different thing', () => {
  it('folding legend rows leaves panes open, and folding a pane leaves legend rows alone', () => {
    const { chart } = stacked();
    const before = heights(chart);
    chart.setIndicatorLegendCollapsed(true);
    expect(heights(chart)).toEqual(before);
    expect(chart.paneCollapsed(1)).toBe(false);
    chart.setIndicatorLegendCollapsed(false);
    chart.setPaneCollapsed(1, true);
    expect(chart.indicatorLegendCollapsed()).toBe(false);
    expect(chart.getState().indicatorLegendCollapsed).toBe(false);
  });

  it.each(['pane first', 'legends first'])('keeps the strip row and its control with compact study legends (%s)', (order) => {
    const { chart, el, rsi } = stacked();
    if (order === 'pane first') chart.setPaneCollapsed(1, true);
    chart.setIndicatorLegendCollapsed(true);
    if (order === 'legends first') chart.setPaneCollapsed(1, true);
    const strip = chart.panes()[1].top.ctx;
    const open = chart.panes()[2].top.ctx;
    recorder(strip).ops.length = 0;
    recorder(open).ops.length = 0;
    fullFrame(chart);
    // The strip's row is its only way back; the open pane's row stays compact.
    expect(texts(strip)).toContain('RSI');
    expect(texts(open)).not.toContain('MACD');

    pressControl(chart, el, rsi.legend()!, 1);
    expect(chart.paneCollapsed(1)).toBe(false);
    expect(chart.indicatorLegendCollapsed()).toBe(true);
    recorder(strip).ops.length = 0;
    fullFrame(chart);
    expect(texts(strip)).not.toContain('RSI');
  });

  it('restores a layout that folds a pane with compact study legends', () => {
    const a = stacked();
    a.chart.setPaneCollapsed(1, true);
    a.chart.setIndicatorLegendCollapsed(true);
    const state = JSON.parse(JSON.stringify(a.chart.getState()));
    const b = makeChart();
    b.chart.addSeries('candlestick').setData(bars(120));
    expect(b.chart.restoreState(state).applied).toBe(true);
    const strip = b.chart.panes()[1].top.ctx;
    recorder(strip).ops.length = 0;
    fullFrame(b.chart);
    expect(texts(strip)).toContain('RSI');
    const rsi = b.chart.indicators().find((study) => study.indicatorId === 'rsi')!;
    pressControl(b.chart, b.el, rsi.legend()!, 1);
    expect(b.chart.paneCollapsed(1)).toBe(false);
  });
});

describe('the collapse control', () => {
  const glyph = (collapsed: boolean): number[][] => {
    const legend = new PaneLegend({ id: 'a', title: 'A', actions: ['collapse'], collapsed });
    const { ctx, rec } = makeCtx();
    const rc: PrimitiveRenderContext = { priceScale: new PriceScale(), timeScale: new TimeScale(), dataLayer: new DataLayer(),
      plotWidth: 400, plotHeight: 200, priceAxisWidth: 60, dpr: 1, theme: darkTheme, hoverId: 'a::row' };
    legend.draw(ctx, rc);
    return rec.ops.filter((op) => op.type === 'moveTo' || op.type === 'lineTo').map((op) => op.args);
  };

  it('draws a chevron that points the way the pane will go', () => {
    const open = glyph(false);
    const folded = glyph(true);
    expect(open.length).toBeGreaterThan(0);
    // The last three points are one arm, the tip and the other arm.
    const [armOpen, tipOpen] = open.slice(-3);
    const [armFolded, tipFolded] = folded.slice(-3);
    expect(tipOpen[1]).toBeLessThan(armOpen[1]);
    expect(tipFolded[1]).toBeGreaterThan(armFolded[1]);
  });

  it('expands a strip to show a drawing the objects list focuses', () => {
    const { chart } = stacked();
    const draw = new DrawingController(chart);
    const drawing = draw.add({ tool: 'trend-line', paneIndex: 1, style: {},
      points: [{ time: bars(1, 40)[0].time, price: 40 }, { time: bars(1, 60)[0].time, price: 60 }] });
    chart.setPaneCollapsed(1, true);
    const objects = new ChartObjects(chart, { drawings: draw });
    expect(objects.focus('drawing:' + drawing.id)).toBe(true);
    expect(chart.paneCollapsed(1)).toBe(false);
    objects.destroy();
    draw.destroy();
  });

  it('is offered by the widget menu on a lower pane only', () => {
    const { chart } = stacked();
    const ctx = { chart, draw: { drawings: () => [] } } as unknown as WidgetContext;
    const event = (paneIndex: number): ContextMenuEvent => ({ paneIndex, point: { x: 400, y: 10 }, price: null, time: null,
      index: null, preventDefault() {}, target: { kind: 'empty', id: null } });
    const row = (paneIndex: number, target: ContextMenuEvent['target'] = { kind: 'empty', id: null }): MenuItem | undefined =>
      contextMenuEntries(ctx, { ...event(paneIndex), target })
        .find((entry) => !entry.kind && entry.id === 'pane-collapse') as MenuItem | undefined;
    expect(row(0)).toBeUndefined();
    // The time axis under a bottom pane belongs to the whole chart, not to that pane.
    expect(row(1, { kind: 'time-scale', id: null })).toBeUndefined();
    expect(row(1)).toMatchObject({ label: 'Collapse pane' });
    row(1)!.run!();
    expect(chart.paneCollapsed(1)).toBe(true);
    expect(row(1)).toMatchObject({ label: 'Expand pane' });
    row(1)!.run!();
    expect(chart.paneCollapsed(1)).toBe(false);
  });
});

describe('the packaged widget', () => {
  const widgets: Widget[] = [];
  afterEach(() => { for (const widget of widgets.splice(0)) widget.destroy(); });

  it('saves a collapse and reports it as a layout change', () => {
    ensureWindowGlobal();
    const document = fakeWidgetDocument();
    const w = createWidget(fakeContainer(document) as unknown as HTMLElement, {
      document: document as unknown as Document, pixelRatio: () => 1,
      rail: false, panels: false, mobile: 'never', animZoom: false, animAutoscale: false,
      raf: { schedule: (cb) => { cb(); return 1; }, cancel() {} },
    });
    widgets.push(w);
    w.chart.applySize(W, H);
    w.series.setData(bars(120));
    const rsi = w.chart.addIndicator('rsi');
    const reasons: string[] = [];
    w.on('layout', (event) => reasons.push((event as { reason: string }).reason));
    expect(w.chart.setPaneCollapsed(rsi.paneIndex, true)).toBe(true);
    expect(reasons).toContain('paneCollapsed');
    expect(w.getState().chart.panes?.[rsi.paneIndex].collapsed).toBe(true);
  });
});
