/**
 * Uniform draw order. A pane paints in bands: behind the series, the series
 * band (the price source and each study, back to front, with drawings placed
 * directly above one of them), the overlay band, and in front. The object
 * inventory exposes only the moves those bands can paint, the renderer paints
 * exactly that order, the pointer hits what is painted on top, and the order
 * is saved.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import '../src/indicators/index';
import { Chart, type ContextMenuEvent } from '../src/core/chart';
import { InvalidationLevel } from '../src/core/invalidate-mask';
import { ChartObjects } from '../src/model/chart-objects';
import { getChartType } from '../src/model/chart-type-registry';
import { getIndicator, plotStyleKeys, registerIndicator } from '../src/model/indicator-registry';
import { DrawingController, getDrawingTool, migrateDrawings, type Drawing } from '../src/draw/index';
import type { IPrimitive, PrimitiveHost } from '../src/primitives/primitive';
import { parseWorkspaceDocument } from '../src/workspace/documents';
import { fakeDocument, type FakeElement } from './helpers/fake-dom';
import { RecordingContext } from './helpers/fake-ctx';

const T0 = 1700000000;
beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

interface Rig { chart: Chart; el: FakeElement; draw: DrawingController; objects: ChartObjects }
const rigs: Rig[] = [];
function rig(): Rig {
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document: doc, pixelRatio: () => 1, shortcuts: false, animZoom: false,
    raf: { schedule: (cb: (t: number) => void) => { cb(0); return 0; } },
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(Array.from({ length: 80 }, (_, i) => ({
    time: T0 + i * 60, open: 100 + i, high: 104 + i, low: 96 + i, close: 100 + i, volume: 100,
  })));
  const draw = new DrawingController(chart);
  const objects = new ChartObjects(chart, { drawings: draw });
  const made = { chart, el, draw, objects };
  rigs.push(made);
  return made;
}
afterEach(() => {
  for (const { chart, draw, objects } of rigs.splice(0)) { objects.destroy(); draw.destroy(); chart.destroy(); }
  vi.restoreAllMocks();
});

const colorKey = (id: string): string => plotStyleKeys(getIndicator(id).plots[0]).color;
const sma = (chart: Chart, color: string) => chart.addIndicator('sma', { length: 1, [colorKey('sma')]: color });
const box = (draw: DrawingController, color: string): Drawing => draw.add({
  tool: 'rectangle', paneIndex: 0, style: { color },
  points: [{ time: T0 + 10 * 60, price: 90 }, { time: T0 + 70 * 60, price: 190 }],
});

/** One full frame, logging every series and drawing paint in the order it happened. */
function paintLog(chart: Chart): string[] {
  const log: string[] = [];
  const line = getChartType('line'), candles = getChartType('candlestick'), rect = getDrawingTool('rectangle');
  const [lineDraw, candleDraw, rectDraw] = [line.draw, candles.draw, rect.draw];
  line.draw = (...args) => { log.push('series:' + String(args[5].color)); return lineDraw(...args); };
  candles.draw = (...args) => { log.push('source'); return candleDraw(...args); };
  rect.draw = (args) => { log.push('drawing:' + String(args.drawing.style.color)); return rectDraw(args); };
  try { chart.invalidate(m => m.invalidateGlobal(InvalidationLevel.Full)); }
  finally { line.draw = lineDraw; candles.draw = candleDraw; rect.draw = rectDraw; }
  return log;
}

describe('series band', () => {
  it('lists the price source and each study on the pane in paint order', () => {
    const { chart } = rig();
    const a = sma(chart, '#aa0000');
    const rsi = chart.addIndicator('rsi');
    const b = sma(chart, '#00aa00');
    expect(chart.seriesStack(0)).toEqual(['source:primary', 'indicator:' + a.id, 'indicator:' + b.id]);
    expect(chart.seriesStack(rsi.paneIndex)).toEqual(['indicator:' + rsi.id]);
    expect(chart.seriesStack(9)).toEqual([]);
  });

  it('moves a study under the candles and the source over a study, painting what it says', () => {
    const { chart } = rig();
    const a = sma(chart, '#aa0000');
    const b = sma(chart, '#00aa00');
    expect(paintLog(chart)).toEqual(['source', 'series:#aa0000', 'series:#00aa00']);
    expect(chart.moveInSeriesStack('indicator:' + b.id, 'source:primary', 'below')).toBe(true);
    expect(chart.seriesStack(0)).toEqual(['indicator:' + b.id, 'source:primary', 'indicator:' + a.id]);
    expect(paintLog(chart)).toEqual(['series:#00aa00', 'source', 'series:#aa0000']);
    expect(chart.indicators().map(item => item.id)).toEqual([b.id, a.id]);
    expect(chart.moveInSeriesStack('source:primary', 'indicator:' + a.id, 'above')).toBe(true);
    expect(paintLog(chart)).toEqual(['series:#00aa00', 'series:#aa0000', 'source']);
    // Nothing to do, a missing entry and an entry of another pane are refused.
    expect(chart.moveInSeriesStack('source:primary', 'indicator:' + a.id, 'above')).toBe(false);
    expect(chart.moveInSeriesStack('indicator:missing', 'source:primary', 'below')).toBe(false);
    const rsi = chart.addIndicator('rsi');
    expect(chart.moveInSeriesStack('indicator:' + rsi.id, 'source:primary', 'below')).toBe(false);
  });

  it('keeps the source where it was put through study changes, and saves only a moved source', () => {
    const { chart } = rig();
    const a = sma(chart, '#aa0000');
    const plain = chart.getState();
    expect(plain).not.toHaveProperty('sourceAbove');
    expect(chart.moveInSeriesStack('source:primary', 'indicator:' + a.id, 'above')).toBe(true);
    a.setSettings({ [plotStyleKeys(getIndicator('sma').plots[0]).type]: 'histogram' });
    const b = sma(chart, '#00aa00');
    expect(chart.seriesStack(0)).toEqual(['indicator:' + a.id, 'source:primary', 'indicator:' + b.id]);
    const saved = JSON.parse(JSON.stringify(chart.getState()));
    expect(saved.sourceAbove).toBe(a.id);
    const other = rig().chart;
    expect(other.restoreState(saved).applied).toBe(true);
    expect(other.seriesStack(0)).toEqual(['indicator:' + a.id, 'source:primary', 'indicator:' + b.id]);
    // An older layout says nothing about the source, and restores the default.
    expect(other.restoreState(JSON.parse(JSON.stringify(plain))).applied).toBe(true);
    expect(other.seriesStack(0)[0]).toBe('source:primary');
    // The study the source sat on goes, and the source goes back to the bottom.
    chart.removeIndicator(a.id);
    expect(chart.seriesStack(0)).toEqual(['source:primary', 'indicator:' + b.id]);
    expect(chart.getState()).not.toHaveProperty('sourceAbove');
  });

  it('keeps the source where it paints when the study it sits on moves to another pane', () => {
    const { chart } = rig();
    const a = sma(chart, '#aa0000');
    const b = sma(chart, '#00aa00');
    expect(chart.moveInSeriesStack('source:primary', 'indicator:' + b.id, 'above')).toBe(true);
    expect(chart.seriesStack(0)).toEqual(['indicator:' + a.id, 'indicator:' + b.id, 'source:primary']);
    expect(chart.moveIndicator(b.id, chart.panes().length)).toBe(true);
    // Over the study that was under the one that left, not dropped to the back of the band.
    expect(chart.seriesStack(0)).toEqual(['indicator:' + a.id, 'source:primary']);
    expect(chart.getState().sourceAbove).toBe(a.id);
    expect(paintLog(chart).slice(0, 2)).toEqual(['series:#aa0000', 'source']);
  });

  it('keeps the price source the instrument wherever it paints: the readout and the price it reads', () => {
    const { chart } = rig();
    // A study on the left axis that paints first once the source moves over it.
    registerIndicator({ id: 'stack-far', name: 'Far', placement: 'onchart', inputs: [],
      plots: [{ key: 'v', title: 'Far', type: 'line', priceScaleId: 'left' }], calc: bars => ({ v: bars.map(() => 500) }) });
    const far = chart.addIndicator('stack-far');
    chart.invalidate(m => m.invalidateGlobal(InvalidationLevel.Full));
    const pane = chart.panes()[0];
    expect(pane.readoutScale()).toBe(pane.priceScale);
    const before = chart.coordinateToPrice(200);
    expect(chart.moveInSeriesStack('source:primary', 'indicator:' + far.id, 'above')).toBe(true);
    chart.invalidate(m => m.invalidateGlobal(InvalidationLevel.Full));
    expect(chart.seriesStack(0)).toEqual(['indicator:' + far.id, 'source:primary']);
    expect(pane.readoutScale()).toBe(pane.priceScale);
    expect(chart.coordinateToPrice(200)).toBe(before);
  });

  it('keeps the price source the instrument on its own scale too: the last-price line, a rebased axis and the bars primitives read', () => {
    const { chart } = rig();
    // A study on the price scale itself, well away from the candles, that paints first once the source moves over it.
    registerIndicator({ id: 'stack-level', name: 'Level', placement: 'onchart', inputs: [],
      plots: [{ key: 'v', title: 'Level', type: 'line' }], calc: bars => ({ v: bars.map(() => 400) }) });
    const level = chart.addIndicator('stack-level');
    let read: readonly { close: number }[] = [];
    chart.addPrimitive({ zOrder: () => 'normal', draw: (_ctx, rc) => { read = rc.bars?.() ?? []; } }, 0);
    expect(chart.moveInSeriesStack('source:primary', 'indicator:' + level.id, 'above')).toBe(true);
    const pane = chart.panes()[0];
    const ctx = (chart as unknown as { _renderContext(i: number): never })._renderContext(0);
    const texts = (): string[] => {
      const rec = new RecordingContext();
      pane.paintBase(ctx, rec as unknown as CanvasRenderingContext2D);
      return rec.ops.filter(op => op.type === 'fillText').map(op => op.text ?? '');
    };
    // The last-price tag quotes the candles' last close, not the level painted before them.
    const shown = texts();
    expect(shown).toContain(pane.priceScale.format(179));
    expect(read).toHaveLength(80);
    expect(read[79].close).toBe(179);
    // A rebased axis quotes against the candles' first visible close.
    pane.priceScale.setOptions({ mode: 'percentage' });
    chart.setVisibleLogicalRange({ from: 20, to: 79 });
    chart.invalidate(m => m.invalidateGlobal(InvalidationLevel.Full));
    const first = chart.getVisibleLogicalRange()!.from;
    expect(pane.priceScale.baseline).toBe(100 + Math.max(0, Math.ceil(first)));
  });

  it('refuses a malformed source placement and carries a valid one through a workspace document', () => {
    const { chart } = rig();
    const a = sma(chart, '#aa0000');
    chart.moveInSeriesStack('source:primary', 'indicator:' + a.id, 'above');
    const state = JSON.parse(JSON.stringify(chart.getState()));
    const document = parseWorkspaceDocument({
      kind: 'workspace', version: 1, id: 'w', name: 'W', createdAt: 1, updatedAt: 1,
      layout: { rows: 1, columns: 1, slots: [{ paneId: 'a', row: 0, column: 0 }] }, activePaneId: 'a',
      panes: [{ id: 'a', symbol: 'X', exchange: 'NSE', interval: '1m', chartType: 'candlestick', chart: state, settings: {} }],
      sync: { crosshair: false, viewport: false, symbol: false, interval: false },
    });
    expect(document.panes[0].chart.sourceAbove).toBe(a.id);
    const report = rig().chart.restoreState({ ...state, sourceAbove: 7 });
    expect(report.applied).toBe(false);
    expect(report.reason).toMatch(/source/i);
  });
});

describe('drawings in the series band', () => {
  it('paints a drawing placed above a study between that study and the next, and saves it', () => {
    const { chart, draw } = rig();
    const a = sma(chart, '#aa0000');
    sma(chart, '#00aa00');
    const d = box(draw, '#0000aa');
    expect(paintLog(chart)).toEqual(['source', 'series:#aa0000', 'series:#00aa00', 'drawing:#0000aa']);
    expect(draw.placeInStack(d.id, { entry: 'indicator:' + a.id }, 'above')).toBe(true);
    expect(draw.get(d.id)!.stackAbove).toBe('indicator:' + a.id);
    expect(paintLog(chart)).toEqual(['source', 'series:#aa0000', 'drawing:#0000aa', 'series:#00aa00']);
    expect(draw.placeInStack(d.id, { entry: 'source:primary' }, 'below')).toBe(true);
    expect(draw.get(d.id)!.stackAbove).toBeUndefined();
    expect(draw.get(d.id)!.zIndex).toBeLessThan(0);
    expect(paintLog(chart)).toEqual(['drawing:#0000aa', 'source', 'series:#aa0000', 'series:#00aa00']);
    expect(draw.placeInStack(d.id, { entry: 'source:primary' }, 'above')).toBe(true);
    const saved = draw.toJSON();
    expect(saved.drawings[0].stackAbove).toBe('source:primary');
    draw.undo();
    expect(draw.get(d.id)!.zIndex).toBeLessThan(0);
    expect(draw.get(d.id)!.stackAbove).toBeUndefined();
    draw.fromJSON(saved);
    expect(paintLog(chart)).toEqual(['source', 'drawing:#0000aa', 'series:#aa0000', 'series:#00aa00']);
  });

  it('paints a drawing whose study is gone in front, and places it back when the study returns', () => {
    const { chart, draw } = rig();
    const a = sma(chart, '#aa0000');
    const b = sma(chart, '#00aa00');
    const d = box(draw, '#0000aa');
    draw.placeInStack(d.id, { entry: 'indicator:' + a.id }, 'above');
    const state = chart.getState();
    chart.removeIndicator(a.id, { force: true });
    expect(paintLog(chart)).toEqual(['source', 'series:#00aa00', 'drawing:#0000aa']);
    expect(chart.restoreState(state).applied).toBe(true);
    expect(chart.indicators().map(item => item.id)).toEqual([a.id, b.id]);
    expect(paintLog(chart)).toEqual(['source', 'series:#aa0000', 'drawing:#0000aa', 'series:#00aa00']);
  });

  it('keeps a stack placement through the migration and drops a malformed one', () => {
    const document = migrateDrawings({ version: 2, drawings: [
      { id: 'a', tool: 'rectangle', paneIndex: 0, points: [{ time: 1, price: 1 }, { time: 2, price: 2 }], style: {}, zIndex: 0, createdAt: 1, stackAbove: 'indicator:x' },
      { id: 'b', tool: 'rectangle', paneIndex: 0, points: [{ time: 1, price: 1 }, { time: 2, price: 2 }], style: {}, zIndex: 1, createdAt: 2, stackAbove: 42 },
    ] });
    expect(document.drawings[0].stackAbove).toBe('indicator:x');
    expect(document.drawings[1]).not.toHaveProperty('stackAbove');
  });

  it('moves one step and to either end only within the slot it paints in, and crosses the series on request', () => {
    const { chart, draw } = rig();
    const a = sma(chart, '#aa0000');
    const one = box(draw, '#0000aa');
    const two = box(draw, '#00aaaa');
    const front = box(draw, '#aaaa00');
    draw.placeInStack(one.id, { entry: 'indicator:' + a.id }, 'above');
    draw.placeInStack(two.id, { drawing: one.id }, 'above');
    expect(paintLog(chart)).toEqual(['source', 'series:#aa0000', 'drawing:#0000aa', 'drawing:#00aaaa', 'drawing:#aaaa00']);
    expect(draw.reorder(two.id, 1)).toBe(false);
    expect(draw.reorder(two.id, -1)).toBe(true);
    expect(paintLog(chart)).toEqual(['source', 'series:#aa0000', 'drawing:#00aaaa', 'drawing:#0000aa', 'drawing:#aaaa00']);
    draw.bringToFront(two.id);
    expect(draw.get(two.id)!.stackAbove).toBe('indicator:' + a.id);
    expect(paintLog(chart).slice(2, 4)).toEqual(['drawing:#0000aa', 'drawing:#00aaaa']);
    draw.bringAboveSeries(one.id);
    expect(draw.get(one.id)!.stackAbove).toBeUndefined();
    draw.sendBehindSeries(two.id);
    expect(draw.get(two.id)!.stackAbove).toBeUndefined();
    // Over the series is the back of the front band, beside a drawing that was already there.
    expect(paintLog(chart)).toEqual(['drawing:#00aaaa', 'source', 'series:#aa0000', 'drawing:#0000aa', 'drawing:#aaaa00']);
    expect(front.stackAbove).toBeUndefined();
  });
});

describe('a drawing keeps its series-band slot', () => {
  it('through send to back, and in a duplicate and a pasted copy', async () => {
    const { chart, draw } = rig();
    const a = sma(chart, '#aa0000');
    const one = box(draw, '#0000aa');
    const two = box(draw, '#00aaaa');
    box(draw, '#aaaa00');
    draw.placeInStack(one.id, { entry: 'indicator:' + a.id }, 'above');
    draw.placeInStack(two.id, { drawing: one.id }, 'above');
    expect(paintLog(chart)).toEqual(['source', 'series:#aa0000', 'drawing:#0000aa', 'drawing:#00aaaa', 'drawing:#aaaa00']);
    // To the back of its own slot, not behind the series.
    draw.sendToBack(two.id);
    expect(draw.get(two.id)!.stackAbove).toBe('indicator:' + a.id);
    expect(paintLog(chart)).toEqual(['source', 'series:#aa0000', 'drawing:#00aaaa', 'drawing:#0000aa', 'drawing:#aaaa00']);
    const [copy] = draw.duplicate([one.id]);
    expect(copy.stackAbove).toBe('indicator:' + a.id);
    expect(await draw.copy(two.id)).toBe(true);
    const [pasted] = await draw.paste();
    expect(pasted.stackAbove).toBe('indicator:' + a.id);
    // Both copies paint in the slot, under the drawing in front.
    const log = paintLog(chart);
    expect(log.slice(0, 2)).toEqual(['source', 'series:#aa0000']);
    expect(log[log.length - 1]).toBe('drawing:#aaaa00');
    expect(log).toHaveLength(7);
  });

  it('ranks send to back and bring to front against its own slot only, which shows once the study is gone', () => {
    const { chart, draw } = rig();
    const a = sma(chart, '#aa0000');
    const one = box(draw, '#0000aa');
    const two = box(draw, '#00aaaa');
    const front = box(draw, '#aaaa00');
    draw.update(front.id, { zIndex: 5 });
    draw.placeInStack(one.id, { entry: 'indicator:' + a.id }, 'above');
    draw.placeInStack(two.id, { drawing: one.id }, 'above');
    draw.bringToFront(one.id);
    draw.sendToBack(two.id);
    expect(paintLog(chart)).toEqual(['source', 'series:#aa0000', 'drawing:#00aaaa', 'drawing:#0000aa', 'drawing:#aaaa00']);
    // Without the study both paint in front by their numbers: still under the
    // drawing that was in front of their slot all along.
    chart.removeIndicator(a.id);
    expect(paintLog(chart)).toEqual(['source', 'drawing:#00aaaa', 'drawing:#0000aa', 'drawing:#aaaa00']);
  });
});

describe('object inventory stack', () => {
  it('lists each pane back to front and places across categories only where the bands can paint it', () => {
    const { chart, draw, objects } = rig();
    const a = sma(chart, '#aa0000');
    const b = sma(chart, '#00aa00');
    const behind = box(draw, '#111111');
    draw.sendBehindSeries(behind.id);
    const onA = box(draw, '#222222');
    draw.placeInStack(onA.id, { entry: 'indicator:' + a.id }, 'above');
    const front = box(draw, '#333333');
    const ids = (): string[] => objects.stack(0).map(row => row.id);
    const A = 'indicator:' + a.id, B = 'indicator:' + b.id;
    expect(ids()).toEqual(['drawing:' + behind.id, 'source:primary', A, 'drawing:' + onA.id, B, 'drawing:' + front.id]);
    expect(objects.get('drawing:' + onA.id)!.band).toBe('series');
    expect(objects.get('drawing:' + onA.id)!.stackAbove).toBe(A);
    expect(objects.get('drawing:' + behind.id)!.band).toBe('below');
    expect(objects.get('drawing:' + front.id)!.band).toBe('above');
    expect(objects.get(A)!.band).toBe('series');
    expect(objects.get('source:primary')!.capabilities.place).toBe(true);

    // A study, or the source, may not split another study from the drawing placed on it.
    expect(objects.canPlace(B, A, 'above')).toBe(false);
    expect(objects.place(B, A, 'above')).toBe(false);
    expect(objects.canPlace('source:primary', A, 'above')).toBe(false);
    expect(objects.place('source:primary', A, 'above')).toBe(false);
    expect(objects.canPlace(B, 'drawing:' + onA.id, 'below')).toBe(false);
    // Nor go behind the series band or in front of it.
    expect(objects.canPlace(B, 'drawing:' + behind.id, 'below')).toBe(false);
    expect(objects.canPlace(A, 'drawing:' + front.id, 'above')).toBe(false);
    // Directly over that drawing is where it already is.
    expect(objects.canPlace(B, 'drawing:' + onA.id, 'above')).toBe(false);
    // It may go at a boundary between slots, and takes its drawings along.
    expect(objects.canPlace(A, 'drawing:' + front.id, 'below')).toBe(true);
    expect(objects.place(A, 'drawing:' + front.id, 'below')).toBe(true);
    expect(ids()).toEqual(['drawing:' + behind.id, 'source:primary', B, A, 'drawing:' + onA.id, 'drawing:' + front.id]);
    expect(objects.place(A, 'drawing:' + behind.id, 'above')).toBe(true);
    expect(ids()).toEqual(['drawing:' + behind.id, A, 'drawing:' + onA.id, 'source:primary', B, 'drawing:' + front.id]);
    expect(objects.place('source:primary', A, 'below')).toBe(true);
    expect(ids()).toEqual(['drawing:' + behind.id, 'source:primary', A, 'drawing:' + onA.id, B, 'drawing:' + front.id]);

    // A drawing goes anywhere in its pane.
    expect(objects.canPlace('drawing:' + front.id, 'drawing:' + front.id, 'below')).toBe(false);
    expect(objects.place('drawing:' + front.id, B, 'below')).toBe(true);
    expect(ids()).toEqual(['drawing:' + behind.id, 'source:primary', A, 'drawing:' + onA.id, 'drawing:' + front.id, B]);
    expect(draw.get(front.id)!.stackAbove).toBe(A);
    expect(objects.place('drawing:' + behind.id, 'drawing:' + front.id, 'above')).toBe(true);
    expect(ids()).toEqual(['source:primary', A, 'drawing:' + onA.id, 'drawing:' + front.id, 'drawing:' + behind.id, B]);
    // Already where it would go.
    expect(objects.canPlace('drawing:' + behind.id, 'drawing:' + front.id, 'above')).toBe(false);
    expect(paintLog(chart)).toEqual(['source', 'series:#aa0000', 'drawing:#222222', 'drawing:#333333', 'drawing:#111111', 'series:#00aa00']);
  });

  it('refuses moves between panes and into rows that are not in the stack', () => {
    const { chart, draw, objects } = rig();
    const rsi = chart.addIndicator('rsi');
    const d = box(draw, '#0000aa');
    expect(objects.canPlace('drawing:' + d.id, 'indicator:' + rsi.id, 'above')).toBe(false);
    expect(objects.canPlace('indicator:' + rsi.id, 'source:primary', 'above')).toBe(false);
    const one = draw.add({ tool: 'trend-line', paneIndex: 0, points: [{ time: T0, price: 100 }], style: {} });
    const group = draw.createGroup('Pair', [d.id, one.id])!;
    expect(objects.canPlace('group:' + group.id, 'source:primary', 'above')).toBe(false);
    expect(objects.stack(0).some(row => row.kind === 'group')).toBe(false);
  });
});

describe('hit precedence follows paint order', () => {
  const menuAt = (r: Rig, x: number, y: number): ContextMenuEvent => {
    const seen: ContextMenuEvent[] = [];
    const off = r.chart.on('contextmenu', p => seen.push(p as ContextMenuEvent));
    r.el.dispatch('contextmenu', { clientX: x, clientY: y, defaultPrevented: false, preventDefault() {} });
    off();
    return seen[0];
  };

  it('gives the study painted over a drawing the pointer, and the drawing painted over a study', () => {
    const r = rig();
    const a = sma(r.chart, '#aa0000');
    a.values();
    const line = r.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 40 * 60, price: 140 }] });
    const x = r.chart.timeToCoordinate(T0 + 40 * 60);
    const y = r.chart.priceToCoordinate(140)!;
    expect(menuAt(r, x, y).target.kind).toBe('drawing');
    r.draw.placeInStack(line.id, { entry: 'source:primary' }, 'above');
    const under = menuAt(r, x, y).target;
    expect(under.kind).toBe('indicator');
    expect(under.instanceId).toBe(a.id);
    r.draw.placeInStack(line.id, { entry: 'indicator:' + a.id }, 'above');
    expect(menuAt(r, x, y).target.kind).toBe('drawing');
    r.draw.sendBehindSeries(line.id);
    expect(menuAt(r, x, y).target.kind).toBe('indicator');
    // Away from every series the drawing is what is there.
    expect(menuAt(r, r.chart.timeToCoordinate(T0 + 5 * 60), y).target.kind).toBe('drawing');
  });

  it('hits the drawing painted on top where two overlap, whatever slot each is in', () => {
    const r = rig();
    const a = sma(r.chart, '#aa0000');
    const lower = box(r.draw, '#111111');
    const upper = box(r.draw, '#222222');
    r.draw.placeInStack(upper.id, { entry: 'indicator:' + a.id }, 'above');
    r.draw.placeInStack(lower.id, { entry: 'source:primary' }, 'above');
    const pane = r.chart.panes()[0];
    const ctx = (r.chart as unknown as { _renderContext(i: number): never })._renderContext(0);
    const x = r.chart.timeToCoordinate(T0 + 10 * 60);
    const y = r.chart.priceToCoordinate(150)!;
    expect(pane.hitTestPrimitives(x, y, ctx)?.externalId).toBe('draw:' + upper.id);
    r.draw.placeInStack(lower.id, { drawing: upper.id }, 'above');
    expect(pane.hitTestPrimitives(x, y, ctx)?.externalId).toBe('draw:' + lower.id);
  });

  /** A thin line in the overlay band that answers within 4 px, the way an order line does. */
  const overlayLine = (chart: Chart, price: number): IPrimitive => {
    const line: IPrimitive = {
      zOrder: () => 'normal',
      draw: () => {},
      hitTest: (_x, y, rc) => {
        const distance = Math.abs(y - rc.priceScale.priceToY(price));
        return distance <= 4 ? { externalId: 'order-line', zOrder: 'normal', distance } : null;
      },
    };
    chart.addPrimitive(line, 0);
    return line;
  };
  const hitAt = (r: Rig, time: number, price: number, dy = 0): string | undefined => {
    const ctx = (r.chart as unknown as { _renderContext(i: number): never })._renderContext(0);
    const y = r.chart.priceToCoordinate(price)! + dy;
    return r.chart.panes()[0].hitTestPrimitives(r.chart.timeToCoordinate(time), y, ctx)?.externalId;
  };

  it('gives a line in the overlay band the press over a box painted under it, and the box when it is in front', () => {
    const r = rig();
    const d = r.draw.add({ tool: 'rectangle', paneIndex: 0, style: { color: '#0000aa', fill: true },
      points: [{ time: T0, price: 90 }, { time: T0 + 79 * 60, price: 190 }] });
    overlayLine(r.chart, 150);
    const at = T0 + 70 * 60;
    // In front, the filled box covers the line, and takes the press 2 px from it.
    expect(hitAt(r, at, 150, 2)).toBe('draw:' + d.id);
    for (const place of [
      () => r.draw.placeInStack(d.id, { entry: 'source:primary' }, 'above'),
      () => r.draw.sendBehindSeries(d.id),
    ]) {
      place();
      // Painted under the line now: the line takes the press wherever it answers.
      expect(hitAt(r, at, 150, 2)).toBe('order-line');
      expect(hitAt(r, at, 150)).toBe('order-line');
      // Away from the line the box is what is there.
      expect(hitAt(r, at, 120)).toBe('draw:' + d.id);
    }
    r.draw.bringAboveSeries(d.id);
    expect(hitAt(r, at, 150, 2)).toBe('draw:' + d.id);
  });

  it('ranks a host primitive placed in the series band by where it paints, and back in its own band after', () => {
    const r = rig();
    const a = sma(r.chart, '#aa0000');
    a.values();
    let host: PrimitiveHost | null = null;
    // A shaded zone that answers anywhere inside it, in front by default.
    const zone: IPrimitive = {
      zOrder: () => 'top',
      draw: () => {},
      attached: h => { host = h; },
      hitTest: () => ({ externalId: 'zone', zOrder: 'top', distance: 0 }),
    };
    r.chart.addPrimitive(zone, 0);
    overlayLine(r.chart, 150);
    const at = T0 + 70 * 60;
    expect(hitAt(r, at, 150, 2)).toBe('zone');
    const levels: number[] = [];
    const spy = vi.spyOn(r.chart, 'invalidate').mockImplementation(fn => {
      fn({ invalidatePane: (_index: number, options: { level: number }) => { levels.push(options.level); } } as never);
    });
    host!.requestUpdate();
    expect(r.chart.setPrimitiveStackAbove(zone, 'source:primary')).toBe(true);
    host!.requestUpdate();
    spy.mockRestore();
    // In front it repaints with the cursor layer; in the series band it is on the base canvas.
    expect(levels[0]).toBe(InvalidationLevel.Cursor);
    expect(levels[levels.length - 1]).toBe(InvalidationLevel.Light);
    expect(r.chart.panes()[0].primitiveStackAbove(zone)).toBe('source:primary');
    expect(hitAt(r, at, 150, 2)).toBe('order-line');
    expect(hitAt(r, at, 120)).toBe('zone');
    // The study painted over it takes the context menu where both are under the pointer.
    const x = r.chart.timeToCoordinate(T0 + 40 * 60);
    const y = r.chart.priceToCoordinate(a.values().ma![40] as number)!;
    const menu = (): ContextMenuEvent => {
      const seen: ContextMenuEvent[] = [];
      const off = r.chart.on('contextmenu', p => seen.push(p as ContextMenuEvent));
      r.el.dispatch('contextmenu', { clientX: x, clientY: y, defaultPrevented: false, preventDefault() {} });
      off();
      return seen[0];
    };
    expect(menu().target.kind).toBe('indicator');
    expect(r.chart.setPrimitiveStackAbove(zone, null)).toBe(true);
    expect(r.chart.panes()[0].primitiveStackAbove(zone)).toBeNull();
    expect(menu().target).toMatchObject({ kind: 'primitive', id: 'zone' });
    expect(hitAt(r, at, 150, 2)).toBe('zone');
  });
});
