import { describe, it, expect } from 'vitest';
import { transition, canTransition, isTerminal } from '../src/trade/order-state-machine';
import { validateOrder, type OrderConstraints } from '../src/trade/validation';
import { OrderEngine, type OrderEngineOptions, type OrderFeed } from '../src/trade/order-engine';
import { FakeBroker } from '../src/trade/fake-broker';

const C: OrderConstraints = { tickSize: 0.05, priceBand: { lower: 90, upper: 110 }, freezeQty: 1000 };

function engine(opts: Partial<OrderEngineOptions> = {}, broker = new FakeBroker()) {
  const clock = { t: 0 };
  let n = 0;
  return {
    broker,
    eng: new OrderEngine({ feed: broker, constraints: C, armed: true, now: () => clock.t, idGen: () => `c${++n}`, ...opts }),
    tick: (ms: number) => { clock.t += ms; },
  };
}

describe('order state machine', () => {
  it('allows valid transitions and blocks invalid ones', () => {
    expect(transition('pending_place', 'ack')).toBe('working');
    expect(transition('working', 'fill')).toBe('filled');
    expect(transition('working', 'submitCancel')).toBe('cancel_pending');
    expect(transition('cancel_pending', 'cancelled')).toBe('cancelled');
    expect(canTransition('filled', 'fill')).toBe(false); // terminal
    expect(transition('filled', 'submitModify')).toBe('filled'); // no-op
  });
  it('identifies terminal states', () => {
    for (const s of ['filled', 'cancelled', 'rejected', 'stale'] as const) expect(isTerminal(s)).toBe(true);
    for (const s of ['working', 'pending_place', 'modify_pending'] as const) expect(isTerminal(s)).toBe(false);
  });
  it('reconnect from non-terminal goes stale', () => {
    expect(transition('working', 'reconnectAbsent')).toBe('stale');
  });
});

describe('validation', () => {
  it('snaps to tick size', () => {
    expect(validateOrder(100.07, 10, C).price).toBeCloseTo(100.05);
  });
  it('rejects out-of-band price and over-freeze qty', () => {
    expect(validateOrder(200, 10, C).ok).toBe(false);
    expect(validateOrder(100, 5000, C).ok).toBe(false);
    expect(validateOrder(100, 0, C).ok).toBe(false);
  });
});

describe('OrderEngine place', () => {
  it('places and reaches working on ack', async () => {
    const { eng } = engine();
    const r = await eng.placeOrder({ symbol: 'X', side: 'BUY', type: 'LIMIT', qty: 10, price: 100.07 });
    expect(r.ok).toBe(true);
    expect(r.state).toBe('working');
  });

  it('rejects an out-of-band order before sending', async () => {
    const { eng, broker } = engine();
    const r = await eng.placeOrder({ symbol: 'X', side: 'BUY', type: 'LIMIT', qty: 10, price: 999 });
    expect(r.ok).toBe(false);
    expect(broker.orders()).toHaveLength(0); // never sent
  });

  it('reaches rejected when the broker rejects', async () => {
    const broker = new FakeBroker();
    broker.rejectNextPlace = 'risk limit';
    const { eng } = engine({}, broker);
    const r = await eng.placeOrder({ symbol: 'X', side: 'BUY', type: 'LIMIT', qty: 10, price: 100 });
    expect(r.ok).toBe(false);
    expect(r.state).toBe('rejected');
  });

  it('is idempotent on a repeated clientToken', async () => {
    const { eng, broker } = engine();
    await eng.placeOrder({ symbol: 'X', side: 'BUY', type: 'LIMIT', qty: 10, price: 100, clientToken: 'tok1' });
    const r2 = await eng.placeOrder({ symbol: 'X', side: 'BUY', type: 'LIMIT', qty: 10, price: 100, clientToken: 'tok1' });
    expect(r2.ok).toBe(false);
    expect(broker.orders()).toHaveLength(1); // not double-sent
  });

  it('confirm gate blocks unconfirmed orders (not armed)', async () => {
    const broker = new FakeBroker();
    const eng = new OrderEngine({ feed: broker, constraints: C, armed: false, gate: () => false });
    const r = await eng.placeOrder({ symbol: 'X', side: 'BUY', type: 'LIMIT', qty: 10, price: 100 });
    expect(r.ok).toBe(false);
    expect(broker.orders()).toHaveLength(0);
  });

  it('carries analyzer mode to the feed', async () => {
    let seenMode = '';
    const feed: OrderFeed = {
      place: async (req) => { seenMode = req.mode; return { orderId: 'B1' }; },
      modify: async () => {},
      cancel: async () => {},
    };
    const eng = new OrderEngine({ feed, constraints: C, armed: true, mode: 'analyzer' });
    await eng.placeOrder({ symbol: 'X', side: 'BUY', type: 'MARKET', qty: 10 });
    expect(seenMode).toBe('analyzer');
    expect(eng.mode).toBe('analyzer');
  });
});

describe('OrderEngine modify (rate-limited drag)', () => {
  it('throttles intermediate modifies, commits the final', async () => {
    const { eng, broker, tick } = engine({ minModifyIntervalMs: 100 });
    const r = await eng.placeOrder({ symbol: 'X', side: 'BUY', type: 'LIMIT', qty: 10, price: 100 });
    const id = r.clientId!;
    const brokerId = broker.orders()[0].id;
    eng.requestModify(id, 101); // first: sends immediately (last=-inf)
    eng.requestModify(id, 102); // within interval: coalesced
    eng.requestModify(id, 103);
    await Promise.resolve();
    expect(broker.orders()[0].price).toBeCloseTo(101); // only the first went
    tick(200);
    await eng.commitModify(id); // forces the latest pending
    expect(broker.orders().find((o) => o.id === brokerId)!.price).toBeCloseTo(103);
  });
});

describe('OrderEngine cancel + OCO + reconnect', () => {
  it('cancels to terminal', async () => {
    const { eng, broker } = engine();
    const r = await eng.placeOrder({ symbol: 'X', side: 'BUY', type: 'LIMIT', qty: 10, price: 100 });
    await eng.cancelOrder(r.clientId!);
    expect(eng.state(r.clientId!)).toBe('cancelled');
    expect(broker.orders()).toHaveLength(0);
  });

  it('OCO: filling one cancels the peer', async () => {
    const { eng, broker } = engine();
    const sl = await eng.placeOrder({ symbol: 'X', side: 'SELL', type: 'SL-M', qty: 10, price: 95 });
    const tp = await eng.placeOrder({ symbol: 'X', side: 'SELL', type: 'LIMIT', qty: 10, price: 105 });
    eng.linkOco(sl.clientId!, tp.clientId!);
    const tpBrokerId = broker.orders().find((o) => o.price === 105)!.id;
    eng.onFill(tpBrokerId, true); // TP fills
    await Promise.resolve();
    expect(eng.state(tp.clientId!)).toBe('filled');
    expect(eng.state(sl.clientId!)).toBe('cancelled'); // peer auto-cancelled
  });

  it('reconnect marks absent orders stale', async () => {
    const { eng, broker } = engine();
    const r = await eng.placeOrder({ symbol: 'X', side: 'BUY', type: 'LIMIT', qty: 10, price: 100 });
    expect(eng.state(r.clientId!)).toBe('working');
    eng.onReconnect(new Set<string>()); // fresh book has nothing
    expect(eng.state(r.clientId!)).toBe('stale');
    void broker;
  });
});
