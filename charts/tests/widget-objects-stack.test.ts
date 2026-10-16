/**
 * The widget's objects panel shows each pane in draw order and reorders by
 * drag within it: the upper half of a row drops the dragged one under it in
 * paint order, the lower half over it, and a drop the bands cannot paint is
 * refused before it lands. Earlier and Later step through the same order, and
 * a study its host protects offers only what its policy allows.
 */
import { afterEach, beforeAll, expect, it } from 'vitest';
import '../src/indicators/index';
import { Chart } from '../src/core/chart';
import { ChartObjects } from '../src/model/chart-objects';
import { DrawingController } from '../src/draw/index';
import { createObjectsPanelContent } from '../src/widget/objects-panel';
import { contextMenuEntries } from '../src/widget/dialogs/context-menu';
import { mountIndicatorSettings } from '../src/widget/dialogs/indicator-settings';
import type { WidgetContext } from '../src/widget/context';
import type { ContextMenuEvent } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import { fakeWidgetDocument, fire, type FakeElement } from './helpers/fake-dom-widget';

const T0 = 1700000000;
beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});
const cleanup: (() => void)[] = [];
afterEach(() => cleanup.splice(0).reverse().forEach(off => off()));

function rig() {
  const engineDoc = fakeDocument();
  const chart = new Chart(engineDoc.createElement('div'), {
    document: engineDoc, pixelRatio: () => 1, shortcuts: false, animZoom: false,
    raf: { schedule: (cb: (t: number) => void) => { cb(0); return 0; } },
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(Array.from({ length: 60 }, (_, i) => ({
    time: T0 + i * 60, open: 100 + i, high: 103 + i, low: 97 + i, close: 100 + i, volume: 10,
  })));
  const draw = new DrawingController(chart);
  const objects = new ChartObjects(chart, { drawings: draw });
  const toasts: string[] = [];
  const document = fakeWidgetDocument();
  const ctx = { document, chart, draw, objects, toast: (text: string) => { toasts.push(text); } } as unknown as WidgetContext;
  const content = createObjectsPanelContent(ctx);
  const root = content.element as unknown as FakeElement;
  cleanup.push(() => chart.destroy(), () => draw.destroy(), () => objects.destroy(), () => content.destroy());
  return { chart, draw, objects, ctx, root, toasts };
}

const box = (draw: DrawingController) => draw.add({
  tool: 'rectangle', paneIndex: 0, style: {}, points: [{ time: T0 + 60, price: 100 }, { time: T0 + 600, price: 120 }],
});
/** Row ids of one pane section, top to bottom as the panel lists them. */
const listed = (root: FakeElement, pane = 0): string[] =>
  [...root.querySelector(`[data-pane-index="${pane}"]`)!.querySelectorAll('[data-object-id]')].map(node => (node as FakeElement).dataset.objectId!);
const row = (root: FakeElement, id: string): FakeElement => root.querySelector(`[data-object-id="${id}"]`)!;
/** Give a row a box so the pointer can land in its upper or lower half. */
const sized = (node: FakeElement, top: number): FakeElement => { node.rect = { left: 0, top, width: 300, height: 40 }; return node; };

it('lists a pane back to front: behind the series, each entry with what is placed on it, then in front', () => {
  const r = rig();
  const a = r.chart.addIndicator('sma');
  const behind = box(r.draw); r.draw.sendBehindSeries(behind.id);
  const onA = box(r.draw); r.draw.placeInStack(onA.id, { entry: 'indicator:' + a.id }, 'above');
  const front = box(r.draw);
  expect(listed(r.root)).toEqual(['drawing:' + behind.id, 'source:primary', 'indicator:' + a.id, 'drawing:' + onA.id, 'drawing:' + front.id]);
  expect(row(r.root, 'drawing:' + behind.id).textContent).toContain('Behind the series');
  expect(row(r.root, 'drawing:' + onA.id).textContent).toContain('Above SMA');
});

it('drops over or under a row by the half the pointer is in, and refuses a drop the bands cannot paint', () => {
  const r = rig();
  const a = r.chart.addIndicator('sma');
  const b = r.chart.addIndicator('ema');
  const onA = box(r.draw); r.draw.placeInStack(onA.id, { entry: 'indicator:' + a.id }, 'above');
  const front = box(r.draw);
  const A = 'indicator:' + a.id, B = 'indicator:' + b.id;
  expect(listed(r.root)).toEqual(['source:primary', A, 'drawing:' + onA.id, B, 'drawing:' + front.id]);
  // The front drawing, dropped on the upper half of the source row, goes under it.
  fire(row(r.root, 'drawing:' + front.id), 'dragstart');
  const over = fire(sized(row(r.root, 'source:primary'), 0), 'dragover', { clientY: 5 });
  expect(over.defaultPrevented).toBe(true);
  expect(row(r.root, 'source:primary').classList.contains('is-drop-before')).toBe(true);
  fire(row(r.root, 'source:primary'), 'drop', { clientY: 5 });
  expect(listed(r.root)).toEqual(['drawing:' + front.id, 'source:primary', A, 'drawing:' + onA.id, B]);
  expect(r.draw.get(front.id)!.zIndex).toBeLessThan(0);
  expect(row(r.root, 'source:primary').classList.contains('is-drop-before')).toBe(false);
  // Study B cannot land between study A and the drawing placed on it.
  fire(row(r.root, B), 'dragstart');
  const refused = fire(sized(row(r.root, A), 100), 'dragover', { clientY: 130 });
  expect(refused.defaultPrevented).toBe(false);
  fire(row(r.root, A), 'drop', { clientY: 130 });
  expect(listed(r.root)).toEqual(['drawing:' + front.id, 'source:primary', A, 'drawing:' + onA.id, B]);
  // It can go under A, and A's drawing stays on A.
  fire(row(r.root, B), 'dragstart');
  expect(fire(sized(row(r.root, A), 100), 'dragover', { clientY: 105 }).defaultPrevented).toBe(true);
  fire(row(r.root, A), 'drop', { clientY: 105 });
  expect(listed(r.root)).toEqual(['drawing:' + front.id, 'source:primary', B, A, 'drawing:' + onA.id]);
  expect(r.chart.indicators().map(item => item.id)).toEqual([b.id, a.id]);
});

it('steps Earlier and Later through the draw order, across categories', () => {
  const r = rig();
  const a = r.chart.addIndicator('sma');
  const d = box(r.draw);
  const A = 'indicator:' + a.id, D = 'drawing:' + d.id;
  const control = (id: string, action: string): FakeElement => row(r.root, id).querySelector(`[data-action="${action}"]`)!;
  expect(listed(r.root)).toEqual(['source:primary', A, D]);
  expect(control(D, 'later').disabled).toBe(true);
  fire(control(D, 'earlier'), 'click');
  expect(listed(r.root)).toEqual(['source:primary', D, A]);
  expect(r.draw.get(d.id)!.stackAbove).toBe('source:primary');
  fire(control(D, 'earlier'), 'click');
  expect(listed(r.root)).toEqual([D, 'source:primary', A]);
  expect(control(D, 'earlier').disabled).toBe(true);
  // The study steps between whole slots.
  fire(control(A, 'earlier'), 'click');
  expect(listed(r.root)).toEqual([D, A, 'source:primary']);
  expect(control(A, 'earlier').disabled).toBe(true);
  expect(control('source:primary', 'later').disabled).toBe(true);
  fire(control('source:primary', 'earlier'), 'click');
  expect(listed(r.root)).toEqual([D, 'source:primary', A]);
  expect(r.toasts).toEqual([]);
});

it('offers a protected study only what its policy allows, and leaves an unlisted one out', () => {
  const r = rig();
  const pinned = r.chart.addIndicator('rsi', {}, { policy: { removable: false, configurable: false, movable: false } });
  const hidden = r.chart.addIndicator('sma', {}, { policy: { listed: false } });
  const id = 'indicator:' + pinned.id;
  const node = row(r.root, id);
  for (const action of ['remove', 'settings', 'earlier', 'later']) expect(node.querySelector(`[data-action="${action}"]`)).toBeNull();
  expect(node.querySelector('[data-action="move"]')).toBeNull();
  expect(node.querySelector('[data-action="visibility"]')).not.toBeNull();
  expect((node as unknown as { draggable: boolean }).draggable).toBe(false);
  expect(r.root.querySelector(`[data-object-id="indicator:${hidden.id}"]`)).toBeNull();
  // The context menu greys what the policy withholds and says why.
  const event = { paneIndex: pinned.paneIndex, point: { x: 10, y: 10 }, price: 50, time: null, index: null,
    target: { kind: 'indicator', id, instanceId: pinned.id }, preventDefault() {} } as unknown as ContextMenuEvent;
  const items = contextMenuEntries(r.ctx, event);
  const remove = items.find(item => 'id' in item && item.id === 'ind-remove') as { disabled?: boolean; note?: string };
  const settings = items.find(item => 'id' in item && item.id === 'ind-settings') as { disabled?: boolean; note?: string };
  expect(remove.disabled).toBe(true);
  expect(remove.note).toBe('protected');
  expect(settings.disabled).toBe(true);
  // A direct open declines with the reason rather than a dialog whose writes fail.
  expect(mountIndicatorSettings(r.ctx, undefined, { instanceId: pinned.id }).isOpen()).toBe(false);
  expect(r.toasts).toContain('RSI settings are protected');
});

it('moves a row with Alt and an arrow key, the keyboard way to drag it', () => {
  const r = rig();
  const a = r.chart.addIndicator('sma');
  const d = box(r.draw);
  const A = 'indicator:' + a.id, D = 'drawing:' + d.id;
  const summary = row(r.root, D).querySelector('.oac-objects__summary') as FakeElement;
  expect(listed(r.root)).toEqual(['source:primary', A, D]);
  const up = fire(summary, 'keydown', { key: 'ArrowUp', altKey: true });
  expect(up.defaultPrevented).toBe(true);
  expect(listed(r.root)).toEqual(['source:primary', D, A]);
  fire(summary, 'keydown', { key: 'ArrowDown', altKey: true });
  expect(listed(r.root)).toEqual(['source:primary', A, D]);
  // Without Alt the arrow is the list's to scroll, and at the front there is nowhere further to go.
  expect(fire(summary, 'keydown', { key: 'ArrowUp' }).defaultPrevented).toBe(false);
  fire(summary, 'keydown', { key: 'ArrowDown', altKey: true });
  expect(listed(r.root)).toEqual(['source:primary', A, D]);
  expect(r.toasts).toEqual([]);
});

it('says how the list reads, and marks the rows that drag with a grip', () => {
  const r = rig();
  const d = box(r.draw);
  expect((r.root.querySelector('.oac-objects__hint') as FakeElement).hidden).toBe(false);
  expect(r.root.querySelector('.oac-objects__hint')!.textContent).toContain('back to front');
  expect(row(r.root, 'drawing:' + d.id).querySelector('.oac-objects__grip')!.getAttribute('aria-hidden')).toBe('true');
  expect((row(r.root, 'drawing:' + d.id) as unknown as { draggable: boolean }).draggable).toBe(true);
});
