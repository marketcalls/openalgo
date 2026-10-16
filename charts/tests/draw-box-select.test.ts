/**
 * Box select: Ctrl (Cmd) plus a drag on empty chart space selects every
 * drawing the box touches, where "touches" means the box intersects the
 * drawing's geometry as a click measures it, not merely its anchors. Shift
 * adds to the selection; what the user cannot select stays out.
 *
 * Driven through the chart's real pointer handlers, so the placement-mode
 * handover that keeps the press from panning is part of what is tested.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { DrawingController, DrawingLayer } from '../src/draw/index';
import type { GestureLayer } from '../src/draw/gesture-layer';
import { touchesBox, touchesPath, boxSamples } from '../src/draw/hit-geometry';
import { darkTheme } from '../src/theme';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import { makeCtx } from './helpers/fake-ctx';
import type { Drawing, DrawingInput } from '../src/draw/types';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';

const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).reverse().forEach((fn) => fn()); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const BARS = (() => {
  let price = 1500;
  let seed = 23;
  const next = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  return Array.from({ length: 100 }, (_, i) => {
    const open = price;
    const close = open + (next() - 0.5) * 24;
    price = close;
    return { time: 1700000000 + i * 300, open, high: Math.max(open, close) + next() * 8, low: Math.min(open, close) - next() * 8, close };
  });
})();

type Keys = { ctrl?: boolean; shift?: boolean; meta?: boolean };

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
  const mods = (k: Keys) => ({ ctrlKey: k.ctrl === true, shiftKey: k.shift === true, metaKey: k.meta === true });
  const move = (x: number, y: number, k: Keys = {}, pressed = false) =>
    el.dispatch('pointermove', pointer('move', x, y, { buttons: pressed ? 1 : 0, ...mods(k) }));
  /** Hover to the start, press, move through the path, release: one gesture. */
  const drag = (from: [number, number], to: [number, number], k: Keys = {}, steps = 4) => {
    move(from[0], from[1], k);
    el.dispatch('pointerdown', pointer('down', from[0], from[1], mods(k)));
    for (let i = 1; i <= steps; i++) {
      move(from[0] + ((to[0] - from[0]) * i) / steps, from[1] + ((to[1] - from[1]) * i) / steps, k, true);
    }
    el.dispatch('pointerup', pointer('up', to[0], to[1], mods(k)));
  };
  const click = (x: number, y: number, k: Keys = {}) => {
    move(x, y, k);
    el.dispatch('pointerdown', pointer('down', x, y, mods(k)));
    el.dispatch('pointerup', pointer('up', x, y, mods(k)));
  };
  const at = (x: number, y: number, pane = 0) => ({ time: chart.coordinateToTime(x), price: chart.coordinateToPrice(y, pane) as number });
  const line = (a: [number, number], b: [number, number], extra: Partial<DrawingInput> = {}) =>
    draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [at(...a), at(...b)], ...extra });
  const top = () => chart.panes()[0].primitives().find((p) => p instanceof DrawingLayer && p.zOrder() === 'top') as GestureLayer;
  return { chart, draw, el, move, drag, click, at, line, top };
}

describe('Ctrl+drag on empty space selects what the box touches', () => {
  it('selects a line the box crosses, though neither anchor is inside it, and leaves one it misses', () => {
    const { draw, drag, line, chart } = mount();
    const crossed = line([100, 100], [700, 500]);   // passes through the box's middle
    const inside = line([320, 280], [360, 300]);    // wholly inside
    line([100, 500], [200, 560]);                   // far away
    const range = chart.getVisibleLogicalRange();
    drag([300, 250], [420, 340], { ctrl: true });
    expect([...draw.selection()].sort()).toEqual([crossed.id, inside.id].sort());
    expect(chart.getVisibleLogicalRange()).toEqual(range);          // the press did not pan
  });

  it('works with Cmd as well, for macOS', () => {
    const { draw, drag, line } = mount();
    const a = line([320, 280], [360, 300]);
    drag([300, 250], [420, 340], { meta: true });
    expect(draw.selection()).toEqual([a.id]);
  });

  it('replaces the selection, and adds to it with Shift held as well', () => {
    const { draw, drag, line } = mount();
    const a = line([320, 280], [360, 300]);
    const b = line([520, 280], [560, 300]);
    draw.select(b.id);
    drag([300, 250], [420, 340], { ctrl: true });
    expect(draw.selection()).toEqual([a.id]);
    draw.select(b.id);
    drag([300, 250], [420, 340], { ctrl: true, shift: true });
    expect(draw.selection()).toEqual([b.id, a.id]);
  });

  it('leaves out what the user cannot select: an unselectable, a locked or a hidden drawing', () => {
    const { draw, drag, line } = mount();
    const plain = line([320, 280], [360, 300]);
    const readOnly = line([330, 260], [370, 320], { policy: { editable: false } });
    line([340, 270], [380, 290], { policy: { selectable: false } });
    line([310, 300], [350, 310], { locked: true });
    line([315, 290], [355, 305], { visible: false });
    drag([300, 250], [420, 340], { ctrl: true });
    expect([...draw.selection()].sort()).toEqual([plain.id, readOnly.id].sort());
  });

  it('shows the box while it is dragged, and nothing once it is let go', () => {
    const { chart, el, move, top, line } = mount();
    line([320, 280], [360, 300]);
    move(300, 250, { ctrl: true });
    el.dispatch('pointerdown', pointer('down', 300, 250, { ctrlKey: true }));
    move(360, 290, { ctrl: true }, true);
    move(420, 340, { ctrl: true }, true);
    const rect = chart.plotRect(0)!;
    expect(top().box()).toEqual({ x0: 300 - rect.left, y0: 250 - rect.top, x1: 420 - rect.left, y1: 340 - rect.top });
    // Painted as a solid rim over a translucent fill, on the overlay.
    const { ctx, rec } = makeCtx();
    top().draw(ctx, top().context()!);
    const rim = rec.ops.find((op) => op.type === 'strokeRect');
    expect(rim?.args.map(Math.floor)).toEqual([300 - rect.left, 250 - rect.top, 120, 90]);   // on the half pixel, for a crisp rim
    expect(rec.ops.some((op) => op.type === 'fillRect')).toBe(true);
    el.dispatch('pointerup', pointer('up', 420, 340, { ctrlKey: true }));
    expect(top().box()).toBeNull();
  });

  it('selects as the box grows, before it is let go', () => {
    const { draw, el, move, line } = mount();
    const a = line([320, 280], [360, 300]);
    const b = line([520, 280], [560, 300]);
    move(300, 250, { ctrl: true });
    el.dispatch('pointerdown', pointer('down', 300, 250, { ctrlKey: true }));
    move(420, 340, { ctrl: true }, true);
    expect(draw.selection()).toEqual([a.id]);
    move(600, 340, { ctrl: true }, true);
    expect(draw.selection()).toEqual([a.id, b.id]);
    move(420, 340, { ctrl: true }, true);
    expect(draw.selection()).toEqual([a.id]);
    el.dispatch('pointerup', pointer('up', 420, 340, { ctrlKey: true }));
    expect(draw.selection()).toEqual([a.id]);
  });

  it('keeps Ctrl+click on empty space what it was: the additive click on nothing', () => {
    const { draw, click, line } = mount();
    const a = line([320, 280], [360, 300]);
    draw.select(a.id);
    click(600, 450, { ctrl: true });
    expect(draw.selection()).toEqual([a.id]);
  });

  it('leaves a plain drag on empty space to the pan', () => {
    const { draw, drag, line, chart } = mount();
    line([320, 280], [360, 300]);
    const range = chart.getVisibleLogicalRange();
    drag([300, 250], [420, 340]);
    expect(draw.selection()).toEqual([]);
    expect(chart.getVisibleLogicalRange()).not.toEqual(range);
  });

  it('leaves Ctrl+drag on a drawing to the drag, which moves it', () => {
    const { draw, drag, line } = mount();
    const a = line([200, 300], [600, 300]);
    const before = draw.get(a.id)!.points.map((p) => ({ ...p }));
    drag([400, 300], [400, 360], { ctrl: true });
    expect(draw.get(a.id)!.points[0].price).not.toBe(before[0].price);
    expect(draw.selection()).toEqual([a.id]);
  });

  it('gives the chart its pan back once Ctrl is let go', () => {
    const { chart, move } = mount();
    const spy = vi.spyOn(chart, 'setPlacementMode');
    move(300, 250, { ctrl: true });
    expect(spy).toHaveBeenLastCalledWith(true);
    move(310, 250);
    expect(spy).toHaveBeenLastCalledWith(false);
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it('never takes the press of a tool armed while Ctrl was held over empty space', () => {
    const { draw, el, move, top } = mount();
    move(300, 250, { ctrl: true });
    draw.setTool('trend-line');
    el.dispatch('pointerdown', pointer('down', 300, 250, { ctrlKey: true }));
    move(360, 290, { ctrl: true }, true);
    move(420, 340, { ctrl: true }, true);
    expect(top()?.box() ?? null).toBeNull();
    el.dispatch('pointerup', pointer('up', 420, 340, { ctrlKey: true }));
    expect(draw.drawings().map((d) => d.tool)).toEqual(['trend-line']);
  });

  it('does nothing when the host turns the gesture off', () => {
    const { draw, drag, line, chart } = mount({ gestures: { boxSelect: false } });
    line([320, 280], [360, 300]);
    const range = chart.getVisibleLogicalRange();
    drag([300, 250], [420, 340], { ctrl: true });
    expect(draw.selection()).toEqual([]);
    expect(chart.getVisibleLogicalRange()).not.toEqual(range);
  });
});

describe('what a box touches', () => {
  const rc = {
    plotWidth: 800, plotHeight: 500, priceAxisWidth: 60, dpr: 1, theme: darkTheme,
    timeScale: { indexToX: (i: number) => i },
    priceScale: { priceToY: (p: number) => p, format: String },
    dataLayer: { timeToIndexFloat: (t: number) => t },
  } as unknown as PrimitiveRenderContext;
  const drawing = (tool: string, points: [number, number][], style: Drawing['style'] = {}): Drawing =>
    ({ id: tool, tool, paneIndex: 0, zIndex: 0, style, points: points.map(([time, price]) => ({ time, price })) });
  const box = { x0: 300, y0: 200, x1: 400, y1: 260 };

  it('counts geometry crossing the box, not only anchors inside it', () => {
    expect(touchesBox(drawing('trend-line', [[100, 100], [700, 400]]), rc, box, 6)).toBe(true);
    expect(touchesBox(drawing('trend-line', [[100, 400], [200, 450]]), rc, box, 6)).toBe(false);
  });

  it('finds a level inside the box whose anchors are both outside it', () => {
    // Levels at 0 (y 100), 0.5 (y 230) and 1 (y 360): only the middle one is in the box.
    const fib = drawing('fib-retracement', [[320, 100], [380, 360]], { levels: [{ ratio: 0 }, { ratio: 0.5 }, { ratio: 1 }] });
    expect(touchesBox(fib, rc, box, 6)).toBe(true);
    expect(touchesBox(fib, rc, { x0: 300, y0: 280, x1: 400, y1: 340 }, 6)).toBe(false);
  });

  it('counts a filled shape the box sits inside, and not an outline it sits inside', () => {
    expect(touchesBox(drawing('rectangle', [[200, 100], [500, 400]], { fill: true }), rc, box, 6)).toBe(true);
    expect(touchesBox(drawing('rectangle', [[200, 100], [500, 400]], { fill: false }), rc, box, 6)).toBe(false);
  });

  it('samples a path along its length', () => {
    const level = drawing('horizontal-line', [[0, 230]]);
    expect(touchesPath(level, rc, { x: 50, y: 200 }, { x: 60, y: 260 }, 6)).toBe(true);
    expect(touchesPath(level, rc, { x: 50, y: 200 }, { x: 60, y: 215 }, 6)).toBe(false);
  });

  it('costs a bounded number of samples per drawing', () => {
    expect(boxSamples(box, 6)).toBeLessThan(150);
    expect(boxSamples({ x0: 0, y0: 0, x1: 0, y1: 0 }, 6)).toBe(4);
  });
});
