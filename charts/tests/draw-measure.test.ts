/**
 * The temporary measure: Shift+click on empty chart space starts a ruler
 * whose far end follows the pointer, and the next click or Escape takes it
 * away. It is a preview, never a drawing: nothing saved, nothing to undo,
 * nothing a drawing link could carry to another chart.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { DrawingController, DrawingLayer, createDrawingLinkGroup } from '../src/draw/index';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import type { Drawing } from '../src/draw/types';

const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).reverse().forEach((fn) => fn()); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

/** A seeded walk: wide enough bars that every anchor has room around it. */
const BARS = (() => {
  let price = 2400;
  let seed = 11;
  const next = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  return Array.from({ length: 100 }, (_, i) => {
    const open = price;
    const close = open + (next() - 0.5) * 30;
    price = close;
    return { time: 1700000000 + i * 300, open, high: Math.max(open, close) + next() * 10, low: Math.min(open, close) - next() * 10, close };
  });
})();

function mount(options: ConstructorParameters<typeof DrawingController>[1] = {}) {
  vi.stubGlobal('window', {});
  const doc = fakeDocument();
  const el = doc.createElement('div') as unknown as FakeElement;
  const chart = new Chart(el as unknown as HTMLElement, { document: doc, raf: { schedule: () => 0 }, shortcuts: false, timeNavigator: false });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(BARS);
  chart.setVisibleLogicalRange({ from: 0, to: 100 });
  const draw = new DrawingController(chart, options);
  cleanups.push(() => draw.destroy(), () => chart.destroy());
  const events: { name: string; payload: unknown }[] = [];
  for (const name of ['draw:measure', 'draw:add', 'drawing:change', 'drawing:select']) {
    chart.on(name, (payload) => events.push({ name, payload }));
  }
  const keys = (shift: boolean) => ({ shiftKey: shift });
  const move = (x: number, y: number, shift = false) => el.dispatch('pointermove', pointer('move', x, y, { buttons: 0, ...keys(shift) }));
  const click = (x: number, y: number, shift = false) => {
    move(x, y, shift);
    el.dispatch('pointerdown', pointer('down', x, y, keys(shift)));
    el.dispatch('pointerup', pointer('up', x, y, keys(shift)));
  };
  return { chart, draw, el, move, click, events };
}

/** The drawing the top layer of pane 0 previews now, from its last `setPreview`. */
function previewOf(chart: Chart): () => Drawing | null {
  const spy = vi.spyOn(DrawingLayer.prototype, 'setPreview');
  return () => {
    const top = chart.panes()[0].primitives().find((p) => p instanceof DrawingLayer && p.zOrder() === 'top');
    for (let i = spy.mock.calls.length - 1; i >= 0; i--) {
      if (spy.mock.contexts[i] === top) return spy.mock.calls[i][0];
    }
    return null;
  };
}

const at = (chart: Chart, x: number, y: number) => ({ time: chart.coordinateToTime(x), price: chart.coordinateToPrice(y, 0) as number });

describe('Shift+click starts a temporary measure', () => {
  it('draws a ruler from the click to the pointer, as a preview of the measure tool', () => {
    const { chart, draw, move, click, events } = mount();
    const preview = previewOf(chart);
    click(300, 200, true);
    expect(draw.measuring()).toBe(true);
    move(520, 330);
    const ruler = preview();
    expect(ruler?.tool).toBe('measure');
    expect(ruler?.points[0].price).toBeCloseTo(at(chart, 300, 200).price, 6);
    // The crosshair reads the bar under the pointer, so the far end sits on that bar's centre.
    expect(Math.abs(chart.timeToCoordinate(ruler!.points[1].time) - 520)).toBeLessThanOrEqual(chart.timeScale.barSpacing / 2);
    expect(ruler?.points[1].price).toBeCloseTo(at(chart, 520, 330).price, 6);
    expect(events.filter((e) => e.name === 'draw:measure').map((e) => e.payload)).toEqual([{ active: true }]);
  });

  it('is never saved, recorded, announced or linked', () => {
    const { chart, draw, move, click, events } = mount();
    const doc = fakeDocument();
    const peer = new Chart(doc.createElement('div') as unknown as HTMLElement, { document: doc, raf: { schedule: () => 0 }, shortcuts: false });
    peer.applySize(800, 600);
    peer.addSeries('candlestick').setData(BARS);
    const peerDraw = new DrawingController(peer);
    const link = createDrawingLinkGroup({ enabled: true });
    const context = { symbol: 'NIFTY', exchange: 'NSE' };
    link.add(chart, draw, () => context);
    link.add(peer, peerDraw, () => context);
    cleanups.push(() => link.destroy(), () => peerDraw.destroy(), () => peer.destroy());
    click(300, 200, true);
    move(520, 330);
    expect(draw.drawings()).toEqual([]);
    expect(draw.toJSON().drawings).toEqual([]);
    expect((chart.drawingState() as { drawings?: unknown[] } | null)?.drawings ?? []).toEqual([]);
    expect(draw.canUndo()).toBe(false);
    expect(events.filter((e) => e.name !== 'draw:measure')).toEqual([]);
    expect(peerDraw.drawings()).toEqual([]);
    // The link is live: a real drawing crosses it.
    draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [at(chart, 400, 250)] });
    expect(peerDraw.drawings()).toHaveLength(1);
  });

  it('goes on the next click, which does nothing else', () => {
    const { chart, draw, move, click, events } = mount();
    const preview = previewOf(chart);
    const line = draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [at(chart, 400, 250)] });
    click(300, 200, true);
    move(520, 330);
    click(400, 250);                       // right on the line
    expect(draw.measuring()).toBe(false);
    expect(preview()).toBeNull();
    expect(draw.selection()).toEqual([]);  // the click that ended it selected nothing
    expect(events.filter((e) => e.name === 'draw:measure').map((e) => e.payload)).toEqual([{ active: true }, { active: false }]);
    click(400, 250);
    expect(draw.selection()).toEqual([line.id]);
  });

  it('goes on Escape, through cancel()', () => {
    const { chart, draw, move, click } = mount();
    const preview = previewOf(chart);
    click(300, 200, true);
    move(520, 330);
    expect(draw.cancel()).toBe(true);
    expect(draw.measuring()).toBe(false);
    expect(preview()).toBeNull();
    expect(draw.cancel()).toBe(false);
  });

  it('goes when a tool is armed, and a Shift+click while one is armed places an anchor instead', () => {
    const { chart, draw, move, click } = mount();
    click(300, 200, true);
    draw.setTool('trend-line');
    expect(draw.measuring()).toBe(false);
    click(300, 200, true);
    move(520, 330);
    click(520, 330, true);
    expect(draw.measuring()).toBe(false);
    expect(draw.drawings().map((d) => d.tool)).toEqual(['trend-line']);
    void chart;
  });

  it('leaves a Shift+click on a drawing to the selection', () => {
    const { chart, draw, click } = mount();
    const line = draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [at(chart, 400, 250)] });
    click(400, 250, true);
    expect(draw.measuring()).toBe(false);
    expect(draw.selection()).toEqual([line.id]);
  });

  it('does nothing when the host turns the gesture off', () => {
    const { draw, click } = mount({ gestures: { measure: false } });
    click(300, 200, true);
    expect(draw.measuring()).toBe(false);
    draw.setOptions({ gestures: { measure: true } });
    click(300, 200, true);
    expect(draw.measuring()).toBe(true);
  });

  it('keeps its far end where the pointer last was on its pane', () => {
    const { chart, draw, move, click } = mount();
    const preview = previewOf(chart);
    click(300, 200, true);
    move(520, 330);
    chart.emit('crosshair:move', { time: null, index: null, price: null, bar: null, point: null, paneIndex: null });
    expect(draw.measuring()).toBe(true);
    expect(preview()?.points[1].price).toBeCloseTo(at(chart, 520, 330).price, 6);
  });
});
