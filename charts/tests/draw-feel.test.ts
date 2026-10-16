/**
 * The feel of the drawing tools: the Shift angle lock, the magnet modes and
 * the ring that shows where a click will land, touch-sized targets, the lift
 * that keeps an under-series drag on the overlay tier, the placement keys,
 * and what a freehand gesture keeps of its samples.
 *
 * Anything measured in pixels runs on a measured chart (`applySize` plus a
 * synchronous raf), because an unmeasured one sits on placeholder scales
 * where every conversion agrees with every other for the wrong reason.
 */
import { describe, it, expect, beforeAll, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import { makeCtx } from './helpers/fake-ctx';
import { darkTheme } from '../src/theme';
import { InvalidateMask, InvalidationLevel } from '../src/core/invalidate-mask';
import { DrawingController, DrawingLayer, BRUSH, HIGHLIGHTER } from '../src/draw/index';
import { pressureWidth } from '../src/draw/freehand';
import type { DrawingChartHost } from '../src/draw/controller';
import type { Bar } from '../src/model/bar';
import type { DataLayer } from '../src/model/data-layer';
import type { IPrimitive } from '../src/primitives/primitive';
import type { Drawing, DrawingPoint, DrawContext, DrawingTool } from '../src/draw/types';

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

/** A host with a working bus, a record of the layers, and no pixel mapping. */
function busHost(): DrawingChartHost & { layers: { layer: DrawingLayer; pane: number }[]; placement: boolean[] } {
  const handlers = new Map<string, ((p: unknown) => void)[]>();
  const layers: { layer: DrawingLayer; pane: number }[] = [];
  const placement: boolean[] = [];
  return {
    layers,
    placement,
    on: (event, handler) => {
      const list = handlers.get(event) ?? [];
      list.push(handler);
      handlers.set(event, list);
      return () => handlers.set(event, (handlers.get(event) ?? []).filter((h) => h !== handler));
    },
    emit: (event, payload) => { for (const h of handlers.get(event) ?? []) h(payload); },
    addPrimitive: (p: IPrimitive, pane = 0) => { layers.push({ layer: p as DrawingLayer, pane }); },
    removePrimitive: () => {},
    setPlacementMode: (active: boolean) => { placement.push(active); },
    dataLayer: { baseIndex: 2, indexToTime: (i: number) => 1700000000 + i * 300 } as unknown as DataLayer,
    getVisibleLogicalRange: () => null,
    drawingState: () => null,
    setDrawingState: () => {},
  };
}

/** Identity mapping: time is x, price is y. */
const identity = {
  timeScale: { indexToX: (i: number) => i },
  priceScale: { priceToY: (p: number) => p, format: (p: number) => String(p) },
  dataLayer: { timeToIndexFloat: (t: number) => t },
  plotWidth: W, plotHeight: H, priceAxisWidth: 60, dpr: 1, theme: darkTheme,
} as never;

/** A container point as the anchor a click there produces. */
const at = (chart: Chart, x: number, y: number, pane = 0): DrawingPoint =>
  ({ time: chart.coordinateToTime(x), price: chart.coordinateToPrice(y, pane) as number });

/** Where an anchor sits on screen. */
const px = (chart: Chart, p: DrawingPoint, pane = 0): { x: number; y: number } =>
  ({ x: chart.timeToCoordinate(p.time), y: chart.priceToCoordinate(p.price, pane) as number });

const click = (chart: DrawingChartHost, p: DrawingPoint, extra: Record<string, unknown> = {}): void =>
  chart.emit('click', { id: null, time: p.time, price: p.price, paneIndex: 0, point: { x: 0, y: 0 }, ...extra });

const topLayerOf = (chart: Chart, pane = 0): DrawingLayer =>
  chart.panes()[pane].primitives().find((p) => p instanceof DrawingLayer && p.zOrder() === 'top') as DrawingLayer;
const bottomLayerOf = (chart: Chart, pane = 0): DrawingLayer =>
  chart.panes()[pane].primitives().find((p) => p instanceof DrawingLayer && p.zOrder() === 'bottom') as DrawingLayer;

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

/** The stroke colours a layer painted, in order, on the identity mapping. */
const strokes = (layer: DrawingLayer): string[] => {
  const { ctx, rec } = makeCtx();
  layer.draw(ctx, identity);
  return rec.ops.filter((o) => o.type === 'stroke' || o.type === 'strokeRect').map((o) => o.strokeStyle ?? '');
};

// ── angle lock ────────────────────────────────────────────────────────────

describe('Shift locks the free end of a line to 45 degree steps on screen', () => {
  it('flattens a nearly level second click to exactly level', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('trend-line');
    click(chart, at(chart, 200, 300));
    click(chart, at(chart, 400, 310), { modifiers: { shift: true } });
    const d = draw.drawings()[0];
    const end = px(chart, d.points[1]);
    expect(end.y).toBeCloseTo(300, 3);
    // Projected, not rotated: the end stays under the pointer's x.
    expect(end.x).toBeCloseTo(400, 3);
  });

  it('projects onto the diagonal, dropping only the stray axis', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('trend-line');
    click(chart, at(chart, 200, 300));
    // 200 across, 180 down: 42 degrees, which rounds to the 45 degree ray,
    // and (200 + 180) / 2 along each axis is where the projection lands.
    click(chart, at(chart, 400, 480), { modifiers: { shift: true } });
    const end = px(chart, draw.drawings()[0].points[1]);
    expect(end.x).toBeCloseTo(390, 3);
    expect(end.y).toBeCloseTo(490, 3);
  });

  it('holds a vertical under the pointer, and snaps the steep side of 22.5 degrees', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('trend-line');
    click(chart, at(chart, 200, 300));
    click(chart, at(chart, 205, 150), { modifiers: { shift: true } });   // 88 degrees up
    const end = px(chart, draw.drawings()[0].points[1]);
    expect(end.x).toBeCloseTo(200, 3);
    expect(end.y).toBeCloseTo(150, 3);
  });

  it('reads the flat shiftKey form as well as modifiers', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('ray');
    click(chart, at(chart, 200, 300));
    click(chart, at(chart, 400, 310), { shiftKey: true });
    expect(px(chart, draw.drawings()[0].points[1]).y).toBeCloseTo(300, 3);
  });

  it('does nothing without Shift, and nothing on a tool without the flag', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('trend-line');
    click(chart, at(chart, 200, 300));
    click(chart, at(chart, 400, 310));
    expect(px(chart, draw.drawings()[0].points[1]).y).toBeCloseTo(310, 3);
    draw.setTool('rectangle');
    click(chart, at(chart, 200, 300));
    click(chart, at(chart, 400, 310), { modifiers: { shift: true } });
    expect(px(chart, draw.drawings()[1].points[1]).y).toBeCloseTo(310, 3);
  });

  it('is a screen angle, so a host without a pixel mapping cannot lock', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    draw.setTool('trend-line');
    click(chart, { time: 1000, price: 10 });
    click(chart, { time: 2000, price: 11 }, { modifiers: { shift: true } });
    expect(draw.drawings()[0].points[1]).toEqual({ time: 2000, price: 11 });
  });

  it('bypasses the magnet while locked, or the snap would bend the angle', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { magnet: 'strong' });
    draw.setTool('trend-line');
    click(chart, at(chart, 200, 300));
    const far = chart.coordinateToPrice(100, 0) as number;
    chart.emit('crosshair:move', {
      time: at(chart, 400, 310).time, price: at(chart, 400, 310).price, paneIndex: 0,
      bar: { open: far, high: far, low: far, close: far }, modifiers: { shift: true },
    });
    click(chart, at(chart, 400, 310), { modifiers: { shift: true } });
    expect(px(chart, draw.drawings()[0].points[1]).y).toBeCloseTo(300, 3);
  });

  it('locks a handle drag the same way, about the other anchor', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const d = draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [at(chart, 200, 300), at(chart, 400, 400)] });
    const target = at(chart, 400, 310);
    chart.emit('drag', { id: `draw:${d.id}#1`, ...target, paneIndex: 0, modifiers: { shift: true } });
    chart.emit('drag:end', {});
    expect(px(chart, draw.get(d.id)?.points[1] as DrawingPoint).y).toBeCloseTo(300, 3);
    expect(px(chart, draw.get(d.id)?.points[0] as DrawingPoint).y).toBeCloseTo(300, 3);   // untouched
    // Without Shift the handle lands where the pointer is.
    chart.emit('drag', { id: `draw:${d.id}#1`, ...target, paneIndex: 0 });
    chart.emit('drag:end', {});
    expect(px(chart, draw.get(d.id)?.points[1] as DrawingPoint).y).toBeCloseTo(310, 3);
  });

  it('shows the locked end in the preview while Shift is held', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('trend-line');
    click(chart, at(chart, 200, 300));
    const cursor = at(chart, 400, 310);
    chart.emit('crosshair:move', { ...cursor, paneIndex: 0, bar: null, modifiers: { shift: true } });
    const { ctx, rec } = makeCtx();
    // On the identity mapping the preview's line ends at (time, price).
    topLayerOf(chart).draw(ctx, identity);
    const end = rec.ops.filter((o) => o.type === 'lineTo').pop() as { args: number[] };
    expect(end.args[1]).toBeCloseTo(at(chart, 400, 300).price, 6);
    expect(end.args[1]).not.toBeCloseTo(cursor.price, 6);
  });
});

// ── magnet ────────────────────────────────────────────────────────────────

describe('magnet modes', () => {
  it('folds the 1.9.x boolean onto the modes', () => {
    expect(new DrawingController(busHost(), { magnet: true }).magnetMode()).toBe('strong');
    expect(new DrawingController(busHost(), { magnet: false }).magnetMode()).toBe('off');
    expect(new DrawingController(busHost()).magnetMode()).toBe('off');
    expect(new DrawingController(busHost(), { magnet: 'weak' }).magnetMode()).toBe('weak');
    const draw = new DrawingController(busHost(), { magnet: 'strong' });
    draw.setOptions({ magnet: 'off' });
    expect(draw.magnetMode()).toBe('off');
    draw.setOptions({ magnet: true });
    expect(draw.magnetMode()).toBe('strong');
    draw.setOptions({ historyLimit: 3 });   // an unrelated patch leaves it alone
    expect(draw.magnetMode()).toBe('strong');
  });

  it('strong always takes the nearest value, at the bar time', () => {
    const chart = busHost();
    const draw = new DrawingController(chart, { magnet: 'strong' });
    chart.emit('crosshair:move', { time: 1700000600, price: 150, paneIndex: 0, bar: { open: 100, high: 104, low: 99, close: 101 } });
    draw.setTool('horizontal-line');
    click(chart, { time: 1700000617, price: 150 });   // a click lands between bars; the anchor does not
    expect(draw.drawings()[0].points[0]).toEqual({ time: 1700000600, price: 104 });
  });

  it('weak pulls only within eight pixels of a value', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { magnet: 'weak' });
    const price = (y: number) => chart.coordinateToPrice(y, 0) as number;
    const bar = { open: price(305), high: price(200), low: price(400), close: price(250) };
    chart.emit('crosshair:move', { time: 1700000600, price: price(300), paneIndex: 0, bar });
    draw.setTool('horizontal-line');
    click(chart, { time: 1700000600, price: price(300) });       // 5 px from the open
    expect(draw.drawings()[0].points[0]).toEqual({ time: 1700000600, price: bar.open });

    chart.emit('crosshair:move', { time: 1700000600, price: price(330), paneIndex: 0, bar });
    draw.setTool('horizontal-line');
    click(chart, { time: 1700000600, price: price(330) });       // 25 px from anything
    expect(draw.drawings()[1].points[0]).toEqual({ time: 1700000600, price: price(330) });
  });

  it('weak needs a pixel mapping: without one nothing pulls', () => {
    const chart = busHost();
    const draw = new DrawingController(chart, { magnet: 'weak' });
    chart.emit('crosshair:move', { time: 1700000600, price: 103.9, paneIndex: 0, bar: { open: 100, high: 104, low: 99, close: 101 } });
    draw.setTool('horizontal-line');
    click(chart, { time: 1700000600, price: 103.9 });
    expect(draw.drawings()[0].points[0].price).toBe(103.9);
  });

  it('never pulls an indicator pane to candle prices (with no study plotted there, nothing pulls)', () => {
    const chart = busHost();
    const draw = new DrawingController(chart, { magnet: 'strong' });
    chart.emit('crosshair:move', { time: 1700000600, price: 50, paneIndex: 1, bar: { open: 100, high: 104, low: 99, close: 101 } });
    draw.setTool('horizontal-line');
    chart.emit('click', { id: null, time: 1700000600, price: 50, paneIndex: 1, point: { x: 0, y: 0 } });
    expect(draw.drawings()[0].points[0].price).toBe(50);
  });
});

describe('the magnet ring', () => {
  const bar = { open: 100, high: 104, low: 99, close: 101 };
  const move = (chart: DrawingChartHost, price: number, extra: Record<string, unknown> = {}): void =>
    chart.emit('crosshair:move', { time: 1700000600, price, paneIndex: 0, bar, ...extra });

  it('marks where the next click will land while a tool is armed and the magnet pulls', () => {
    const chart = busHost();
    const draw = new DrawingController(chart, { magnet: 'strong' });
    draw.setTool('trend-line');
    move(chart, 103.4);
    const top = chart.layers.find((l) => l.layer.zOrder() === 'top')?.layer as DrawingLayer;
    expect(top.snapPoint()).toEqual({ time: 1700000600, price: 104 });
    // It follows the pointer.
    move(chart, 99.2);
    expect(top.snapPoint()).toEqual({ time: 1700000600, price: 99 });
    // And goes with the tool.
    draw.setTool(null);
    expect(top.snapPoint()).toBeNull();
  });

  it('shows nothing with no tool, for a brush, with the magnet off, or off the bar', () => {
    const chart = busHost();
    const draw = new DrawingController(chart, { magnet: 'strong' });
    move(chart, 103.4);
    expect(chart.layers).toHaveLength(0);           // no ring, so no layers were made for it
    draw.setTool('brush');
    move(chart, 103.4);
    expect(chart.layers).toHaveLength(0);
    draw.setOptions({ magnet: 'off' });
    draw.setTool('trend-line');
    move(chart, 103.4);
    expect(chart.layers).toHaveLength(0);
    chart.emit('crosshair:move', { time: 1700009999, price: 103.4, paneIndex: 0, bar: null });
    draw.setOptions({ magnet: 'strong' });          // pulls again, but there is no bar under the pointer
    expect(chart.layers).toHaveLength(0);
    move(chart, 103.4);                             // and now there is
    expect(chart.layers).toHaveLength(2);
  });

  it('clears when the pointer leaves, and when the shape commits', () => {
    const chart = busHost();
    const draw = new DrawingController(chart, { magnet: 'strong' });
    draw.setTool('horizontal-line');
    move(chart, 103.4);
    const top = chart.layers.find((l) => l.layer.zOrder() === 'top')?.layer as DrawingLayer;
    expect(top.snapPoint()).not.toBeNull();
    chart.emit('crosshair:move', { time: null, index: null, price: null, bar: null, point: null, paneIndex: null });
    expect(top.snapPoint()).toBeNull();
    move(chart, 103.4);
    click(chart, { time: 1700000600, price: 103.4 });
    expect(draw.drawings()).toHaveLength(1);
    expect(top.snapPoint()).toBeNull();
  });

  it('hides while the angle lock holds, since the lock bypasses the magnet', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { magnet: 'strong' });
    draw.setTool('trend-line');
    click(chart, at(chart, 200, 300));
    const cursor = at(chart, 400, 310);
    chart.emit('crosshair:move', { ...cursor, paneIndex: 0, bar });
    expect(topLayerOf(chart).snapPoint()).not.toBeNull();
    chart.emit('crosshair:move', { ...cursor, paneIndex: 0, bar, modifiers: { shift: true } });
    expect(topLayerOf(chart).snapPoint()).toBeNull();
  });

  it('paints as a hollow ring in the axis text colour', () => {
    const top = new DrawingLayer('top');
    top.setSnapPoint({ time: 120, price: 240 });
    const { ctx, rec } = makeCtx();
    top.draw(ctx, identity);
    const ring = rec.ops.find((o) => o.type === 'arc') as { args: number[] };
    expect(ring.args).toEqual([120, 240, 5.5]);
    const stroke = rec.ops.find((o) => o.type === 'stroke');
    expect(stroke?.strokeStyle).toBe(darkTheme.axisText);
    // Hollow: nothing is filled for it.
    expect(rec.count('fill')).toBe(0);
  });

  it('costs the overlay tier only', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { magnet: 'strong' });
    draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [at(chart, 100, 100), at(chart, 300, 300)] });
    draw.setTool('trend-line');
    const levels = recordLevels(chart);
    move(chart, 103.4);
    move(chart, 99.2);
    expect(levels.length).toBeGreaterThan(0);
    expect(Math.max(...levels)).toBe(InvalidationLevel.Cursor);
  });
});

// ── touch targets ─────────────────────────────────────────────────────────

describe('touch targets', () => {
  const line = (): Drawing => ({
    id: 'a', tool: 'trend-line', paneIndex: 0, zIndex: 0, style: {},
    points: [{ time: 100, price: 100 }, { time: 300, price: 100 }],
  });

  it('doubles the grab radius of a body for a fingertip', () => {
    const top = new DrawingLayer('top');
    top.setDrawings([line()]);
    expect(top.hitTest(200, 110, identity)).toBeNull();          // 10 px off: a miss for a mouse
    top.setPointerType('touch');
    expect(top.hitTest(200, 110, identity)?.externalId).toBe('draw:a');
    expect(top.hitTest(200, 113, identity)).toBeNull();          // and 13 px is still a miss
    top.setPointerType('pen');
    expect(top.hitTest(200, 110, identity)).toBeNull();
  });

  it('doubles the handle radius too', () => {
    const top = new DrawingLayer('top');
    top.setDrawings([line()]);
    top.setSelected(['a']);
    expect(top.hitTest(100, 109, identity)).toBeNull();          // 9 px: past the 7 px handle and the 6 px body
    top.setPointerType('touch');
    expect(top.hitTest(100, 109, identity)?.externalId).toBe('draw:a#0');
  });

  it('takes the device off the render context when it names one', () => {
    const top = new DrawingLayer('top');
    top.setDrawings([line()]);
    const touch = { ...(identity as object), pointerType: 'touch' } as never;
    expect(top.hitTest(200, 110, touch)?.externalId).toBe('draw:a');
    top.setPointerType('touch');
    const mouse = { ...(identity as object), pointerType: 'mouse' } as never;
    expect(top.hitTest(200, 110, mouse)).toBeNull();
  });

  it('the controller passes the device of the last pointer report to every layer', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [{ time: 100, price: 100 }, { time: 300, price: 100 }] });
    const top = chart.layers.find((l) => l.layer.zOrder() === 'top')?.layer as DrawingLayer;
    expect(top.hitTest(200, 110, identity)).toBeNull();
    chart.emit('crosshair:move', { time: 1, price: 1, paneIndex: 0, bar: null, pointerType: 'touch' });
    expect(top.hitTest(200, 110, identity)).not.toBeNull();
    chart.emit('click', { id: null, time: 1, price: 1, paneIndex: 0, point: { x: 0, y: 0 }, pointerType: 'mouse' });
    expect(top.hitTest(200, 110, identity)).toBeNull();
  });
});

// ── overlay lift ──────────────────────────────────────────────────────────

describe('dragging an under-series drawing lifts it to the top layer', () => {
  const box = (draw: DrawingController): Drawing => draw.add({
    tool: 'rectangle', paneIndex: 0, zIndex: -1, style: { color: '#c0ffee', fill: true },
    points: [{ time: 100, price: 100 }, { time: 300, price: 300 }],
  });
  const drag = (chart: DrawingChartHost, id: string, time: number, price: number): void =>
    chart.emit('drag', { id, time, price, paneIndex: 0 });

  it('paints on top for the gesture and goes back under on release, without changing its z-order', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    const d = box(draw);
    const bottom = chart.layers[0].layer;
    const top = chart.layers[1].layer;
    expect(strokes(bottom)).toContain('#c0ffee');
    expect(strokes(top)).not.toContain('#c0ffee');

    drag(chart, `draw:${d.id}`, 100, 100);
    drag(chart, `draw:${d.id}`, 120, 120);
    expect(strokes(top)).toContain('#c0ffee');
    expect(strokes(bottom)).not.toContain('#c0ffee');
    expect(draw.get(d.id)?.zIndex).toBe(-1);

    chart.emit('drag:end', {});
    expect(strokes(bottom)).toContain('#c0ffee');
    expect(strokes(top)).not.toContain('#c0ffee');
    expect(draw.get(d.id)?.zIndex).toBe(-1);
    expect(draw.get(d.id)?.points[0]).toEqual({ time: 120, price: 120 });
  });

  it('keeps every frame after the first on the cursor tier', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const d = box(draw);
    const levels = recordLevels(chart);
    drag(chart, `draw:${d.id}`, 100, 100);
    // The lift itself re-lists the bottom layer once: one series repaint.
    expect(Math.max(...levels)).toBe(InvalidationLevel.Light);
    levels.length = 0;
    drag(chart, `draw:${d.id}`, 110, 110);
    drag(chart, `draw:${d.id}`, 120, 120);
    drag(chart, `draw:${d.id}`, 130, 130);
    expect(levels.length).toBeGreaterThan(0);
    expect(Math.max(...levels)).toBe(InvalidationLevel.Cursor);
    // And the layer that repaints on that tier is the one holding the shape,
    // or the cheap repaint would be showing a stale position.
    expect(strokes(topLayerOf(chart))).toContain('#c0ffee');
    expect(strokes(bottomLayerOf(chart))).not.toContain('#c0ffee');
    levels.length = 0;
    chart.emit('drag:end', {});
    // Returning under the series is the other series repaint.
    expect(Math.max(...levels)).toBe(InvalidationLevel.Light);
    expect(strokes(bottomLayerOf(chart))).toContain('#c0ffee');
    expect(strokes(topLayerOf(chart))).not.toContain('#c0ffee');
  });

  it('an over-series drag never touches the bottom layer at all', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const d = draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [{ time: 100, price: 100 }, { time: 300, price: 300 }] });
    draw.select(d.id);
    const levels = recordLevels(chart);
    drag(chart, `draw:${d.id}`, 100, 100);
    drag(chart, `draw:${d.id}`, 110, 110);
    chart.emit('drag:end', {});
    expect(levels.length).toBeGreaterThan(0);
    expect(Math.max(...levels)).toBe(InvalidationLevel.Cursor);
  });

  it('a lifted drawing survives an undo mid-gesture', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    const d = box(draw);
    drag(chart, `draw:${d.id}`, 100, 100);
    drag(chart, `draw:${d.id}`, 120, 120);
    draw.undo();                                  // the drag's own snapshot: back to the start
    drag(chart, `draw:${d.id}`, 130, 130);
    chart.emit('drag:end', {});
    expect(strokes(chart.layers[0].layer)).toContain('#c0ffee');
    expect(strokes(chart.layers[1].layer)).not.toContain('#c0ffee');
  });
});

// ── placement keys ────────────────────────────────────────────────────────

describe('placement ergonomics', () => {
  it('cancel drops the anchors placed so far and returns to the cursor', () => {
    const chart = busHost();
    const tools: (string | null)[] = [];
    chart.on('draw:tool', (p) => tools.push((p as { tool: string | null }).tool));
    const draw = new DrawingController(chart);
    draw.setTool('trend-line');
    click(chart, { time: 1000, price: 10 });
    chart.placement.length = 0;
    expect(draw.cancel()).toBe(true);
    expect(draw.drawings()).toHaveLength(0);
    expect(draw.activeTool()).toBeNull();
    expect(chart.placement).toEqual([false]);
    expect(tools).toEqual(['trend-line', null]);
    // A second anchor after the cancel starts a fresh shape, not the old one.
    draw.setTool('trend-line');
    click(chart, { time: 3000, price: 30 });
    click(chart, { time: 4000, price: 40 });
    expect(draw.drawings()[0].points[0]).toEqual({ time: 3000, price: 30 });
  });

  it('cancel keeps the tool armed when the controller stays in drawing mode', () => {
    const chart = busHost();
    const draw = new DrawingController(chart, { stayInDrawingMode: true });
    draw.setTool('trend-line');
    click(chart, { time: 1000, price: 10 });
    expect(draw.cancel()).toBe(true);
    expect(draw.activeTool()).toBe('trend-line');
    click(chart, { time: 3000, price: 30 });
    click(chart, { time: 4000, price: 40 });
    expect(draw.drawings()[0].points[0]).toEqual({ time: 3000, price: 30 });
    // With nothing pending, a second Escape disarms even then.
    expect(draw.cancel()).toBe(true);
    expect(draw.activeTool()).toBeNull();
  });

  it('cancel with no tool armed does nothing and says so', () => {
    const draw = new DrawingController(busHost());
    expect(draw.cancel()).toBe(false);
    draw.setTool('trend-line');
    expect(draw.cancel()).toBe(true);           // armed, nothing pending: disarmed
    expect(draw.activeTool()).toBeNull();
  });

  it('popAnchor removes the last vertex of a polyline in progress', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    draw.setTool('polyline');
    click(chart, { time: 1000, price: 10 });
    click(chart, { time: 2000, price: 20 });
    click(chart, { time: 3000, price: 30 });
    expect(draw.popAnchor()).toBe(true);
    expect(draw.finish()).toBe(true);
    expect(draw.drawings()[0].points).toEqual([{ time: 1000, price: 10 }, { time: 2000, price: 20 }]);
  });

  it('popAnchor can empty the shape, after which there is nothing to finish', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    draw.setTool('path');
    click(chart, { time: 1000, price: 10 });
    expect(draw.popAnchor()).toBe(true);
    expect(draw.popAnchor()).toBe(false);
    expect(draw.finish()).toBe(false);
    expect(draw.drawings()).toHaveLength(0);
    expect(draw.activeTool()).toBe('path');     // still armed for another go
  });

  it('popAnchor refuses fixed-anchor tools and brushes', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    draw.setTool('trend-line');
    click(chart, { time: 1000, price: 10 });
    expect(draw.popAnchor()).toBe(false);
    click(chart, { time: 2000, price: 20 });
    expect(draw.drawings()).toHaveLength(1);
    draw.setTool('brush');
    chart.emit('crosshair:move', { time: 1000, price: 10, paneIndex: 0, bar: null, pressed: true });
    expect(draw.popAnchor()).toBe(false);
    expect(draw.popAnchor()).toBe(false);
  });
});

// ── freehand ──────────────────────────────────────────────────────────────

describe('freehand strokes', () => {
  /** Press, move through every sample, release. */
  const stroke = (chart: DrawingChartHost, pts: readonly DrawingPoint[], extra: Record<string, unknown> = {}): void => {
    click(chart, pts[0]);
    for (const p of pts) {
      chart.emit('crosshair:move', { time: p.time, price: p.price, paneIndex: 0, bar: null, point: { x: 0, y: 0 }, pressed: true, ...extra });
    }
    click(chart, pts[pts.length - 1], { viaDrag: true });
  };

  it('thins a stroke to what its shape needs: a straight run keeps only its ends', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('brush');
    const pts = Array.from({ length: 30 }, (_, i) => at(chart, 200 + i * 5, 300 + i * 2));
    stroke(chart, pts);
    const d = draw.drawings()[0];
    expect(d.points).toHaveLength(2);
    expect(d.points[0]).toEqual(pts[0]);
    expect(d.points[1]).toEqual(pts[29]);
  });

  it('keeps every vertex the hand actually made', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('brush');
    // A zigzag of 20 px is far outside the pixel-and-a-half tolerance.
    const pts = Array.from({ length: 12 }, (_, i) => at(chart, 200 + i * 15, 300 + (i % 2) * 20));
    stroke(chart, pts);
    expect(draw.drawings()[0].points).toEqual(pts);
  });

  it('keeps a long zigzag whole, and still offers only its two end handles', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('brush');
    const pts: DrawingPoint[] = Array.from({ length: 30 }, (_, i) => ({ time: 1700000600 + i * 60, price: 100 + i * 0.2 + (i % 2) }));
    stroke(chart, pts);
    const d = draw.drawings()[0];
    expect(d.points).toHaveLength(30);
    draw.select(d.id);
    const { ctx, rec } = makeCtx();
    topLayerOf(chart).draw(ctx, identity);
    expect(rec.count('arc')).toBe(2);
  });

  it('keeps every sample on a host that cannot map to pixels', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    draw.setTool('brush');
    const pts = Array.from({ length: 10 }, (_, i) => ({ time: 1000 + i * 60, price: 10 + i }));
    stroke(chart, pts);
    expect(draw.drawings()[0].points).toEqual(pts);
  });

  it('inks every coalesced sample a pressed move carries, not just its point', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('brush');
    const xs = [200, 215, 230, 245];
    const ys = [300, 320, 300, 320];
    const end = at(chart, xs[3], ys[3]);
    click(chart, at(chart, xs[0], ys[0]));
    chart.emit('crosshair:move', {
      ...end, paneIndex: 0, bar: null, pressed: true,
      point: { x: xs[3], y: ys[3] },
      samples: xs.map((x, i) => ({ x, y: ys[i], pressure: 0.5 })),
    });
    click(chart, end, { viaDrag: true });
    const d = draw.drawings()[0];
    expect(d.points).toHaveLength(4);
    for (let i = 0; i < 3; i++) {
      expect(px(chart, d.points[i]).x).toBeCloseTo(xs[i], 6);
      expect(px(chart, d.points[i]).y).toBeCloseTo(ys[i], 6);
    }
    expect(d.points[3]).toEqual(end);
  });

  it('stores pen pressure per sample, and nothing for the mouse stand-in', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('brush');
    const a = at(chart, 200, 300);
    const b = at(chart, 220, 340);
    const c = at(chart, 240, 300);
    click(chart, a);
    chart.emit('crosshair:move', { ...a, paneIndex: 0, bar: null, pressed: true, pointerType: 'pen', pressure: 0.2 });
    chart.emit('crosshair:move', { ...b, paneIndex: 0, bar: null, pressed: true, pointerType: 'pen', pressure: 0.5 });
    chart.emit('crosshair:move', { ...c, paneIndex: 0, bar: null, pressed: true, pointerType: 'pen', pressure: 0.9 });
    click(chart, c, { viaDrag: true });
    const d = draw.drawings()[0];
    expect(d.points.map((p) => p.pressure)).toEqual([0.2, undefined, 0.9]);
    // The stored pressure survives a whole-shape drag.
    chart.emit('drag', { id: `draw:${d.id}`, ...a, paneIndex: 0 });
    chart.emit('drag', { id: `draw:${d.id}`, ...b, paneIndex: 0 });
    chart.emit('drag:end', {});
    expect(draw.get(d.id)?.points.map((p) => p.pressure)).toEqual([0.2, undefined, 0.9]);
  });

  /** Paint a stroke through the identity mapping and hand back the ops. */
  function paint(tool: DrawingTool, points: DrawingPoint[], style: Drawing['style']) {
    const { ctx, rec } = makeCtx();
    const d: Drawing = { id: 'd', tool: tool.id, paneIndex: 0, zIndex: 0, points, style: { ...tool.defaultStyle, ...style } };
    tool.draw({
      ctx, rc: identity, drawing: d,
      pts: points.map((p) => ({ x: p.time, y: p.price })),
      style: { color: '#4f8cff', lineWidth: 2, ...d.style },
      selected: false, formatPrice: (p: number) => String(p),
    } as DrawContext);
    return rec;
  }

  const wave: DrawingPoint[] = [
    { time: 0, price: 100 }, { time: 40, price: 80 }, { time: 80, price: 120 }, { time: 120, price: 100 },
  ];

  it('renders through the spline, not a polyline', () => {
    for (const tool of [BRUSH, HIGHLIGHTER]) {
      const rec = paint(tool, wave, {});
      expect(rec.count('bezierCurveTo'), tool.id).toBe(3);
      expect(rec.count('lineTo'), tool.id).toBe(0);
      expect(rec.count('stroke'), tool.id).toBe(1);
      expect(rec.count('fill'), tool.id).toBe(0);
      expect(rec.count('save'), tool.id).toBe(rec.count('restore'));
    }
  });

  it('with pressure on, fills a ribbon whose width follows each sample', () => {
    const flat: DrawingPoint[] = [
      { time: 0, price: 100, pressure: 0.1 }, { time: 50, price: 100 }, { time: 100, price: 100, pressure: 0.9 },
    ];
    const rec = paint(BRUSH, flat, { pressure: true, lineWidth: 10 });
    expect(rec.count('fill')).toBe(1);
    expect(rec.count('stroke')).toBe(0);
    // The ribbon runs out along one edge and back along the other, so each
    // sample appears twice among the path's points; their gap is the width.
    const ends = [
      (rec.ops.find((o) => o.type === 'moveTo') as { args: number[] }).args,
      ...rec.ops.filter((o) => o.type === 'bezierCurveTo').map((o) => o.args.slice(4)),
    ];
    const widthAt = (x: number) => {
      const ys = ends.filter((p) => Math.abs(p[0] - x) < 1e-6).map((p) => p[1]);
      return Math.max(...ys) - Math.min(...ys);
    };
    expect(widthAt(0)).toBeCloseTo(pressureWidth(10, 0.1), 6);
    expect(widthAt(50)).toBeCloseTo(10, 6);            // no pressure stored: the configured width
    expect(widthAt(100)).toBeCloseTo(pressureWidth(10, 0.9), 6);
    expect(widthAt(100)).toBeGreaterThan(widthAt(0));
  });

  it('the highlighter keeps its translucency in either mode', () => {
    const rec = paint(HIGHLIGHTER, wave, { pressure: true });
    expect(rec.count('fill')).toBe(1);
    expect(rec.count('save')).toBe(rec.count('restore'));
  });
});
