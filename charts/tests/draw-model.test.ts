/**
 * The 2.0 drawing model as the controller exposes it: what `add` fills in,
 * what a patch merges, what a batch records as history, what `toJSON` and
 * `fromJSON` accept and produce, and the moves (nudge, duplicate) that work in
 * screen distance.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import { DrawingController, registerDrawingTool, DRAWING_STATE_VERSION } from '../src/draw/index';
import type { DrawingChartHost } from '../src/draw/controller';
import type { Bar } from '../src/model/bar';
import type { DataLayer } from '../src/model/data-layer';
import type { Drawing, DrawingsDocument } from '../src/draw/types';

const W = 800;
const H = 600;

beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
  // A tool with default text, so the merge is testable without depending on
  // which built-in happens to declare one.
  registerDrawingTool({
    id: 'test-note', name: 'Test note', points: 1,
    defaultStyle: { color: '#123456' },
    defaultText: { value: 'Note', fontSize: 14 },
    draw: () => {}, distance: () => 0,
  });
});

const bars = (n: number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = 100 + Math.sin(i / 4) * 5;
    return { time: 1700000000 + i * 60, open: c, high: c + 2, low: c - 2, close: c, volume: 10 };
  });

/** A measured chart; see tests/compare.test.ts for why both halves matter. */
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

/** The least a host can be: no pixel mapping at all. */
function stubHost(): DrawingChartHost {
  return {
    on: () => () => {},
    emit: () => {},
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
    points: [{ time: 1700001000, price: 100 }, { time: 1700002000, price: 104 }],
    ...extra,
  });

describe('add', () => {
  it('fills in z-order, creation time and an id', () => {
    const draw = new DrawingController(makeChart());
    const before = Date.now();
    const d = line(draw);
    expect(d.zIndex).toBe(0);
    expect(typeof d.createdAt).toBe('number');
    expect(d.createdAt as number).toBeGreaterThanOrEqual(before);
    expect(d.id).toMatch(/^d\d+$/);
    expect(d.text).toBeUndefined();
  });

  it('keeps a z-order and id the caller supplies', () => {
    const draw = new DrawingController(makeChart());
    const d = line(draw, { id: 'mine', zIndex: -3 });
    expect(d.id).toBe('mine');
    expect(d.zIndex).toBe(-3);
  });

  it("merges the tool's default text under the caller's", () => {
    const draw = new DrawingController(makeChart());
    const plain = draw.add({ tool: 'test-note', paneIndex: 0, style: {}, points: [{ time: 1, price: 1 }] });
    expect(plain.text).toEqual({ value: 'Note', fontSize: 14 });
    expect(plain.style.color).toBe('#123456');
    const own = draw.add({
      tool: 'test-note', paneIndex: 0, style: {}, points: [{ time: 1, price: 1 }],
      text: { value: 'Mine', bold: true },
    });
    expect(own.text).toEqual({ value: 'Mine', fontSize: 14, bold: true });
  });

  it('never mints an id a restored layout already uses', () => {
    const draw = new DrawingController(makeChart());
    const first = line(draw);
    const n = Number(first.id.slice(1));
    // Restore a drawing holding the very id the counter would hand out next.
    draw.fromJSON([{ ...first, id: `d${n + 1}` }]);
    const next = line(draw);
    expect(next.id).not.toBe(`d${n + 1}`);
    expect(draw.get(`d${n + 1}`)).toBeDefined();
  });
});

describe('update', () => {
  it('merges text and props, and sets z-order', () => {
    const draw = new DrawingController(makeChart());
    const d = line(draw, { text: { value: 'a', bold: true }, props: { k: 1 } });
    expect(draw.update(d.id, { text: { value: 'b' }, props: { j: 2 }, zIndex: 5 })).toBe(true);
    expect(d.text).toEqual({ value: 'b', bold: true });
    expect(d.props).toEqual({ k: 1, j: 2 });
    expect(d.zIndex).toBe(5);
  });

  it('gives a drawing text it did not have', () => {
    const draw = new DrawingController(makeChart());
    const d = line(draw);
    draw.update(d.id, { text: { value: 'label' } });
    expect(d.text).toEqual({ value: 'label' });
  });

  it('ignores a z-order that is not a number', () => {
    const draw = new DrawingController(makeChart());
    const d = line(draw);
    draw.update(d.id, { zIndex: Number.NaN });
    expect(d.zIndex).toBe(0);
  });

  it('answers false for an unknown id and records nothing', () => {
    const draw = new DrawingController(makeChart());
    expect(draw.update('nope', { locked: true })).toBe(false);
    expect(draw.canUndo()).toBe(false);
  });
});

describe('updateMany and removeMany', () => {
  it('patches several drawings as one undo entry', () => {
    const draw = new DrawingController(makeChart());
    const a = line(draw);
    const b = line(draw);
    draw.updateMany([
      { id: a.id, patch: { style: { color: '#f00' } } },
      { id: b.id, patch: { style: { color: '#0f0' } } },
      { id: 'nope', patch: { style: { color: '#00f' } } },
    ]);
    expect(a.style.color).toBe('#f00');
    expect(b.style.color).toBe('#0f0');
    expect(draw.undo()).toBe(true);
    expect(draw.get(a.id)?.style.color).toBeUndefined();
    expect(draw.get(b.id)?.style.color).toBeUndefined();
  });

  it('records nothing when no patch names a live drawing', () => {
    const draw = new DrawingController(makeChart());
    line(draw);
    draw.fromJSON(draw.toJSON());        // keeps the drawing, clears the history
    draw.updateMany([{ id: 'nope', patch: { locked: true } }]);
    expect(draw.canUndo()).toBe(false);
  });

  it('removes several drawings as one undo entry and drops them from the selection', () => {
    const draw = new DrawingController(makeChart());
    const a = line(draw);
    const b = line(draw);
    const c = line(draw);
    draw.select([a.id, b.id, c.id]);
    draw.removeMany([a.id, c.id, 'nope']);
    expect(draw.drawings().map((d) => d.id)).toEqual([b.id]);
    expect(draw.selection()).toEqual([b.id]);
    expect(draw.undo()).toBe(true);
    expect(draw.drawings()).toHaveLength(3);
  });
});

describe('events', () => {
  it('reports every change on drawing:change with its kind', () => {
    const chart = makeChart();
    const seen: { ids: string[]; kind: string }[] = [];
    chart.on('drawing:change', (p) => seen.push(p as { ids: string[]; kind: string }));
    const draw = new DrawingController(chart);
    const a = line(draw);
    draw.update(a.id, { locked: true });
    draw.setZIndex(a.id, 2);
    draw.remove(a.id);
    expect(seen.map((s) => s.kind)).toEqual(['add', 'update', 'reorder', 'remove']);
    for (const s of seen) expect(s.ids).toEqual([a.id]);
  });

  it('still emits the per-drawing draw:* events hosts already listen to', () => {
    const chart = makeChart();
    const seen: string[] = [];
    for (const ev of ['draw:add', 'draw:update', 'draw:remove']) chart.on(ev, () => seen.push(ev));
    const draw = new DrawingController(chart);
    const a = line(draw);
    draw.update(a.id, { visible: false });
    draw.remove(a.id);
    expect(seen).toEqual(['draw:add', 'draw:update', 'draw:remove']);
  });
});

describe('toJSON and fromJSON', () => {
  it('serialises to a versioned document of deep copies', () => {
    const draw = new DrawingController(makeChart());
    const d = draw.add({
      tool: 'fib-retracement', paneIndex: 0, style: { levels: [{ ratio: 0.5 }] },
      text: { value: 'x' }, props: { rows: [1] },
      points: [{ time: 1, price: 1 }, { time: 2, price: 2 }],
    });
    const doc = draw.toJSON();
    // Version 3 only for an interval range; this drawing has none.
    expect(doc.version).toBe(2);
    expect(DRAWING_STATE_VERSION).toBe(3);
    expect(doc.drawings).toHaveLength(1);
    expect(doc.drawings[0]).toEqual(d);
    // A host mutating the snapshot must not reach the model.
    doc.drawings[0].style.levels?.push({ ratio: 1 });
    (doc.drawings[0].props?.rows as number[]).push(2);
    doc.drawings[0].text!.value = 'y';
    expect(d.style.levels).toHaveLength(1);
    expect(d.props?.rows).toEqual([1]);
    expect(d.text?.value).toBe('x');
  });

  it('writes the document into the chart state and reads it back', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    line(draw, { zIndex: -1 });
    const state = chart.drawingState() as DrawingsDocument;
    expect(state.version).toBe(2);
    expect(state.drawings[0].zIndex).toBe(-1);

    const other = makeChart();
    other.setDrawingState(JSON.parse(JSON.stringify(state)));
    const restored = new DrawingController(other);
    expect(restored.drawings()).toHaveLength(1);
    expect(restored.drawings()[0].zIndex).toBe(-1);
  });

  it('accepts a 1.9.x array and lifts its text fields', () => {
    const draw = new DrawingController(makeChart());
    draw.fromJSON([
      {
        id: 'old-1', tool: 'text', paneIndex: 0, points: [{ time: 1, price: 2 }],
        style: {
          color: '#abc', text: 'Hello', fontColor: '#fff', fontWeight: 'bold', fontStyle: 'italic',
          textAlign: 'center', textVAlign: 'bottom', textPosition: 'outside', fontSize: 16,
        },
      },
      {
        id: 'old-2', tool: 'fib-retracement', paneIndex: 0, locked: true,
        points: [{ time: 1, price: 2 }, { time: 3, price: 4 }],
        style: { levels: [0, 0.5, 1] },
      },
    ]);
    const [t, f] = draw.drawings();
    expect(t.id).toBe('old-1');
    expect(t.text).toEqual({
      value: 'Hello', color: '#fff', bold: true, italic: true,
      align: 'center', valign: 'bottom', position: 'outside', fontSize: 16,
    });
    expect(t.style).toEqual({ color: '#abc' });
    expect(t.zIndex).toBe(0);
    expect(t.createdAt).toBeUndefined();
    expect(f.id).toBe('old-2');
    expect(f.locked).toBe(true);
    expect(f.style.levels?.map((l) => l.ratio)).toEqual([0, 0.5, 1]);
    // Array order is paint order, so it is preserved exactly.
    expect(draw.drawings().map((d) => d.id)).toEqual(['old-1', 'old-2']);
  });

  it('restores a 1.9.x array left in the chart state, and writes a document back', () => {
    const chart = makeChart();
    chart.setDrawingState([{
      id: 'legacy', tool: 'rectangle', paneIndex: 0,
      points: [{ time: 1, price: 2 }, { time: 3, price: 4 }],
      style: { color: '#abc', text: 'zone' },
    }]);
    const draw = new DrawingController(chart);
    expect(draw.drawings()).toHaveLength(1);
    expect(draw.drawings()[0].text).toEqual({ value: 'zone' });
    expect((chart.drawingState() as DrawingsDocument).version).toBe(2);
  });

  it('accepts a document unchanged', () => {
    const draw = new DrawingController(makeChart());
    const d = line(draw, { zIndex: 3, text: { value: 'x' } });
    const doc = draw.toJSON();
    draw.fromJSON(doc);
    expect(draw.drawings()).toEqual([d]);
  });

  it('keeps a drawing whose tool is not registered, for a tool that registers later', () => {
    const draw = new DrawingController(makeChart());
    draw.fromJSON([{ id: 'x', tool: 'plugin-tool', paneIndex: 0, points: [{ time: 1, price: 2 }], style: {} }]);
    expect(draw.drawings()).toHaveLength(1);
  });

  it('never throws on garbage, and clears the selection and history', () => {
    const draw = new DrawingController(makeChart());
    const d = line(draw);
    draw.select(d.id);
    for (const junk of ['nope', 42, null, undefined, {}, { version: 2, drawings: 'x' }, [1, 'two', null]]) {
      expect(() => draw.fromJSON(junk)).not.toThrow();
      expect(draw.drawings()).toEqual([]);
    }
    expect(draw.selection()).toEqual([]);
    expect(draw.canUndo()).toBe(false);
  });

  it('gives two drawings sharing an id their own ids', () => {
    const draw = new DrawingController(makeChart());
    const entry = { id: 'dup', tool: 'trend-line', paneIndex: 0, points: [{ time: 1, price: 2 }, { time: 3, price: 4 }], style: {} };
    draw.fromJSON([entry, entry]);
    const ids = draw.drawings().map((d) => d.id);
    expect(ids).toHaveLength(2);
    expect(new Set(ids).size).toBe(2);
  });
});

describe('duplicate', () => {
  it('clones with an offset, fresh ids, and selects the clones as one undo entry', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const a = draw.add({
      tool: 'trend-line', paneIndex: 0, style: { color: '#f00' }, text: { value: 'a' },
      points: [
        { time: chart.coordinateToTime(200), price: chart.coordinateToPrice(300, 0) as number },
        { time: chart.coordinateToTime(400), price: chart.coordinateToPrice(200, 0) as number },
      ],
    });
    const b = line(draw);
    const clones = draw.duplicate([a.id, b.id, 'nope']);
    expect(clones).toHaveLength(2);
    expect(draw.drawings()).toHaveLength(4);
    expect(draw.selection()).toEqual(clones.map((c) => c.id));
    expect(clones[0].id).not.toBe(a.id);
    expect(clones[0].style).toEqual(a.style);
    expect(clones[0].text).toEqual(a.text);
    expect(clones[0].text).not.toBe(a.text);
    // Two bars along and 16 px down, like a paste.
    expect(clones[0].points[0].time).toBe(a.points[0].time + 120);
    const y0 = chart.priceToCoordinate(a.points[0].price, 0) as number;
    const y1 = chart.priceToCoordinate(clones[0].points[0].price, 0) as number;
    expect(y1 - y0).toBeCloseTo(16, 6);
    expect(draw.undo()).toBe(true);
    expect(draw.drawings()).toHaveLength(2);
  });

  it('returns nothing and records nothing for unknown ids', () => {
    const draw = new DrawingController(makeChart());
    line(draw);
    draw.fromJSON(draw.toJSON());        // keeps the drawing, clears the history
    expect(draw.duplicate(['nope'])).toEqual([]);
    expect(draw.drawings()).toHaveLength(1);
    expect(draw.canUndo()).toBe(false);
  });
});

describe('nudge', () => {
  it('moves by a screen distance on both axes, as one undo entry', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const d = draw.add({
      tool: 'trend-line', paneIndex: 0, style: {},
      points: [
        { time: chart.coordinateToTime(200), price: chart.coordinateToPrice(300, 0) as number },
        { time: chart.coordinateToTime(400), price: chart.coordinateToPrice(200, 0) as number },
      ],
    });
    const before = d.points.map((p) => ({ ...p }));
    draw.nudge([d.id], 10, -7);
    draw.nudge([d.id], 5, 0);
    for (let i = 0; i < 2; i++) {
      const dx = chart.timeToCoordinate(d.points[i].time) - chart.timeToCoordinate(before[i].time);
      const dy = (chart.priceToCoordinate(d.points[i].price, 0) as number)
        - (chart.priceToCoordinate(before[i].price, 0) as number);
      expect(dx).toBeCloseTo(15, 6);
      expect(dy).toBeCloseTo(-7, 6);
    }
    // Each nudge is its own undo entry; two undos restore the start.
    expect(draw.undo()).toBe(true);
    expect(draw.undo()).toBe(true);
    expect(draw.get(d.id)?.points).toEqual(before);
  });

  it('leaves locked drawings and unknown ids alone, and records nothing for a zero move', () => {
    const draw = new DrawingController(makeChart());
    const locked = line(draw, { locked: true });
    const before = locked.points.map((p) => ({ ...p }));
    draw.nudge([locked.id, 'nope'], 10, 10);
    expect(draw.get(locked.id)?.points).toEqual(before);
    // The only history entry is the add: undoing it empties the chart, so the
    // nudge recorded nothing.
    expect(draw.undo()).toBe(true);
    expect(draw.drawings()).toHaveLength(0);
    expect(draw.canUndo()).toBe(false);

    const free = line(draw);
    draw.nudge([free.id], 0, 0);
    expect(draw.undo()).toBe(true);
    expect(draw.drawings()).toHaveLength(0);
    expect(draw.canUndo()).toBe(false);
  });

  it('assumes the default bar spacing on a host without a time mapping', () => {
    // 300 s bars at 8 px each: 16 px is two bars.
    const draw = new DrawingController(stubHost());
    const d = line(draw);
    const t0 = d.points[0].time;
    const p0 = d.points[0].price;
    draw.nudge([d.id], 16, 10);
    expect(d.points[0].time).toBe(t0 + 600);
    expect(d.points[0].price).toBe(p0);   // no price mapping: time only
  });
});
