/**
 * Interactive value capture (src/input/pick.ts). A settings input that names a
 * price or a time is the host's to render, but the value can come from pointing
 * at the chart, and only the engine knows what is under the cursor.
 *
 * The unit half runs against a bus that mirrors `Chart.emit`; the chart half
 * proves a real pointer gesture answers a pick, and that panning does not.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { beginPick, type PickHost } from '../src/input/pick';
import { Chart } from '../src/core/chart';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';

interface Rig extends PickHost {
  /** Dispatch a plot click, the way the chart's pointer path would. */
  click(price: number | null, time: number): void;
  events: { event: string; payload: unknown }[];
}

/** Bars at 1000, 1060, 1120, so index i is time 1000 + i * 60. */
function rig(): Rig {
  const listeners = new Map<string, ((p: unknown) => void)[]>();
  const events: { event: string; payload: unknown }[] = [];
  const times = [1000, 1060, 1120];
  const host: Rig = {
    on: (event, cb) => {
      const list = listeners.get(event) ?? [];
      list.push(cb);
      listeners.set(event, list);
      return () => {
        const i = list.indexOf(cb);
        if (i >= 0) list.splice(i, 1);
      };
    },
    // Copy on dispatch, as the chart's bus does: a listener that unsubscribes
    // itself mid-dispatch must not shift the list under the loop.
    emit: (event, payload) => {
      events.push({ event, payload });
      for (const cb of [...(listeners.get(event) ?? [])]) cb(payload);
    },
    dataLayer: {
      timeToIndexFloat: (t: number) => (t - 1000) / 60,
      indexToTime: (i: number) => times[i],
    },
    click: (price, time) => host.emit('click', { price, time }),
    events,
  };
  return host;
}

const kinds = (r: Rig): string[] => r.events.map((e) => e.event);

describe('beginPick', () => {
  it('reports its own active lifetime before and after delivery or cancellation', () => {
    const r = rig(), seen = vi.fn();
    const delivered = beginPick(r, 'price', seen);
    expect(delivered.active()).toBe(true);
    r.click(null, 1060);
    expect(delivered.active()).toBe(true);
    r.click(12, 1060);
    expect(delivered.active()).toBe(false);
    expect(seen).toHaveBeenCalledExactlyOnceWith(12);
    const cancelled = beginPick(r, 'time', seen);
    expect(cancelled.active()).toBe(true);
    cancelled();
    expect(cancelled.active()).toBe(false);
    expect(delivered.active()).toBe(false);
  });

  it('reports a displaced invocation inactive while its same-kind replacement stays active', () => {
    const r = rig(), ignored = vi.fn(), selected = vi.fn();
    const first = beginPick(r, 'price', ignored);
    let newest: ReturnType<typeof beginPick> | undefined;
    const off = r.on('pick:end', () => {
      off(); newest = beginPick(r, 'price', selected);
    });
    const displaced = beginPick(r, 'price', ignored);
    expect(first.active()).toBe(false);
    expect(displaced.active()).toBe(false);
    expect(newest?.active()).toBe(true);
    displaced();
    r.click(24, 1060);
    expect(selected).toHaveBeenCalledExactlyOnceWith(24);
    expect(ignored).not.toHaveBeenCalled();
    expect(newest?.active()).toBe(false);
  });

  it('reports synchronous cancellation during its start notification', () => {
    const r = rig(), selected = vi.fn();
    r.on('pick:start', () => r.emit('data:context', {}));
    const handle = beginPick(r, 'price', selected);
    expect(handle.active()).toBe(false);
    r.click(12, 1060);
    expect(selected).not.toHaveBeenCalled();
  });

  it('answers with the price under the click and disarms itself', () => {
    const r = rig();
    const seen: number[] = [];
    beginPick(r, 'price', (v) => seen.push(v));
    r.click(250.5, 1060);
    r.click(999, 1120);
    expect(seen).toEqual([250.5]);
  });

  it('answers with a price of zero', () => {
    const r = rig();
    let seen: number | null = null;
    beginPick(r, 'price', (v) => { seen = v; });
    r.click(0, 1060);
    expect(seen).toBe(0);
  });

  it('stays armed when the chart could not resolve the click', () => {
    // No pane under the pointer, or no bars loaded. Answering with a bogus
    // number would be worse than making the user click again.
    const r = rig();
    const seen: number[] = [];
    beginPick(r, 'price', (v) => seen.push(v));
    r.click(null, 1060);
    expect(seen).toEqual([]);
    r.click(120, 1060);
    expect(seen).toEqual([120]);
  });

  it('snaps a time to the bar the click landed on', () => {
    // The axis is gapless, so a raw click time is interpolated between bars and
    // matches no bar at all; anything anchored to it would never line up.
    const r = rig();
    const seen: number[] = [];
    beginPick(r, 'time', (v) => seen.push(v));
    r.click(100, 1035);
    beginPick(r, 'time', (v) => seen.push(v));
    r.click(100, 1010);
    expect(seen).toEqual([1060, 1000]);
  });

  it('keeps a projected time from a click past the last bar', () => {
    const r = rig();
    let seen = 0;
    beginPick(r, 'time', (v) => { seen = v; });
    r.click(100, 1300); // in the empty space to the right of the data
    expect(seen).toBe(1300);
  });

  it('brackets the pick with pick:start and pick:end', () => {
    const r = rig();
    const order: string[] = [];
    r.on('pick:end', () => order.push('event'));
    beginPick(r, 'price', () => order.push('callback'));
    r.click(140, 1060);
    expect(kinds(r)).toEqual(['pick:start', 'click', 'pick:end']);
    expect(r.events[0].payload).toEqual({ kind: 'price' });
    expect(r.events[2].payload).toEqual({ kind: 'price', value: 140 });
    // The host learns the pick is over before the caller acts on the value, so
    // a cursor or hint is already down by the time a dialog opens.
    expect(order).toEqual(['event', 'callback']);
  });

  it('cancels without calling back, idempotently', () => {
    const r = rig();
    const seen: number[] = [];
    const cancel = beginPick(r, 'price', (v) => seen.push(v));
    cancel();
    cancel();
    r.click(140, 1060);
    expect(seen).toEqual([]);
    expect(r.events.filter((e) => e.event === 'pick:end')).toEqual([
      { event: 'pick:end', payload: { kind: 'price', value: null } },
    ]);
  });

  it('lets a second pick take over from the first', () => {
    // One pick per chart: two listeners would both answer the same click.
    const r = rig();
    const seen: string[] = [];
    beginPick(r, 'price', () => seen.push('first'));
    beginPick(r, 'price', () => seen.push('second'));
    r.click(140, 1060);
    expect(seen).toEqual(['second']);
    expect(r.events.filter((e) => e.event === 'pick:end')).toHaveLength(2);
  });

  it('lets the callback arm the next pick', () => {
    const r = rig();
    const seen: number[] = [];
    beginPick(r, 'price', (v) => {
      seen.push(v);
      if (seen.length === 1) beginPick(r, 'price', (w) => seen.push(w));
    });
    r.click(10, 1060);
    r.click(20, 1060);
    expect(seen).toEqual([10, 20]);
  });

  it('keeps two charts independent', () => {
    const a = rig();
    const b = rig();
    const seen: string[] = [];
    beginPick(a, 'price', () => seen.push('a'));
    beginPick(b, 'price', () => seen.push('b'));
    a.click(1, 1060);
    expect(seen).toEqual(['a']);
    b.click(1, 1060);
    expect(seen).toEqual(['a', 'b']);
  });
});

describe('on a real chart', () => {
  afterEach(() => vi.unstubAllGlobals());

  function mount(): { chart: Chart; el: FakeElement } {
    vi.stubGlobal('window', {});
    vi.stubGlobal('requestAnimationFrame', () => 0);
    vi.stubGlobal('cancelAnimationFrame', () => {});
    const doc = fakeDocument();
    const container = doc.createElement('div') as unknown as Record<string, unknown>;
    container.clientWidth = 800;
    container.clientHeight = 600;
    container.ownerDocument = doc;
    container.contains = () => false;
    container.tabIndex = 0;
    const chart = new Chart(container as unknown as HTMLElement, {
      document: doc, pixelRatio: () => 1,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    });
    chart.addSeries('candlestick').setData([
      { time: 1000, open: 10, high: 12, low: 8, close: 11 },
      { time: 1060, open: 11, high: 13, low: 9, close: 12 },
      { time: 1120, open: 12, high: 14, low: 10, close: 13 },
    ]);
    return { chart, el: container as unknown as FakeElement };
  }

  const tap = (el: FakeElement, x: number, y: number): void => {
    el.dispatch('pointerdown', pointer('down', x, y));
    el.dispatch('pointerup', pointer('up', x, y));
  };

  it('resolves the next click on the plot to the price under it', () => {
    const { chart, el } = mount();
    const clicked: number[] = [];
    chart.on('click', (p) => clicked.push((p as { price: number }).price));
    let picked: number | null = null;
    beginPick(chart, 'price', (v) => { picked = v; });
    tap(el, 200, 150);
    expect(picked).toBe(clicked[0]);
    expect(Number.isFinite(picked as unknown as number)).toBe(true);
  });

  it('resolves a time to a bar that is actually on the chart', () => {
    const { chart, el } = mount();
    let picked = 0;
    beginPick(chart, 'time', (v) => { picked = v; });
    tap(el, 300, 200);
    expect([1000, 1060, 1120]).toContain(picked);
  });

  it('lets the user pan to the bar they meant before answering', () => {
    // Placement mode is deliberately not armed, so a drag pans and emits no
    // click: scrolling back through history cannot answer the pick by accident.
    const { chart, el } = mount();
    let picked: number | null = null;
    beginPick(chart, 'price', (v) => { picked = v; });
    el.dispatch('pointerdown', pointer('down', 400, 300));
    for (let i = 1; i <= 6; i++) el.dispatch('pointermove', pointer('move', 400 - i * 40, 300));
    el.dispatch('pointerup', pointer('up', 160, 300));
    expect(picked).toBeNull();
    tap(el, 200, 150);
    expect(picked).not.toBeNull();
  });
});
