import { describe, it, expect, vi, afterEach } from 'vitest';
import { Chart } from '../src/core/chart';
import { makeCtx } from './helpers/fake-ctx';
import type { IPrimitive, PrimitiveHit } from '../src/primitives/primitive';

/**
 * Regression: a right-click (or any non-primary mouse button) must not replay
 * the previous left-click. `_onPointerDown` ignores non-primary buttons, so the
 * cached down-position never refreshes; without a matching guard on pointerup,
 * the right-click's pointerup re-hit-tests at the stale position and re-fires
 * the click callback, e.g. placing a phantom order from a Buy/Sell button.
 */

// Document that only needs to mint canvases (with a fake 2D context) and divs.
function fakeDoc(): Document {
  const make = (tag: string): Record<string, unknown> => {
    const el: Record<string, unknown> = {
      tagName: tag.toUpperCase(), style: {}, children: [],
      appendChild(c: unknown) { (el.children as unknown[]).push(c); return c; },
      remove() {},
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 }),
      addEventListener() {}, removeEventListener() {},
      setAttribute() {}, getAttribute: () => null, hasAttribute: () => false,
    };
    if (tag === 'canvas') {
      el.width = 0; el.height = 0;
      el.getContext = () => makeCtx().ctx;
    }
    return el;
  };
  return { createElement: (t: string) => make(t) } as unknown as Document;
}

// Container that records the pointer listeners Chart attaches, so the test can
// dispatch synthetic pointer events at them.
function captureContainer(doc: Document) {
  const listeners = new Map<string, Array<(e: unknown) => void>>();
  const el: Record<string, unknown> = {
    ownerDocument: doc,
    style: {} as Record<string, string>,
    children: [] as unknown[],
    clientWidth: 800, clientHeight: 600, tabIndex: 0,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 }),
    getAttribute: () => null, setAttribute() {}, hasAttribute: () => false,
    contains: () => false,
    appendChild(c: unknown) { (el.children as unknown[]).push(c); return c; },
    remove() {},
    setPointerCapture() {}, releasePointerCapture() {},
    addEventListener(type: string, fn: (e: unknown) => void) {
      const arr = listeners.get(type) ?? [];
      arr.push(fn);
      listeners.set(type, arr);
    },
    removeEventListener(type: string, fn: (e: unknown) => void) {
      const arr = listeners.get(type);
      if (arr) listeners.set(type, arr.filter((f) => f !== fn));
    },
  };
  const dispatch = (type: string, e: Record<string, unknown>) => {
    for (const fn of [...(listeners.get(type) ?? [])]) fn(e);
  };
  return { el: el as unknown as HTMLElement, dispatch };
}

// A clickable overlay region at plot px x∈[100,200], y∈[20,40] gives 'trade:buy'.
// Independent of any draw() so the test targets pointer routing, not geometry.
const buyButton: IPrimitive = {
  zOrder: () => 'top',
  draw: () => {},
  hitTest: (x: number, y: number): PrimitiveHit | null =>
    x >= 100 && x <= 200 && y >= 20 && y <= 40
      ? { externalId: 'trade:buy', zOrder: 'top', distance: 0, cursor: 'pointer' }
      : null,
};

const ev = (button: number, clientX: number, clientY: number) =>
  ({ pointerType: 'mouse', pointerId: 1, button, clientX, clientY });

function mountChart() {
  const doc = fakeDoc();
  const { el, dispatch } = captureContainer(doc);
  const chart = new Chart(el, {
    document: doc, pixelRatio: () => 1,
    raf: { schedule: (cb) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.addSeries('candlestick').setData([
    { time: 1000, open: 10, high: 12, low: 8, close: 11 },
    { time: 1060, open: 11, high: 13, low: 9, close: 12 },
  ]);
  chart.addPrimitive(buyButton, 0);
  const clicks: string[] = [];
  chart.subscribeClick((id) => clicks.push(id));
  return { chart, dispatch, clicks };
}

describe('pointer button guard (right-click must not replay a click)', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('a left-click over the buy button fires exactly one click', () => {
    vi.stubGlobal('window', {}); // _attachInput bails when window is undefined
    const { dispatch, clicks } = mountChart();

    dispatch('pointerdown', ev(0, 150, 30));
    dispatch('pointerup', ev(0, 150, 30));

    expect(clicks).toEqual(['trade:buy']);
  });

  it('a following right-click anywhere does NOT re-fire the stale click', () => {
    vi.stubGlobal('window', {});
    const { dispatch, clicks } = mountChart();

    // 1) left-click the buy button: arms the cached down-position + fires once
    dispatch('pointerdown', ev(0, 150, 30));
    dispatch('pointerup', ev(0, 150, 30));
    expect(clicks).toEqual(['trade:buy']);

    // 2) right-click far away: its pointerdown is ignored (button !== 0), so the
    //    cached position is stale. The guarded pointerup must swallow it.
    dispatch('pointerdown', ev(2, 400, 300));
    dispatch('pointerup', ev(2, 400, 300));

    expect(clicks).toEqual(['trade:buy']); // still just one: no phantom replay
  });

  it('middle-click is likewise ignored', () => {
    vi.stubGlobal('window', {});
    const { dispatch, clicks } = mountChart();

    dispatch('pointerdown', ev(0, 150, 30));
    dispatch('pointerup', ev(0, 150, 30));
    dispatch('pointerdown', ev(1, 150, 30));
    dispatch('pointerup', ev(1, 150, 30));

    expect(clicks).toEqual(['trade:buy']);
  });
});
