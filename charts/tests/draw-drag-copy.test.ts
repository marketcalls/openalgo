/**
 * Drag to copy: Alt (Option) plus a drag on a drawing's body leaves the
 * drawing where it was and moves a copy of it instead, as one undo step. The
 * copy is the user's own drawing: no policy, no link lineage.
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import { DrawingController, createDrawingLinkGroup } from '../src/draw/index';
import { DRAWING_LINK_METADATA_KEY } from '../src/draw/controller';
import type { Bar } from '../src/model/bar';
import type { DrawingInput, DrawingPoint } from '../src/draw/types';

beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

const BARS: Bar[] = (() => {
  let price = 812;
  let seed = 5;
  const next = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  return Array.from({ length: 120 }, (_, i) => {
    const open = price;
    const close = open + (next() - 0.5) * 9;
    price = close;
    return { time: 1700000000 + i * 60, open, high: Math.max(open, close) + next() * 3, low: Math.min(open, close) - next() * 3, close, volume: 500 };
  });
})();

const charts: Chart[] = [];
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

function makeChart(): Chart {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div') as unknown as HTMLElement, {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: (cb: (t: number) => void) => { cb(0); return 0; } },
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(BARS);
  charts.push(chart);
  return chart;
}

const line = (draw: DrawingController, a = 20, b = 40, extra: Partial<DrawingInput> = {}) => draw.add({
  tool: 'trend-line', paneIndex: 0, style: { color: '#e0a030' },
  points: [{ time: BARS[a].time, price: BARS[a].close }, { time: BARS[b].time, price: BARS[b].close }], ...extra,
});

/** One body drag from `from` by `dt` seconds and `dp` in price, in `steps` frames, then the release. */
function dragBody(chart: Chart, id: string, from: DrawingPoint, dt: number, dp: number, alt = true, steps = 3, end = true): void {
  for (let i = 1; i <= steps; i++) {
    chart.emit('drag', { id: `draw:${id}`, time: from.time + (dt * i) / steps, price: from.price + (dp * i) / steps,
      paneIndex: 0, fromTime: from.time, fromPrice: from.price, modifiers: { alt } });
  }
  if (end) chart.emit('drag:end', {});
}

const grab = (draw: DrawingController, id: string): DrawingPoint => {
  const [a, b] = draw.get(id)!.points;
  return { time: (a.time + b.time) / 2, price: (a.price + b.price) / 2 };
};

describe('Alt+drag on a body moves a copy and leaves the drawing', () => {
  it('clones the drawing, moves the clone by the drag, and selects it', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const d = line(draw);
    const before = draw.get(d.id)!.points.map((p) => ({ ...p }));
    dragBody(chart, d.id, grab(draw, d.id), 600, 4);
    expect(draw.drawings()).toHaveLength(2);
    const copy = draw.drawings()[1];
    expect(copy.id).not.toBe(d.id);
    expect(draw.get(d.id)!.points).toEqual(before);
    expect(copy.points.map((p) => p.time)).toEqual(before.map((p) => p.time + 600));
    copy.points.forEach((p, i) => expect(p.price).toBeCloseTo(before[i].price + 4, 9));
    expect(copy.style).toEqual(draw.get(d.id)!.style);
    expect(draw.selection()).toEqual([copy.id]);
  });

  it('is one undo step, announced once as an add', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const d = line(draw);
    const changes: { ids: string[]; kind: string; step?: number }[] = [];
    const adds: string[] = [];
    chart.on('drawing:change', (p) => changes.push(p as { ids: string[]; kind: string }));
    chart.on('draw:add', (p) => adds.push((p as { drawing: { id: string } }).drawing.id));
    const steps = draw.historySteps().undo.length;
    dragBody(chart, d.id, grab(draw, d.id), 600, 4);
    const copy = draw.drawings()[1];
    expect(adds).toEqual([copy.id]);
    expect(changes).toHaveLength(1);
    expect(changes[0]).toMatchObject({ ids: [copy.id], kind: 'add' });
    expect(changes[0].step).toBeDefined();
    expect(draw.historySteps().undo.length).toBe(steps + 1);
    expect(draw.undo()).toBe(true);
    expect(draw.drawings().map((x) => x.id)).toEqual([d.id]);
    expect(draw.redo()).toBe(true);
    expect(draw.drawings().map((x) => x.id)).toEqual([d.id, copy.id]);
  });

  it('copies the whole selection, leaving out what a drag would not move', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const a = line(draw, 20, 40);
    const b = line(draw, 50, 70);
    const locked = line(draw, 80, 90, { locked: true });
    const readOnly = line(draw, 95, 110, { policy: { editable: false } });
    draw.select([a.id, b.id, locked.id, readOnly.id]);
    dragBody(chart, a.id, grab(draw, a.id), 300, -2);
    expect(draw.drawings()).toHaveLength(6);
    const copies = draw.drawings().slice(4);
    expect(copies.map((c) => c.points[0].time)).toEqual([BARS[20].time + 300, BARS[50].time + 300]);
    expect(draw.selection()).toEqual(copies.map((c) => c.id));
  });

  it('gives the copy no policy and no link lineage: it is the user\'s own drawing', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const d = line(draw, 20, 40, { policy: { persistent: false }, props: { [DRAWING_LINK_METADATA_KEY]: { version: 1, id: 'x', context: 'y' } } });
    dragBody(chart, d.id, grab(draw, d.id), 600, 4);
    const copy = draw.drawings()[1];
    expect(copy.policy).toBeUndefined();
    expect(copy.props?.[DRAWING_LINK_METADATA_KEY]).toBeUndefined();
    expect(draw.toJSON().drawings.map((x) => x.id)).toEqual([copy.id]);   // the original was transient
  });

  it('takes the copy back out when the drag is cancelled, with nothing to undo', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const d = line(draw);
    const steps = draw.historySteps();
    dragBody(chart, d.id, grab(draw, d.id), 600, 4, true, 3, false);
    expect(draw.drawings()).toHaveLength(2);
    chart.emit('drag:cancel', {});
    expect(draw.drawings().map((x) => x.id)).toEqual([d.id]);
    expect(draw.selection()).toEqual([d.id]);
    expect(draw.historySteps()).toEqual(steps);
  });

  it('waits for a real drag: a jitter under three pixels copies nothing', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const d = line(draw);
    const from = grab(draw, d.id);
    const nudge = (chart.coordinateToPrice((chart.priceToCoordinate(from.price, 0) as number) + 1, 0) as number) - from.price;
    dragBody(chart, d.id, from, 0, nudge, true, 1);
    expect(draw.drawings()).toHaveLength(1);
  });

  it('leaves a plain drag, a handle drag and a host that turned it off to move the drawing itself', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const d = line(draw);
    dragBody(chart, d.id, grab(draw, d.id), 600, 4, false);
    expect(draw.drawings()).toHaveLength(1);
    chart.emit('drag', { id: `draw:${d.id}#1`, time: BARS[60].time, price: BARS[60].close, paneIndex: 0, modifiers: { alt: true } });
    chart.emit('drag:end', {});
    expect(draw.drawings()).toHaveLength(1);
    expect(draw.get(d.id)!.points[1]).toEqual({ time: BARS[60].time, price: BARS[60].close });
    draw.setOptions({ gestures: { dragCopy: false } });
    dragBody(chart, d.id, grab(draw, d.id), 600, 4);
    expect(draw.drawings()).toHaveLength(1);
  });

  it('lands the copy with the magnet, from its anchor nearest the grab', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { magnet: 'strong' });
    const d = line(draw);
    const a0 = { ...draw.get(d.id)!.points[0] };
    const from = { time: a0.time + 5, price: a0.price };
    chart.emit('drag', { id: `draw:${d.id}`, time: from.time + 607, price: from.price + 0.3, paneIndex: 0,
      fromTime: from.time, fromPrice: from.price, modifiers: { alt: true } });
    chart.emit('drag:end', {});
    const copy = draw.drawings()[1];
    const bar = BARS[30];
    expect(copy.points[0].time).toBe(bar.time);
    expect([bar.open, bar.high, bar.low, bar.close]).toContain(copy.points[0].price);
    expect(draw.get(d.id)!.points[0]).toEqual(a0);
  });

  it('reaches a linked chart once, at the drop, as a new drawing', () => {
    const chart = makeChart();
    const peer = makeChart();
    const draw = new DrawingController(chart);
    const peerDraw = new DrawingController(peer);
    const link = createDrawingLinkGroup({ enabled: true });
    const context = { symbol: 'RELIANCE', exchange: 'NSE' };
    link.add(chart, draw, () => context);
    link.add(peer, peerDraw, () => context);
    const d = line(draw);
    expect(peerDraw.drawings()).toHaveLength(1);
    dragBody(chart, d.id, grab(draw, d.id), 600, 4, true, 3, false);
    expect(peerDraw.drawings()).toHaveLength(1);
    chart.emit('drag:end', {});
    expect(peerDraw.drawings()).toHaveLength(2);
    expect(peerDraw.drawings()[1].points.map((p) => p.time)).toEqual(draw.drawings()[1].points.map((p) => p.time));
    link.destroy();
    peerDraw.destroy();
  });
});
