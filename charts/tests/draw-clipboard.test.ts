import { describe, it, expect, beforeAll, beforeEach } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
// The tier entry registers the built-in tools; the clipboard validates tool ids
// against that registry, so importing the controller from anywhere else would
// make every paste look like an unknown tool.
import { DrawingController } from '../src/draw/index';
import type { DrawingChartHost } from '../src/draw/controller';
import {
  DrawingClipboard, clearMemoryClipboard, decodeClipboardPayload, encodeClipboardPayload,
  sanitizeDrawing, cloneDrawing,
  DRAWING_CLIPBOARD_KEY, DRAWING_CLIPBOARD_VERSION,
  type ClipboardPort,
} from '../src/draw/clipboard';
import type { Bar } from '../src/model/bar';
import type { Drawing } from '../src/draw/types';
import type { DataLayer } from '../src/model/data-layer';

const W = 800;
const H = 600;

beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

beforeEach(() => {
  // The in-memory clipboard is process-wide on purpose (two charts in one page
  // share it), so a test must not inherit the previous test's copy.
  clearMemoryClipboard();
});

const bars = (n: number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = 100 + Math.sin(i / 4) * 5;
    return { time: 1700000000 + i * 60, open: c, high: c + 2, low: c - 2, close: c, volume: 10 };
  });

/**
 * A measured chart. Without `applySize` plus a synchronous raf every price
 * scale sits on its 0..1 placeholder, and the pixel half of the paste offset
 * would be measured against nothing.
 */
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

/** One "OS clipboard": the text every port in a test writes to and reads from. */
interface Os { text: string }

function osPort(os: Os): ClipboardPort {
  return {
    writeText: async (t: string) => { os.text = t; },
    readText: async () => os.text,
  };
}

/** A browser that refuses clipboard access, the way a denied permission does. */
const deniedPort: ClipboardPort = {
  writeText: async () => { throw new Error('NotAllowedError: write permission denied'); },
  readText: async () => { throw new Error('NotAllowedError: read permission denied'); },
};

function trendLine(draw: DrawingController, chart: Chart): Drawing {
  return draw.add({
    tool: 'trend-line',
    paneIndex: 0,
    style: { color: '#ff9900', lineWidth: 3 },
    points: [
      { time: chart.coordinateToTime(200), price: chart.coordinateToPrice(300, 0) as number },
      { time: chart.coordinateToTime(400), price: chart.coordinateToPrice(200, 0) as number },
    ],
  });
}

/** A clipboard body of the given version, as text. */
const payloadOf = (version: number, drawings: unknown): string =>
  JSON.stringify({ [DRAWING_CLIPBOARD_KEY]: { version, drawings } });

describe('copy and paste round trip', () => {
  it('copies to the clipboard and pastes a second drawing back', async () => {
    const os: Os = { text: '' };
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: osPort(os) });
    const original = trendLine(draw, chart);

    expect(await draw.copy(original.id)).toBe(true);
    expect(os.text).toContain(DRAWING_CLIPBOARD_KEY);

    const pasted = await draw.paste();
    expect(pasted).toHaveLength(1);
    expect(draw.drawings()).toHaveLength(2);
    expect(pasted[0].tool).toBe('trend-line');
    expect(pasted[0].style.color).toBe('#ff9900');
    expect(pasted[0].style.lineWidth).toBe(3);
    expect(pasted[0].paneIndex).toBe(0);
    expect(draw.selected()).toBe(pasted[0].id);
  });

  it('copies the selection when no id is given, and reports nothing to copy otherwise', async () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: null });
    const original = trendLine(draw, chart);
    draw.select(null);
    expect(await draw.copy()).toBe(false);
    draw.select(original.id);
    expect(await draw.copy()).toBe(true);
    expect(await draw.paste()).toHaveLength(1);
  });

  it('copies every selected drawing, and a paste selects every copy', async () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: null });
    const a = trendLine(draw, chart);
    const b = trendLine(draw, chart);
    draw.select([a.id, b.id]);
    expect(await draw.copy()).toBe(true);
    const pasted = await draw.paste();
    expect(pasted).toHaveLength(2);
    expect(draw.selection()).toEqual(pasted.map((d) => d.id));
  });

  it('pastes a copy, not a second reference to the original', async () => {
    const os: Os = { text: '' };
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: osPort(os) });
    const original = trendLine(draw, chart);
    await draw.copy(original.id);
    const [copy] = await draw.paste();

    expect(copy.id).not.toBe(original.id);
    expect(copy).not.toBe(original);
    expect(copy.points).not.toBe(original.points);
    expect(copy.style).not.toBe(original.style);

    // Editing the paste must not reach back into its source.
    draw.update(copy.id, { style: { color: '#00ff00' }, points: [{ time: 1, price: 2 }, { time: 3, price: 4 }] });
    expect(draw.get(original.id)?.style.color).toBe('#ff9900');
    expect(draw.get(original.id)?.points[0].price).toBe(original.points[0].price);
  });

  it('pastes offset from the original so the copy is visible', async () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: null });
    const original = trendLine(draw, chart);
    const before = original.points.map((p) => ({ ...p }));
    await draw.copy(original.id);
    const [copy] = await draw.paste();

    // Two bars along (bars are 60 s apart) and 16 px down the price axis.
    expect(copy.points[0].time).toBe(before[0].time + 120);
    expect(copy.points[1].time).toBe(before[1].time + 120);
    expect(copy.points[0].price).toBeLessThan(before[0].price);
    const y0 = chart.priceToCoordinate(before[0].price, 0) as number;
    const y1 = chart.priceToCoordinate(copy.points[0].price, 0) as number;
    expect(y1 - y0).toBeCloseTo(16, 6);
    // The source is untouched by the offset.
    expect(draw.get(original.id)?.points[0].price).toBe(before[0].price);
  });

  it('honours a configured offset, including one that is time-only', async () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, {
      clipboard: null, pasteOffsetBars: 5, pasteOffsetPixels: 0,
    });
    const original = trendLine(draw, chart);
    const before = original.points[0].price;
    await draw.copy(original.id);
    const [copy] = await draw.paste();
    expect(copy.points[0].time).toBe(original.points[0].time + 300);
    expect(copy.points[0].price).toBe(before);
  });

  it('pastes several drawings as one undo step', async () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: null });
    const a = trendLine(draw, chart);
    const b = trendLine(draw, chart);
    expect(await draw.copy([a.id, b.id])).toBe(true);
    const pasted = await draw.paste();
    expect(pasted).toHaveLength(2);
    expect(draw.drawings()).toHaveLength(4);
    expect(draw.undo()).toBe(true);
    expect(draw.drawings()).toHaveLength(2);
  });

  it('carries text, props and z-order through a paste', async () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: null });
    const original = draw.add({
      tool: 'rectangle', paneIndex: 0, zIndex: -2,
      style: { color: '#123456', fill: true },
      text: { value: 'zone', color: '#ffffff', bold: true, align: 'center', position: 'inside' },
      props: { note: 'breakout', tags: ['a', 'b'], grid: { rows: 2 } },
      points: [
        { time: chart.coordinateToTime(200), price: chart.coordinateToPrice(300, 0) as number },
        { time: chart.coordinateToTime(400), price: chart.coordinateToPrice(200, 0) as number },
      ],
    });
    await draw.copy(original.id);
    const [copy] = await draw.paste();
    expect(copy.text).toEqual(original.text);
    expect(copy.text).not.toBe(original.text);
    expect(copy.props).toEqual(original.props);
    expect(copy.props).not.toBe(original.props);
    expect(copy.zIndex).toBe(-2);
  });
});

describe('undo', () => {
  it('undo removes a paste and redo brings it back', async () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: null });
    const original = trendLine(draw, chart);
    await draw.copy(original.id);
    const [copy] = await draw.paste();
    expect(draw.drawings()).toHaveLength(2);

    expect(draw.undo()).toBe(true);
    expect(draw.drawings()).toHaveLength(1);
    expect(draw.get(copy.id)).toBeUndefined();
    expect(draw.get(original.id)).toBeDefined();

    expect(draw.redo()).toBe(true);
    expect(draw.drawings()).toHaveLength(2);
  });

  it('a cut is one undo step that restores the drawing', async () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: null });
    const original = trendLine(draw, chart);
    draw.select(original.id);

    expect(await draw.cut()).toBe(true);
    expect(draw.drawings()).toHaveLength(0);
    expect(draw.selected()).toBeNull();

    expect(draw.undo()).toBe(true);
    expect(draw.drawings()).toHaveLength(1);
  });

  it('a cut of a multi-selection is one undo step too', async () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: null });
    const a = trendLine(draw, chart);
    const b = trendLine(draw, chart);
    draw.select([a.id, b.id]);
    expect(await draw.cut()).toBe(true);
    expect(draw.drawings()).toHaveLength(0);
    expect(draw.selection()).toEqual([]);
    expect(draw.undo()).toBe(true);
    expect(draw.drawings()).toHaveLength(2);
  });

  it('a cut drawing can be pasted back', async () => {
    const os: Os = { text: '' };
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: osPort(os) });
    const original = trendLine(draw, chart);
    await draw.cut(original.id);
    expect(draw.drawings()).toHaveLength(0);
    const [back] = await draw.paste();
    expect(back.tool).toBe('trend-line');
    expect(back.id).not.toBe(original.id);
    expect(draw.drawings()).toHaveLength(1);
  });
});

describe('a second chart', () => {
  it('pastes a drawing copied in another chart', async () => {
    const os: Os = { text: '' };
    const chartA = makeChart();
    const chartB = makeChart();
    // Separate ports over one OS clipboard: two tabs, two documents, one buffer.
    const drawA = new DrawingController(chartA, { clipboard: osPort(os) });
    const drawB = new DrawingController(chartB, { clipboard: osPort(os) });

    const original = trendLine(drawA, chartA);
    expect(await drawA.copy(original.id)).toBe(true);
    // Nothing in this process may be carrying the payload: it has to travel
    // through the clipboard text, which is what a real second tab sees.
    clearMemoryClipboard();

    const pasted = await drawB.paste();
    expect(pasted).toHaveLength(1);
    expect(pasted[0].style.color).toBe('#ff9900');
    expect(drawB.drawings()).toHaveLength(1);
    expect(drawA.drawings()).toHaveLength(1);   // the source chart is untouched
  });

  it('folds a pane index the receiving chart does not have onto one it does', async () => {
    // Adding a primitive creates the pane it names, so a drawing copied out of
    // an indicator pane must not conjure an empty pane in a chart without one.
    const os: Os = { text: payloadOf(DRAWING_CLIPBOARD_VERSION, [{
      tool: 'trend-line', paneIndex: 7,
      points: [{ time: 1700000000, price: 100 }, { time: 1700000600, price: 105 }],
    }]) };
    const chart = makeChart();
    const paneCount = chart.panes().length;
    const draw = new DrawingController(chart, { clipboard: osPort(os) });
    const [pasted] = await draw.paste();
    expect(pasted.paneIndex).toBe(paneCount - 1);
    expect(chart.panes()).toHaveLength(paneCount);
  });

  it('shares the in-memory clipboard between charts when there is no OS clipboard', async () => {
    const chartA = makeChart();
    const chartB = makeChart();
    const drawA = new DrawingController(chartA, { clipboard: null });
    const drawB = new DrawingController(chartB, { clipboard: null });
    const original = trendLine(drawA, chartA);
    expect(await drawA.copy(original.id)).toBe(true);
    expect(await drawB.paste()).toHaveLength(1);
  });
});

describe('a payload from a 1.9.x build', () => {
  const pasteText = async (text: string): Promise<Drawing[]> => {
    const os: Os = { text };
    const draw = new DrawingController(makeChart(), { clipboard: osPort(os) });
    return draw.paste();
  };

  it('lifts the style-bag text fields into the text block', async () => {
    const [pasted] = await pasteText(payloadOf(1, [{
      tool: 'text', paneIndex: 0,
      points: [{ time: 1700000000, price: 100 }],
      style: {
        color: '#abcdef', text: 'Hello', fontColor: '#ffffff', fontSize: 16, fontWeight: 'bold',
        fontStyle: 'italic', textAlign: 'center', textVAlign: 'bottom', textPosition: 'outside',
        background: true, backgroundColor: '#000', backgroundOpacity: 0.5, border: true,
        borderColor: '#111', wrap: true, wrapWidth: 180, fontFamily: 'Georgia',
      },
    }]));
    expect(pasted.text).toEqual({
      value: 'Hello', color: '#ffffff', fontSize: 16, bold: true, italic: true,
      align: 'center', valign: 'bottom', position: 'outside',
      background: true, backgroundColor: '#000', backgroundOpacity: 0.5, border: true,
      borderColor: '#111', wrap: true, wrapWidth: 180, fontFamily: 'Georgia',
    });
    // Nothing textual is left behind in the style bag.
    expect(pasted.style).toEqual({ color: '#abcdef' });
    expect(pasted.zIndex).toBe(0);
  });

  it('turns bare level ratios into levels', async () => {
    const [pasted] = await pasteText(payloadOf(1, [{
      tool: 'fib-retracement', paneIndex: 0,
      points: [{ time: 1700000000, price: 100 }, { time: 1700000600, price: 110 }],
      style: { levels: [0, 0.5, 1] },
    }]));
    expect(pasted.style.levels?.map((l) => l.ratio)).toEqual([0, 0.5, 1]);
  });

  it('leaves a shape with no text value without a text block', async () => {
    // A rectangle with a font colour but nothing to say has no label to keep.
    const [pasted] = await pasteText(payloadOf(1, [{
      tool: 'rectangle', paneIndex: 0,
      points: [{ time: 1700000000, price: 100 }, { time: 1700000600, price: 110 }],
      style: { color: '#abcdef', fontColor: '#ffffff' },
    }]));
    expect(pasted.text).toBeUndefined();
    expect(pasted.style.color).toBe('#abcdef');
    expect(pasted.style).not.toHaveProperty('fontColor');
  });
});

describe('a hostile or foreign clipboard', () => {
  const pasteText = async (text: string): Promise<{ draw: DrawingController; pasted: Drawing[] }> => {
    const os: Os = { text };
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: osPort(os) });
    trendLine(draw, chart);
    const pasted = await draw.paste();
    return { draw, pasted };
  };

  it('ignores plain text that is not ours', async () => {
    for (const text of ['', 'hello world', 'RELIANCE,2450.10,+1.2%']) {
      const { draw, pasted } = await pasteText(text);
      expect(pasted).toEqual([]);
      expect(draw.drawings()).toHaveLength(1);
    }
  });

  it('ignores JSON belonging to some other application', async () => {
    const { draw, pasted } = await pasteText(JSON.stringify({ shapes: [{ type: 'line' }] }));
    expect(pasted).toEqual([]);
    expect(draw.drawings()).toHaveLength(1);
  });

  it('rejects a malformed payload without mutating the model or history', async () => {
    const payload = (drawings: unknown): string => payloadOf(DRAWING_CLIPBOARD_VERSION, drawings);
    const bad: string[] = [
      // Truncated: valid JSON prefix, nothing more.
      '{"openalgo-charts/drawings":{"version":2,"draw',
      payload('not-an-array'),
      payload([]),
      payload([{ tool: 'trend-line' }]),                                   // no points
      payload([{ tool: 'trend-line', points: [] }]),                       // empty points
      payload([{ tool: 'no-such-tool', points: [{ time: 1, price: 2 }] }]),
      payload([{ tool: 'trend-line', points: [{ time: 1, price: null }] }]),
      payload([{ tool: 'trend-line', points: [{ time: 'soon', price: 2 }] }]),
      payload([{ tool: 'trend-line', points: [{ time: 1, price: 2 }], paneIndex: -1 }]),
      payload([{ tool: 'trend-line', points: [{ time: 1, price: 2 }], paneIndex: 1.5 }]),
      payload([{ tool: 'trend-line', points: [{ time: 1, price: 2 }], style: 'red' }]),
      payload([{ tool: 'trend-line', points: [{ time: 1, price: 2 }], locked: 'yes' }]),
      // One good entry, one bad: all or nothing, so neither is pasted.
      payload([
        { tool: 'trend-line', points: [{ time: 1, price: 2 }, { time: 3, price: 4 }] },
        { tool: 'trend-line', points: [{ time: 1, price: Number.NaN }] },
      ]),
      payloadOf(99, []),
      JSON.stringify({ [DRAWING_CLIPBOARD_KEY]: 'drawings' }),
    ];
    for (const text of bad) {
      const { draw, pasted } = await pasteText(text);
      expect(pasted, text).toEqual([]);
      expect(draw.drawings(), text).toHaveLength(1);
      // History holds the add and nothing else: a rejected paste must not leave
      // an undo entry describing a state that never existed.
      expect(draw.undo(), text).toBe(true);
      expect(draw.drawings(), text).toHaveLength(0);
      expect(draw.canUndo(), text).toBe(false);
    }
  });

  it('drops style values it cannot render instead of failing the paste', async () => {
    const { pasted } = await pasteText(payloadOf(DRAWING_CLIPBOARD_VERSION, [{
      tool: 'trend-line',
      points: [{ time: 1700000000, price: 100 }, { time: 1700000600, price: 105 }],
      style: {
        color: '#abcdef', onDraw: null, nested: { a: 1 }, lineStyle: 'wavy', lineWidth: 'fat',
        levels: [0, { ratio: 0.5, color: '#f00', enabled: false, label: 'half' }, 1],
      },
    }]));
    expect(pasted).toHaveLength(1);
    expect(pasted[0].style.color).toBe('#abcdef');
    // Ratios survive in order, and what a level said about itself survives; a
    // bare ratio may pick up a default colour on the way through the migration.
    const levels = pasted[0].style.levels ?? [];
    expect(levels.map((l) => l.ratio)).toEqual([0, 0.5, 1]);
    expect(levels[1]).toMatchObject({ ratio: 0.5, color: '#f00', enabled: false, label: 'half' });
    const style = pasted[0].style as Record<string, unknown>;
    expect(style.nested).toBeUndefined();
    expect(style.lineStyle).toBeUndefined();   // not one of the three styles
    expect(style.lineWidth).toBeUndefined();   // not a number
  });

  it('drops a text block with no value and text keys it does not draw', async () => {
    const good = { tool: 'rectangle', points: [{ time: 1, price: 2 }, { time: 3, price: 4 }] };
    const { pasted: noValue } = await pasteText(payloadOf(DRAWING_CLIPBOARD_VERSION, [
      { ...good, text: { color: '#fff' } },
    ]));
    expect(noValue).toHaveLength(1);
    expect(noValue[0].text).toBeUndefined();

    const { pasted: extras } = await pasteText(payloadOf(DRAWING_CLIPBOARD_VERSION, [
      { ...good, text: { value: 'hi', align: 'sideways', fontSize: 'big', onClick: 'x', bold: true } },
    ]));
    expect(extras[0].text).toEqual({ value: 'hi', bold: true });
  });

  it('keeps props that are plain data and drops the rest', async () => {
    const { pasted } = await pasteText(payloadOf(DRAWING_CLIPBOARD_VERSION, [{
      tool: 'rectangle', points: [{ time: 1, price: 2 }, { time: 3, price: 4 }],
      props: {
        label: 'x', count: 3, on: true, list: [1, 'two'], cells: { a: 1 },
        fn: null, deep: { a: { b: { c: 1 } } },
      },
    }]));
    // Three levels of records are kept (`props.deep.a`); the fourth is not.
    expect(pasted[0].props).toEqual({
      label: 'x', count: 3, on: true, list: [1, 'two'], cells: { a: 1 }, deep: { a: {} },
    });
  });

  it('never lets a payload reach Object.prototype', async () => {
    const text = '{"openalgo-charts/drawings":{"version":2,"drawings":[{"tool":"trend-line",'
      + '"points":[{"time":1,"price":2},{"time":3,"price":4}],"style":{"__proto__":{"polluted":true}},'
      + '"props":{"__proto__":{"polluted":true}},"text":{"value":"x","__proto__":{"polluted":true}}}]}}';
    const { pasted } = await pasteText(text);
    expect(pasted).toHaveLength(1);
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
  });

  it('refuses a payload with more anchors than a pointer could produce', () => {
    const points = Array.from({ length: 20001 }, (_, i) => ({ time: i, price: i }));
    expect(decodeClipboardPayload(payloadOf(DRAWING_CLIPBOARD_VERSION, [{ tool: 'path', points }]))).toBeNull();
  });
});

describe('a refused clipboard permission', () => {
  it('falls back to memory so copy and paste still work in the tab', async () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: deniedPort });
    const original = trendLine(draw, chart);

    expect(await draw.copy(original.id)).toBe(true);
    expect(draw.clipboard().lastError()).toContain('NotAllowedError');

    const pasted = await draw.paste();
    expect(pasted).toHaveLength(1);
    expect(pasted[0].style.color).toBe('#ff9900');
  });

  it('leaves a cut drawing in place when the write cannot be stored anywhere', async () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: deniedPort });
    draw.clipboard().setFallbackToMemory(false);
    const original = trendLine(draw, chart);

    expect(await draw.cut(original.id)).toBe(false);
    expect(draw.drawings()).toHaveLength(1);       // not destroyed
    expect(draw.get(original.id)).toBeDefined();
    expect(draw.canUndo()).toBe(true);             // only the add, not a cut
    draw.undo();
    expect(draw.canUndo()).toBe(false);
  });

  it('starts working again when the host hands over a port later', async () => {
    const os: Os = { text: '' };
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: deniedPort });
    draw.clipboard().setFallbackToMemory(false);
    const original = trendLine(draw, chart);
    expect(await draw.copy(original.id)).toBe(false);

    draw.setOptions({ clipboard: osPort(os) });
    expect(await draw.copy(original.id)).toBe(true);
    expect(os.text).toContain(DRAWING_CLIPBOARD_KEY);
  });
});

describe('payload encoding', () => {
  it('round-trips through encode and decode without an id', () => {
    const d: Drawing = {
      id: 'd42', tool: 'rectangle', paneIndex: 1, zIndex: 3, locked: true, visible: false,
      points: [{ time: 1700000000, price: 100 }, { time: 1700000600, price: 110 }],
      style: { color: '#fff', fill: true, fillOpacity: 0.2, levels: [{ ratio: 0.5, color: '#0f0' }] },
      text: { value: 'box', italic: true, valign: 'middle' },
      props: { kind: 'zone' },
      createdAt: 1700000000000,
    };
    const decoded = decodeClipboardPayload(encodeClipboardPayload([d]));
    expect(decoded).not.toBeNull();
    expect(decoded).toHaveLength(1);
    expect(decoded?.[0]).toEqual({
      tool: 'rectangle', paneIndex: 1, zIndex: 3, locked: true, visible: false,
      points: d.points, style: d.style, text: d.text, props: d.props,
    });
    expect((decoded?.[0] as Record<string, unknown>).id).toBeUndefined();
    // The moment of creation belongs to the original, not to the copy.
    expect((decoded?.[0] as Record<string, unknown>).createdAt).toBeUndefined();
  });

  it('names its version so an older build can refuse a newer payload', () => {
    const parsed = JSON.parse(encodeClipboardPayload([{
      id: 'x', tool: 'trend-line', paneIndex: 0, zIndex: 0, style: {},
      points: [{ time: 1, price: 2 }, { time: 3, price: 4 }],
    }])) as Record<string, { version: number }>;
    // The lowest version that holds it, so a build reading only version 2
    // still pastes a copy with no interval range.
    expect(parsed[DRAWING_CLIPBOARD_KEY].version).toBe(2);
    // The body is a drawings document, so it tracks the model version.
    expect(DRAWING_CLIPBOARD_VERSION).toBe(3);
    const ranged = JSON.parse(encodeClipboardPayload([{
      id: 'x', tool: 'trend-line', paneIndex: 0, zIndex: 0, style: {}, intervals: { from: '1m', to: '1h' },
      points: [{ time: 1, price: 2 }, { time: 3, price: 4 }],
    }])) as Record<string, { version: number; drawings: { intervals?: unknown }[] }>;
    expect(ranged[DRAWING_CLIPBOARD_KEY].version).toBe(DRAWING_CLIPBOARD_VERSION);
    expect(ranged[DRAWING_CLIPBOARD_KEY].drawings[0].intervals).toEqual({ from: '1m', to: '1h' });
  });

  it('still accepts a version 1 body, and refuses one from the future', () => {
    const entry = { tool: 'trend-line', points: [{ time: 1, price: 2 }, { time: 3, price: 4 }] };
    expect(decodeClipboardPayload(payloadOf(1, [entry]))).toHaveLength(1);
    expect(decodeClipboardPayload(payloadOf(DRAWING_CLIPBOARD_VERSION + 1, [entry]))).toBeNull();
  });

  it('sanitizeDrawing fills in z-order and accepts the old shape', () => {
    const d = sanitizeDrawing({
      tool: 'text', points: [{ time: 1, price: 2 }],
      style: { text: 'old', fontWeight: 'bold' },
    });
    expect(d).not.toBeNull();
    expect(d?.zIndex).toBe(0);
    expect(d?.text).toEqual({ value: 'old', bold: true });
    expect(sanitizeDrawing({ tool: 'no-such-tool', points: [{ time: 1, price: 2 }] })).toBeNull();
  });

  it('cloneDrawing shares nothing with its source', () => {
    const d: Drawing = {
      id: 'a', tool: 'fib-retracement', paneIndex: 0, zIndex: 0,
      points: [{ time: 1, price: 2 }, { time: 3, price: 4 }],
      style: { levels: [{ ratio: 0.5 }] }, text: { value: 'x' }, props: { rows: [1, 2] },
    };
    const c = cloneDrawing(d);
    expect(c).toEqual(d);
    expect(c.points[0]).not.toBe(d.points[0]);
    expect(c.style.levels?.[0]).not.toBe(d.style.levels?.[0]);
    expect(c.text).not.toBe(d.text);
    expect(c.props?.rows).not.toBe(d.props?.rows);
  });

  it('keeps pen pressure through a clone and a paste, and drops a pressure it cannot trust', () => {
    // A pen stroke that lost its pressure would paint at the configured width
    // after a paste: graceful, but not what was copied.
    const d: Drawing = {
      id: 'a', tool: 'brush', paneIndex: 0, zIndex: 0,
      points: [{ time: 1, price: 2, pressure: 0.2 }, { time: 3, price: 4 }, { time: 5, price: 6, pressure: 1 }],
      style: { pressure: true },
    };
    const c = cloneDrawing(d);
    expect(c.points).toEqual(d.points);
    expect(c.points[1]).toEqual({ time: 3, price: 4 });   // no key invented for the mouse stand-in
    const pasted = decodeClipboardPayload(encodeClipboardPayload([d]));
    expect(pasted?.[0].points).toEqual(d.points);

    const s = sanitizeDrawing({
      tool: 'brush',
      points: [{ time: 1, price: 2, pressure: 1.5 }, { time: 3, price: 4, pressure: -0.1 }, { time: 5, price: 6, pressure: 'x' }, { time: 7, price: 8, pressure: 0.4 }],
    });
    expect(s?.points).toEqual([{ time: 1, price: 2 }, { time: 3, price: 4 }, { time: 5, price: 6 }, { time: 7, price: 8, pressure: 0.4 }]);
  });

  it('reads nothing from an empty clipboard', async () => {
    const clip = new DrawingClipboard({ port: osPort({ text: '' }) });
    expect(await clip.read()).toBeNull();
    expect(await clip.write([])).toBe(false);
  });
});

describe('a host without pixel mapping', () => {
  /** The minimum a controller needs: no priceToCoordinate, no coordinateToPrice. */
  function stubHost(): DrawingChartHost {
    return {
      on: () => () => {},
      emit: () => {},
      addPrimitive: () => {},
      removePrimitive: () => {},
      dataLayer: {
        baseIndex: 2,
        indexToTime: (i: number) => 1700000000 + i * 300,
      } as unknown as DataLayer,
      getVisibleLogicalRange: () => null,
      drawingState: () => null,
      setDrawingState: () => {},
    };
  }

  it('offsets the paste in time only, and still pastes', async () => {
    const draw = new DrawingController(stubHost(), { clipboard: null });
    const original = draw.add({
      tool: 'trend-line', paneIndex: 0, style: {},
      points: [{ time: 1700000000, price: 100 }, { time: 1700000600, price: 110 }],
    });
    await draw.copy(original.id);
    const [copy] = await draw.paste();
    expect(copy.points[0].time).toBe(1700000000 + 600);   // 300 s bars, 2 bars
    expect(copy.points[0].price).toBe(100);
  });
});

describe('the memory fallback is reachable from the controller', () => {
  /** A clipboard the browser has denied: every write throws. */
  const denied = (): ClipboardPort => ({
    readText: async () => '',
    writeText: async () => { throw new Error('permission denied'); },
  });

  it('threads clipboardFallbackToMemory through, so cut can be made safe', async () => {
    // The option existed on DrawingClipboard but the controller never passed it,
    // so a host could not turn it off without reaching past the public API. With
    // it off a refused write must leave the drawing in place: a shape destroyed
    // for a transfer that never happened is unrecoverable.
    const chart = makeChart();
    const draw = new DrawingController(chart, {
      clipboard: denied(),
      clipboardFallbackToMemory: false,
    });
    const d = trendLine(draw, chart);

    await draw.cut([d.id]);
    expect(draw.toJSON().drawings.map((x) => x.id)).toContain(d.id);
    draw.destroy();
  });

  it('turns the fallback off through setOptions too, so a refused write cuts nothing', async () => {
    // setOptions accepted the option and stored it where nothing read it: a
    // host that turned the backstop off after construction still had a cut
    // delete a drawing whose write had failed.
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: denied() });
    const d = trendLine(draw, chart);

    draw.setOptions({ clipboardFallbackToMemory: false });
    expect(await draw.cut([d.id])).toBe(false);
    expect(draw.toJSON().drawings.map((x) => x.id)).toContain(d.id);
    // And back on: the in-process clipboard takes the copy again.
    draw.setOptions({ clipboardFallbackToMemory: true });
    expect(await draw.cut([d.id])).toBe(true);
    expect(draw.toJSON().drawings).toHaveLength(0);
    draw.destroy();
  });

  it('defaults to keeping the fallback on, so a denied browser still copies', async () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { clipboard: denied() });
    const d = trendLine(draw, chart);

    await draw.copy([d.id]);
    const before = draw.toJSON().drawings.length;
    await draw.paste();
    expect(draw.toJSON().drawings.length).toBe(before + 1);
    draw.destroy();
  });
});
