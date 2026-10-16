import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { createWidget, SAVE_DEBOUNCE_MS, STATE_KEY, STORAGE_PREFIX, type Widget, type WidgetOptions } from '../src/widget/index';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, fireKey, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
const live: Widget[] = [];
afterEach(() => { for (const w of live.splice(0)) w.destroy(); vi.useRealTimers(); });

function make(options: WidgetOptions = {}) {
  const doc = fakeWidgetDocument();
  const w = createWidget(fakeContainer(doc) as unknown as HTMLElement, {
    document: doc as unknown as Document, persist: false, pixelRatio: () => 1,
    raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} }, ...options,
  });
  live.push(w);
  w.chart.applySize(800, 600);
  w.series.setData([{ time: 1000, open: 100, high: 102, low: 98, close: 100 }]);
  const root = w.root as unknown as FakeElement;
  const chartEl = root.querySelector('.oac-chart')!;
  fire(root, 'pointerenter');
  const alert = w.alerts.add({ source: { kind: 'price', price: 101 } });
  w.chart.emit('hover', { id: `alert:${alert.id}:0` });
  expect(w.alerts.hovered()).toBe(alert.id);
  return { w, doc, root, chartEl, alert };
}

describe('widget alert keyboard ownership', () => {
  it.each(['Delete', 'Backspace'])('gives selected drawings priority over a hovered alert for %s', key => {
    const { w, chartEl, alert } = make();
    const first = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 1000, price: 99 }] });
    const second = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 1000, price: 100 }] });
    w.draw.select([first.id, second.id]);
    w.chart.emit('hover', { id: `alert:${alert.id}:0` });
    expect(w.alerts.hovered()).toBe(alert.id);
    expect(fireKey(chartEl, key).defaultPrevented).toBe(true);
    expect(w.draw.drawings()).toEqual([]);
    expect(w.alerts.list().map(item => item.id)).toEqual([alert.id]);
  });

  it.each(['Delete', 'Backspace'])('deletes only the hovered drawing for %s', key => {
    const { w, chartEl, alert } = make();
    const drawing = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 1000, price: 99 }] });
    w.chart.emit('hover', { id: `draw:${drawing.id}` });
    expect(w.draw.hovered()).toBe(drawing.id);
    expect(fireKey(chartEl, key).defaultPrevented).toBe(true);
    expect(w.draw.get(drawing.id)).toBeUndefined();
    expect(w.alerts.list().map(item => item.id)).toEqual([alert.id]);
  });

  it('keeps Delete with placement and lets Backspace remove the last pending anchor', () => {
    const { w, chartEl, alert } = make();
    w.draw.setTool('polyline');
    for (const [time, price] of [[1000, 99], [1060, 100], [1120, 101]]) {
      w.chart.emit('click', { time, price, paneIndex: 0 });
    }
    expect(fireKey(chartEl, 'Delete').defaultPrevented).toBe(false);
    expect(fireKey(chartEl, 'Backspace').defaultPrevented).toBe(true);
    fireKey(chartEl, 'Enter');
    expect(w.draw.drawings()).toHaveLength(1);
    expect(w.draw.drawings()[0].points).toEqual([{ time: 1000, price: 99 }, { time: 1060, price: 100 }]);
    expect(w.alerts.list().map(item => item.id)).toEqual([alert.id]);
  });

  it.each(['Delete', 'Backspace'])('removes and persists only the hovered alert for %s', key => {
    vi.useFakeTimers();
    const store = new Map<string, string>();
    const { w, chartEl } = make({ persist: true, storage: {
      getItem: name => store.get(name) ?? null,
      setItem: (name, value) => { store.set(name, value); },
      removeItem: name => { store.delete(name); },
    } });
    const kept = w.alerts.add({ source: { kind: 'price', price: 99 } });
    vi.advanceTimersByTime(SAVE_DEBOUNCE_MS + 1);
    expect(fireKey(chartEl, key).defaultPrevented).toBe(true);
    expect(w.alerts.list().map(item => item.id)).toEqual([kept.id]);
    vi.advanceTimersByTime(SAVE_DEBOUNCE_MS + 1);
    const saved = JSON.parse(store.get(`${STORAGE_PREFIX}default:${STATE_KEY}`)!);
    expect(saved.chart.alerts.alerts.map((item: { id: string }) => item.id)).toEqual([kept.id]);
  });

  it.each(['input', 'textarea', 'select', 'editable'])('leaves %s editing alone', kind => {
    const { w, doc, root, alert } = make();
    const input = doc.createElement(kind === 'editable' ? 'div' : kind);
    if (kind === 'editable') input.setAttribute('contenteditable', 'true');
    root.appendChild(input);
    for (const key of ['Delete', 'Backspace']) expect(fireKey(input, key).defaultPrevented).toBe(false);
    expect(w.alerts.list().map(item => item.id)).toEqual([alert.id]);
  });

  it('leaves modal controls, modified keys and events outside the widget alone', () => {
    const { w, doc, root, chartEl, alert } = make();
    for (const modifier of ['ctrlKey', 'metaKey', 'altKey', 'shiftKey']) {
      for (const key of ['Delete', 'Backspace']) expect(fireKey(chartEl, key, { [modifier]: true }).defaultPrevented).toBe(false);
    }
    w.openAlerts();
    for (const key of ['Delete', 'Backspace']) expect(fireKey(chartEl, key).defaultPrevented).toBe(false);
    w.context.overlays.closeAll();
    fire(root, 'pointerleave');
    doc.body.focus();
    for (const key of ['Delete', 'Backspace']) expect(fireKey(doc.body, key).defaultPrevented).toBe(false);
    expect(w.alerts.list().map(item => item.id)).toEqual([alert.id]);
  });
});
