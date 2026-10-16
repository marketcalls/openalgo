/**
 * Viewport-anchored drawings: anchors stored as fractions of the pane's plot
 * area instead of time and price. Each contract here is checked through the
 * real chart and the real layer, because the failure this feature exists to
 * prevent (an annotation that slides when the chart pans) only shows up where
 * the chart's own scales move under the drawing.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import {
  DrawingController, DrawingLayer, migrateDrawings, encodeClipboardPayload, decodeClipboardPayload, createDrawingLinkGroup,
  BUILTIN_DRAWING_TOOLS, registerDrawingTool, drawingSettingsSchema, readDrawingSetting, applyDrawingSettings, SPACE_FIELD,
  type ClipboardPort, type Drawing, type DrawingInput,
} from '../src/draw/index';
import { darkTheme } from '../src/theme';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import { makeCtx, type RecordingContext } from './helpers/fake-ctx';

const T0 = 1700000000;
const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).reverse().forEach(fn => fn()); vi.unstubAllGlobals(); });

const bars = Array.from({ length: 100 }, (_, i) => {
  const c = 100 + Math.sin(i / 6) * 4;
  return { time: T0 + i * 60, open: c - 0.5, high: c + 1, low: c - 1, close: c };
});

function memoryPort(): ClipboardPort & { text: string } {
  const port = { text: '', writeText: async (t: string) => { port.text = t; }, readText: async () => port.text };
  return port;
}

function mount(width = 800, height = 600, options: { panes?: number; clipboard?: ClipboardPort } = {}) {
  vi.stubGlobal('window', {});
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as FakeElement;
  const chart = new Chart(el as unknown as HTMLElement, { document: doc, raf: { schedule: () => 0 }, shortcuts: false, timeNavigator: false });
  chart.applySize(width, height);
  chart.addSeries('candlestick').setData(bars);
  for (let pane = 1; pane < (options.panes ?? 1); pane++) chart.addSeries('line', { paneIndex: pane }).setData(bars.map(b => ({ time: b.time, value: b.close })));
  chart.setVisibleLogicalRange({ from: 0, to: 99 });
  const draw = new DrawingController(chart, options.clipboard === undefined ? {} : { clipboard: options.clipboard });
  cleanups.push(() => chart.destroy(), () => draw.destroy());
  const move = (x: number, y: number, pressed = false) => el.dispatch('pointermove', pointer('move', x, y, { buttons: pressed ? 1 : 0 }));
  const dragBy = (x: number, y: number, dx: number, dy: number) => {
    move(x, y);
    el.dispatch('pointerdown', pointer('down', x, y));
    for (let i = 1; i <= 5; i++) move(x + (dx * i) / 5, y + (dy * i) / 5, true);
    el.dispatch('pointerup', pointer('up', x + dx, y + dy));
  };
  const click = (x: number, y: number) => {
    move(x, y);
    el.dispatch('pointerdown', pointer('down', x, y));
    el.dispatch('pointerup', pointer('up', x, y));
  };
  const size = (paneIndex = 0) => ({ w: chart.timeScale.width, h: chart.panes()[paneIndex].priceScale.height });
  /** Paint a pane's top drawing layer the way the chart would, at `dpr`. */
  const paint = (paneIndex = 0, dpr = 1): RecordingContext => {
    const { ctx, rec } = makeCtx();
    const pane = chart.panes()[paneIndex];
    const layer = pane.primitives().find(p => p instanceof DrawingLayer && p.zOrder() === 'top') as DrawingLayer;
    const { w, h } = size(paneIndex);
    layer.draw(ctx, { timeScale: chart.timeScale, dataLayer: chart.dataLayer, priceScale: pane.priceScale,
      plotWidth: w, plotHeight: h, priceAxisWidth: 56, dpr, theme: darkTheme } as never);
    return rec;
  };
  const hit = (x: number, y: number, paneIndex = 0, dpr = 1) => {
    const pane = chart.panes()[paneIndex];
    const layer = pane.primitives().find(p => p instanceof DrawingLayer && p.zOrder() === 'top') as DrawingLayer;
    const { w, h } = size(paneIndex);
    return layer.hitTest(x, y, { timeScale: chart.timeScale, dataLayer: chart.dataLayer, priceScale: pane.priceScale,
      plotWidth: w, plotHeight: h, priceAxisWidth: 56, dpr, theme: darkTheme } as never);
  };
  return { chart, draw, el, move, click, dragBy, paint, hit, size };
}

const viewportRect = (draw: DrawingController, extra: Partial<DrawingInput> = {}): Drawing => draw.add({
  tool: 'rectangle', paneIndex: 0, style: { color: '#ff00ff' }, points: [], space: 'viewport',
  viewportPoints: [{ x: 0.2, y: 0.2 }, { x: 0.5, y: 0.5 }], ...extra,
});

const dataRect = (draw: DrawingController): Drawing => draw.add({
  tool: 'rectangle', paneIndex: 0, style: { color: '#00ffff' },
  points: [{ time: bars[40].time, price: 101 }, { time: bars[60].time, price: 99 }],
});

/** The strokeRect a rectangle paints, as [x, y, w, h]. */
const strokeOf = (rec: RecordingContext, color: string): number[] | undefined =>
  rec.ops.find(op => op.type === 'strokeRect' && op.strokeStyle === color)?.args;

const close = (a: readonly number[] | undefined, b: readonly number[], digits = 6): void => {
  expect(a).toBeDefined();
  expect(a!.length).toBe(b.length);
  a!.forEach((v, i) => expect(v).toBeCloseTo(b[i], digits));
};

type Hit = (x: number, y: number) => { externalId: string } | null;

/**
 * Where a drawing answers the pointer, found by probing a grid that reaches
 * well past the plot on every side: its body or any of its handles.
 */
function hitRegion(hit: Hit, id: string, w: number, h: number, step = 7) {
  const region = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity, count: 0, inside: 0 };
  for (let y = -60; y <= h + 300; y += step) {
    for (let x = -60; x <= w + 300; x += step) {
      const at = hit(x, y)?.externalId;
      if (at !== `draw:${id}` && at?.startsWith(`draw:${id}#`) !== true) continue;
      region.count++;
      if (x > 0 && x < w && y > 0 && y < h) region.inside++;
      region.x0 = Math.min(region.x0, x); region.y0 = Math.min(region.y0, y);
      region.x1 = Math.max(region.x1, x); region.y1 = Math.max(region.y1, y);
    }
  }
  return region;
}

/**
 * A drawing that can be seen and clicked: it answers the pointer at several
 * places inside the plot, and nowhere further out than the few pixels a grab
 * reaches past an edge. A box left outside the plot is clipped away and the
 * chart never routes a click to it.
 */
function expectOnPlot(hit: Hit, id: string, w: number, h: number) {
  const region = hitRegion(hit, id, w, h);
  expect(region.inside).toBeGreaterThan(3);
  expect(region.x0).toBeGreaterThanOrEqual(-8);
  expect(region.y0).toBeGreaterThanOrEqual(-8);
  expect(region.x1).toBeLessThanOrEqual(w + 8);
  expect(region.y1).toBeLessThanOrEqual(h + 8);
  return region;
}

/** Every piece of text, fill and outline the layer painted starts inside the clipped plot, in device px. */
function expectPaintedOnPlot(rec: RecordingContext, w: number, h: number, dpr: number) {
  const ops = rec.ops.filter(op => op.type === 'fillText' || op.type === 'strokeRect' || op.type === 'fillRect' || op.type === 'roundRect');
  expect(ops.length).toBeGreaterThan(0);
  for (const op of ops) {
    const [x, y, bw, bh] = op.args;
    expect(x).toBeGreaterThanOrEqual(-1);
    expect(y).toBeGreaterThanOrEqual(-1);
    expect(x).toBeLessThanOrEqual(w * dpr + 1);
    expect(y).toBeLessThanOrEqual(h * dpr + 1);
    if (op.type !== 'fillText') {
      expect(x + bw).toBeLessThanOrEqual(w * dpr + 1);
      expect(y + bh).toBeLessThanOrEqual(h * dpr + 1);
    }
  }
}

describe('a viewport drawing on screen', () => {
  it('paints at its fraction of the plot and stays there through pan, zoom and a price range change', () => {
    const { chart, draw, paint, size } = mount();
    viewportRect(draw);
    dataRect(draw);
    const { w, h } = size();
    const expected = [0.2 * w, 0.2 * h, 0.3 * w, 0.3 * h];
    close(strokeOf(paint(), '#ff00ff'), expected);
    const dataBefore = strokeOf(paint(), '#00ffff');
    chart.setVisibleLogicalRange({ from: 30, to: 70 });
    const scale = chart.panes()[0].priceScale;
    scale.setAutoScale(false);
    scale.setPriceRange({ min: 90, max: 110 });
    close(strokeOf(paint(), '#ff00ff'), expected);
    // The data rectangle is the control: the same changes do move it.
    expect(strokeOf(paint(), '#00ffff')).not.toEqual(dataBefore);
  });

  it('stays put under a real pointer pan of the chart', () => {
    const { draw, paint, dragBy, size } = mount();
    viewportRect(draw);
    const { w, h } = size();
    dragBy(700, 520, -180, -60);
    close(strokeOf(paint(), '#ff00ff'), [0.2 * w, 0.2 * h, 0.3 * w, 0.3 * h]);
  });

  it('keeps its proportions when the chart is resized', () => {
    const { chart, draw, paint, size } = mount();
    viewportRect(draw);
    chart.applySize(1000, 720);
    const { w, h } = size();
    close(strokeOf(paint(), '#ff00ff'), [0.2 * w, 0.2 * h, 0.3 * w, 0.3 * h]);
  });

  it('multiplies by the device pixel ratio like every other drawing', () => {
    const { draw, paint, size } = mount();
    viewportRect(draw);
    draw.add({ tool: 'text', paneIndex: 0, style: {}, points: [], space: 'viewport', viewportPoints: [{ x: 0.1, y: 0.05 }], text: { value: 'Pinned' } });
    const { w, h } = size();
    close(strokeOf(paint(0, 2), '#ff00ff'), [0.4 * w, 0.4 * h, 0.6 * w, 0.6 * h]);
    const text1 = paint(0, 1).ops.find(op => op.type === 'fillText' && op.text === 'Pinned')!.args;
    const text2 = paint(0, 2).ops.find(op => op.type === 'fillText' && op.text === 'Pinned')!.args;
    expect(text2[0]).toBeCloseTo(text1[0] * 2, 6);
    expect(text2[1]).toBeCloseTo(text1[1] * 2, 6);
  });

  it('hit-tests where it paints, body and handles alike', () => {
    const { chart, draw, hit, size } = mount();
    const r = viewportRect(draw);
    const { w, h } = size();
    expect(hit(0.35 * w, 0.35 * h)?.externalId).toBe(`draw:${r.id}`);
    expect(hit(0.9 * w, 0.9 * h)).toBeNull();
    draw.select(r.id);
    expect(hit(0.5 * w, 0.5 * h)?.externalId).toBe(`draw:${r.id}#1`);
    chart.setVisibleLogicalRange({ from: 10, to: 40 });
    expect(hit(0.35 * w, 0.35 * h)?.externalId).toBe(`draw:${r.id}`);
  });

  it('skips a saved viewport entry whose tool cannot be anchored to the screen, without throwing', () => {
    const { draw, paint, hit, size } = mount();
    draw.fromJSON({ version: 2, drawings: [{ id: 'h', tool: 'horizontal-line', paneIndex: 0, zIndex: 0, style: { color: '#ff00ff' },
      points: [], space: 'viewport', viewportPoints: [{ x: 0.5, y: 0.5 }] }] });
    expect(draw.drawings()).toHaveLength(1);
    expect(() => paint()).not.toThrow();
    expect(paint().count('stroke')).toBe(0);
    const { w, h } = size();
    expect(hit(0.5 * w, 0.5 * h)).toBeNull();
  });

  it('keeps a pinned box with fewer anchors than its tool needs unpainted, like any incomplete drawing, without throwing', () => {
    const { draw, paint, hit, size } = mount();
    // One corner of a box: a hand-edited save or a host can hand it over, and
    // both `add` and the migration accept any finite anchors.
    const r = draw.add({ tool: 'rectangle', paneIndex: 0, style: { color: '#ff00ff' }, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.8, y: 0.8 }] });
    viewportRect(draw, { style: { color: '#00ff00' } });
    expect(() => paint()).not.toThrow();
    expect(strokeOf(paint(), '#ff00ff')).toBeUndefined();
    expect(strokeOf(paint(), '#00ff00')).toBeDefined();
    const { w, h } = size();
    expect(hit(0.8 * w, 0.8 * h)).toBeNull();
    const [at] = draw.screenPoints(r.id)!;
    expect(at.x).toBeCloseTo(0.8 * w, 6);
    expect(at.y).toBeCloseTo(0.8 * h, 6);
  });

  it('pins a box with fewer anchors than its tool needs where its one anchor is, without throwing', () => {
    const { draw, size } = mount();
    const r = draw.add({ tool: 'rectangle', paneIndex: 0, style: {}, points: [{ time: bars[50].time, price: 100 }] });
    const before = draw.screenPoints(r.id)!;
    expect(() => draw.update(r.id, { space: 'viewport' })).not.toThrow();
    expect(draw.get(r.id)!.space).toBe('viewport');
    const { w, h } = size();
    const [p] = draw.get(r.id)!.viewportPoints!;
    expect(p.x * w).toBeCloseTo(before[0].x, 6);
    expect(p.y * h).toBeCloseTo(before[0].y, 6);
  });
});

describe('adding a viewport drawing', () => {
  it('keeps the fractions, clears the data anchors and copies what it was given', () => {
    const { draw } = mount();
    const given = [{ x: 0.2, y: 0.2 }, { x: 0.5, y: 0.5 }];
    const r = draw.add({ tool: 'rectangle', paneIndex: 0, style: {}, space: 'viewport', viewportPoints: given,
      points: [{ time: T0, price: 100 }] });
    expect(r.space).toBe('viewport');
    expect(r.points).toEqual([]);
    expect(r.viewportPoints).toEqual(given);
    given[0].x = 0.9;
    expect(draw.get(r.id)?.viewportPoints?.[0].x).toBe(0.2);
    // A data drawing carries no space and no viewport anchors at all.
    const d = dataRect(draw);
    expect('space' in d).toBe(false);
    expect('viewportPoints' in d).toBe(false);
  });

  it('refuses a tool that cannot be anchored to the screen, and anchors that are not numbers', () => {
    const { draw } = mount();
    expect(() => draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.1, y: 0.1 }, { x: 0.2, y: 0.2 }] })).toThrow(/viewport/);
    expect(() => draw.add({ tool: 'rectangle', paneIndex: 0, style: {}, points: [], space: 'viewport',
      viewportPoints: [{ x: Number.NaN, y: 0.1 }, { x: 0.2, y: 0.2 }] })).toThrow(/viewport/);
    expect(() => draw.add({ tool: 'rectangle', paneIndex: 0, style: {}, points: [], space: 'viewport' })).toThrow(/viewport/);
    expect(draw.drawings()).toHaveLength(0);
  });

  it('places one with the pointer when the tool is armed for the viewport', () => {
    const { draw, click, size, chart } = mount();
    expect(() => draw.setTool('trend-line', { space: 'viewport' })).toThrow(/viewport/);
    draw.setTool('text', { space: 'viewport' });
    expect(draw.activeToolSpace()).toBe('viewport');
    click(300, 200);
    const [t] = draw.drawings();
    const { w, h } = size();
    expect(t.space).toBe('viewport');
    expect(t.viewportPoints![0].x).toBeCloseTo(300 / w, 6);
    expect(t.viewportPoints![0].y).toBeCloseTo(200 / h, 6);
    chart.setVisibleLogicalRange({ from: 50, to: 60 });
    const [at] = draw.screenPoints(t.id)!;
    expect(at.x).toBeCloseTo(300, 6);
    expect(at.y).toBeCloseTo(200, 6);
    // Disarmed, the next tool places in data space again.
    draw.setTool('rectangle');
    expect(draw.activeToolSpace()).toBe('data');
  });
});

describe('editing a viewport drawing', () => {
  it('moves by the pointer delta as a fraction of the plot, and undoes in one step', () => {
    const { chart, draw, dragBy, size } = mount();
    const r = viewportRect(draw);
    const { w, h } = size();
    dragBy(0.35 * w, 0.35 * h, 50, 30);
    const moved = draw.get(r.id)!.viewportPoints!;
    expect(moved[0].x).toBeCloseTo(0.2 + 50 / w, 6);
    expect(moved[0].y).toBeCloseTo(0.2 + 30 / h, 6);
    expect(moved[1].x).toBeCloseTo(0.5 + 50 / w, 6);
    expect(draw.get(r.id)!.points).toEqual([]);
    // The chart did not pan under the drag.
    expect(chart.getVisibleLogicalRange().from).toBeCloseTo(0, 6);
    expect(draw.undo()).toBe(true);
    expect(draw.get(r.id)!.viewportPoints).toEqual([{ x: 0.2, y: 0.2 }, { x: 0.5, y: 0.5 }]);
  });

  it('resizes by a handle to the pointer position', () => {
    const { draw, dragBy, size } = mount();
    const r = viewportRect(draw);
    draw.select(r.id);
    const { w, h } = size();
    dragBy(0.5 * w, 0.5 * h, 0.1 * w, 0.2 * h);
    const [a, b] = draw.get(r.id)!.viewportPoints!;
    expect(a).toEqual({ x: 0.2, y: 0.2 });
    expect(b.x).toBeCloseTo(0.6, 6);
    expect(b.y).toBeCloseTo(0.7, 6);
  });

  it('never drags an anchor out of its pane, where no gesture could reach it again', () => {
    const { draw, dragBy, size } = mount();
    const r = viewportRect(draw);
    const { w, h } = size();
    dragBy(0.35 * w, 0.35 * h, 2000, 2000);
    const [p0, p1] = draw.get(r.id)!.viewportPoints!;
    close([p0.x, p0.y, p1.x, p1.y], [0.7, 0.7, 1, 1], 9);
    draw.select(r.id);
    dragBy(0.2 * w + 0.7 * w - 0.2 * w, 0.7 * h, -3000, -3000);
    const [a] = draw.get(r.id)!.viewportPoints!;
    expect(a).toEqual({ x: 0, y: 0 });
  });

  it('nudges by screen pixels', () => {
    const { draw, size } = mount();
    const r = viewportRect(draw);
    const { w, h } = size();
    draw.nudge([r.id], 10, -5);
    const [a] = draw.get(r.id)!.viewportPoints!;
    expect(a.x).toBeCloseTo(0.2 + 10 / w, 9);
    expect(a.y).toBeCloseTo(0.2 - 5 / h, 9);
  });

  it('has no price for an alert to read, even on a tool that offers alerts in data space', () => {
    const { draw } = mount();
    registerDrawingTool({
      id: 'test-viewport-level', name: 'Level', points: 1, viewport: true,
      alertValue: c => ({ price: c.fromY(c.pts[0].y) ?? Number.NaN }),
      draw: () => {}, distance: () => null,
    });
    const level = draw.add({ tool: 'test-viewport-level', paneIndex: 0, style: {}, points: [{ time: bars[50].time, price: 100 }] });
    expect(draw.alertInfo(level.id).available).toBe(true);
    const pinned = draw.add({ tool: 'test-viewport-level', paneIndex: 0, style: {}, points: [], space: 'viewport', viewportPoints: [{ x: 0.5, y: 0.5 }] });
    const info = draw.alertInfo(pinned.id);
    expect(info.available).toBe(false);
    expect(info.reason).toMatch(/screen/);
    expect(draw.valueAt(pinned.id, bars[50].time)).toBeUndefined();
  });
});

describe('keeping a pinned drawing on screen', () => {
  const pinnedNote = (draw: DrawingController, text: Partial<NonNullable<Drawing['text']>> = {}): Drawing => draw.add({
    tool: 'text', paneIndex: 0, style: {}, points: [], space: 'viewport', viewportPoints: [{ x: 0.45, y: 0.45 }],
    text: { value: 'Edge note', ...text },
  });
  const pinnedTable = (draw: DrawingController): Drawing => draw.add({
    tool: 'table', paneIndex: 0, style: {}, points: [], space: 'viewport', viewportPoints: [{ x: 0.45, y: 0.45 }],
    text: { value: 'Level|Price\nEntry|101.25\nStop|99.50' },
  });
  const makers: [string, (draw: DrawingController) => Drawing][] = [
    ['a note', draw => pinnedNote(draw)],
    ['a note hung from its bottom edge', draw => pinnedNote(draw, { valign: 'bottom' })],
    ['a table', pinnedTable],
    ['a box', draw => viewportRect(draw)],
  ];
  const corners = [[1, 1], [-1, -1], [1, -1], [-1, 1]];

  it.each(makers)('keeps %s wholly inside the plot, painted and clickable, when dragged past every corner', (_name, make) => {
    for (const [sx, sy] of corners) {
      const { draw, dragBy, hit, paint, size } = mount();
      const d = make(draw);
      const { w, h } = size();
      const start = expectOnPlot(hit, d.id, w, h);
      dragBy((start.x0 + start.x1) / 2, (start.y0 + start.y1) / 2, sx * 3000, sy * 3000);
      const end = expectOnPlot(hit, d.id, w, h);
      // It went all the way to the corner it was thrown at.
      if (sx > 0) expect(end.x1).toBeGreaterThan(w - 16); else expect(end.x0).toBeLessThan(16);
      if (sy > 0) expect(end.y1).toBeGreaterThan(h - 16); else expect(end.y0).toBeLessThan(16);
      expectPaintedOnPlot(paint(0, 1), w, h, 1);
      expectPaintedOnPlot(paint(0, 2), w, h, 2);
      // Grabbable again from where it landed, and it moves off the edge. The
      // grab is near its top-right corner, clear of the chart's logo mark,
      // which takes a press in the bottom-left before any drawing does.
      const before = draw.get(d.id)!.viewportPoints!.map(p => ({ ...p }));
      dragBy(end.x1 - 8, end.y0 + 8, -sx * 40, -sy * 30);
      const after = draw.get(d.id)!.viewportPoints!;
      expect(after[0].x).toBeCloseTo(before[0].x - (sx * 40) / w, 6);
      expect(after[0].y).toBeCloseTo(before[0].y - (sy * 30) / h, 6);
    }
  });

  it('keeps a note inside through a nudge and a drag of its handle, and a box resized by a handle keeps its other corner', () => {
    const { draw, dragBy, hit, size } = mount();
    const note = pinnedNote(draw);
    const { w, h } = size();
    draw.nudge([note.id], 5000, 5000);
    expectOnPlot(hit, note.id, w, h);
    draw.nudge([note.id], -9000, -9000);
    expectOnPlot(hit, note.id, w, h);
    close([draw.get(note.id)!.viewportPoints![0].x, draw.get(note.id)!.viewportPoints![0].y], [0, 0], 9);
    draw.select(note.id);
    const [corner] = draw.screenPoints(note.id)!;
    dragBy(corner.x, corner.y, 3000, 3000);
    const region = expectOnPlot(hit, note.id, w, h);
    expect(region.x1).toBeGreaterThan(w - 16);
    const box = viewportRect(draw);
    draw.select(box.id);
    dragBy(0.5 * w, 0.5 * h, 3000, 3000);
    const [a, b] = draw.get(box.id)!.viewportPoints!;
    close([a.x, a.y, b.x, b.y], [0.2, 0.2, 1, 1], 9);
  });

  it('pastes and duplicates a note at the edge onto the plot', async () => {
    const port = memoryPort();
    const { draw, dragBy, hit, size } = mount(800, 600, { clipboard: port });
    const note = pinnedNote(draw);
    const { w, h } = size();
    const start = hitRegion(hit, note.id, w, h);
    dragBy((start.x0 + start.x1) / 2, (start.y0 + start.y1) / 2, 3000, 3000);
    expect(await draw.copy(note.id)).toBe(true);
    const [pasted] = await draw.paste();
    expectOnPlot(hit, pasted.id, w, h);
    const [dup] = draw.duplicate([note.id]);
    expectOnPlot(hit, dup.id, w, h);
  });

  it('stays wholly on screen and clickable when the chart shrinks, and where a host placed it off the plot', () => {
    const { chart, draw, dragBy, hit, paint, size } = mount();
    const note = pinnedNote(draw);
    let { w, h } = size();
    const noteAt = hitRegion(hit, note.id, w, h);
    dragBy((noteAt.x0 + noteAt.x1) / 2, (noteAt.y0 + noteAt.y1) / 2, 3000, 3000);
    // The table goes to the other corner on the right, so neither covers the other.
    const table = pinnedTable(draw);
    const tableAt = hitRegion(hit, table.id, w, h);
    dragBy((tableAt.x0 + tableAt.x1) / 2, (tableAt.y0 + tableAt.y1) / 2, 3000, -3000);
    chart.applySize(360, 240);
    ({ w, h } = size());
    expectOnPlot(hit, note.id, w, h);
    expectOnPlot(hit, table.id, w, h);
    expectPaintedOnPlot(paint(0, 1), w, h, 1);
    expectPaintedOnPlot(paint(0, 2), w, h, 2);
    // The host's editor is placed where the note is painted.
    const region = hitRegion(hit, note.id, w, h);
    const [at] = draw.screenPoints(note.id)!;
    expect(Math.abs(at.x - (region.x0 + 3))).toBeLessThanOrEqual(7);
    // A host may store any finite fraction; the note is still painted on the plot.
    const off = draw.add({ tool: 'text', paneIndex: 0, style: {}, points: [], space: 'viewport',
      viewportPoints: [{ x: 1.4, y: -0.3 }], text: { value: 'Parked' } });
    expectOnPlot(hit, off.id, w, h);
    expect(draw.get(off.id)!.viewportPoints).toEqual([{ x: 1.4, y: -0.3 }]);
  });

  it('hit-tests a pinned drawing at a device pixel ratio of two where it does at one', () => {
    const { draw, hit, size } = mount();
    const note = pinnedNote(draw);
    const box = viewportRect(draw);
    const { w, h } = size();
    for (const d of [note, box]) {
      const one = hitRegion((x, y) => hit(x, y, 0, 1), d.id, w, h, 11);
      const two = hitRegion((x, y) => hit(x, y, 0, 2), d.id, w, h, 11);
      expect(two).toEqual(one);
      expect(one.inside).toBeGreaterThan(3);
    }
  });
});

describe('a pinned box with its label outside', () => {
  // A 14 px label (the shape default) is one line of 14 * 1.35 px, lifted 6 px
  // clear of the outline: the shape's top sits this far below the label's.
  const LIFT = 14 * 1.35 + 6;
  const labelled = (draw: DrawingController, tool: string, at = [{ x: 0.3, y: 0.4 }, { x: 0.5, y: 0.6 }]): Drawing => draw.add({
    tool, paneIndex: 0, style: { color: '#ff00ff' }, points: [], space: 'viewport', viewportPoints: at,
    text: { value: 'Outside label', position: 'outside', color: '#ffd400' },
  });
  /** The label's [x, y] as painted, and the shape's top edge, in device px. */
  const painted = (rec: RecordingContext) => {
    const label = rec.ops.find(op => op.type === 'fillText' && op.text === 'Outside label')?.args;
    const rect = strokeOf(rec, '#ff00ff');
    const ellipse = rec.ops.find(op => op.type === 'ellipse')?.args;
    expect(label).toBeDefined();
    return { label: label!, top: rect !== undefined ? rect[1] : ellipse![1] - ellipse![3] };
  };
  const tools = ['rectangle', 'ellipse'];

  it.each(tools)('keeps the label of a %s at the top edge on the plot, where a host put it and where a drag took it', (tool) => {
    const { draw, dragBy, hit, paint, size } = mount();
    const { w, h } = size();
    const parked = labelled(draw, tool, [{ x: 0.3, y: 0 }, { x: 0.5, y: 0.2 }]);
    for (const dpr of [1, 2]) {
      const at = painted(paint(0, dpr));
      expect(at.label[1]).toBeGreaterThanOrEqual(0);
      expect(at.top).toBeCloseTo(LIFT * dpr, 6);
    }
    expectOnPlot(hit, parked.id, w, h);
    draw.remove(parked.id);
    const thrown = labelled(draw, tool);
    const start = expectOnPlot(hit, thrown.id, w, h);
    dragBy((start.x0 + start.x1) / 2, (start.y0 + start.y1) / 2, 0, -3000);
    for (const dpr of [1, 2]) {
      const at = painted(paint(0, dpr));
      expect(at.label[1]).toBeGreaterThanOrEqual(0);
      expect(at.label[1]).toBeLessThan(1);
      expect(at.top).toBeCloseTo(LIFT * dpr, 6);
    }
    expectOnPlot(hit, thrown.id, w, h);
  });

  it.each(tools)('stops the top handle of a %s below its label at the top edge, and leaves the other corner where it was', (tool) => {
    const { draw, dragBy, paint, size } = mount();
    const { h } = size();
    const d = labelled(draw, tool);
    draw.select(d.id);
    const [corner] = draw.screenPoints(d.id)!;
    dragBy(corner.x, corner.y, 0, -3000);
    const [a, b] = draw.get(d.id)!.viewportPoints!;
    close([a.x, a.y, b.x, b.y], [0.3, LIFT / h, 0.5, 0.6], 9);
    expect(painted(paint()).label[1]).toBeCloseTo(0, 6);
  });

  it('keeps a label that runs past the sides of a narrow box on the plot at the right edge', () => {
    const { draw, paint, size } = mount();
    const { w } = size();
    const value = 'A label much wider than its box';
    draw.add({ tool: 'rectangle', paneIndex: 0, style: { color: '#ff00ff' }, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.97, y: 0.4 }, { x: 1, y: 0.5 }], text: { value } });
    for (const dpr of [1, 2]) {
      const rec = paint(0, dpr);
      const label = rec.ops.find(op => op.type === 'fillText' && op.text === value)!;
      // The recording context measures 6 px a character.
      expect(label.args[0] + value.length * 6 * dpr).toBeLessThanOrEqual(w * dpr);
      expect(strokeOf(rec, '#ff00ff')![0]).toBeGreaterThanOrEqual(0);
    }
  });

  it('pins a labelled box taller than the plot with its label and both handles on screen', () => {
    const { chart, draw, hit, paint, size } = mount();
    const scale = chart.panes()[0].priceScale;
    scale.setAutoScale(false);
    scale.setPriceRange({ min: 90, max: 110 });
    const r = draw.add({ tool: 'rectangle', paneIndex: 0, style: { color: '#ff00ff' },
      points: [{ time: bars[40].time, price: 130 }, { time: bars[60].time, price: 70 }],
      text: { value: 'Outside label', position: 'outside', color: '#ffd400' } });
    expect(draw.update(r.id, { space: 'viewport' })).toBe(true);
    const { w, h } = size();
    const at = painted(paint());
    expect(at.label[1]).toBeGreaterThanOrEqual(0);
    expect(at.top).toBeCloseTo(LIFT, 6);
    draw.select(r.id);
    draw.screenPoints(r.id)!.forEach((p, i) => {
      expect(p.y).toBeLessThanOrEqual(h);
      expect(hit(p.x, p.y)?.externalId).toBe(`draw:${r.id}#${i}`);
    });
    expectOnPlot(hit, r.id, w, h);
  });
});

describe('placing a pinned drawing', () => {
  it('lands where it is clicked with the magnet on, and shows no magnet ring on the way', () => {
    const { draw, click, move, paint, size } = mount();
    viewportRect(draw);
    draw.setOptions({ magnet: 'strong' });
    // The control: armed for time and price, the strong magnet shows its ring.
    draw.setTool('text');
    move(300, 40);
    expect(paint().count('arc')).toBeGreaterThan(0);
    draw.setTool('text', { space: 'viewport' });
    move(300, 41);
    expect(paint().count('arc')).toBe(0);
    click(300, 40);
    const note = draw.drawings().find(d => d.tool === 'text')!;
    const { w, h } = size();
    expect(note.space).toBe('viewport');
    expect(note.viewportPoints![0].x).toBeCloseTo(300 / w, 6);
    expect(note.viewportPoints![0].y).toBeCloseTo(40 / h, 6);
  });

  it('places a note clicked at the right edge with the whole note on the plot', () => {
    const { draw, click, hit, size } = mount();
    const { w, h } = size();
    draw.setTool('text', { space: 'viewport' });
    click(w - 2, h - 2);
    const note = draw.drawings()[0];
    expect(note.space).toBe('viewport');
    expectOnPlot(hit, note.id, w, h);
  });
});

describe('pinning a drawing that is not wholly on screen', () => {
  it('brings one that is scrolled off the plot onto it, where it can be grabbed and moved', () => {
    const { chart, draw, dragBy, hit, size } = mount();
    const r = dataRect(draw);
    chart.setVisibleLogicalRange({ from: 70, to: 99 });
    const { w, h } = size();
    expect(hitRegion(hit, r.id, w, h).inside).toBe(0);
    expect(draw.update(r.id, { space: 'viewport' })).toBe(true);
    const region = expectOnPlot(hit, r.id, w, h);
    // What is stored is where it is painted, so a resize keeps it there in proportion.
    for (const p of draw.get(r.id)!.viewportPoints!) {
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThanOrEqual(1);
    }
    const [a] = draw.get(r.id)!.viewportPoints!;
    dragBy((region.x0 + region.x1) / 2, (region.y0 + region.y1) / 2, 60, 20);
    expect(draw.get(r.id)!.viewportPoints![0].x).toBeCloseTo(a.x + 60 / w, 6);
  });

  it('cuts one wider than the plot to it, so every handle is on screen', () => {
    const { chart, draw, hit, size } = mount();
    const r = draw.add({ tool: 'rectangle', paneIndex: 0, style: { color: '#00ffff' },
      points: [{ time: bars[2].time, price: 101 }, { time: bars[97].time, price: 99 }] });
    chart.setVisibleLogicalRange({ from: 30, to: 60 });
    draw.update(r.id, { space: 'viewport' });
    const { w, h } = size();
    for (const p of draw.get(r.id)!.viewportPoints!) {
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThanOrEqual(1);
    }
    draw.select(r.id);
    draw.screenPoints(r.id)!.forEach((p, i) => expect(hit(Math.min(p.x, w - 1), p.y)?.externalId).toBe(`draw:${r.id}#${i}`));
    expectOnPlot(hit, r.id, w, h);
  });

  it('reports a change of space it could not make, and applies the rest of the patch', () => {
    const { draw } = mount();
    const line = draw.add({ tool: 'trend-line', paneIndex: 0, style: {},
      points: [{ time: bars[10].time, price: 100 }, { time: bars[20].time, price: 102 }] });
    expect(draw.update(line.id, { space: 'viewport', style: { color: '#123456' } })).toBe(false);
    expect(draw.get(line.id)!.style.color).toBe('#123456');
    const r = dataRect(draw);
    expect(draw.update(r.id, { space: 'viewport' })).toBe(true);
    expect(draw.update(r.id, { space: 'viewport' })).toBe(true);
    expect(draw.update(r.id, { style: { color: '#654321' } })).toBe(true);
  });
});

describe('converting between spaces', () => {
  it('keeps the drawing where it is on screen both ways, and each way is one undo step', () => {
    const { chart, draw } = mount();
    const r = dataRect(draw);
    const original = draw.get(r.id)!.points.map(p => ({ ...p }));
    const before = draw.screenPoints(r.id)!;
    draw.update(r.id, { space: 'viewport' });
    const pinned = draw.get(r.id)!;
    expect(pinned.space).toBe('viewport');
    expect(pinned.points).toEqual([]);
    expect(pinned.viewportPoints).toHaveLength(2);
    draw.screenPoints(r.id)!.forEach((p, i) => { expect(p.x).toBeCloseTo(before[i].x, 6); expect(p.y).toBeCloseTo(before[i].y, 6); });
    // Pan and zoom: still where it was.
    chart.setVisibleLogicalRange({ from: 20, to: 60 });
    draw.screenPoints(r.id)!.forEach((p, i) => { expect(p.x).toBeCloseTo(before[i].x, 6); expect(p.y).toBeCloseTo(before[i].y, 6); });
    // Back to time and price, at the view in force now.
    draw.update(r.id, { space: 'data' });
    const back = draw.get(r.id)!;
    expect('space' in back).toBe(false);
    expect('viewportPoints' in back).toBe(false);
    expect(back.points).toHaveLength(2);
    draw.screenPoints(r.id)!.forEach((p, i) => { expect(p.x).toBeCloseTo(before[i].x, 6); expect(p.y).toBeCloseTo(before[i].y, 6); });
    expect(draw.undo()).toBe(true);
    expect(draw.get(r.id)!.space).toBe('viewport');
    expect(draw.undo()).toBe(true);
    expect(draw.get(r.id)!.space).toBeUndefined();
    expect(draw.get(r.id)!.points).toEqual(original);
    expect(draw.redo()).toBe(true);
    expect(draw.get(r.id)!.space).toBe('viewport');
  });

  it('converts what it can in one edit and leaves a tool that cannot be anchored to the screen in data space', () => {
    const { draw } = mount();
    const line = draw.add({ tool: 'trend-line', paneIndex: 0, style: {},
      points: [{ time: bars[10].time, price: 100 }, { time: bars[20].time, price: 102 }] });
    const r = dataRect(draw);
    draw.updateMany([line.id, r.id].map(id => ({ id, patch: { space: 'viewport' as const, style: { color: '#123456' } } })));
    expect(draw.get(r.id)!.space).toBe('viewport');
    expect(draw.get(r.id)!.viewportPoints).toHaveLength(2);
    expect(draw.get(line.id)!.space).toBeUndefined();
    expect(draw.get(line.id)!.style.color).toBe('#123456');
    expect(draw.get(line.id)!.points).toHaveLength(2);
    expect(draw.undo()).toBe(true);
    expect(draw.get(r.id)!.space).toBeUndefined();
    expect(draw.get(line.id)!.style.color).toBeUndefined();
  });

  it('takes the anchors of the new space as given when the patch carries them', () => {
    const { draw } = mount();
    const r = dataRect(draw);
    draw.update(r.id, { space: 'viewport', viewportPoints: [{ x: 0.1, y: 0.1 }, { x: 0.3, y: 0.4 }] });
    expect(draw.get(r.id)!.viewportPoints).toEqual([{ x: 0.1, y: 0.1 }, { x: 0.3, y: 0.4 }]);
  });
});

describe('panes', () => {
  it('follows its pane when the pane moves, at the same fraction of the new slot', () => {
    const { chart, draw, size } = mount(800, 700, { panes: 3 });
    const note = draw.add({ tool: 'text', paneIndex: 1, style: {}, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.25, y: 0.5 }], text: { value: 'Pane note' } });
    expect(chart.movePane(1, 1)).toBe(true);
    const moved = draw.get(note.id)!;
    expect(moved.paneIndex).toBe(2);
    expect(moved.viewportPoints).toEqual([{ x: 0.25, y: 0.5 }]);
    const [at] = draw.screenPoints(note.id)!;
    // Placed by the chart's rectangle, and asking for it scaled the moved
    // pane, so the pane's own scale puts its top at the same place.
    const rect = chart.plotRect(2)!;
    expect(rect.width).toBe(size(2).w);
    expect(at.x).toBeCloseTo(rect.left + 0.25 * rect.width, 6);
    expect(at.y).toBeCloseTo(rect.top + 0.5 * rect.height, 6);
    expect(at.y).toBeLessThan(700);
    const top = chart.priceToCoordinate(chart.panes()[2].yToPrice(0), 2)!;
    expect(at.y).toBeCloseTo(top + 0.5 * size(2).h, 6);
  });

  it('converts on a pane no frame has painted yet at the prices that pane shows, both ways', () => {
    // A moved pane, and a pane just made, keep their placeholder scale until
    // something asks for a price there: pinning or unpinning in code is such
    // an ask, or it stores the placeholder's 0..1 as prices.
    const { chart, draw } = mount(800, 700, { panes: 3 });
    const box = draw.add({ tool: 'rectangle', paneIndex: 1, style: {}, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.2, y: 0.25 }, { x: 0.6, y: 0.75 }] });
    expect(chart.movePane(1, 1)).toBe(true);
    expect(draw.update(box.id, { space: 'data' })).toBe(true);
    const rect = chart.plotRect(2)!;
    const prices = draw.get(box.id)!.points.map(p => p.price);
    expect(prices[0]).toBeCloseTo(chart.coordinateToPrice(rect.top + 0.25 * rect.height, 2)!, 6);
    expect(prices[1]).toBeCloseTo(chart.coordinateToPrice(rect.top + 0.75 * rect.height, 2)!, 6);
    expect(Math.min(...prices)).toBeGreaterThan(90);

    const fresh = mount(800, 700);
    fresh.chart.addSeries('line', { paneIndex: 1 }).setData(bars.map(b => ({ time: b.time, value: b.close })));
    const note = fresh.draw.add({ tool: 'rectangle', paneIndex: 1, style: {}, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.2, y: 0.25 }, { x: 0.6, y: 0.75 }] });
    expect(fresh.draw.update(note.id, { space: 'data' })).toBe(true);
    expect(Math.min(...fresh.draw.get(note.id)!.points.map(p => p.price))).toBeGreaterThan(90);

    const other = mount(800, 700, { panes: 3 });
    expect(other.chart.movePane(1, 1)).toBe(true);
    const data = other.draw.add({ tool: 'rectangle', paneIndex: 2, style: {},
      points: [{ time: bars[20].time, price: 99 }, { time: bars[40].time, price: 102 }] });
    expect(other.draw.update(data.id, { space: 'viewport' })).toBe(true);
    const frame = other.chart.plotRect(2)!;
    const ys = other.draw.get(data.id)!.viewportPoints!.map(p => p.y);
    expect(ys[0]).toBeCloseTo((other.chart.priceToCoordinate(99, 2)! - frame.top) / frame.height, 6);
    expect(ys[1]).toBeCloseTo((other.chart.priceToCoordinate(102, 2)! - frame.top) / frame.height, 6);
    expect(ys[0]).toBeGreaterThan(ys[1]);
  });

  it('survives a pane collapse and comes back where it was', () => {
    const { chart, draw } = mount(800, 700, { panes: 2 });
    const note = draw.add({ tool: 'text', paneIndex: 1, style: {}, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.4, y: 0.3 }], text: { value: 'Folded' } });
    const before = draw.screenPoints(note.id)!;
    expect(chart.setPaneCollapsed(1, true)).toBe(true);
    // A strip plots nothing, so it has no place on screen for the note.
    expect(draw.screenPoints(note.id)).toBeNull();
    expect(draw.get(note.id)!.viewportPoints).toEqual([{ x: 0.4, y: 0.3 }]);
    // Nor can it be converted while folded: the strip is not the plot it is a
    // fraction of. The call says so, where a host would otherwise think it did.
    expect(draw.update(note.id, { space: 'data' })).toBe(false);
    expect(draw.get(note.id)!.space).toBe('viewport');
    expect(chart.setPaneCollapsed(1, false)).toBe(true);
    const after = draw.screenPoints(note.id)!;
    expect(after[0].x).toBeCloseTo(before[0].x, 6);
    expect(after[0].y).toBeCloseTo(before[0].y, 6);
  });
});

describe('the plot the chart reports', () => {
  /**
   * The chart answers where a pane's plot is (`chart.plotRect`), and a pinned
   * drawing is a fraction of that answer. A host that moves the plot (an
   * inset, a custom frame) moves the drawing with it; the controller no longer
   * works the rectangle out from the scales, so nothing can make the two
   * disagree.
   */
  function insetPlot(chart: Chart, dx: number, dy: number, scale: number): void {
    const own = chart.plotRect.bind(chart);
    chart.plotRect = (paneIndex: number) => {
      const rect = own(paneIndex);
      return rect && { left: rect.left + dx, top: rect.top + dy, width: rect.width * scale, height: rect.height * scale };
    };
  }

  it('places a pinned drawing on the screen by chart.plotRect', () => {
    const { chart, draw } = mount(800, 700, { panes: 2 });
    const note = draw.add({ tool: 'text', paneIndex: 1, style: {}, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.25, y: 0.5 }], text: { value: 'Reported' } });
    const rect = chart.plotRect(1)!;
    const [at] = draw.screenPoints(note.id)!;
    expect(at.x).toBeCloseTo(rect.left + 0.25 * rect.width, 6);
    expect(at.y).toBeCloseTo(rect.top + 0.5 * rect.height, 6);
    insetPlot(chart, 12, 7, 0.5);
    const [inset] = draw.screenPoints(note.id)!;
    expect(inset.x).toBeCloseTo(rect.left + 12 + 0.25 * rect.width * 0.5, 6);
    expect(inset.y).toBeCloseTo(rect.top + 7 + 0.5 * rect.height * 0.5, 6);
  });

  it('pins a data drawing, and places one with the pointer, as fractions of that plot', () => {
    const { chart, draw, click } = mount();
    const rect = chart.plotRect(0)!;
    insetPlot(chart, 0, 0, 2);
    // The data rectangle stays where it is on screen, so its fractions halve.
    const d = dataRect(draw);
    const before = draw.screenPoints(d.id)!;
    expect(draw.update(d.id, { space: 'viewport' })).toBe(true);
    const pinned = draw.get(d.id)!.viewportPoints!;
    pinned.forEach((p, i) => {
      expect(p.x).toBeCloseTo((before[i].x - rect.left) / (rect.width * 2), 6);
      expect(p.y).toBeCloseTo((before[i].y - rect.top) / (rect.height * 2), 6);
    });
    draw.setTool('text', { space: 'viewport' });
    click(300, 200);
    const placed = draw.drawings().find(item => item.tool === 'text')!;
    expect(placed.viewportPoints![0].x).toBeCloseTo((300 - rect.left) / (rect.width * 2), 6);
    expect(placed.viewportPoints![0].y).toBeCloseTo((200 - rect.top) / (rect.height * 2), 6);
  });

  it('has no place for a pinned drawing where the chart reports no plot', () => {
    const { chart, draw } = mount();
    const r = viewportRect(draw);
    chart.plotRect = () => null;
    expect(draw.screenPoints(r.id)).toBeNull();
    expect(draw.update(r.id, { space: 'data' })).toBe(false);
  });
});

describe('copy, paste and restore', () => {
  it('pastes at the same fraction plus the paste offset, on this chart and on another of a different size', async () => {
    const port = memoryPort();
    const a = mount(800, 600, { clipboard: port });
    const r = viewportRect(a.draw);
    expect(await a.draw.copy(r.id)).toBe(true);
    const [same] = await a.draw.paste();
    const { w, h } = a.size();
    expect(same.space).toBe('viewport');
    expect(same.viewportPoints![0].x).toBeCloseTo(0.2 + 16 / w, 9);
    expect(same.viewportPoints![0].y).toBeCloseTo(0.2 + 16 / h, 9);
    const b = mount(1000, 720, { clipboard: port });
    const [other] = await b.draw.paste();
    const size = b.size();
    expect(other.space).toBe('viewport');
    expect(other.viewportPoints![0].x).toBeCloseTo(0.2 + 16 / size.w, 9);
    expect(other.viewportPoints![1].y).toBeCloseTo(0.5 + 16 / size.h, 9);
    const [dup] = a.draw.duplicate([r.id]);
    expect(dup.space).toBe('viewport');
    expect(dup.viewportPoints![0].x).toBeCloseTo(0.2 + 16 / w, 9);
  });

  it('round-trips through the chart state and a restore', () => {
    const a = mount();
    const r = viewportRect(a.draw, { text: { value: 'Box' } });
    dataRect(a.draw);
    const state = JSON.parse(JSON.stringify(a.chart.getState()));
    const b = mount(1000, 700);
    b.chart.restoreState(state);
    const restored = b.draw.get(r.id)!;
    expect(restored.space).toBe('viewport');
    expect(restored.viewportPoints).toEqual([{ x: 0.2, y: 0.2 }, { x: 0.5, y: 0.5 }]);
    expect(restored.points).toEqual([]);
    const { w, h } = b.size();
    close(strokeOf(b.paint(), '#ff00ff'), [0.2 * w, 0.2 * h, 0.3 * w, 0.3 * h]);
    // A controller made after the restore reads the same slot.
    const late = new DrawingController(b.chart);
    cleanups.push(() => late.destroy());
    expect(late.get(r.id)?.viewportPoints).toEqual([{ x: 0.2, y: 0.2 }, { x: 0.5, y: 0.5 }]);
  });
});

describe('persistence formats', () => {
  it('loads a document with no viewport drawings exactly as before', () => {
    const doc = { version: 2, drawings: [
      { id: 'a', tool: 'rectangle', points: [{ time: 1, price: 2 }, { time: 3, price: 4 }], style: { color: '#fff' }, paneIndex: 0, zIndex: 0 },
      { id: 'b', tool: 'text', points: [{ time: 5, price: 6 }], style: {}, paneIndex: 1, zIndex: -1, text: { value: 'hi' } },
    ] };
    expect(JSON.stringify(migrateDrawings(doc))).toBe(JSON.stringify(doc));
    // A 1.9 bare array still upgrades, and still gains no space.
    const legacy = migrateDrawings([{ id: 'c', tool: 'text', points: [{ time: 1, price: 1 }], style: { text: 'old' }, paneIndex: 0 }]);
    expect(legacy.drawings[0].text?.value).toBe('old');
    expect('space' in legacy.drawings[0]).toBe(false);
  });

  it('round-trips a viewport drawing and drops one whose anchors are unusable', () => {
    const doc = migrateDrawings({ version: 2, drawings: [
      { id: 'v', tool: 'rectangle', points: [], space: 'viewport', viewportPoints: [{ x: 0.1, y: 0.2 }, { x: 0.3, y: 0.4 }], style: {}, paneIndex: 0, zIndex: 0 },
      { id: 'bad', tool: 'rectangle', points: [], space: 'viewport', viewportPoints: [{ x: 'a', y: 0.2 }], style: {}, paneIndex: 0, zIndex: 0 },
      { id: 'none', tool: 'text', points: [{ time: 1, price: 1 }], space: 'viewport', style: {}, paneIndex: 0, zIndex: 0 },
      { id: 'data', tool: 'text', points: [{ time: 1, price: 1 }], space: 'data', style: {}, paneIndex: 0, zIndex: 0 },
    ] });
    expect(doc.drawings.map(d => d.id)).toEqual(['v', 'data']);
    expect(doc.drawings[0]).toMatchObject({ space: 'viewport', points: [], viewportPoints: [{ x: 0.1, y: 0.2 }, { x: 0.3, y: 0.4 }] });
    // Data is the default, so it is not written out.
    expect('space' in doc.drawings[1]).toBe(false);
    expect(JSON.stringify(migrateDrawings(doc))).toBe(JSON.stringify(doc));
  });

  it('carries the space through the clipboard payload and refuses a tool that cannot hold it', () => {
    mount();
    const v: Drawing = { id: 'v', tool: 'rectangle', points: [], space: 'viewport', viewportPoints: [{ x: 0.1, y: 0.2 }, { x: 0.3, y: 0.4 }], style: {}, paneIndex: 0, zIndex: 0 };
    const [back] = decodeClipboardPayload(encodeClipboardPayload([v]))!;
    expect(back).toMatchObject({ space: 'viewport', points: [], viewportPoints: [{ x: 0.1, y: 0.2 }, { x: 0.3, y: 0.4 }] });
    expect(decodeClipboardPayload(encodeClipboardPayload([{ ...v, tool: 'horizontal-line', viewportPoints: [{ x: 0.1, y: 0.2 }] }]))).toBeNull();
    expect(decodeClipboardPayload(encodeClipboardPayload([{ ...v, viewportPoints: [{ x: 0.1, y: Number.NaN }] }]))).toBeNull();
  });
});

describe('drawing links', () => {
  it('never shares a viewport drawing, and a shared drawing moved to the screen leaves the link on that chart only', () => {
    const a = mount();
    const b = mount();
    const group = createDrawingLinkGroup({ enabled: true });
    cleanups.push(() => group.destroy());
    group.add(a.chart, a.draw, { symbol: 'X', exchange: 'NSE' });
    group.add(b.chart, b.draw, { symbol: 'X', exchange: 'NSE' });
    viewportRect(a.draw);
    expect(b.draw.drawings()).toHaveLength(0);
    expect(group.share(a.chart)).toBe(0);
    const shared = dataRect(a.draw);
    expect(b.draw.drawings()).toHaveLength(1);
    const copy = b.draw.drawings()[0];
    a.draw.update(shared.id, { space: 'viewport' });
    // The peer keeps its copy where it was, as a drawing of its own.
    expect(b.draw.get(copy.id)?.space).toBeUndefined();
    expect(b.draw.get(copy.id)?.points).toHaveLength(2);
    // Editing the peer no longer reaches the drawing now pinned to the screen.
    b.draw.update(copy.id, { style: { color: '#abcdef' } });
    expect(a.draw.get(shared.id)?.style.color).toBe('#00ffff');
    expect(a.draw.get(shared.id)?.space).toBe('viewport');
    expect(a.draw.get(shared.id)?.props?.['openalgo-charts/drawing-link']).toBeUndefined();
  });

  const linked = () => {
    const a = mount();
    const b = mount();
    const group = createDrawingLinkGroup({ enabled: true });
    cleanups.push(() => group.destroy());
    group.add(a.chart, a.draw, { symbol: 'X', exchange: 'NSE' });
    group.add(b.chart, b.draw, { symbol: 'X', exchange: 'NSE' });
    const shared = dataRect(a.draw);
    return { a, b, shared, copy: b.draw.drawings()[0] };
  };

  it('rejoins the link when pinning a shared drawing is undone, so edits reach both charts again', () => {
    const { a, b, shared, copy } = linked();
    a.draw.update(shared.id, { space: 'viewport' });
    expect(a.draw.undo()).toBe(true);
    expect(a.draw.get(shared.id)!.space).toBeUndefined();
    b.draw.update(copy.id, { style: { color: '#abcdef' } });
    expect(a.draw.get(shared.id)!.style.color).toBe('#abcdef');
    a.draw.update(shared.id, { style: { lineWidth: 3 } });
    expect(b.draw.get(copy.id)!.style.lineWidth).toBe(3);
    // A restore finds nothing stale to pull back over this chart's edits.
    a.chart.restoreState(JSON.parse(JSON.stringify(a.chart.getState())));
    expect(a.draw.get(shared.id)!.style).toMatchObject({ color: '#abcdef', lineWidth: 3 });
  });

  it('keeps an undone pin on this chart alone when the other charts have deleted their copies', () => {
    const { a, b, shared, copy } = linked();
    a.draw.update(shared.id, { space: 'viewport' });
    expect(b.draw.remove(copy.id)).toBe(true);
    expect(a.draw.undo()).toBe(true);
    expect(a.draw.get(shared.id)!.space).toBeUndefined();
    expect(b.draw.get(copy.id)).toBeUndefined();
    // A later restore does not apply the other chart's deletion here.
    a.chart.restoreState(JSON.parse(JSON.stringify(a.chart.getState())));
    expect(a.draw.get(shared.id)).toBeDefined();
    expect(b.draw.drawings()).toHaveLength(0);
  });
});

describe('the settings schema', () => {
  it('offers the anchor field on exactly the tools that can be anchored to the screen', () => {
    const viewport = BUILTIN_DRAWING_TOOLS.filter(t => t.viewport === true).map(t => t.id).sort();
    expect(viewport).toEqual(['ellipse', 'rectangle', 'table', 'text']);
    const offering = BUILTIN_DRAWING_TOOLS.filter(t => drawingSettingsSchema(t.id).fields.some(f => f.path === 'space')).map(t => t.id).sort();
    expect(offering).toEqual(viewport);
    expect(SPACE_FIELD.options?.map(o => o.value)).toEqual(['data', 'viewport']);
  });

  it('reads and writes the space by its path', () => {
    const d: Drawing = { id: 'x', tool: 'rectangle', points: [], style: {}, paneIndex: 0, zIndex: 0 };
    const schema = drawingSettingsSchema('rectangle');
    expect(readDrawingSetting(d, 'space')).toBeUndefined();
    expect(readDrawingSetting({ ...d, space: 'viewport' }, 'space')).toBe('viewport');
    expect(applyDrawingSettings(d, { space: 'viewport' }, schema)).toEqual({ space: 'viewport' });
    expect(applyDrawingSettings(d, { space: 'sideways' }, schema)).toEqual({});
  });
});
