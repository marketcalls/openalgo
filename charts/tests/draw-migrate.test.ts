/**
 * The 1.9.x to 2.0 drawing migration. The fixtures below are shaped exactly as
 * the 1.9.2 controller persisted them: `toJSON()` was a bare array, ids were
 * `d1, d2, ...`, and every tool's `defaultStyle` had been merged into the style
 * bag on add, text keys included. A host that saved that array per pane must
 * read it back into 2.0 with nothing missing.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import { DrawingController, DRAWING_STATE_VERSION, migrateDrawings as fromTier } from '../src/draw/index';
import { migrateDrawings } from '../src/draw/migrate';
import { levelColor, cycleColor, LEVEL_NEUTRAL } from '../src/draw/levels';
import {
  decodeClipboardPayload, encodeClipboardPayload, DRAWING_CLIPBOARD_KEY, DRAWING_CLIPBOARD_VERSION,
} from '../src/draw/clipboard';
import type { Bar } from '../src/model/bar';
import type { Drawing, DrawingsDocument, FibLevel } from '../src/draw/types';

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

/** The 1.9.x text keys; none may survive in a 2.0 style bag. */
const LEGACY_TEXT_KEYS = [
  'text', 'fontSize', 'fontFamily', 'fontWeight', 'fontStyle', 'background', 'backgroundColor',
  'backgroundOpacity', 'border', 'borderColor', 'wrap', 'wrapWidth', 'textAlign', 'textVAlign',
  'textPosition', 'fontColor',
];

/** A brush stroke the way a pointer produces one: a few hundred close samples. */
const strokePoints = (n: number): { time: number; price: number }[] =>
  Array.from({ length: n }, (_, i) => ({ time: 1700006000 + i * 7, price: 100 + Math.sin(i / 9) * 3 }));

/**
 * A layout as 1.9.2 wrote it. Fresh objects on every call so a test can mutate
 * its copy. The style bags carry the 1.9.2 tool defaults verbatim.
 */
function v1Layout(): unknown[] {
  return [
    {
      id: 'd1', tool: 'text', paneIndex: 0,
      points: [{ time: 1700003600, price: 101.5 }],
      style: {
        text: 'Breakout\nwatch', fontSize: 14, fontWeight: 'bold', fontStyle: 'normal',
        background: true, backgroundColor: '#1e222d', backgroundOpacity: 0.8,
        border: true, borderColor: '#2962ff', wrap: true, wrapWidth: 220,
        textAlign: 'center', textVAlign: 'middle', fontColor: '#ffffff', fontFamily: 'Georgia',
        color: '#2962ff',
      },
    },
    {
      id: 'd2', tool: 'callout', paneIndex: 0,
      points: [{ time: 1700001200, price: 98.2 }, { time: 1700002400, price: 104.1 }],
      style: { fontSize: 12, text: 'Note', color: '#f23645', lineWidth: 1 },
    },
    {
      id: 'd3', tool: 'fib-retracement', paneIndex: 0,
      points: [{ time: 1700000600, price: 95 }, { time: 1700004200, price: 105 }],
      style: {
        showLabels: true, levels: [0, 0.382, 0.5, 0.618, 1, 1.618],
        fill: true, fillOpacity: 0.06, color: '#089981',
      },
    },
    {
      id: 'd4', tool: 'long-position', paneIndex: 0,
      points: [
        { time: 1700003000, price: 100 }, { time: 1700005400, price: 103 }, { time: 1700005400, price: 98.5 },
      ],
      style: { showLabels: true, fillOpacity: 0.13, accountSize: 250000, risk: 0.5 },
    },
    {
      id: 'd5', tool: 'trend-line', paneIndex: 0, locked: true, visible: false,
      points: [{ time: 1700000300, price: 96 }, { time: 1700006900, price: 106 }],
      style: { extendLeft: false, extendRight: false, color: '#ff9900', lineWidth: 2, lineStyle: 'dashed' },
    },
    {
      id: 'd6', tool: 'brush', paneIndex: 1,
      points: strokePoints(400),
      style: { lineWidth: 2 },
    },
  ];
}

const byId = (doc: DrawingsDocument, id: string): Drawing => {
  const d = doc.drawings.find((x) => x.id === id);
  if (d === undefined) throw new Error(`no drawing ${id}`);
  return d;
};

describe('a 1.9.2 layout', () => {
  it('keeps every drawing, its id and its order', () => {
    const doc = migrateDrawings(v1Layout());
    // No drawing carries an interval range, so the lowest version that holds it.
    expect(doc.version).toBe(2);
    expect(DRAWING_STATE_VERSION).toBe(3);
    expect(doc.drawings.map((d) => d.id)).toEqual(['d1', 'd2', 'd3', 'd4', 'd5', 'd6']);
    expect(doc.drawings.map((d) => d.tool)).toEqual([
      'text', 'callout', 'fib-retracement', 'long-position', 'trend-line', 'brush',
    ]);
  });

  it('lifts the text tool out of the style bag', () => {
    const t = byId(migrateDrawings(v1Layout()), 'd1');
    expect(t.text).toEqual({
      value: 'Breakout\nwatch', color: '#ffffff', fontSize: 14, fontFamily: 'Georgia', bold: true,
      align: 'center', valign: 'middle', wrap: true, wrapWidth: 220,
      background: true, backgroundColor: '#1e222d', backgroundOpacity: 0.8,
      border: true, borderColor: '#2962ff',
    });
    // `fontStyle: 'normal'` is the default, so no `italic` flag appears at all.
    expect(t.text).not.toHaveProperty('italic');
    expect(t.style).toEqual({ color: '#2962ff' });
    expect(t.points).toEqual([{ time: 1700003600, price: 101.5 }]);
  });

  it('gives a callout its label and keeps its outline', () => {
    const c = byId(migrateDrawings(v1Layout()), 'd2');
    expect(c.text).toEqual({ value: 'Note', fontSize: 12 });
    expect(c.style).toEqual({ color: '#f23645', lineWidth: 1 });
    expect(c.points).toHaveLength(2);
  });

  it('turns custom fib ratios into levels in their conventional colours', () => {
    const f = byId(migrateDrawings(v1Layout()), 'd3');
    expect(f.style.levels).toEqual([
      { ratio: 0, color: LEVEL_NEUTRAL },
      { ratio: 0.382, color: '#ff9800' },
      { ratio: 0.5, color: '#4caf50' },
      { ratio: 0.618, color: '#089981' },
      { ratio: 1, color: LEVEL_NEUTRAL },
      { ratio: 1.618, color: '#e91e63' },
    ]);
    for (const l of f.style.levels as FibLevel[]) expect(l.color).toBe(levelColor(l.ratio));
    expect(f.style).toMatchObject({ showLabels: true, fill: true, fillOpacity: 0.06, color: '#089981' });
  });

  it('keeps the position sizing inputs', () => {
    const p = byId(migrateDrawings(v1Layout()), 'd4');
    expect(p.style).toEqual({ showLabels: true, fillOpacity: 0.13, accountSize: 250000, risk: 0.5 });
    expect(p.points).toHaveLength(3);
    expect(p.text).toBeUndefined();
  });

  it('keeps a locked, hidden trend line locked and hidden', () => {
    const l = byId(migrateDrawings(v1Layout()), 'd5');
    expect(l.locked).toBe(true);
    expect(l.visible).toBe(false);
    expect(l.style).toEqual({
      extendLeft: false, extendRight: false, color: '#ff9900', lineWidth: 2, lineStyle: 'dashed',
    });
  });

  it('keeps every sample of a brush stroke, on its own pane', () => {
    const b = byId(migrateDrawings(v1Layout()), 'd6');
    expect(b.points).toEqual(strokePoints(400));
    expect(b.paneIndex).toBe(1);
    expect(b.style).toEqual({ lineWidth: 2 });
  });

  it('produces the v2 shape for every drawing', () => {
    for (const d of migrateDrawings(v1Layout()).drawings) {
      expect(typeof d.id).toBe('string');
      expect(d.id).not.toBe('');
      expect(typeof d.zIndex).toBe('number');
      expect(d.zIndex).toBe(0);
      expect(d.createdAt).toBeUndefined();
      expect(Number.isInteger(d.paneIndex)).toBe(true);
      for (const key of LEGACY_TEXT_KEYS) expect(d.style, `${d.id}.style.${key}`).not.toHaveProperty(key);
      if (d.style.levels !== undefined) {
        for (const l of d.style.levels) {
          expect(typeof l.ratio).toBe('number');
          expect(typeof l.color).toBe('string');
        }
      }
      if (d.text !== undefined) expect(typeof d.text.value).toBe('string');
      for (const p of d.points) {
        expect(Number.isFinite(p.time)).toBe(true);
        expect(Number.isFinite(p.price)).toBe(true);
      }
    }
  });

  it('is idempotent: migrating its own output changes nothing', () => {
    const once = migrateDrawings(v1Layout());
    expect(migrateDrawings(once)).toEqual(once);
    expect(migrateDrawings(JSON.parse(JSON.stringify(once)))).toEqual(once);
  });

  it('round-trips through a controller: fromJSON(v1), toJSON() is a document fromJSON takes again', () => {
    const draw = new DrawingController(makeChart());
    draw.fromJSON(v1Layout());
    expect(draw.drawings()).toHaveLength(6);
    const doc = draw.toJSON();
    expect(doc.version).toBe(2);
    expect(doc).toEqual(migrateDrawings(v1Layout()));

    const again = new DrawingController(makeChart());
    again.fromJSON(JSON.parse(JSON.stringify(doc)));
    expect(again.toJSON()).toEqual(doc);
    expect(again.drawings().map((d) => d.id)).toEqual(['d1', 'd2', 'd3', 'd4', 'd5', 'd6']);
    expect(again.get('d1')?.text?.value).toBe('Breakout\nwatch');
    expect(again.get('d3')?.style.levels?.map((l) => l.ratio)).toEqual([0, 0.382, 0.5, 0.618, 1, 1.618]);
  });

  it('is what the chart state holds after a 1.9.x save is restored', () => {
    const chart = makeChart();
    chart.setDrawingState(v1Layout());
    new DrawingController(chart);
    const state = chart.drawingState() as DrawingsDocument;
    expect(state.version).toBe(2);
    expect(state.drawings.map((d) => d.id)).toEqual(['d1', 'd2', 'd3', 'd4', 'd5', 'd6']);
    expect(state.drawings[0].text?.value).toBe('Breakout\nwatch');
  });
});

describe('a version 2 document', () => {
  it('passes through unchanged', () => {
    const draw = new DrawingController(makeChart());
    draw.add({
      tool: 'rectangle', paneIndex: 0, zIndex: -2, locked: true, visible: false,
      style: { color: '#123456', fill: true, fillOpacity: 0.3 },
      text: { value: 'zone', color: '#fff', bold: true, italic: false, align: 'center', position: 'inside' },
      props: { note: 'breakout', tags: ['a', 'b'], grid: { rows: 2, cells: [[1, 2], [3, 4]] }, tail: null },
      points: [{ time: 1700000000, price: 100 }, { time: 1700000600, price: 110 }],
    });
    draw.add({
      tool: 'fib-retracement', paneIndex: 0, zIndex: 3,
      style: { levels: [{ ratio: 0.5, color: '#0f0', enabled: false, label: 'half' }, { ratio: 1 }], showLabels: true },
      text: { value: '' },
      points: [{ time: 1700000000, price: 100 }, { time: 1700000600, price: 110 }],
    });
    draw.add({
      tool: 'fib-time-zone', paneIndex: 1,
      style: { levels: [{ ratio: 1 }, { ratio: 2 }, { ratio: 3 }], color: '#abc' },
      points: [{ time: 1700000000, price: 100 }, { time: 1700000600, price: 110 }],
    });
    const doc = draw.toJSON();
    expect(doc.drawings.every((d) => typeof d.createdAt === 'number')).toBe(true);
    const out = migrateDrawings(doc);
    expect(out).toEqual(doc);
    // A level with no colour of its own stays that way: the tool decides the
    // fallback (a time zone takes the drawing's colour, a fib the convention).
    expect(out.drawings[1].style.levels?.[1]).toEqual({ ratio: 1 });
    expect(out.drawings[2].style.levels).toEqual([{ ratio: 1 }, { ratio: 2 }, { ratio: 3 }]);
    // A document, not the same object: a host mutating one must not touch the other.
    expect(out).not.toBe(doc);
    expect(out.drawings[0]).not.toBe(doc.drawings[0]);
  });

  it('keeps pen pressure on a brush sample, and drops one outside 0..1', () => {
    // A stroke reloaded without its pressure paints at the configured width,
    // which is graceful and lossy; the field is the user's own hand.
    const doc: DrawingsDocument = {
      version: DRAWING_STATE_VERSION,
      drawings: [{
        id: 'b', tool: 'brush', paneIndex: 0, zIndex: 0, style: { pressure: true },
        points: [
          { time: 1700000000, price: 100, pressure: 0.25 },
          { time: 1700000060, price: 101 },
          { time: 1700000120, price: 102, pressure: 2 } as unknown as { time: number; price: number },
        ],
      }],
    };
    const out = migrateDrawings(doc);
    expect(out.drawings[0].points).toEqual([
      { time: 1700000000, price: 100, pressure: 0.25 },
      { time: 1700000060, price: 101 },
      { time: 1700000120, price: 102 },
    ]);
  });

  it('keeps an empty level list empty, and every level field it knows', () => {
    const doc = migrateDrawings({
      version: 2, drawings: [{
        id: 'a', tool: 'fib-extension', paneIndex: 0, zIndex: 0, style: { levels: [] },
        points: [{ time: 1, price: 2 }, { time: 3, price: 4 }, { time: 5, price: 6 }],
      }],
    });
    expect(doc.drawings[0].style.levels).toEqual([]);
  });
});

/**
 * A document exactly as 2.5.8 persisted one: version 2, a note pinned to the
 * screen, a shape placed in the series band with a policy, a group, and every
 * optional field a drawing then had. Fresh objects on every call.
 */
function v2Document(): DrawingsDocument {
  return {
    version: 2,
    drawings: [
      {
        id: 'd1', tool: 'rectangle', paneIndex: 0, zIndex: 1, createdAt: 1727400000000,
        points: [{ time: 1700000000, price: 2140.5 }, { time: 1700003600, price: 2162.25 }],
        style: { color: '#089981', fill: true, fillOpacity: 0.12 },
        text: { value: 'Demand', color: '#ffffff', position: 'outside' },
        props: { note: 'weekly low' }, locked: true, stackAbove: 'source:primary',
        policy: { editable: false, listed: true },
      },
      {
        id: 'd2', tool: 'text', paneIndex: 0, zIndex: 0, createdAt: 1727400001000, points: [],
        space: 'viewport', viewportPoints: [{ x: 0.05, y: 0.08 }],
        style: {}, text: { value: 'Plan: fade the open', fontSize: 14 },
      },
      {
        id: 'd3', tool: 'trend-line', paneIndex: 0, zIndex: -1, createdAt: 1727400002000, visible: false,
        points: [{ time: 1700000900, price: 2138 }, { time: 1700009000, price: 2171.75 }],
        style: { lineWidth: 2, lineStyle: 'dashed', extendRight: true },
      },
    ],
    groups: [{ id: 'group-1', name: 'Morning', members: ['d1', 'd3'] }],
  };
}

describe('version 2 to version 3', () => {
  it('loads a version 2 document unchanged, version and all', () => {
    const doc = v2Document();
    expect(migrateDrawings(doc)).toEqual(v2Document());
    expect(migrateDrawings(JSON.parse(JSON.stringify(doc)))).toEqual(v2Document());
    // Through a controller and the chart state, and back out: nothing moves.
    const chart = makeChart();
    chart.setDrawingState(doc);
    const draw = new DrawingController(chart);
    expect(draw.toJSON()).toEqual(v2Document());
    expect(chart.drawingState()).toEqual(v2Document());
    const again = new DrawingController(makeChart());
    again.fromJSON(JSON.parse(JSON.stringify(draw.toJSON())));
    expect(JSON.stringify(again.toJSON())).toBe(JSON.stringify(draw.toJSON()));
  });

  it('writes version 3 only while a drawing carries a range', () => {
    const draw = new DrawingController(makeChart());
    draw.fromJSON(v2Document());
    draw.update('d3', { intervals: { from: '1m', to: '1h' } });
    expect(draw.toJSON().version).toBe(3);
    expect(draw.toJSON().version).toBe(DRAWING_STATE_VERSION);
    draw.update('d3', { intervals: null });
    expect(draw.toJSON()).toEqual(v2Document());
  });

  it('round-trips a version 3 document through a controller, text, history and the migration', () => {
    const v3 = v2Document();
    v3.version = 3;
    v3.drawings[0].intervals = { from: '15m', to: 'D' };
    v3.drawings[2].intervals = { to: '1h' };
    expect(migrateDrawings(v3)).toEqual(v3);
    expect(migrateDrawings(migrateDrawings(v3))).toEqual(v3);
    const draw = new DrawingController(makeChart());
    draw.fromJSON(JSON.parse(JSON.stringify(v3)));
    expect(draw.toJSON()).toEqual(v3);
    const again = new DrawingController(makeChart());
    again.fromJSON(JSON.parse(JSON.stringify(draw.toJSON())));
    expect(again.toJSON()).toEqual(v3);
    // An undo restores a snapshot through the same migration: the ranges stay.
    again.update('d2', { style: { color: '#2962ff' } });
    expect(again.undo()).toBe(true);
    expect(again.toJSON()).toEqual(v3);
  });

  it('drops a range that names no usable bound on load, and keeps the drawing', () => {
    const doc = migrateDrawings({
      version: 3, drawings: [
        { id: 'a', tool: 'trend-line', paneIndex: 0, points: [{ time: 1, price: 2 }, { time: 3, price: 4 }], intervals: { from: 7 } },
        { id: 'b', tool: 'trend-line', paneIndex: 0, points: [{ time: 1, price: 2 }, { time: 3, price: 4 }], intervals: '1m-1h' },
        { id: 'c', tool: 'trend-line', paneIndex: 0, points: [{ time: 1, price: 2 }, { time: 3, price: 4 }], intervals: { from: 7, to: '1h' } },
      ],
    });
    expect(doc.drawings.map((d) => d.id)).toEqual(['a', 'b', 'c']);
    expect(doc.drawings[0]).not.toHaveProperty('intervals');
    expect(doc.drawings[1]).not.toHaveProperty('intervals');
    expect(doc.drawings[2].intervals).toEqual({ to: '1h' });
    expect(doc.version).toBe(3);
  });

  it('pastes a range whole or not at all, where a load is lenient', () => {
    const payload = (intervals: unknown) => JSON.stringify({
      [DRAWING_CLIPBOARD_KEY]: { version: 3, drawings: [{ tool: 'trend-line', paneIndex: 0, intervals, points: [{ time: 1, price: 2 }, { time: 3, price: 4 }] }] },
    });
    expect(decodeClipboardPayload(payload({ from: '1m', to: '1h' }))?.[0].intervals).toEqual({ from: '1m', to: '1h' });
    expect(decodeClipboardPayload(payload({ from: 7, to: '1h' }))).toBeNull();
    expect(decodeClipboardPayload(payload({}))).toBeNull();
    expect(decodeClipboardPayload(payload('1m'))).toBeNull();
  });
});

/**
 * What a reader older than the document does with it. An older build's
 * clipboard refuses a payload newer than it reads, which this build's gate
 * shows for a version from the future; a copy is written as the lowest
 * version that holds it, so only a copy carrying a range is one an older
 * build refuses. An older build's migration never refused a document: it
 * keeps what it knows, which this build shows for a later version, so an
 * older build shows a version 3 drawing on every interval and drops its
 * range when it next saves. The skill reference and the website say so.
 */
describe('an older reader and a newer document', () => {
  const entry = { tool: 'trend-line', paneIndex: 0, points: [{ time: 1, price: 2 }, { time: 3, price: 4 }] };

  it('writes a copy as version 3 only when it carries a range, so a version 2 reader takes the rest', () => {
    const version = (drawings: Drawing[]) =>
      (JSON.parse(encodeClipboardPayload(drawings)) as Record<string, { version: number }>)[DRAWING_CLIPBOARD_KEY].version;
    expect(version([{ ...entry, id: 'a', zIndex: 0, style: {} }])).toBe(2);
    expect(version([{ ...entry, id: 'a', zIndex: 0, style: {} }, { ...entry, id: 'b', zIndex: 0, style: {}, intervals: { to: '1h' } }])).toBe(3);
  });

  it('refuses a clipboard payload newer than it reads', () => {
    const text = (version: number) => JSON.stringify({ [DRAWING_CLIPBOARD_KEY]: { version, drawings: [entry] } });
    expect(decodeClipboardPayload(text(DRAWING_CLIPBOARD_VERSION))).toHaveLength(1);
    expect(decodeClipboardPayload(text(DRAWING_CLIPBOARD_VERSION + 1))).toBeNull();
  });

  it('reads a document newer than it knows by keeping what it knows, never by emptying the chart', () => {
    const later = {
      version: DRAWING_STATE_VERSION + 1, layers: ['a later field'],
      drawings: [{ ...entry, id: 'x', style: { color: '#f23645' }, intervals: { to: '1h' }, laterField: { any: 1 } }],
    };
    const doc = migrateDrawings(later);
    expect(doc.version).toBe(3);
    expect(doc.drawings).toHaveLength(1);
    expect(doc.drawings[0]).toEqual({ ...entry, id: 'x', zIndex: 0, style: { color: '#f23645' }, intervals: { to: '1h' } });
    expect(doc).not.toHaveProperty('layers');
  });
});

describe('garbage', () => {
  it('yields an empty document and never throws', () => {
    const junk: unknown[] = [
      null, undefined, 'nope', 42, true, {}, { version: 2 }, { version: 2, drawings: 'x' },
      { drawings: null }, [1, 'two', null], [[]], [[{ tool: 'text' }]],
      [{ tool: 'trend-line' }],                                             // no points
      [{ tool: 'trend-line', points: [] }],                                 // empty points
      [{ tool: '', points: [{ time: 1, price: 2 }] }],                      // no tool
      [{ tool: 7, points: [{ time: 1, price: 2 }] }],
      [{ tool: 'trend-line', points: [{ time: 1, price: null }] }],
      [{ tool: 'trend-line', points: [{ time: 'soon', price: 2 }] }],
      [{ tool: 'trend-line', points: [{ time: 1, price: 2 }], paneIndex: -1 }],
      [{ tool: 'trend-line', points: [{ time: 1, price: 2 }], paneIndex: 1.5 }],
      [{ tool: 'trend-line', points: [{ time: 1, price: 2 }], paneIndex: 'main' }],
    ];
    for (const input of junk) {
      let doc: DrawingsDocument | undefined;
      expect(() => { doc = migrateDrawings(input); }, JSON.stringify(input)).not.toThrow();
      expect(doc, JSON.stringify(input)).toEqual({ version: 2, drawings: [] });
    }
  });

  it('drops only the entries it cannot draw, in place', () => {
    const good = { id: 'ok', tool: 'trend-line', paneIndex: 0, points: [{ time: 1, price: 2 }, { time: 3, price: 4 }], style: {} };
    const doc = migrateDrawings([42, good, { tool: 'trend-line', points: [{ time: Number.NaN, price: 1 }] }, { ...good, id: 'ok2' }]);
    expect(doc.drawings.map((d) => d.id)).toEqual(['ok', 'ok2']);
  });

  it('never lets a saved key reach Object.prototype', () => {
    const text = '[{"id":"x","tool":"trend-line","points":[{"time":1,"price":2}],'
      + '"style":{"__proto__":{"polluted":true},"color":"#abc"},'
      + '"props":{"__proto__":{"polluted":true},"k":1},'
      + '"text":{"value":"x","__proto__":{"polluted":true}},"__proto__":{"polluted":true}}]';
    const doc = migrateDrawings(JSON.parse(text));
    expect(doc.drawings).toHaveLength(1);
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
    expect(Object.getPrototypeOf(doc.drawings[0].props)).toBe(Object.prototype);
    expect(doc.drawings[0].props).toEqual({ k: 1 });
    expect(doc.drawings[0].style).toEqual({ color: '#abc' });
  });
});

describe('fields', () => {
  const entry = (extra: Record<string, unknown>): unknown => ({
    id: 'e', tool: 'trend-line', paneIndex: 0, style: {},
    points: [{ time: 1, price: 2 }, { time: 3, price: 4 }],
    ...extra,
  });
  const one = (extra: Record<string, unknown>): Drawing => migrateDrawings([entry(extra)]).drawings[0];

  it('drops unknown fields at every level', () => {
    const d = one({
      meta: { owner: 'me' }, selected: true,
      style: { color: '#abc', glow: 4, onDraw: null, nested: { a: 1 }, levels: [0.5] },
      text: { value: 'hi', onClick: 'x', size: 3 },
    });
    expect(d).not.toHaveProperty('meta');
    expect(d).not.toHaveProperty('selected');
    expect(d.style).toEqual({ color: '#abc', levels: [{ ratio: 0.5, color: levelColor(0.5) }] });
    expect(d.text).toEqual({ value: 'hi' });
  });

  it('drops an optional field with the wrong type and keeps the drawing', () => {
    const d = one({ locked: 'yes', visible: 1, zIndex: 'top', createdAt: 'yesterday', style: 'red', props: 'none', text: 'hello' });
    expect(d.id).toBe('e');
    expect(d).not.toHaveProperty('locked');
    expect(d).not.toHaveProperty('visible');
    expect(d.zIndex).toBe(0);
    expect(d).not.toHaveProperty('createdAt');
    expect(d.style).toEqual({});
    expect(d).not.toHaveProperty('props');
    expect(d).not.toHaveProperty('text');
  });

  it('keeps z-order, creation time and an absent pane as pane zero', () => {
    const d = one({ zIndex: -4, createdAt: 1700000000000, paneIndex: undefined });
    expect(d.zIndex).toBe(-4);
    expect(d.createdAt).toBe(1700000000000);
    expect(d.paneIndex).toBe(0);
  });

  it('validates the style bag key by key', () => {
    const d = one({
      style: {
        color: 7, fillColor: '#f00', lineWidth: 'fat', fillOpacity: 0.5, lineStyle: 'wavy',
        fill: 'yes', extendRight: true, showLabels: false, showStats: true, pressure: false,
        accountSize: Number.NaN, risk: 2,
      },
    });
    expect(d.style).toEqual({
      fillColor: '#f00', fillOpacity: 0.5, extendRight: true, showLabels: false,
      showStats: true, pressure: false, risk: 2,
    });
  });

  it('validates the text block key by key and needs a value', () => {
    expect(one({ text: { color: '#fff', bold: true } })).not.toHaveProperty('text');
    const d = one({
      text: {
        value: 'v', color: 1, fontSize: '12', fontFamily: 'Mono', bold: 'yes', italic: true,
        align: 'sideways', valign: 'bottom', position: 'inside', wrap: true, wrapWidth: 100,
        background: true, backgroundColor: '#000', backgroundOpacity: 0.5, border: false, borderColor: 3,
      },
    });
    expect(d.text).toEqual({
      value: 'v', fontFamily: 'Mono', italic: true, valign: 'bottom', position: 'inside',
      wrap: true, wrapWidth: 100, background: true, backgroundColor: '#000', backgroundOpacity: 0.5,
      border: false,
    });
  });

  it('prefers a text block on the entry to the 1.9.x style keys', () => {
    const d = one({ text: { value: 'new' }, style: { text: 'old', fontColor: '#fff' } });
    expect(d.text).toEqual({ value: 'new' });
    expect(d.style).toEqual({});
    // A block without a value is no block, so the old keys fill the gap.
    const back = one({ text: { color: '#0f0' }, style: { text: 'old', fontColor: '#fff' } });
    expect(back.text).toEqual({ value: 'old', color: '#fff' });
  });

  it('maps every 1.9.x text key to its new name', () => {
    const d = one({
      style: {
        text: 'T', fontColor: '#fff', fontSize: 16, fontFamily: 'Serif', fontWeight: 'bold', fontStyle: 'italic',
        textAlign: 'right', textVAlign: 'top', textPosition: 'outside', wrap: false, wrapWidth: 300,
        background: true, backgroundColor: '#111', backgroundOpacity: 0.9, border: true, borderColor: '#222',
        color: '#abc',
      },
    });
    expect(d.text).toEqual({
      value: 'T', color: '#fff', fontSize: 16, fontFamily: 'Serif', bold: true, italic: true,
      align: 'right', valign: 'top', position: 'outside', wrap: false, wrapWidth: 300,
      background: true, backgroundColor: '#111', backgroundOpacity: 0.9, border: true, borderColor: '#222',
    });
    expect(d.style).toEqual({ color: '#abc' });
    // A 1.9.x shape with text styling but no text has no label to keep.
    const shape = one({ style: { color: '#abc', fontSize: 14, textAlign: 'left', textPosition: 'inside' } });
    expect(shape.text).toBeUndefined();
    expect(shape.style).toEqual({ color: '#abc' });
  });

  it('keeps an empty text value: a cleared label is still a label', () => {
    expect(one({ style: { text: '' } }).text).toEqual({ value: '' });
  });
});

describe('levels', () => {
  const fib = (tool: string, levels: unknown): FibLevel[] | undefined =>
    migrateDrawings([{
      id: 'l', tool, paneIndex: 0, style: { levels },
      points: [{ time: 1, price: 2 }, { time: 3, price: 4 }, { time: 5, price: 6 }],
    }]).drawings[0].style.levels;

  it('colours bare ratios by the family convention', () => {
    expect(fib('fib-extension', [0, 0.618, 1.618])).toEqual([
      { ratio: 0, color: LEVEL_NEUTRAL }, { ratio: 0.618, color: '#089981' }, { ratio: 1.618, color: '#e91e63' },
    ]);
    expect(fib('fib-channel', [0.5])).toEqual([{ ratio: 0.5, color: levelColor(0.5) }]);
    expect(fib('fib-fan', [0.382])).toEqual([{ ratio: 0.382, color: levelColor(0.382) }]);
    expect(fib('gann-box', [0.25])).toEqual([{ ratio: 0.25, color: levelColor(0.25) }]);
  });

  it('colours a Gann fan by position and leaves a time zone uncoloured', () => {
    expect(fib('gann-fan', [0.5, 1, 2])).toEqual([
      { ratio: 0.5, color: cycleColor(0) }, { ratio: 1, color: cycleColor(1) }, { ratio: 2, color: cycleColor(2) },
    ]);
    expect(fib('fib-time-zone', [1, 2, 3, 5, 8])).toEqual([
      { ratio: 1 }, { ratio: 2 }, { ratio: 3 }, { ratio: 5 }, { ratio: 8 },
    ]);
  });

  it('keeps what a level record says about itself and nothing else', () => {
    expect(fib('fib-retracement', [
      { ratio: 0.5, color: '#f00', enabled: false, label: 'half', glow: true },
      { ratio: 1, color: 5, enabled: 'no', label: null },
    ])).toEqual([{ ratio: 0.5, color: '#f00', enabled: false, label: 'half' }, { ratio: 1 }]);
  });

  it('skips a rung it cannot read, and drops a ladder with none left', () => {
    expect(fib('fib-retracement', [0.5, 'x', null, { ratio: 'a' }, { ratio: 1 }])).toEqual([
      { ratio: 0.5, color: levelColor(0.5) }, { ratio: 1 },
    ]);
    expect(fib('fib-retracement', ['x', null])).toBeUndefined();
    expect(fib('fib-retracement', 'all')).toBeUndefined();
    expect(fib('fib-retracement', [])).toEqual([]);
  });
});

describe('props', () => {
  const props = (value: unknown): Record<string, unknown> | undefined =>
    migrateDrawings([{
      id: 'p', tool: 'table', paneIndex: 0, style: {}, props: value, points: [{ time: 1, price: 2 }],
    }]).drawings[0].props;

  it('keeps anything JSON would write and drops what it would not', () => {
    const fn = (): number => 1;
    expect(props({
      label: 'x', count: 3, on: true, none: null, list: [1, 'two', null, fn, undefined],
      cells: [['a', 'b'], ['c', 'd']], nested: { a: { b: { c: [1, { d: 2 }] } } },
      fn, gone: undefined, nan: Number.NaN, inf: Infinity,
    })).toEqual({
      label: 'x', count: 3, on: true, none: null, list: [1, 'two', null, null, null],
      cells: [['a', 'b'], ['c', 'd']], nested: { a: { b: { c: [1, { d: 2 }] } } },
    });
    expect(props({})).toEqual({});
    expect(props(null)).toBeUndefined();
    expect(props([1, 2])).toBeUndefined();
  });

  it('stops at a depth no tool needs, so a cyclic host object cannot hang it', () => {
    const cyclic: Record<string, unknown> = { name: 'loop' };
    cyclic.self = cyclic;
    expect(() => props(cyclic)).not.toThrow();
    expect(props(cyclic)?.name).toBe('loop');
  });
});

describe('ids', () => {
  const line = (id: unknown): unknown => ({
    id, tool: 'trend-line', paneIndex: 0, style: {}, points: [{ time: 1, price: 2 }, { time: 3, price: 4 }],
  });

  it('keeps ids, and gives a second holder of an id a fresh one', () => {
    const doc = migrateDrawings([line('a'), line('b'), line('a'), line('a')]);
    const ids = doc.drawings.map((d) => d.id);
    expect(ids.slice(0, 2)).toEqual(['a', 'b']);
    expect(new Set(ids).size).toBe(4);
    for (const id of ids) expect(id).not.toBe('');
  });

  it('mints an id for an entry without one, unique across calls', () => {
    const a = migrateDrawings([line(undefined), line('')]).drawings.map((d) => d.id);
    const b = migrateDrawings([line(undefined)]).drawings.map((d) => d.id);
    expect(new Set([...a, ...b]).size).toBe(3);
    // Never the controller's own scheme, so a later add cannot collide with it.
    for (const id of [...a, ...b]) expect(id).toMatch(/^m\d+$/);
  });

  it('keeps a numeric id as its string, so a host keyed on it still finds the drawing', () => {
    expect(migrateDrawings([line(7)]).drawings[0].id).toBe('7');
  });

  it('keeps a drawing whose tool is not registered', () => {
    const doc = migrateDrawings([{ ...(line('x') as Record<string, unknown>), tool: 'plugin-tool' }]);
    expect(doc.drawings).toHaveLength(1);
    expect(doc.drawings[0].tool).toBe('plugin-tool');
  });
});

describe('the tier entry and the clipboard', () => {
  it('exports the migration from the draw tier', () => {
    expect(fromTier).toBe(migrateDrawings);
  });

  it('gives a pasted 1.9.x fib its level colours', () => {
    const text = JSON.stringify({
      [DRAWING_CLIPBOARD_KEY]: {
        version: 1,
        drawings: [{
          tool: 'fib-retracement', paneIndex: 0, style: { levels: [0, 0.618, 1] },
          points: [{ time: 1, price: 2 }, { time: 3, price: 4 }],
        }],
      },
    });
    const decoded = decodeClipboardPayload(text);
    expect(decoded?.[0].style.levels).toEqual([
      { ratio: 0, color: LEVEL_NEUTRAL }, { ratio: 0.618, color: '#089981' }, { ratio: 1, color: LEVEL_NEUTRAL },
    ]);
  });

  it('is lenient where the clipboard is strict: a bad flag loses the flag on load and the paste on paste', () => {
    const entry = {
      tool: 'trend-line', paneIndex: 0, locked: 'yes',
      points: [{ time: 1, price: 2 }, { time: 3, price: 4 }],
    };
    expect(migrateDrawings([entry]).drawings).toHaveLength(1);
    expect(decodeClipboardPayload(JSON.stringify({
      [DRAWING_CLIPBOARD_KEY]: { version: 2, drawings: [entry] },
    }))).toBeNull();
  });
});
