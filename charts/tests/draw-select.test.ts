/**
 * Multi-selection: the list, the additive gesture, the events, and the drag
 * that moves everything selected as one edit.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import { DrawingController } from '../src/draw/index';
import type { DrawingChartHost } from '../src/draw/controller';
import type { Bar } from '../src/model/bar';
import type { DataLayer } from '../src/model/data-layer';
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

/** A host with a working bus and no pixel mapping. */
function busHost(): DrawingChartHost {
  const handlers = new Map<string, ((p: unknown) => void)[]>();
  return {
    on: (event, handler) => {
      const list = handlers.get(event) ?? [];
      list.push(handler);
      handlers.set(event, list);
      return () => handlers.set(event, (handlers.get(event) ?? []).filter((h) => h !== handler));
    },
    emit: (event, payload) => { for (const h of handlers.get(event) ?? []) h(payload); },
    addPrimitive: () => {},
    removePrimitive: () => {},
    dataLayer: { baseIndex: 2, indexToTime: (i: number) => 1700000000 + i * 300 } as unknown as DataLayer,
    getVisibleLogicalRange: () => null,
    drawingState: () => null,
    setDrawingState: () => {},
  };
}

const line = (draw: DrawingController, extra: Partial<Drawing> = {}): Drawing =>
  draw.add({
    tool: 'trend-line', paneIndex: 0, style: {},
    points: [{ time: 1000, price: 10 }, { time: 2000, price: 20 }],
    ...extra,
  });

const click = (chart: DrawingChartHost, id: string | null, mods: Record<string, boolean> = {}): void =>
  chart.emit('click', { id, time: 1, price: 1, paneIndex: 0, point: { x: 1, y: 1 }, ...mods });

describe('the selection list', () => {
  it('holds several ids, with the first as the primary', () => {
    const draw = new DrawingController(makeChart());
    const a = line(draw);
    const b = line(draw);
    draw.select([a.id, b.id]);
    expect(draw.selection()).toEqual([a.id, b.id]);
    expect(draw.selected()).toBe(a.id);
    draw.select(b.id);
    expect(draw.selection()).toEqual([b.id]);
    draw.select(null);
    expect(draw.selection()).toEqual([]);
    expect(draw.selected()).toBeNull();
  });

  it('toggles ids in and out when additive', () => {
    const draw = new DrawingController(makeChart());
    const a = line(draw);
    const b = line(draw);
    draw.select(a.id);
    draw.select(b.id, true);
    expect(draw.selection()).toEqual([a.id, b.id]);
    draw.select(a.id, true);
    expect(draw.selection()).toEqual([b.id]);
    draw.select([a.id, b.id], true);
    expect(draw.selection()).toEqual([a.id]);
  });

  it('ignores ids that name nothing, and repeats', () => {
    const draw = new DrawingController(makeChart());
    const a = line(draw);
    draw.select([a.id, 'nope', a.id]);
    expect(draw.selection()).toEqual([a.id]);
    draw.select('nope');
    expect(draw.selection()).toEqual([]);
  });

  it('drops an id when its drawing goes, including through undo', () => {
    const draw = new DrawingController(makeChart());
    const a = line(draw);
    const b = line(draw);
    draw.select([a.id, b.id]);
    draw.remove(a.id);
    expect(draw.selection()).toEqual([b.id]);
    draw.undo();                         // a is back, but not re-selected
    expect(draw.selection()).toEqual([b.id]);
    draw.undo();                         // b was never added
    expect(draw.selection()).toEqual([]);
  });

  it('emits drawing:select with every id, and draw:select with the primary, only on change', () => {
    const chart = makeChart();
    const multi: string[][] = [];
    const single: (string | null)[] = [];
    chart.on('drawing:select', (p) => multi.push((p as { ids: string[] }).ids));
    chart.on('draw:select', (p) => single.push((p as { id: string | null }).id));
    const draw = new DrawingController(chart);
    const a = line(draw);
    const b = line(draw);
    multi.length = 0;
    single.length = 0;
    draw.select([a.id, b.id]);
    draw.select([a.id, b.id]);           // same again: silence
    draw.select(null);
    draw.select(null);
    expect(multi).toEqual([[a.id, b.id], []]);
    expect(single).toEqual([a.id, null]);
  });
});

describe('clicking', () => {
  it('a plain click replaces the selection, a modified click adds to it', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const a = line(draw);
    const b = line(draw);
    const c = line(draw);
    click(chart, `draw:${a.id}`);
    click(chart, `draw:${b.id}`, { shiftKey: true });
    click(chart, `draw:${c.id}`, { ctrlKey: true });
    expect(draw.selection()).toEqual([a.id, b.id, c.id]);
    click(chart, `draw:${b.id}`, { metaKey: true });    // toggles out
    expect(draw.selection()).toEqual([a.id, c.id]);
    click(chart, `draw:${b.id}`);
    expect(draw.selection()).toEqual([b.id]);
  });

  it('reads the additive gesture from `modifiers`, which outlives the flat flags', () => {
    // The flat shiftKey, ctrlKey and metaKey on a click are deprecated for
    // removal in the next major; the draw tier must not depend on them.
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const a = line(draw);
    const b = line(draw);
    const c = line(draw);
    const modified = (id: string, modifiers: Record<string, boolean>): void =>
      chart.emit('click', { id, time: 1, price: 1, paneIndex: 0, point: { x: 1, y: 1 }, modifiers });
    click(chart, `draw:${a.id}`);
    modified(`draw:${b.id}`, { shift: true });
    modified(`draw:${c.id}`, { ctrl: true });
    expect(draw.selection()).toEqual([a.id, b.id, c.id]);
    modified(`draw:${b.id}`, { meta: true });
    expect(draw.selection()).toEqual([a.id, c.id]);
    draw.select(a.id);
    chart.emit('click', { id: null, time: 1, price: 1, paneIndex: 0, point: { x: 1, y: 1 }, modifiers: { shift: true } });
    expect(draw.selection()).toEqual([a.id]);
  });

  it('a click on empty space clears, unless it is the additive gesture', () => {
    const chart = makeChart();
    // Shift+click on empty space is the temporary measure when that gesture
    // is on (draw-measure.test.ts); with it off it is the additive click.
    const draw = new DrawingController(chart, { gestures: { measure: false } });
    const a = line(draw);
    draw.select(a.id);
    click(chart, null, { shiftKey: true });
    expect(draw.selection()).toEqual([a.id]);
    click(chart, null, { ctrlKey: true });
    expect(draw.selection()).toEqual([a.id]);
    click(chart, null);
    expect(draw.selection()).toEqual([]);
  });

  it('a click on a handle id selects the drawing, not the handle', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const a = line(draw);
    draw.select(null);
    click(chart, `draw:${a.id}#1`);
    expect(draw.selection()).toEqual([a.id]);
  });
});

describe('multi-drag', () => {
  const drag = (chart: DrawingChartHost, id: string, time: number, price: number, extra: Record<string, unknown> = {}): void =>
    chart.emit('drag', { id, time, price, paneIndex: 0, ...extra });

  it('moves every selected drawing with the one grabbed, as one undo entry', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    const a = line(draw);
    const b = line(draw, { points: [{ time: 5000, price: 50 }, { time: 6000, price: 60 }] });
    draw.select([a.id, b.id]);
    drag(chart, `draw:${a.id}`, 1000, 10);
    drag(chart, `draw:${a.id}`, 1300, 13);
    drag(chart, `draw:${a.id}`, 1500, 15);
    chart.emit('drag:end', {});
    expect(draw.get(a.id)?.points).toEqual([{ time: 1500, price: 15 }, { time: 2500, price: 25 }]);
    expect(draw.get(b.id)?.points).toEqual([{ time: 5500, price: 55 }, { time: 6500, price: 65 }]);
    expect(draw.selection()).toEqual([a.id, b.id]);   // the drag kept the selection
    expect(draw.undo()).toBe(true);
    expect(draw.get(a.id)?.points).toEqual([{ time: 1000, price: 10 }, { time: 2000, price: 20 }]);
    expect(draw.get(b.id)?.points).toEqual([{ time: 5000, price: 50 }, { time: 6000, price: 60 }]);
  });

  it('measures from the grab point the chart reports', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    const a = line(draw);
    draw.select(a.id);
    drag(chart, `draw:${a.id}`, 1400, 14, { fromTime: 1200, fromPrice: 12 });
    chart.emit('drag:end', {});
    expect(draw.get(a.id)?.points[0]).toEqual({ time: 1200, price: 12 });
  });

  it('grabbing an unselected drawing selects it alone and moves only it', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    const a = line(draw);
    const b = line(draw, { points: [{ time: 5000, price: 50 }, { time: 6000, price: 60 }] });
    draw.select(a.id);
    drag(chart, `draw:${b.id}`, 5000, 50);
    drag(chart, `draw:${b.id}`, 5100, 51);
    chart.emit('drag:end', {});
    expect(draw.selection()).toEqual([b.id]);
    expect(draw.get(a.id)?.points[0]).toEqual({ time: 1000, price: 10 });
    expect(draw.get(b.id)?.points[0]).toEqual({ time: 5100, price: 51 });
  });

  it('leaves a locked member of the selection where it is', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    const a = line(draw);
    const locked = line(draw, { locked: true, points: [{ time: 5000, price: 50 }, { time: 6000, price: 60 }] });
    draw.select([a.id, locked.id]);
    drag(chart, `draw:${a.id}`, 1000, 10);
    drag(chart, `draw:${a.id}`, 1100, 11);
    chart.emit('drag:end', {});
    expect(draw.get(a.id)?.points[0]).toEqual({ time: 1100, price: 11 });
    expect(draw.get(locked.id)?.points[0]).toEqual({ time: 5000, price: 50 });
  });

  it('carries a drawing on another pane along in time, and in price only through pixels', () => {
    // Without a pixel mapping the other pane's price scale is unknowable, so
    // the shape there follows in time and keeps its price.
    const chart = busHost();
    const draw = new DrawingController(chart);
    const a = line(draw);
    const other = line(draw, { paneIndex: 1, points: [{ time: 1000, price: 30 }, { time: 2000, price: 70 }] });
    draw.select([a.id, other.id]);
    drag(chart, `draw:${a.id}`, 1000, 10);
    drag(chart, `draw:${a.id}`, 1200, 14);
    chart.emit('drag:end', {});
    expect(draw.get(other.id)?.points).toEqual([{ time: 1200, price: 30 }, { time: 2200, price: 70 }]);
  });

  it('follows the pane scale for a drawing on another pane when the host maps pixels', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    // The second pane goes in first: adding it shrinks pane 0, and every price
    // below is read off the settled layout.
    const other = line(draw, { paneIndex: 1, points: [{ time: 1000, price: 0.25 }, { time: 2000, price: 0.5 }] });
    const p0 = chart.coordinateToPrice(300, 0) as number;
    const p1 = chart.coordinateToPrice(200, 0) as number;
    const a = draw.add({
      tool: 'trend-line', paneIndex: 0, style: {},
      points: [{ time: chart.coordinateToTime(200), price: p0 }, { time: chart.coordinateToTime(400), price: p1 }],
    });
    const yBefore = chart.priceToCoordinate(0.25, 1) as number;
    draw.select([a.id, other.id]);
    const target = chart.coordinateToPrice(340, 0) as number;   // 40 px down on pane 0
    chart.emit('drag', { id: `draw:${a.id}`, time: a.points[0].time, price: p0, paneIndex: 0 });
    chart.emit('drag', { id: `draw:${a.id}`, time: a.points[0].time, price: target, paneIndex: 0 });
    chart.emit('drag:end', {});
    const yAfter = chart.priceToCoordinate(draw.get(other.id)?.points[0].price as number, 1) as number;
    expect(yAfter - yBefore).toBeCloseTo(40, 3);
  });

  it('reports every moved drawing once the gesture ends', () => {
    const chart = busHost();
    const updated: string[] = [];
    let changed: { ids: string[]; kind: string } | null = null;
    chart.on('draw:update', (p) => updated.push((p as { drawing: Drawing }).drawing.id));
    chart.on('drawing:change', (p) => { changed = p as { ids: string[]; kind: string }; });
    const draw = new DrawingController(chart);
    const a = line(draw);
    const b = line(draw);
    draw.select([a.id, b.id]);
    drag(chart, `draw:${a.id}`, 1000, 10);
    drag(chart, `draw:${a.id}`, 1100, 11);
    expect(updated).toEqual([]);                 // nothing until release
    chart.emit('drag:end', {});
    expect(updated).toEqual([a.id, b.id]);
    expect(changed).toEqual({ ids: [a.id, b.id], kind: 'update', step: expect.any(Number) });
  });

  it('a handle drag moves that anchor only, whatever else is selected', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    const a = line(draw);
    const b = line(draw, { points: [{ time: 5000, price: 50 }, { time: 6000, price: 60 }] });
    draw.select([a.id, b.id]);
    drag(chart, `draw:${a.id}#1`, 3000, 33);
    chart.emit('drag:end', {});
    expect(draw.get(a.id)?.points).toEqual([{ time: 1000, price: 10 }, { time: 3000, price: 33 }]);
    expect(draw.get(b.id)?.points[0]).toEqual({ time: 5000, price: 50 });
    expect(draw.selection()).toEqual([a.id, b.id]);
  });
});
