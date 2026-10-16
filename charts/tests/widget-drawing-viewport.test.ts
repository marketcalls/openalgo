/**
 * Viewport anchoring as the widget offers it: an Anchor row in the drawing
 * properties for the tools that can be pinned to the screen, and nowhere
 * else, and the inline text editor opening over a pinned note, whose place on
 * screen is not a time and a price the chart could map.
 */
import { describe, it, expect, beforeAll, afterEach } from 'vitest';
import { Chart, darkTheme } from 'openalgo-charts';
import type { Bar } from 'openalgo-charts';
import { DrawingController, registerBuiltinDrawingTools } from 'openalgo-charts/draw';
import { createOverlayStack, WidgetBus, WidgetStorage, type OverlayStack, type WidgetContext } from '../src/widget/context';
import { mountDrawingProperties, mountTextEditor } from '../src/widget/dialogs/index';
import { installDom, asDoc, asEl, type FakeElement, type Dom } from './widget-form.test';

const T0 = 1700000000;
const BARS: Bar[] = Array.from({ length: 40 }, (_, i) => {
  const c = 100 + Math.sin(i / 4) * 5;
  return { time: T0 + i * 60, open: c - 0.5, high: c + 1, low: c - 1, close: c, volume: 100 + i };
});

interface Rig { ctx: WidgetContext; dom: Dom; chart: Chart; draw: DrawingController; stack: OverlayStack; q(sel: string): FakeElement | null; qa(sel: string): FakeElement[] }
const rigs: Rig[] = [];

function makeRig(): Rig {
  const dom = installDom();
  const doc = asDoc(dom.doc);
  const chart = new Chart(asEl(dom.chartEl), {
    document: doc, pixelRatio: () => 1, shortcuts: false, timeNavigator: false,
    raf: { schedule: (cb) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(958, 660);
  chart.addSeries('candlestick').setData(BARS);
  const draw = new DrawingController(chart);
  const stack = createOverlayStack(asEl(dom.root), doc);
  const ctx: WidgetContext = {
    chart, draw, root: asEl(dom.root), document: doc, theme: 'dark', chartTheme: darkTheme,
    keymap: {} as WidgetContext['keymap'], bus: new WidgetBus(), storage: new WidgetStorage('test', null), locale: undefined,
    toast: () => ({ node: doc.createElement('div'), dismiss: () => {} }),
    openOverlay: (el, opts) => stack.open(el, opts), status: () => {},
    tips: { attach() {}, refreshLabel() {}, show() {}, hide() {}, target: () => null, destroy() {} },
    overlays: stack, symbol: () => ({ symbol: 'TEST', exchange: 'NSE' }), interval: () => '5m',
  };
  const layer = (): FakeElement => stack.layer as unknown as FakeElement;
  const rig: Rig = { ctx, dom, chart, draw, stack, q: (sel) => layer().querySelector(sel), qa: (sel) => layer().querySelectorAll(sel) };
  rigs.push(rig);
  return rig;
}

beforeAll(() => { registerBuiltinDrawingTools(); });
afterEach(() => { for (const r of rigs.splice(0)) { r.stack.destroy(); r.chart.destroy(); } });

describe('the Anchor row in the drawing properties', () => {
  it('pins a rectangle to the screen where it is, and one undo puts it back on time and price', () => {
    const rig = makeRig();
    const r = rig.draw.add({ tool: 'rectangle', paneIndex: 0, style: {},
      points: [{ time: T0 + 600, price: 98 }, { time: T0 + 1800, price: 103 }] });
    rig.draw.select(r.id);
    const before = rig.draw.screenPoints(r.id)!;
    mountDrawingProperties(rig.ctx);
    const select = rig.q('[data-key="space"] select') as FakeElement;
    expect(select).not.toBeNull();
    expect(select.value).toBe('data');
    expect(select.querySelectorAll('option').map((o) => o.value)).toEqual(['data', 'viewport']);
    select.value = 'viewport';
    select.fire('change');
    const pinned = rig.draw.get(r.id)!;
    expect(pinned.space).toBe('viewport');
    expect(pinned.points).toEqual([]);
    rig.draw.screenPoints(r.id)!.forEach((p, i) => { expect(p.x).toBeCloseTo(before[i].x, 6); expect(p.y).toBeCloseTo(before[i].y, 6); });
    // The form reads the model back, not the control's own state.
    expect((rig.q('[data-key="space"] select') as FakeElement).value).toBe('viewport');
    expect(rig.draw.undo()).toBe(true);
    expect(rig.draw.get(r.id)!.space).toBeUndefined();
    expect(rig.draw.get(r.id)!.points).toHaveLength(2);
  });

  it('is not offered for a tool that cannot be pinned, or a selection that mixes one in', () => {
    const rig = makeRig();
    const line = rig.draw.add({ tool: 'trend-line', paneIndex: 0, style: {},
      points: [{ time: T0 + 600, price: 98 }, { time: T0 + 1800, price: 103 }] });
    const r = rig.draw.add({ tool: 'rectangle', paneIndex: 0, style: {},
      points: [{ time: T0 + 600, price: 98 }, { time: T0 + 1800, price: 103 }] });
    rig.draw.select(line.id);
    mountDrawingProperties(rig.ctx);
    expect(rig.q('[data-key="space"]')).toBeNull();
    rig.stack.closeAll();
    rig.draw.select([r.id, line.id]);
    mountDrawingProperties(rig.ctx);
    expect(rig.q('[data-key="space"]')).toBeNull();
  });
});

describe('a pin the controller cannot make', () => {
  it('leaves the row on the space the drawing is in and says why, on a folded pane', () => {
    const rig = makeRig();
    rig.chart.addSeries('line', { paneIndex: 1 }).setData(BARS.map((b) => ({ time: b.time, value: b.close })));
    const r = rig.draw.add({ tool: 'rectangle', paneIndex: 1, style: {},
      points: [{ time: T0 + 600, price: 98 }, { time: T0 + 1800, price: 103 }] });
    expect(rig.chart.setPaneCollapsed(1, true)).toBe(true);
    const toasts: string[] = [];
    rig.ctx.toast = (message) => { toasts.push(message); return { node: rig.ctx.document.createElement('div'), dismiss: () => {} }; };
    rig.draw.select(r.id);
    mountDrawingProperties(rig.ctx);
    const select = rig.q('[data-key="space"] select') as FakeElement;
    select.value = 'viewport';
    select.fire('change');
    expect(rig.draw.get(r.id)!.space).toBeUndefined();
    expect((rig.q('[data-key="space"] select') as FakeElement).value).toBe('data');
    expect(toasts).toEqual(["The anchor changes only while the drawing's pane is on screen"]);
    // On screen again, the same choice pins it, and says nothing.
    expect(rig.chart.setPaneCollapsed(1, false)).toBe(true);
    const again = rig.q('[data-key="space"] select') as FakeElement;
    again.value = 'viewport';
    again.fire('change');
    expect(rig.draw.get(r.id)!.space).toBe('viewport');
    expect(toasts).toHaveLength(1);
  });
});

describe('the inline text editor', () => {
  it('opens over a pinned note at the place the controller reports, after the chart has panned', () => {
    const rig = makeRig();
    const t = rig.draw.add({ tool: 'text', paneIndex: 0, style: {}, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.25, y: 0.3 }], text: { value: 'Pinned' } });
    rig.chart.setVisibleLogicalRange({ from: 5, to: 25 });
    mountTextEditor(rig.ctx, undefined, { id: t.id });
    const box = rig.q('.oac-textedit') as FakeElement;
    expect(box).not.toBeNull();
    const [at] = rig.draw.screenPoints(t.id)!;
    // Chart coordinates plus the container's offset inside the root.
    expect(box.style.left).toBe(`${Math.round(at.x + 42)}px`);
    expect(box.style.top).toBe(`${Math.round(at.y + 40)}px`);
    box.textContent = 'Edited';
    box.blur();
    expect(rig.draw.get(t.id)?.text?.value).toBe('Edited');
    expect(rig.draw.get(t.id)?.viewportPoints).toEqual([{ x: 0.25, y: 0.3 }]);
  });
});
