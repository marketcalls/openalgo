/**
 * `subscribeClick`, `subscribeDrag` and `subscribeCrosshairMove` take several
 * subscribers and hand each one its own unsubscribe.
 *
 * Each used to be one slot. The trade layer claims the click and drag slots
 * when `chart.trading` is first read, so a host that subscribed afterwards
 * replaced it: the cancel box on an order line stopped emitting
 * `trading:order_cancel`, and a dragged order line no longer armed or emitted
 * `trading:order_modify`. A host that subscribed first lost its own callback
 * the moment the trade layer was built. The reference host lost its volume
 * legend eye the same way, to a second subscription of its own.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { Chart } from '../src/core/chart';
import type { CrosshairMoveEvent } from '../src/core/chart-types';
import type { TradingOrder } from '../src/core/trading-controller';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';

// The chart only wires its pointer handlers when it can see a window.
beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

/** A seeded random walk, so the fixture looks like a traded stock. */
function walk(n = 80): Bar[] {
  let seed = 7;
  const rand = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  const out: Bar[] = [];
  let close = 1500;
  for (let i = 0; i < n; i++) {
    const open = close;
    close = Math.round((open + (rand() - 0.5) * 12) * 100) / 100;
    const high = Math.max(open, close) + rand() * 4, low = Math.min(open, close) - rand() * 4;
    out.push({ time: 1735699500 + i * 300, open, high, low, close, volume: 1000 + Math.round(rand() * 900) });
  }
  return out;
}

function makeChart(): { chart: Chart; el: FakeElement } {
  const el = fakeDocument().createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document: fakeDocument(), pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(walk());
  return { chart, el };
}

interface HitProbe {
  _panes: { hitTestPrimitives(x: number, y: number, rc: unknown, skip: unknown): { externalId: string } | null }[];
  _renderContext(pane: number): unknown;
}

/** The first plot x where the primary pane reports `id` at price `price`. */
function xOf(chart: Chart, id: string, price: number): { x: number; y: number } {
  const probe = chart as unknown as HitProbe;
  const y = chart.priceToCoordinate(price) as number;
  for (let x = 0; x < 800; x++) {
    if (probe._panes[0]!.hitTestPrimitives(x, y, probe._renderContext(0), null)?.externalId === id) return { x, y };
  }
  throw new Error(`nothing hit-tests as ${id}`);
}

function click(el: FakeElement, at: { x: number; y: number }): void {
  el.dispatch('pointerdown', pointer('down', at.x, at.y));
  el.dispatch('pointerup', pointer('up', at.x, at.y));
}

function drag(el: FakeElement, at: { x: number; y: number }, dy: number): void {
  el.dispatch('pointerdown', pointer('down', at.x, at.y));
  el.dispatch('pointermove', pointer('move', at.x, at.y + dy / 2));
  el.dispatch('pointermove', pointer('move', at.x, at.y + dy));
  el.dispatch('pointerup', pointer('up', at.x, at.y + dy));
}

/** A fresh order each time: the trade layer keeps the object and moves its price on a drag. */
const PRICE = 1490;
const order = (): TradingOrder => ({ id: 'o1', side: 'buy', type: 'limit', price: PRICE, size: 25 });

describe('host subscriptions beside the trade layer', () => {
  it('a host click subscription made after the trade layer leaves order cancel working', () => {
    const { chart, el } = makeChart();
    chart.trading.setOrders([order()]);
    const cancels: unknown[] = [];
    chart.on('trading:order_cancel', (e) => cancels.push(e));
    const hostClicks: string[] = [];
    chart.subscribeClick((id) => hostClicks.push(id));

    click(el, xOf(chart, 'ord:o1::close', PRICE));

    expect(cancels).toEqual([{ orderId: 'o1' }]);
    expect(hostClicks).toEqual(['ord:o1::close']);
  });

  it('a host drag subscription made after the trade layer leaves order modify working', () => {
    const { chart, el } = makeChart();
    chart.trading.setOrders([order()]);
    const modifies: { orderId: string; newPrice: number; previousPrice: number }[] = [];
    chart.on('trading:order_modify', (e) => modifies.push(e));
    const hostMoves: string[] = [], hostEnds: string[] = [];
    chart.subscribeDrag((id) => hostMoves.push(id), (id) => hostEnds.push(id));

    // The line away from its pill group: that part of the line drags.
    const at = { x: 60, y: chart.priceToCoordinate(PRICE) as number };
    drag(el, at, 40);

    expect(modifies).toHaveLength(1);
    expect(modifies[0]!.orderId).toBe('o1');
    expect(modifies[0]!.previousPrice).toBe(PRICE);
    expect(modifies[0]!.newPrice).toBeLessThan(PRICE);
    expect(hostMoves.length).toBeGreaterThan(0);
    expect(hostEnds).toEqual(['ord:o1']);
  });

  it('a host that subscribed before the trade layer was built keeps its callbacks', () => {
    const { chart, el } = makeChart();
    const hostClicks: string[] = [], hostEnds: string[] = [];
    chart.subscribeClick((id) => hostClicks.push(id));
    chart.subscribeDrag(() => {}, (id) => hostEnds.push(id));
    chart.trading.setOrders([order()]);
    const cancels: unknown[] = [];
    chart.on('trading:order_cancel', (e) => cancels.push(e));

    click(el, xOf(chart, 'ord:o1::close', PRICE));
    drag(el, { x: 60, y: chart.priceToCoordinate(PRICE) as number }, 30);

    expect(cancels).toEqual([{ orderId: 'o1' }]);
    expect(hostClicks).toEqual(['ord:o1::close']);
    expect(hostEnds).toEqual(['ord:o1']);
  });

  it('two host click subscriptions both hear a click, and each unsubscribes alone', () => {
    const { chart, el } = makeChart();
    chart.trading.setOrders([order()]);
    const a: string[] = [], b: string[] = [];
    const offA = chart.subscribeClick((id) => a.push(id));
    chart.subscribeClick((id) => b.push(id));
    const at = xOf(chart, 'ord:o1::close', PRICE);

    click(el, at);
    offA();
    click(el, at);

    expect(a).toEqual(['ord:o1::close']);
    expect(b).toEqual(['ord:o1::close', 'ord:o1::close']);
  });

  it('a throwing host callback does not stop the trade layer', () => {
    const { chart, el } = makeChart();
    chart.subscribeClick(() => { throw new Error('host bug'); });
    chart.trading.setOrders([order()]);
    const cancels: unknown[] = [];
    chart.on('trading:order_cancel', (e) => cancels.push(e));

    expect(() => click(el, xOf(chart, 'ord:o1::close', PRICE))).not.toThrow();
    expect(cancels).toEqual([{ orderId: 'o1' }]);
  });

  it('an unsubscribed drag leaves a plain price line to pan the chart again', () => {
    const { chart, el } = makeChart();
    const offDrag = chart.subscribeDrag(() => {});
    const line = chart.addPriceLine({ price: 1480, color: '#4f8cff', lineWidth: 1, dashed: false, id: 'level', cursor: 'ns-resize' });
    expect(line).toBeDefined();
    const ends: string[] = [];
    chart.on('drag:end', (e) => ends.push(e.id));
    const at = { x: 60, y: chart.priceToCoordinate(1480) as number };

    drag(el, at, 20);
    offDrag();
    drag(el, at, 20);

    expect(ends).toEqual(['level']);
  });

  it('two crosshair subscriptions both follow the pointer, and each unsubscribes alone', () => {
    const { chart, el } = makeChart();
    const a: (number | null)[] = [], b: (number | null)[] = [];
    const offA = chart.subscribeCrosshairMove((e: CrosshairMoveEvent) => a.push(e.index));
    chart.subscribeCrosshairMove((e: CrosshairMoveEvent) => b.push(e.index));

    el.dispatch('pointermove', pointer('move', 300, 200, { buttons: 0 }));
    offA();
    el.dispatch('pointermove', pointer('move', 340, 200, { buttons: 0 }));

    expect(a).toHaveLength(1);
    expect(b).toHaveLength(2);
    expect(b[0]).toBe(a[0]);
  });
});
