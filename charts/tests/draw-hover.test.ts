/**
 * Hover state: the drawing under the pointer, read off the chart's own
 * hit-test rather than tested a second time, shown as light handles, and
 * paid for on the overlay tier alone. The pointer moves sixty times a second,
 * so anything on this path that repaints the series is a stutter.
 */
import { describe, it, expect, beforeAll, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import { makeCtx } from './helpers/fake-ctx';
import { darkTheme } from '../src/theme';
import { InvalidateMask, InvalidationLevel } from '../src/core/invalidate-mask';
import { DrawingController, DrawingLayer } from '../src/draw/index';
import type { DrawingChartHost } from '../src/draw/controller';
import type { Bar } from '../src/model/bar';
import type { DataLayer } from '../src/model/data-layer';
import type { IPrimitive } from '../src/primitives/primitive';
import type { Drawing } from '../src/draw/types';

const W = 800;
const H = 600;

beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

const bars = (n: number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = 100 + Math.sin(i / 4) * 5;
    return { time: 1700000000 + i * 60, open: c, high: c + 2, low: c - 2, close: c, volume: 10 };
  });

/** A measured chart that paints synchronously; see tests/compare.test.ts. */
function makeChart(): Chart {
  const chart = new Chart(fakeDocument().createElement('div') as unknown as HTMLElement, {
    document: fakeDocument(),
    raf: { schedule: (cb: (t: number) => void) => { cb(0); return 0; } },
    pixelRatio: () => 1, shortcuts: false,
  });
  chart.applySize(W, H);
  chart.addSeries('candlestick').setData(bars(120));
  return chart;
}

/** Identity mapping: time is x, price is y. */
const rc = {
  timeScale: { indexToX: (i: number) => i },
  priceScale: { priceToY: (p: number) => p, format: (p: number) => String(p) },
  dataLayer: { timeToIndexFloat: (t: number) => t },
  plotWidth: W, plotHeight: H, priceAxisWidth: 60, dpr: 1, theme: darkTheme,
} as never;

/** A host with a working bus and a record of the primitives it was handed. */
function busHost(): DrawingChartHost & { layers: { layer: DrawingLayer; pane: number }[] } {
  const handlers = new Map<string, ((p: unknown) => void)[]>();
  const layers: { layer: DrawingLayer; pane: number }[] = [];
  return {
    layers,
    on: (event, handler) => {
      const list = handlers.get(event) ?? [];
      list.push(handler);
      handlers.set(event, list);
      return () => handlers.set(event, (handlers.get(event) ?? []).filter((h) => h !== handler));
    },
    emit: (event, payload) => { for (const h of handlers.get(event) ?? []) h(payload); },
    addPrimitive: (p: IPrimitive, pane = 0) => { layers.push({ layer: p as DrawingLayer, pane }); },
    removePrimitive: () => {},
    dataLayer: { baseIndex: 2, indexToTime: (i: number) => 1700000000 + i * 300 } as unknown as DataLayer,
    getVisibleLogicalRange: () => null,
    drawingState: () => null,
    setDrawingState: () => {},
  };
}

const lineAt = (id: string, zIndex = 0, extra: Partial<Drawing> = {}): Drawing => ({
  id, tool: 'trend-line', paneIndex: 0, zIndex, style: {},
  points: [{ time: 100, price: 100 }, { time: 300, price: 300 }],
  ...extra,
});

/** The handle circles a layer painted: one entry per arc, with the stroke width it got. */
function handles(layer: DrawingLayer): number[] {
  const { ctx, rec } = makeCtx();
  layer.draw(ctx, rc);
  const out: number[] = [];
  for (let i = 0; i < rec.ops.length; i++) {
    if (rec.ops[i].type !== 'arc') continue;
    // The stroke that closes this handle is the next stroke op.
    const stroke = rec.ops.slice(i).find((o) => o.type === 'stroke');
    out.push(stroke?.lineWidth ?? -1);
  }
  return out;
}

/** Every invalidation level the chart is asked for from now on. */
function recordLevels(chart: Chart): number[] {
  const levels: number[] = [];
  const orig = chart.invalidate.bind(chart);
  vi.spyOn(chart, 'invalidate').mockImplementation((build) => {
    const m = new InvalidateMask();
    build(m);
    levels.push(m.globalLevel);
    for (const p of m.panes().values()) levels.push(p.level);
    orig(build);
  });
  return levels;
}

const topLayerOf = (chart: Chart, pane = 0): DrawingLayer =>
  chart.panes()[pane].primitives().find((p) => p instanceof DrawingLayer && p.zOrder() === 'top') as DrawingLayer;

describe('the controller tracks the drawing under the pointer', () => {
  it('reads the hit id off the chart hover event, body or handle, and reports it once', () => {
    const chart = busHost();
    const seen: (string | null)[] = [];
    chart.on('drawing:hover', (p) => seen.push((p as { id: string | null }).id));
    const draw = new DrawingController(chart);
    const a = draw.add(lineAt('a'));
    expect(draw.hovered()).toBeNull();
    chart.emit('hover', { id: `draw:${a.id}` });
    chart.emit('hover', { id: `draw:${a.id}#1` });   // a handle of the same drawing
    expect(draw.hovered()).toBe(a.id);
    chart.emit('hover', { id: 'legend:remove' });     // something that is not a drawing
    expect(draw.hovered()).toBeNull();
    chart.emit('hover', { id: null });
    expect(seen).toEqual([a.id, null]);
  });

  it('clears when the pointer leaves the plot, and when the drawing goes', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    const a = draw.add(lineAt('a'));
    chart.emit('hover', { id: `draw:${a.id}` });
    chart.emit('crosshair:move', { time: null, index: null, price: null, bar: null, point: null, paneIndex: null });
    expect(draw.hovered()).toBeNull();
    chart.emit('hover', { id: `draw:${a.id}` });
    draw.remove(a.id);
    expect(draw.hovered()).toBeNull();
  });

  it('hands the id to both layers of every pane', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    const a = draw.add(lineAt('a'));
    draw.add(lineAt('b', 0, { paneIndex: 1 }));
    chart.emit('hover', { id: `draw:${a.id}` });
    expect(chart.layers.map((l) => l.layer.hovered())).toEqual([a.id, a.id, a.id, a.id]);
  });
});

describe('hover handles', () => {
  it('paints a hovered drawing at a lighter weight than a selected one', () => {
    const top = new DrawingLayer('top');
    top.setDrawings([lineAt('a'), lineAt('b')]);
    top.setSelected(['a']);
    top.setHovered('b');
    // Two anchors each: the selection at full weight, the hover thin.
    expect(handles(top)).toEqual([1, 1, 2, 2]);
  });

  it('shows a drawing that is both hovered and selected once, at full weight', () => {
    const top = new DrawingLayer('top');
    top.setDrawings([lineAt('a')]);
    top.setSelected(['a']);
    top.setHovered('a');
    expect(handles(top)).toEqual([2, 2]);
  });

  it('paints the hover of an under-series drawing on the top layer', () => {
    const bottom = new DrawingLayer('bottom');
    const top = new DrawingLayer('top');
    top.setBelow(bottom);
    bottom.setDrawings([lineAt('under', -1)]);
    bottom.setHovered('under');
    top.setHovered('under');
    expect(handles(top)).toEqual([1, 1]);
    expect(handles(bottom)).toEqual([]);
  });

  it('gives a locked or hidden drawing no hover handles', () => {
    const top = new DrawingLayer('top');
    top.setDrawings([lineAt('a', 0, { locked: true }), lineAt('b', 0, { visible: false })]);
    top.setHovered('a');
    expect(handles(top)).toEqual([]);
    top.setHovered('b');
    expect(handles(top)).toEqual([]);
  });
});

describe('hover costs the overlay tier only', () => {
  it('the top layer asks for a repaint; the adopted bottom layer asks for nothing', () => {
    let topUpdates = 0;
    let bottomUpdates = 0;
    const bottom = new DrawingLayer('bottom');
    const top = new DrawingLayer('top');
    top.setBelow(bottom);
    top.attached({ requestUpdate: () => { topUpdates++; } });
    bottom.attached({ requestUpdate: () => { bottomUpdates++; } });
    topUpdates = 0;
    bottomUpdates = 0;
    top.setHovered('x');
    bottom.setHovered('x');
    expect(topUpdates).toBe(1);
    expect(bottomUpdates).toBe(0);
    // The same id again is not a change.
    top.setHovered('x');
    expect(topUpdates).toBe(1);
  });

  it('a standalone bottom layer still repaints itself, since nothing else will', () => {
    let updates = 0;
    const layer = new DrawingLayer('bottom');
    layer.attached({ requestUpdate: () => { updates++; } });
    layer.setHovered('x');
    expect(updates).toBe(1);
  });

  it('on a real chart a hover change raises nothing above the cursor level', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const a = draw.add(lineAt('a'));
    draw.add(lineAt('under', -1));
    const levels = recordLevels(chart);
    chart.emit('hover', { id: `draw:${a.id}` });
    chart.emit('hover', { id: 'draw:under' });
    chart.emit('hover', { id: null });
    expect(levels.length).toBeGreaterThan(0);
    expect(Math.max(...levels)).toBe(InvalidationLevel.Cursor);
    expect(topLayerOf(chart).hovered()).toBeNull();
  });

  /** A hover through the chart's own pointer path, not a bus emission. */
  const pointer = (chart: Chart) => (x: number, y: number): void => {
    (chart as unknown as { _onPointerMove(e: unknown): void })._onPointerMove({
      clientX: x, clientY: y, pointerId: 1, pointerType: 'mouse', button: 0, buttons: 0, preventDefault() {},
    });
  };

  it('end to end: a real pointer move between drawings, and off to empty space, stays at the cursor level', () => {
    // Both drawing layers are 'top' primitives, so the chart has nothing on
    // the base canvas to restyle: the overlay is the whole cost.
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const y = (price: number): number => chart.priceToCoordinate(price) as number;
    draw.add({ id: 'a', tool: 'horizontal-line', paneIndex: 0, zIndex: 0, style: {}, points: [{ time: 1700000000, price: 104 }] });
    draw.add({ id: 'b', tool: 'horizontal-line', paneIndex: 0, zIndex: -1, style: {}, points: [{ time: 1700000000, price: 96 }] });
    const move = pointer(chart);
    const levels = recordLevels(chart);
    move(300, y(104));
    expect(topLayerOf(chart).hovered()).toBe('a');
    move(300, y(96));
    expect(topLayerOf(chart).hovered()).toBe('b');
    move(300, y(100));
    expect(topLayerOf(chart).hovered()).toBeNull();
    expect(levels.length).toBeGreaterThan(0);
    expect(Math.max(...levels)).toBe(InvalidationLevel.Cursor);
  });

  it('while a primitive on the base canvas still gets its light repaint on enter and on leave', () => {
    const chart = makeChart();
    let under = true;
    const orderLine: IPrimitive = {
      zOrder: () => 'normal',
      draw: () => {},
      hitTest: () => (under ? { externalId: 'order', zOrder: 'normal', distance: 0 } : null),
    };
    chart.addPrimitive(orderLine, 0);
    const move = pointer(chart);
    const levels = recordLevels(chart);
    move(300, 300);
    expect(Math.max(...levels)).toBe(InvalidationLevel.Light);
    levels.length = 0;
    under = false;
    move(310, 300);
    expect(Math.max(...levels)).toBe(InvalidationLevel.Light);
  });
});
