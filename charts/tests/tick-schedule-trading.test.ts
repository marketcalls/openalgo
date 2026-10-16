/**
 * A price-dependent tick schedule reaching every path that turns a price into
 * an order: typed validation, the order engine's place and drag-modify, and
 * the data-driven trading layer's order and bracket drags.
 */
import { describe, expect, it, vi } from 'vitest';
import { TickSchedule } from '../src/feed/tick-schedule';
import { validateOrder, validatePrice, type OrderConstraints } from '../src/trade/validation';
import { OrderEngine } from '../src/trade/order-engine';
import { FakeBroker } from '../src/trade/fake-broker';
import { TradingController, type TradingHost } from '../src/core/trading-controller';
import { PriceLine } from '../src/primitives/price-line';
import type { IPrimitive } from '../src/primitives/primitive';
import { roundToTick } from '../src/helpers/math';

// Synthetic rules: 0.01 below 10, 0.05 from 10, 0.10 from 100.
const TICKS = new TickSchedule([{ tick: 0.01 }, { from: 10, tick: 0.05 }, { from: 100, tick: 0.1 }]);
const SCHEDULED: OrderConstraints = { tickSize: TICKS.minMove, tickSchedule: TICKS };

describe('validatePrice with a tick schedule', () => {
  it('snaps a typed price to the band it lands in, crossing boundaries exactly', () => {
    expect(validatePrice(9.994, SCHEDULED)).toEqual({ ok: true, price: 9.99 });
    expect(validatePrice(9.996, SCHEDULED)).toEqual({ ok: true, price: 10 });
    expect(validatePrice(10, SCHEDULED)).toEqual({ ok: true, price: 10 });
    expect(validatePrice(10.03, SCHEDULED)).toEqual({ ok: true, price: 10.05 });
    expect(validatePrice(10.025, SCHEDULED)).toEqual({ ok: true, price: 10.05 });
    expect(validatePrice(99.98, SCHEDULED)).toEqual({ ok: true, price: 100 });
    expect(validatePrice(100.06, SCHEDULED)).toEqual({ ok: true, price: 100.1 });
  });

  it('ignores tickSize for snapping once a schedule is present', () => {
    // A stale 0.05 tickSize would move 9.99 to 10.00; the schedule keeps it.
    expect(validatePrice(9.99, { tickSize: 0.05, tickSchedule: TICKS }).price).toBe(9.99);
  });

  it('checks price limits after snapping, on either side of a boundary', () => {
    const limited: OrderConstraints = { ...SCHEDULED, priceBand: { lower: 9.97, upper: 10.04 } };
    expect(validatePrice(10.02, limited)).toEqual({ ok: true, price: 10 });
    // 10.03 is inside the limits as typed but snaps to 10.05, which is not.
    expect(validatePrice(10.03, limited)).toMatchObject({ ok: false, code: 'PRICE_OUT_OF_BAND' });
    expect(validatePrice(10.03, limited).reason).toBe('price 10.05 outside band 9.97 to 10.04');
    expect(validatePrice(9.965, limited)).toEqual({ ok: true, price: 9.97 });
    expect(validatePrice(9.964, limited)).toMatchObject({ ok: false, code: 'PRICE_OUT_OF_BAND' });
  });

  it('handles zero and negative prices, leaving the floor to the price limits', () => {
    expect(validatePrice(0, SCHEDULED)).toEqual({ ok: true, price: 0 });
    expect(Object.is(validatePrice(-0.004, SCHEDULED).price, 0)).toBe(true);
    expect(validatePrice(-0.013, SCHEDULED)).toEqual({ ok: true, price: -0.01 });
    const positive: OrderConstraints = { ...SCHEDULED, priceBand: { lower: 0, upper: 1000 } };
    expect(validatePrice(-0.004, positive)).toEqual({ ok: true, price: 0 });
    expect(validatePrice(-0.013, positive)).toMatchObject({ ok: false, code: 'PRICE_OUT_OF_BAND' });
    expect(validatePrice(NaN, SCHEDULED)).toMatchObject({ ok: false, code: 'PRICE_INVALID' });
  });

  it('keeps constant-tick snapping byte-identical when no schedule is given', () => {
    for (const price of [100.07, 2950.03, 0.123456789, -1.03, 10.025]) {
      expect(validatePrice(price, { tickSize: 0.05 }).price).toBe(roundToTick(price, 0.05));
    }
  });

  it('treats a null schedule as none, as chart.trading.setTickSchedule(null) does', async () => {
    const none: OrderConstraints = { tickSize: 0.05, tickSchedule: null };
    for (const price of [100.07, 10.025, -1.03]) {
      expect(validatePrice(price, none).price).toBe(roundToTick(price, 0.05));
    }
    const { broker, eng } = engine(none);
    await eng.placeOrder({ symbol: 'X', side: 'BUY', type: 'LIMIT', qty: 1, price: 100.07 });
    expect(broker.orders()[0].price).toBe(roundToTick(100.07, 0.05));
  });

  it('refuses a schedule that was never validated, naming the fix', () => {
    const raw = { tickSize: 0.01, tickSchedule: [{ tick: 0.01 }] } as unknown as OrderConstraints;
    expect(() => validatePrice(10, raw)).toThrow(/new TickSchedule/);
    expect(() => validateOrder(10, 1, raw)).toThrow(TypeError);
  });
});

function engine(constraints: OrderConstraints = SCHEDULED) {
  const broker = new FakeBroker();
  const errors: string[] = [];
  const clock = { t: 0 };
  let n = 0;
  const eng = new OrderEngine({
    feed: broker, constraints, armed: true, minModifyIntervalMs: 0,
    now: () => clock.t, idGen: () => `c${++n}`, onValidationError: reason => errors.push(reason),
  });
  return { broker, eng, errors };
}

describe('OrderEngine with a tick schedule', () => {
  it('snaps typed limit and trigger prices on the typed-input path', async () => {
    const { broker, eng } = engine();
    const limit = await eng.placeOrder({ symbol: 'X', side: 'BUY', type: 'LIMIT', qty: 1, price: 10.03 });
    expect(limit.ok).toBe(true);
    expect(broker.orders()[0].price).toBe(10.05);
    await eng.placeOrder({ symbol: 'X', side: 'SELL', type: 'SL', qty: 1, price: 9.994, triggerPrice: 10.021 });
    expect(broker.orders()[1]).toMatchObject({ price: 9.99, triggerPrice: 10 });
  });

  it('snaps a dragged level across a boundary on the drag path', async () => {
    const { broker, eng, errors } = engine();
    const placed = await eng.placeOrder({ symbol: 'X', side: 'BUY', type: 'LIMIT', qty: 1, price: 9.98 });
    eng.requestModify(placed.clientId!, 10.07);
    await eng.commitModify(placed.clientId!);
    expect(broker.orders()[0].price).toBe(10.05);
    eng.requestModify(placed.clientId!, 9.996);
    await eng.commitModify(placed.clientId!);
    expect(broker.orders()[0].price).toBe(10);
    eng.requestModify(placed.clientId!, 9.9449);
    await eng.commitModify(placed.clientId!);
    expect(broker.orders()[0].price).toBe(9.94);
    expect(errors).toEqual([]);
  });

  it('carries a stop-limit offset across a boundary and snaps the trigger in its own band', async () => {
    const { broker, eng } = engine();
    const placed = await eng.placeOrder({ symbol: 'X', side: 'SELL', type: 'SL', qty: 1, price: 9.95, triggerPrice: 9.98 });
    eng.requestModify(placed.clientId!, 10.4);
    await eng.commitModify(placed.clientId!);
    // 10.40 + 0.03 = 10.43, which the 0.05 band moves to 10.45.
    expect(broker.orders()[0]).toMatchObject({ price: 10.4, triggerPrice: 10.45 });
  });

  it('refuses a drag that snaps outside the price limits and sends nothing', async () => {
    const { broker, eng, errors } = engine({ ...SCHEDULED, priceBand: { lower: 9, upper: 10.04 } });
    const placed = await eng.placeOrder({ symbol: 'X', side: 'BUY', type: 'LIMIT', qty: 1, price: 9.98 });
    eng.requestModify(placed.clientId!, 10.03);
    await eng.commitModify(placed.clientId!);
    expect(broker.orders()[0].price).toBe(9.98);
    expect(errors).toEqual(['price 10.05 outside band 9 to 10.04']);
  });
});

function tradingHost() {
  const added: IPrimitive[] = [];
  let onDrag: (id: string, price: number) => void = () => {};
  let onDragEnd: (id: string, price: number) => void = () => {};
  const host: TradingHost = {
    addPrimitive: primitive => { added.push(primitive); },
    removePrimitive: primitive => { const index = added.indexOf(primitive); if (index >= 0) added.splice(index, 1); },
    subscribeClick: () => {},
    subscribeDrag: (drag, end) => { onDrag = drag; if (end) onDragEnd = end; },
  };
  const line = (): PriceLine => added.find((p): p is PriceLine => p instanceof PriceLine)!;
  return { host, line, drag: (id: string, p: number) => onDrag(id, p), end: (id: string, p: number) => onDragEnd(id, p) };
}

describe('chart trading drags with a tick schedule', () => {
  it('previews and emits the snapped price of a dragged order line', () => {
    const h = tradingHost();
    const trading = new TradingController(h.host);
    const modify = vi.fn();
    trading.on('trading:order_modify', modify);
    trading.setTickSchedule(TICKS);
    trading.setOrders([{ id: 'o1', type: 'limit', side: 'buy', price: 9.98, size: 1 }]);
    h.drag('ord:o1', 10.031);
    expect(h.line().options().price).toBe(10.05);
    h.drag('ord:o1', 9.9912);
    expect(h.line().options().price).toBe(9.99);
    h.end('ord:o1', 100.061);
    expect(modify).toHaveBeenCalledWith({ orderId: 'o1', newPrice: 100.1, previousPrice: 9.98 });
    expect(trading.getOrders()[0].price).toBe(100.1);
  });

  it('snaps a dragged bracket leg in the band it is released in', () => {
    const h = tradingHost();
    const trading = new TradingController(h.host);
    const bracket = vi.fn();
    trading.on('trading:bracket_modify', bracket);
    trading.setTickSchedule(TICKS);
    trading.setOrders([{ id: 'sl', type: 'stop', side: 'sell', price: 10.5, size: 1, parentId: 'p1', bracketRole: 'sl' }]);
    h.drag('ord:sl', 9.9951);
    h.end('ord:sl', 9.9951);
    expect(bracket).toHaveBeenCalledWith({ parentId: 'p1', bracketRole: 'sl', newPrice: 10 });
  });

  it('refuses a band list when it is set, not with a pointer error on the first drag', () => {
    const h = tradingHost();
    const trading = new TradingController(h.host);
    const modify = vi.fn();
    trading.on('trading:order_modify', modify);
    trading.setOrders([{ id: 'o1', type: 'limit', side: 'buy', price: 9.98, size: 1 }]);
    trading.setTickSchedule(TICKS);
    for (const bad of [[{ tick: 0.05 }], { tick: 0.05 }, 0.05, 'ticks']) {
      expect(() => trading.setTickSchedule(bad as unknown as TickSchedule)).toThrow(TypeError);
      expect(() => trading.setTickSchedule(bad as unknown as TickSchedule)).toThrow(/new TickSchedule\(bands\)/);
    }
    // A refused value leaves the schedule that was in force.
    h.end('ord:o1', 10.031);
    // A plain-JS host that clears with undefined gets the same as null.
    trading.setTickSchedule(undefined as unknown as null);
    h.end('ord:o1', 10.0312);
    expect(modify.mock.calls.map(([event]) => event.newPrice)).toEqual([10.05, 10.0312]);
  });

  it('keeps raw pointer prices without a schedule and after clearing one', () => {
    const h = tradingHost();
    const trading = new TradingController(h.host);
    const modify = vi.fn();
    trading.on('trading:order_modify', modify);
    trading.setOrders([{ id: 'o1', type: 'limit', side: 'buy', price: 9.98, size: 1 }]);
    h.drag('ord:o1', 10.031);
    expect(h.line().options().price).toBe(10.031);
    h.end('ord:o1', 10.031);
    trading.setTickSchedule(TICKS);
    trading.setTickSchedule(null);
    h.end('ord:o1', 10.0312);
    expect(modify.mock.calls.map(([event]) => event.newPrice)).toEqual([10.031, 10.0312]);
  });
});
