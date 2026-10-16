/**
 * Eraser mode: a click on a drawing, or a drag across drawings, deletes what
 * it touches as one undo step. Read-only, locked, unselectable and hidden
 * drawings survive it. While the mode is on the chart is in placement mode,
 * so a drag erases instead of panning.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { DrawingController, DrawingLayer } from '../src/draw/index';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import { makeCtx } from './helpers/fake-ctx';
import type { Drawing, DrawingInput } from '../src/draw/types';

const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).reverse().forEach((fn) => fn()); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const BARS = (() => {
  let price = 310;
  let seed = 41;
  const next = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  return Array.from({ length: 100 }, (_, i) => {
    const open = price;
    const close = open + (next() - 0.5) * 5;
    price = close;
    return { time: 1700000000 + i * 900, open, high: Math.max(open, close) + next() * 2, low: Math.min(open, close) - next() * 2, close };
  });
})();

function mount() {
  vi.stubGlobal('window', {});
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as FakeElement;
  const chart = new Chart(el as unknown as HTMLElement, { document: doc, raf: { schedule: () => 0 }, shortcuts: false, timeNavigator: false });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(BARS);
  chart.setVisibleLogicalRange({ from: 0, to: 100 });
  const draw = new DrawingController(chart);
  cleanups.push(() => draw.destroy(), () => chart.destroy());
  const move = (x: number, y: number, pressed = false) => el.dispatch('pointermove', pointer('move', x, y, { buttons: pressed ? 1 : 0 }));
  const drag = (path: [number, number][], release = true) => {
    move(...path[0]);
    el.dispatch('pointerdown', pointer('down', ...path[0]));
    for (const p of path.slice(1)) move(p[0], p[1], true);
    if (release) el.dispatch('pointerup', pointer('up', ...path[path.length - 1]));
  };
  const click = (x: number, y: number) => {
    move(x, y);
    el.dispatch('pointerdown', pointer('down', x, y));
    el.dispatch('pointerup', pointer('up', x, y));
  };
  const at = (x: number, y: number) => ({ time: chart.coordinateToTime(x), price: chart.coordinateToPrice(y, 0) as number });
  /** A vertical-ish line at screen x from y 150 to 450. */
  const post = (x: number, extra: Partial<DrawingInput> = {}) =>
    draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [at(x, 150), at(x + 20, 450)], ...extra });
  const changes: { ids: string[]; kind: string }[] = [];
  chart.on('drawing:change', (p) => changes.push(p as { ids: string[]; kind: string }));
  return { chart, draw, el, move, drag, click, at, post, changes };
}

describe('eraser mode', () => {
  it('turns on and off, holding the chart in placement mode and disarming a tool', () => {
    const { chart, draw } = mount();
    const events: unknown[] = [];
    const tools: unknown[] = [];
    chart.on('draw:eraser', (p) => events.push(p));
    chart.on('draw:tool', (p) => tools.push(p));
    const placement = vi.spyOn(chart, 'setPlacementMode');
    draw.setTool('trend-line');
    draw.setEraser(true);
    expect(draw.erasing()).toBe(true);
    expect(draw.activeTool()).toBeNull();
    expect(tools).toEqual([{ tool: 'trend-line' }, { tool: null }]);
    expect(placement).toHaveBeenLastCalledWith(true);
    draw.setEraser(true);
    expect(events).toEqual([{ active: true }]);
    draw.setEraser(false);
    expect(draw.erasing()).toBe(false);
    expect(placement).toHaveBeenLastCalledWith(false);
    expect(events).toEqual([{ active: true }, { active: false }]);
  });

  it('deletes a drawing it clicks, as one undo step', () => {
    const { draw, click, post } = mount();
    const a = post(300);
    const b = post(500);
    draw.setEraser(true);
    click(310, 300);
    expect(draw.drawings().map((d) => d.id)).toEqual([b.id]);
    expect(draw.erasing()).toBe(true);
    expect(draw.undo()).toBe(true);
    expect(draw.drawings().map((d) => d.id)).toEqual([a.id, b.id]);
  });

  it('deletes every drawing a drag crosses, as one step, and leaves the rest', () => {
    const { chart, draw, drag, post, changes } = mount();
    const a = post(200);
    const b = post(350);
    const c = post(600);
    const range = chart.getVisibleLogicalRange();
    draw.setEraser(true);
    changes.length = 0;
    drag([[150, 300], [250, 302], [330, 298], [420, 300]]);
    expect(draw.drawings().map((d) => d.id)).toEqual([c.id]);
    expect(changes).toEqual([expect.objectContaining({ ids: [a.id, b.id], kind: 'remove' })]);
    expect(chart.getVisibleLogicalRange()).toEqual(range);   // the drag erased; it did not pan
    expect(draw.undo()).toBe(true);
    expect(draw.drawings().map((d) => d.id)).toEqual([a.id, b.id, c.id]);
  });

  it('hides what it has touched while the drag goes on, and deletes it only on release', () => {
    const { chart, draw, el, drag, post } = mount();
    const a = post(200);
    const listed = vi.spyOn(DrawingLayer.prototype, 'setDrawings');
    const top = () => chart.panes()[0].primitives().find((p) => p instanceof DrawingLayer && p.zOrder() === 'top');
    const lastListed = (): Drawing[] => {
      for (let i = listed.mock.calls.length - 1; i >= 0; i--) if (listed.mock.contexts[i] === top()) return [...listed.mock.calls[i][0]];
      return [];
    };
    draw.setEraser(true);
    drag([[150, 300], [260, 300]], false);
    expect(draw.get(a.id)).toBeDefined();
    expect(lastListed().map((d) => d.id)).not.toContain(a.id);
    el.dispatch('pointerup', pointer('up', 260, 300));
    expect(draw.get(a.id)).toBeUndefined();
  });

  it('spares read-only, locked, unselectable and hidden drawings', () => {
    const { draw, drag, post } = mount();
    const kept = [
      post(200, { policy: { editable: false } }),
      post(260, { locked: true }),
      post(320, { policy: { selectable: false } }),
      post(380, { visible: false }),
    ];
    const gone = post(440);
    draw.setEraser(true);
    drag([[150, 300], [300, 300], [520, 300]]);
    expect(draw.drawings().map((d) => d.id)).toEqual(kept.map((d) => d.id));
    expect(draw.get(gone.id)).toBeUndefined();
  });

  it('ignores a click on empty space', () => {
    const { draw, click, post } = mount();
    const a = post(300);
    draw.select(a.id);
    draw.setEraser(true);
    const steps = draw.historySteps();
    click(600, 500);
    expect(draw.drawings()).toHaveLength(1);
    expect(draw.selection()).toEqual([a.id]);
    expect(draw.historySteps()).toEqual(steps);
  });

  it('gives everything back when the sweep is interrupted', () => {
    const { chart, draw, drag, post } = mount();
    const a = post(200);
    draw.setEraser(true);
    const steps = draw.historySteps();
    drag([[150, 300], [260, 300]], false);
    chart.emit('data:context', {});
    expect(draw.get(a.id)).toBeDefined();
    expect(draw.historySteps()).toEqual(steps);
  });

  it('goes off on Escape, through cancel(), and when a tool is armed', () => {
    const { draw } = mount();
    draw.setEraser(true);
    expect(draw.cancel()).toBe(true);
    expect(draw.erasing()).toBe(false);
    expect(draw.cancel()).toBe(false);
    draw.setEraser(true);
    draw.setTool('rectangle');
    expect(draw.erasing()).toBe(false);
    expect(draw.activeTool()).toBe('rectangle');
  });

  it('marks the pointer with a ring the width it erases', () => {
    const { chart, draw, move } = mount();
    draw.setEraser(true);
    move(310, 310);   // the ring makes the pane's layer; the next move is hit-tested on it
    move(300, 300);
    const top = chart.panes()[0].primitives().find((p) => p instanceof DrawingLayer && p.zOrder() === 'top') as DrawingLayer;
    const { ctx, rec } = makeCtx();
    top.draw(ctx, (top as unknown as { context(): never }).context());
    const rect = chart.plotRect(0)!;
    expect(rec.ops.some((op) => op.type === 'arc' && Math.round(op.args[0] as number) === 300 - rect.left
      && Math.round(op.args[1] as number) === 300 - rect.top && op.args[2] === 6)).toBe(true);
    draw.setEraser(false);
    const after = makeCtx();
    top.draw(after.ctx, (top as unknown as { context(): never }).context());
    expect(after.rec.count('arc')).toBe(0);
  });
});
