/**
 * The drawing actions (lock, hide, the order moves, delete) keep one rule on
 * every surface that offers them: the floating toolbar, the right-click menu,
 * the properties dialog, the rail, the phone bar and the keys. One press is
 * one undo step, a switch reads every editable drawing it acts on, and a
 * selection whose every drawing is locked is not deleted.
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import type { Bar, ContextMenuEvent } from '../src/index';
import { createWidget, type Widget, type WidgetOptions } from '../src/widget/index';
import { contextMenuEntries, type MenuItem } from '../src/widget/dialogs/context-menu';
import { mountDrawingProperties } from '../src/widget/dialogs/drawing-properties';
import { historyPress } from '../src/widget/context';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, fireKey, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);

const T0 = 1700000100;
// A seeded random walk, so the drawings sit on bars a trader would draw on.
const bars: Bar[] = (() => {
  let seed = 11;
  const next = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 - 0.5; };
  let close = 2400;
  return Array.from({ length: 80 }, (_, i) => {
    const open = close;
    close = Math.round((open + next() * 14) * 20) / 20;
    return { time: T0 + i * 300, open, high: Math.max(open, close) + 3, low: Math.min(open, close) - 3, close, volume: 1000 + i };
  });
})();

const live: Widget[] = [];
afterEach(() => { for (const w of live.splice(0)) if (!w.isDestroyed) w.destroy(); });

function make(opts: WidgetOptions = {}): { w: Widget; root: FakeElement; chartEl: FakeElement } {
  const doc = fakeWidgetDocument();
  const w = createWidget(fakeContainer(doc, 1000, 640) as unknown as HTMLElement, {
    document: doc as unknown as Document, persist: false, mobile: 'never', pixelRatio: () => 1,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    ...opts,
  });
  w.chart.applySize(900, 560);
  w.series.setData(bars);
  live.push(w);
  const root = w.root as unknown as FakeElement;
  fire(root, 'pointerenter');
  return { w, root, chartEl: root.querySelector('.oac-chart') as FakeElement };
}

/** Three trend lines on the swings of the walk, the first two selected. */
function three(w: Widget): string[] {
  const at = (from: number, to: number): string => w.draw.add({
    tool: 'trend-line', paneIndex: 0, style: {},
    points: [{ time: bars[from]!.time, price: bars[from]!.low }, { time: bars[to]!.time, price: bars[to]!.high }],
  }).id;
  const ids = [at(10, 30), at(25, 50), at(40, 70)];
  w.draw.select(ids.slice(0, 2));
  return ids;
}

const order = (w: Widget): string[] => w.draw.drawings().map((d) => `${d.id}:${d.zIndex}`);
const locks = (w: Widget, ids: readonly string[]): boolean[] => ids.map((id) => w.draw.get(id)?.locked === true);

const menuEvent = (id: string): ContextMenuEvent => ({
  paneIndex: 0, point: { x: 100, y: 100 }, price: null, time: null, index: null,
  target: { kind: 'drawing', id: `draw:${id}` }, preventDefault: () => {},
});
const menuItem = (w: Widget, id: string, act: string): MenuItem =>
  contextMenuEntries(w.context, menuEvent(id)).find((e) => (e as MenuItem).id === act) as MenuItem;

describe('the properties dialog', () => {
  it('reorders a selection as one undo step', () => {
    const { w, root } = make();
    three(w);
    const before = order(w);
    mountDrawingProperties(w.context);
    (root.querySelector('.oac-props [data-act="front"]') as FakeElement).click();
    expect(order(w)).not.toEqual(before);
    historyPress(w.context, 'undo');
    expect(order(w)).toEqual(before);
  });

  it('locks a partly locked selection, whichever drawing comes first', () => {
    const { w, root } = make();
    const [a, b] = three(w);
    w.draw.update(a!, { locked: true });
    mountDrawingProperties(w.context);
    const lock = root.querySelector('.oac-props [data-act="lock"]') as FakeElement;
    expect(lock.getAttribute('aria-pressed')).toBe('false');
    lock.click();
    expect(locks(w, [a!, b!])).toEqual([true, true]);
  });

  it('greys Delete when every drawing is locked', () => {
    const { w, root } = make();
    const [a, b] = three(w);
    w.draw.updateMany([{ id: a!, patch: { locked: true } }, { id: b!, patch: { locked: true } }]);
    mountDrawingProperties(w.context);
    const remove = root.querySelector('.oac-props [data-act="delete"]') as FakeElement;
    expect(remove.disabled).toBe(true);
    remove.click();
    expect(w.draw.get(a!)).toBeDefined();
  });
});

describe('the right-click menu', () => {
  it('locks a partly locked selection even when the locked drawing was clicked', () => {
    const { w } = make();
    const [a, b] = three(w);
    w.draw.update(a!, { locked: true });
    const lock = menuItem(w, a!, 'draw-lock');
    expect(lock.on).toBe(false);
    w.history.transact(() => lock.run!());
    expect(locks(w, [a!, b!])).toEqual([true, true]);
  });

  it('deletes a partly locked selection and refuses one whose every drawing is locked', () => {
    const { w } = make();
    const [a, b] = three(w);
    w.draw.update(a!, { locked: true });
    expect(menuItem(w, a!, 'draw-delete').disabled).toBe(false);
    expect(menuItem(w, a!, 'draw-cut').disabled).toBe(false);
    w.draw.update(b!, { locked: true });
    expect(menuItem(w, a!, 'draw-delete')).toMatchObject({ disabled: true, note: 'locked' });
    expect(menuItem(w, a!, 'draw-cut')).toMatchObject({ disabled: true, note: 'locked' });
  });
});

describe('the floating toolbar', () => {
  it('reads lock over the drawings it can change, so a read-only one does not jam it', () => {
    const { w, root } = make();
    const [a, b] = three(w);
    w.draw.update(a!, { policy: { editable: false } }, { force: true });
    w.draw.update(b!, { locked: true });
    w.draw.select([a!, b!]);
    const lock = root.querySelector('[data-drawbar="lock"]') as FakeElement;
    expect(lock.getAttribute('aria-pressed')).toBe('true');
    lock.click();
    expect(w.draw.get(b!)?.locked).toBe(false);
  });
});

describe('the rail', () => {
  const control = (root: FakeElement, index: number): FakeElement => root.querySelectorAll('.oac-rail__ctl .oac-rail__btn')[index]!;

  it('locks, hides and deletes a selection as one undo step each', () => {
    const { w, root } = make();
    const [a, b] = three(w);
    control(root, 2).click();
    expect(locks(w, [a!, b!])).toEqual([true, true]);
    historyPress(w.context, 'undo');
    expect(locks(w, [a!, b!])).toEqual([false, false]);

    control(root, 3).click();
    expect([a!, b!].map((id) => w.draw.get(id)?.visible)).toEqual([false, false]);
    historyPress(w.context, 'undo');
    expect([a!, b!].map((id) => w.draw.get(id)?.visible !== false)).toEqual([true, true]);

    control(root, 4).click();
    expect(w.draw.drawings()).toHaveLength(1);
    historyPress(w.context, 'undo');
    expect(w.draw.drawings()).toHaveLength(3);
  });
});

describe('the phone bar', () => {
  const action = (root: FakeElement, name: string): FakeElement => root.querySelector(`[data-mobile-action="${name}"]`) as FakeElement;

  it('locks a selection as one undo step', () => {
    const { w, root } = make({ mobile: 'always' });
    const [a, b] = three(w);
    action(root, 'lock').click();
    expect(locks(w, [a!, b!])).toEqual([true, true]);
    historyPress(w.context, 'undo');
    expect(locks(w, [a!, b!])).toEqual([false, false]);
  });

  it('keeps a selection whose every drawing is locked from Delete, as the desktop does', () => {
    const { w, root } = make({ mobile: 'always' });
    const [a, b] = three(w);
    w.draw.updateMany([{ id: a!, patch: { locked: true } }, { id: b!, patch: { locked: true } }]);
    const remove = action(root, 'delete');
    expect(remove.getAttribute('aria-disabled')).toBe('true');
    remove.click();
    expect(w.draw.drawings()).toHaveLength(3);
  });
});

describe('the keys', () => {
  it.each(['Delete', 'Backspace'])('%s keeps a selection whose every drawing is locked, and deletes a partly locked one', (key) => {
    const { w, chartEl } = make();
    const [a, b] = three(w);
    w.draw.updateMany([{ id: a!, patch: { locked: true } }, { id: b!, patch: { locked: true } }]);
    fireKey(chartEl, key);
    expect(w.draw.drawings()).toHaveLength(3);
    w.draw.update(b!, { locked: false });
    fireKey(chartEl, key);
    expect(w.draw.drawings()).toHaveLength(1);
  });

  it('Mod+X keeps a selection whose every drawing is locked, as the menu greys Cut', async () => {
    const { w, chartEl } = make();
    const [a, b] = three(w);
    w.draw.updateMany([{ id: a!, patch: { locked: true } }, { id: b!, patch: { locked: true } }]);
    fireKey(chartEl, 'x', { ctrlKey: true });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(w.draw.drawings()).toHaveLength(3);
    w.draw.update(b!, { locked: false });
    fireKey(chartEl, 'x', { ctrlKey: true });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(w.draw.drawings()).toHaveLength(1);
  });
});
