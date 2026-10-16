/**
 * Hardening regression tests for the order engine write path.
 *
 * Every block here fails against the pre-hardening engine. Where a test also
 * pins behaviour that must NOT change (a place still reporting `working`, a
 * cancel still reporting `cancelled`), that assertion sits inside a block whose
 * other assertions fail on the old code, so nothing in this file is vacuous.
 */
import { describe, it, expect } from 'vitest';
import { OrderEngine, type OrderEngineOptions, type OrderFeed, type PlaceRequest, type TradeMode } from '../src/trade/order-engine';
import type { OrderConstraints } from '../src/trade/validation';
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

const limit = (over: Partial<PlaceRequest> = {}): PlaceRequest =>
  ({ symbol: 'X', side: 'BUY', type: 'LIMIT', qty: 10, price: 100, ...over });

/** A feed whose place() fails a fixed number of times, optionally pre-flight. */
function flakyFeed(failures: number, preflight: boolean) {
  const sent: Array<PlaceRequest & { mode: TradeMode }> = [];
  let left = failures;
  const feed: OrderFeed = {
    place: async (req) => {
      if (left > 0) {
        left--;
        const err = new Error('network down');
        if (preflight) Object.assign(err, { preflight: true });
        throw err;
      }
      sent.push(req);
      return { orderId: `B${sent.length}` };
    },
    modify: async () => {},
    cancel: async () => {},
  };
  return { feed, sent };
}

describe('idempotency token is reserved before the confirm gate', () => {
  it('two clicks racing through an async gate place one order', async () => {
    const broker = new FakeBroker();
    let release: (v: boolean) => void = () => {};
    const gated = new Promise<boolean>((r) => { release = r; });
    const eng = new OrderEngine({ feed: broker, constraints: C, armed: false, gate: () => gated });

    const first = eng.placeOrder(limit({ clientToken: 'race' }));
    const second = eng.placeOrder(limit({ clientToken: 'race' }));
    release(true);
    const results = await Promise.all([first, second]);

    expect(broker.orders()).toHaveLength(1);
    expect(results.filter((r) => r.ok)).toHaveLength(1);
    const dup = results.find((r) => !r.ok);
    expect(dup?.reason).toMatch(/duplicate clientToken/);
  });

  it('a declined gate frees the token again, because nothing was sent', async () => {
    const broker = new FakeBroker();
    let approve = false;
    const eng = new OrderEngine({ feed: broker, constraints: C, armed: false, gate: () => approve });

    const declined = await eng.placeOrder(limit({ clientToken: 'ask' }));
    expect(declined.ok).toBe(false);
    expect(declined.intent).toBe('BLOCKED');

    approve = true;
    const accepted = await eng.placeOrder(limit({ clientToken: 'ask' }));
    expect(accepted.ok).toBe(true);
    expect(broker.orders()).toHaveLength(1);
  });
});

describe('a token is kept when the transport fails', () => {
  it('refuses the retry and says the first attempt may be live', async () => {
    const { feed } = flakyFeed(1, false);
    const eng = new OrderEngine({ feed, constraints: C, armed: true });

    const first = await eng.placeOrder(limit({ clientToken: 'tokA' }));
    expect(first.ok).toBe(false);
    expect(first.intent).toBe('AMBIGUOUS');
    expect(first.state).toBe('rejected'); // unchanged for existing consumers
    expect(first.reason).toMatch(/may have reached the broker/);

    const retry = await eng.placeOrder(limit({ clientToken: 'tokA' }));
    expect(retry.ok).toBe(false);
    expect(retry.reason).toMatch(/may be live/);
  });

  it('never puts the same token on the wire twice after a transport failure', async () => {
    const { feed, sent } = flakyFeed(1, false);
    const eng = new OrderEngine({ feed, constraints: C, armed: true });
    await eng.placeOrder(limit({ clientToken: 'tokB' }));
    await eng.placeOrder(limit({ clientToken: 'tokB' }));
    await eng.placeOrder(limit({ clientToken: 'tokB' }));
    expect(sent).toHaveLength(0);
  });

  it('releases the token only when the feed proves the request never left', async () => {
    const { feed, sent } = flakyFeed(1, true);
    const eng = new OrderEngine({ feed, constraints: C, armed: true });

    const first = await eng.placeOrder(limit({ clientToken: 'tokC' }));
    expect(first.ok).toBe(false);
    expect(first.intent).toBe('BLOCKED'); // provably unsent, not ambiguous
    expect(first.reason).not.toMatch(/may have reached the broker/);

    const retry = await eng.placeOrder(limit({ clientToken: 'tokC' }));
    expect(retry.ok).toBe(true);
    expect(sent).toHaveLength(1);
  });
});

describe('transport success is not authoritative state', () => {
  it('a resolved place() reaches SUBMITTED and leaves brokerStatus unset', async () => {
    const { eng, broker } = engine();
    const r = await eng.placeOrder(limit());
    const id = r.clientId as string;

    expect(r.state).toBe('working'); // historical field, unchanged
    expect(r.intent).toBe('SUBMITTED');
    expect(eng.brokerStatus(id)).toBeUndefined();

    eng.onBrokerUpdate(broker.orders()[0].id, 'working');
    expect(eng.brokerStatus(id)).toBe('working');
    expect(eng.intentState(id)).toBe('ACKNOWLEDGED');
  });

  it('a resolved cancel() is acknowledged, not settled, until the broker says so', async () => {
    const { eng, broker } = engine();
    const r = await eng.placeOrder(limit());
    const id = r.clientId as string;
    const brokerId = broker.orders()[0].id;

    await eng.cancelOrder(id);
    expect(eng.state(id)).toBe('cancelled'); // historical field, unchanged
    expect(eng.intentState(id)).toBe('ACKNOWLEDGED');
    expect(eng.brokerStatus(id)).toBeUndefined();

    eng.onBrokerUpdate(brokerId, 'cancelled');
    expect(eng.brokerStatus(id)).toBe('cancelled');
    expect(eng.intentState(id)).toBe('SETTLED');
  });

  it('a failed modify leaves the intent ambiguous', async () => {
    const broker = new FakeBroker();
    const eng = new OrderEngine({ feed: broker, constraints: C, armed: true, minModifyIntervalMs: 0 });
    const r = await eng.placeOrder(limit());
    const id = r.clientId as string;
    broker.modify = async () => { throw new Error('gateway timeout'); };

    eng.requestModify(id, 101);
    await eng.commitModify(id);
    expect(eng.intentState(id)).toBe('AMBIGUOUS');
  });
});

describe('modify carries the stop trigger', () => {
  it('drags a stop-market order by its trigger, not by a price it does not have', async () => {
    const { eng, broker } = engine();
    const r = await eng.placeOrder({ symbol: 'X', side: 'SELL', type: 'SL-M', qty: 10, triggerPrice: 95 });
    eng.requestModify(r.clientId as string, 96.02);
    await Promise.resolve();

    const order = broker.orders()[0];
    expect(order.triggerPrice).toBeCloseTo(96); // snapped to the tick and actually moved
  });

  it('moves a stop-limit order as a pair, keeping the offset it was placed with', async () => {
    const { eng, broker } = engine();
    const r = await eng.placeOrder({ symbol: 'X', side: 'SELL', type: 'SL', qty: 10, price: 100, triggerPrice: 100.5 });
    eng.requestModify(r.clientId as string, 101);
    await Promise.resolve();

    const order = broker.orders()[0];
    expect(order.price).toBeCloseTo(101);
    expect(order.triggerPrice).toBeCloseTo(101.5);
  });

  it('accepts an explicit trigger and validates it', async () => {
    const { eng, broker, tick } = engine({ minModifyIntervalMs: 0 });
    const r = await eng.placeOrder({ symbol: 'X', side: 'SELL', type: 'SL', qty: 10, price: 100, triggerPrice: 100.5 });
    const id = r.clientId as string;
    eng.requestModify(id, 101, { triggerPrice: 102.03 });
    await Promise.resolve();
    tick(10);

    const order = broker.orders()[0];
    expect(order.price).toBeCloseTo(101);
    expect(order.triggerPrice).toBeCloseTo(102.05); // snapped, not passed through raw
  });

  it('sends nothing when the derived trigger leaves the price band', async () => {
    let rejected = '';
    const { eng, broker } = engine({ onValidationError: (r) => { rejected = r; } });
    const r = await eng.placeOrder({ symbol: 'X', side: 'SELL', type: 'SL', qty: 10, price: 100, triggerPrice: 109 });
    const before = { ...broker.orders()[0] };

    eng.requestModify(r.clientId as string, 102); // trigger would be 111, band tops out at 110
    await Promise.resolve();

    expect(rejected).toMatch(/trigger/);
    expect(broker.orders()[0].price).toBeCloseTo(before.price);
    expect(broker.orders()[0].triggerPrice).toBeCloseTo(before.triggerPrice as number);
  });
});

describe('quantity is validated for every order type', () => {
  it('blocks a market order over the freeze limit', async () => {
    const { eng, broker } = engine();
    const r = await eng.placeMarket('X', 'BUY', 5000);
    expect(r.ok).toBe(false);
    expect(r.intent).toBe('BLOCKED');
    expect(r.reason).toMatch(/freeze limit/);
    expect(broker.orders()).toHaveLength(0);
  });

  it('blocks a stop-market order over the freeze limit and snaps its trigger otherwise', async () => {
    const { eng, broker } = engine();
    const over = await eng.placeOrder({ symbol: 'X', side: 'SELL', type: 'SL-M', qty: 5000, triggerPrice: 95 });
    expect(over.ok).toBe(false);
    expect(broker.orders()).toHaveLength(0);

    const ok = await eng.placeOrder({ symbol: 'X', side: 'SELL', type: 'SL-M', qty: 10, triggerPrice: 95.03 });
    expect(ok.ok).toBe(true);
    expect(broker.orders()[0].triggerPrice).toBeCloseTo(95.05);
  });

  it('rejects an out-of-band trigger before sending', async () => {
    const { eng, broker } = engine();
    const r = await eng.placeOrder({ symbol: 'X', side: 'SELL', type: 'SL-M', qty: 10, triggerPrice: 999 });
    expect(r.ok).toBe(false);
    expect(r.reason).toMatch(/trigger/);
    expect(broker.orders()).toHaveLength(0);
  });
});

describe('placeMarket carries exchange and product', () => {
  it('passes what it is given and nothing when it is given nothing', async () => {
    const seen: Array<PlaceRequest & { mode: TradeMode }> = [];
    const feed: OrderFeed = {
      place: async (req) => { seen.push(req); return { orderId: `B${seen.length}` }; },
      modify: async () => {},
      cancel: async () => {},
    };
    const eng = new OrderEngine({ feed, constraints: C, armed: true });

    await eng.placeMarket('X', 'BUY', 10);
    expect(seen[0].exchange).toBeUndefined(); // unchanged default: the feed decides
    expect(seen[0].product).toBeUndefined();

    await eng.placeMarket('NIFTY24AUGFUT', 'SELL', 50, { exchange: 'NFO', product: 'NRML' });
    expect(seen[1].exchange).toBe('NFO');
    expect(seen[1].product).toBe('NRML');
  });

  it('honours a clientToken so a double-clicked button places one order', async () => {
    const { eng, broker } = engine();
    await eng.placeMarket('X', 'BUY', 10, { clientToken: 'btn' });
    const second = await eng.placeMarket('X', 'BUY', 10, { clientToken: 'btn' });
    expect(second.ok).toBe(false);
    expect(broker.orders()).toHaveLength(1);
  });
});

describe('per-order maps are pruned, tokens are not', () => {
  it('evicts the oldest settled orders and still refuses their tokens', async () => {
    const { eng } = engine({ maxSettledOrders: 2 });
    for (let i = 0; i < 5; i++) {
      const r = await eng.placeOrder(limit({ clientToken: `t${i}` }));
      await eng.cancelOrder(r.clientId as string);
    }
    expect(eng.state('t0')).toBeUndefined(); // evicted
    expect(eng.state('t4')).toBe('cancelled'); // recent history still readable

    const retry = await eng.placeOrder(limit({ clientToken: 't0' }));
    expect(retry.ok).toBe(false); // the token outlives the row
  });

  it('never evicts a live row whose token was reoffered after a pre-flight failure', async () => {
    const { feed } = flakyFeed(1, true);
    const eng = new OrderEngine({ feed, constraints: C, armed: true, maxSettledOrders: 1 });

    await eng.placeOrder(limit({ clientToken: 'tokC' })); // pre-flight fail, token freed
    const live = await eng.placeOrder(limit({ clientToken: 'tokC' })); // same token, now live
    expect(live.ok).toBe(true);

    const other = await eng.placeOrder(limit({ clientToken: 'tokD' }));
    await eng.cancelOrder(other.clientId as string); // settles, pushing tokC out of the ring

    expect(eng.state('tokC')).toBe('working');
    expect(eng.intentState('tokC')).toBe('SUBMITTED');
  });

  it('keeps an ambiguous row even when settled rows are dropped at once', async () => {
    const broker = new FakeBroker();
    const eng = new OrderEngine({ feed: broker, constraints: C, armed: true, maxSettledOrders: 0 });

    const done = await eng.placeOrder(limit({ clientToken: 'done' }));
    await eng.cancelOrder(done.clientId as string);
    expect(eng.state('done')).toBeUndefined();

    broker.rejectNextPlace = 'socket reset';
    await eng.placeOrder(limit({ clientToken: 'unsure' }));
    expect(eng.intentState('unsure')).toBe('AMBIGUOUS');
    expect(eng.state('unsure')).toBe('rejected'); // retained: it may be live
  });
});

describe('reconciliation', () => {
  it('marks rows reconciling, then acknowledges the ones the fresh book has', async () => {
    const { eng, broker } = engine();
    const r = await eng.placeOrder(limit());
    const id = r.clientId as string;
    const brokerId = broker.orders()[0].id;

    eng.beginReconcile();
    expect(eng.intentState(id)).toBe('RECONCILING');

    eng.onReconnect(new Set([brokerId]));
    expect(eng.intentState(id)).toBe('ACKNOWLEDGED');
    expect(eng.state(id)).toBe('working');
  });

  it('treats absence from a snapshot as ambiguous, not as death', async () => {
    const { eng } = engine();
    const r = await eng.placeOrder(limit());
    const id = r.clientId as string;

    eng.onReconnect(new Set<string>());
    expect(eng.state(id)).toBe('stale'); // historical field, unchanged
    expect(eng.intentState(id)).toBe('AMBIGUOUS');
    expect(eng.brokerStatus(id)).toBeUndefined();
  });
});
