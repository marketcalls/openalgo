/**
 * A chart whose container leaves the document while the pointer is over it.
 *
 * A framework that keeps a view alive parks its DOM outside the document when
 * the user switches away, from the keyboard or in code, and the browser sends
 * no pointerleave to a node it has removed. The chart listens for keys on the
 * document, so its hover scope used to go on answering keys typed at whatever
 * replaced it: an arrow panned a chart nobody could see.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';

const charts: Chart[] = [];
afterEach(() => { charts.splice(0).forEach((chart) => chart.destroy()); vi.unstubAllGlobals(); });

/** Bars from a random walk with a quiet and a busy stretch, as a session has. */
function walk(count: number): { time: number; open: number; high: number; low: number; close: number }[] {
  let s = 91, price = 2412;
  const rnd = (): number => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0), s / 4294967296);
  return Array.from({ length: count }, (_, i) => {
    const vol = i > 120 && i < 160 ? 4 : 1.2;
    const open = price, close = open + (rnd() - 0.5) * 2 * vol;
    price = close;
    return { time: 1_700_000_000 + i * 60, open, high: Math.max(open, close) + rnd() * vol, low: Math.min(open, close) - rnd() * vol, close };
  });
}

function mount(scope: 'hover' | 'global' = 'hover') {
  vi.stubGlobal('window', {});
  // A document that takes listeners, as a browser's does, so the chart hears
  // keys there and not on its own container.
  const doc = fakeDocument() as unknown as Record<string, unknown>;
  const onDoc = new Map<string, ((e: unknown) => void)[]>();
  doc.addEventListener = (type: string, fn: (e: unknown) => void) => onDoc.set(type, [...(onDoc.get(type) ?? []), fn]);
  doc.removeEventListener = (type: string, fn: (e: unknown) => void) => onDoc.set(type, (onDoc.get(type) ?? []).filter((f) => f !== fn));
  doc.activeElement = null;
  const element = (doc.createElement as (tag: string) => unknown)('div') as FakeElement & { isConnected: boolean };
  element.isConnected = true;
  const chart = new Chart(element, {
    document: doc as unknown as Document, pixelRatio: () => 1, timeNavigator: false, animZoom: false, animAutoscale: false,
    shortcuts: { scope, persist: false }, raf: { schedule: (cb) => { cb(); return 0; }, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(walk(240));
  const key = (code: string): void => {
    for (const fn of onDoc.get('keydown') ?? []) fn({ code, key: code, target: null, preventDefault() {} });
  };
  const offset = (): number => chart.timeScale.rightOffset;
  return { chart, element, key, offset };
}

describe('a container taken out of the document under the pointer', () => {
  it('answers hover-scoped keys while it is in the document and hovered', () => {
    const { element, key, offset } = mount();
    element.dispatch('pointerenter', {});
    const before = offset();
    key('ArrowLeft');
    expect(offset()).not.toBe(before);
  });

  it('does not answer them while it is parked', () => {
    const { element, key, offset } = mount();
    element.dispatch('pointerenter', {});
    element.isConnected = false;
    const before = offset();
    key('ArrowLeft');
    key('Equal');
    expect(offset()).toBe(before);
  });

  it('waits for the pointer to come in again once it is back', () => {
    const { chart, element, key, offset } = mount();
    element.dispatch('pointerenter', {});
    element.isConnected = false;
    key('ArrowLeft');
    element.isConnected = true;
    const before = offset();
    const spacing = chart.timeScale.barSpacing;
    key('ArrowLeft');
    key('Equal');
    expect(offset()).toBe(before);
    expect(chart.timeScale.barSpacing).toBe(spacing);
    element.dispatch('pointerenter', {});
    key('ArrowLeft');
    expect(offset()).not.toBe(before);
  });

  it('takes a move over it for the pointer coming in, with no enter to say so', () => {
    // Two of the three engines send no pointerenter to a container put back
    // under a pointer that had entered it before it was parked.
    const { element, key, offset } = mount();
    element.dispatch('pointerenter', {});
    element.isConnected = false;
    key('ArrowLeft');
    element.isConnected = true;
    element.dispatch('pointermove', pointer('move', 300, 200, { buttons: 0 }));
    const before = offset();
    key('ArrowLeft');
    expect(offset()).not.toBe(before);
  });

  it('still answers a global scope, which a host chose so keys act wherever the pointer is', () => {
    const { element, key, offset } = mount('global');
    element.isConnected = false;
    const before = offset();
    key('ArrowLeft');
    expect(offset()).not.toBe(before);
  });
});
