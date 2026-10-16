/**
 * Hardening of the OpenAlgo trade adapter.
 *
 * Two defects are covered, both of which reach the shipping terminal directly
 * (OpenAlgo drives `OpenAlgoTradeFeed` and never constructs `OrderEngine`):
 *
 * 1. Order book parsing failed OPEN. An unmappable broker status became
 *    `working`, a missing or unrecognised action became BUY, and `"abc"`
 *    became 0. Each of those asserts a fact nobody checked, on a surface that
 *    draws draggable order lines and Buy/Sell buttons.
 * 2. `place` took a `mode` and did nothing with it. Analyzer mode is a
 *    server-side global in OpenAlgo, so the fix is a guard that asks the
 *    server, not a field on the order payload that the server would ignore.
 */
import { describe, it, expect } from 'vitest';
import {
  OpenAlgoTradeFeed, decodeOrder, mapOrder, mapOrderStatus,
  type OpenAlgoTradeConfig, type OrderBookSnapshot, type RawOrder,
} from '../src/feed/openalgo-trade';

type Route = unknown | ((body: Record<string, unknown>) => unknown);

interface Harness {
  calls: { path: string; body: Record<string, unknown> }[];
  paths: () => string[];
  feed: OpenAlgoTradeFeed;
}

function harness(routes: Record<string, Route>, cfg: Partial<OpenAlgoTradeConfig> = {}): Harness {
  const calls: { path: string; body: Record<string, unknown> }[] = [];
  const fetchImpl = (async (url: string, init?: RequestInit) => {
    const path = String(url).replace('http://x', '');
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    calls.push({ path, body });
    if (!(path in routes)) {
      return { ok: false, status: 404, json: async () => ({ message: `no route ${path}` }) } as Response;
    }
    const r = routes[path];
    const json = typeof r === 'function' ? (r as (b: Record<string, unknown>) => unknown)(body) : r;
    return { ok: true, status: 200, json: async () => json } as Response;
  }) as unknown as typeof fetch;
  const feed = new OpenAlgoTradeFeed({ baseUrl: 'http://x', apiKey: 'k', fetchImpl, ...cfg });
  return { calls, paths: () => calls.map((c) => c.path), feed };
}

/** A row that decodes cleanly, so a test can vary exactly one field. */
function goodRow(over: Partial<RawOrder> = {}): RawOrder {
  return {
    orderid: 'OA1', symbol: 'SBIN', exchange: 'NSE', action: 'BUY', pricetype: 'LIMIT',
    product: 'CNC', quantity: '10', price: '780.5', trigger_price: '0', order_status: 'open',
    ...over,
  };
}

const book = (rows: RawOrder[]): Record<string, Route> => ({
  '/api/v1/orderbook': { status: 'success', data: { orders: rows } },
});

describe('fail-closed order book parsing', () => {
  it('keeps a row whose status is unmappable, but reports it as unknown rather than working', () => {
    // Not hypothetical: OpenAlgo's own broker mappings emit the literal string
    // "unknown" when a broker sends a state they do not recognise.
    const o = mapOrder(goodRow({ order_status: 'unknown' }));
    expect(o.status).toBe('unknown');
    expect(o.status).not.toBe('working');
    expect(o.rawStatus).toBe('unknown');
  });

  it('does not read a missing status as working', () => {
    const o = mapOrder(goodRow({ order_status: undefined }));
    expect(o.status).toBe('unknown');
  });

  it('maps the documented statuses unchanged', () => {
    expect(mapOrderStatus('open')).toBe('working');
    expect(mapOrderStatus('trigger pending')).toBe('working');
    expect(mapOrderStatus('complete')).toBe('filled');
    expect(mapOrderStatus('cancelled')).toBe('cancelled');
    expect(mapOrderStatus('rejected')).toBe('rejected');
    expect(mapOrderStatus('modify pending')).toBe('unknown');
  });

  it('never turns an unrecognised action into a BUY', () => {
    const res = decodeOrder(goodRow({ action: 'B' }), 'orders[0]');
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.issue).toMatchObject({ path: 'orders[0].action', code: 'UNKNOWN_ENUM', got: 'B' });
  });

  it('never turns a missing action into a BUY', () => {
    const res = decodeOrder(goodRow({ action: undefined }));
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.issue.code).toBe('UNKNOWN_ENUM');
  });

  it('rejects a row rather than coercing an unreadable quantity to 0', () => {
    const res = decodeOrder(goodRow({ quantity: 'abc' }));
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.issue).toMatchObject({ code: 'NON_FINITE', got: 'abc' });
  });

  it('rejects a row rather than coercing an unreadable price to 0', () => {
    // A limit price of 0 on a live order is a market order in disguise.
    const res = decodeOrder(goodRow({ price: 'n/a' }));
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.issue.code).toBe('NON_FINITE');
  });

  it('rejects an unrecognised price type and a negative quantity', () => {
    expect(decodeOrder(goodRow({ pricetype: 'BO' })).ok).toBe(false);
    expect(decodeOrder(goodRow({ quantity: -5 })).ok).toBe(false);
  });

  it('rejects a row with no usable identity', () => {
    expect(decodeOrder(goodRow({ orderid: '' })).ok).toBe(false);
    expect(decodeOrder(goodRow({ symbol: '   ' })).ok).toBe(false);
  });

  it('still decodes a well-formed row, including string numerics', () => {
    const res = decodeOrder(goodRow({ pricetype: 'SL', trigger_price: '779.25' }));
    expect(res.ok).toBe(true);
    if (!res.ok) return;
    expect(res.order).toMatchObject({
      id: 'OA1', symbol: 'SBIN', side: 'BUY', type: 'SL', qty: 10, price: 780.5,
      triggerPrice: 779.25, status: 'working',
    });
    expect(res.order.rawStatus).toBeUndefined();
  });

  it('mapOrder marks an undecodable row unknown instead of inventing a side', () => {
    const o = mapOrder(goodRow({ action: 'XYZ', quantity: 'abc' }));
    expect(o.status).toBe('unknown');
    expect(o.side).not.toBe('BUY');
    expect(o.side).toBe('XYZ');
  });
});

describe('fail-closed order book, over the wire', () => {
  const rows = [
    goodRow({ orderid: 'GOOD' }),
    goodRow({ orderid: 'BADSIDE', action: 'B' }),
    goodRow({ orderid: 'BADQTY', quantity: 'abc' }),
    goodRow({ orderid: 'ODDSTATUS', order_status: 'modify pending' }),
  ];

  it('drops unreadable rows from getOrders and never presents one as a working BUY', async () => {
    const { feed } = harness(book(rows));
    const orders = await feed.getOrders();
    expect(orders.map((o) => o.id)).toEqual(['GOOD', 'ODDSTATUS']);
    expect(orders.some((o) => o.id === 'BADSIDE')).toBe(false);
    // The kept row degrades instead of disappearing: hiding an order that
    // exists is worse than showing one nobody can classify.
    const odd = orders.find((o) => o.id === 'ODDSTATUS');
    expect(odd?.status).toBe('unknown');
    expect(odd?.rawStatus).toBe('modify pending');
  });

  it('quarantines the unreadable rows with a path and a code, and tells the host', async () => {
    let seen: OrderBookSnapshot | undefined;
    const { feed } = harness(book(rows), { onDecodeIssue: (s) => { seen = s; } });
    const snap = await feed.getOrderBook();
    expect(snap.quarantined.map((q) => q.issue.path)).toEqual(['orders[1].action', 'orders[2].quantity']);
    expect(snap.quarantined[0].raw.orderid).toBe('BADSIDE');
    expect(seen).toBeDefined();
    expect(seen?.quarantined).toHaveLength(2);
  });

  it('does not notify when every row reads cleanly', async () => {
    let calls = 0;
    const { feed } = harness(book([goodRow()]), { onDecodeIssue: () => { calls++; } });
    const snap = await feed.getOrderBook();
    expect(snap.quarantined).toHaveLength(0);
    expect(calls).toBe(0);
  });

  it('caches a modify context only from fields the book actually carried', async () => {
    const routes = {
      ...book([goodRow({ orderid: 'FULL', exchange: 'MCX', product: 'NRML' }), goodRow({ orderid: 'NOPROD', product: undefined })]),
      '/api/v1/modifyorder': { status: 'success' },
    };
    const { calls, feed } = harness(routes);
    await feed.getOrders();
    await feed.modify('FULL', { price: 781 });
    expect(calls[1].body).toMatchObject({ orderid: 'FULL', exchange: 'MCX', product: 'NRML', price: 781, quantity: 10 });
    // No product in the book means no honest modify payload. Refusing by name
    // beats silently rewriting a CNC order as MIS.
    await expect(feed.modify('NOPROD', { price: 781 })).rejects.toThrow(/NOPROD/);
  });
});

describe('analyzer mode is a server-side global, checked and never claimed', () => {
  const analyzer = (mode: 'analyze' | 'live') => ({
    '/api/v1/analyzer/': { status: 'success', data: { mode, analyze_mode: mode === 'analyze', total_logs: 0 } },
  });
  const placeOk = { '/api/v1/placeorder': { status: 'success', orderid: 'OA1' } };
  const order = { symbol: 'SBIN', exchange: 'NSE', side: 'BUY', type: 'MARKET', qty: 1, product: 'MIS' } as const;

  it('refuses to place a paper order while the server is live, and sends nothing', async () => {
    const { calls, paths, feed } = harness({ ...analyzer('live'), ...placeOk });
    await expect(feed.place({ ...order, mode: 'analyzer' })).rejects.toThrow(/analyzer.*live|live.*analyzer/);
    expect(paths()).toEqual(['/api/v1/analyzer/']);
    expect(calls.some((c) => c.path === '/api/v1/placeorder')).toBe(false);
  });

  it('names both modes in the refusal', async () => {
    const { feed } = harness({ ...analyzer('live'), ...placeOk });
    const err = await feed.place({ ...order, mode: 'analyzer' }).catch((e: Error) => e);
    expect(String(err)).toContain('analyzer');
    expect(String(err)).toContain('live');
  });

  it('places once the server confirms the mode, and keeps mode out of the payload', async () => {
    const { calls, paths, feed } = harness({ ...analyzer('analyze'), ...placeOk });
    const r = await feed.place({ ...order, mode: 'analyzer' });
    expect(r.orderId).toBe('OA1');
    expect(paths()).toEqual(['/api/v1/analyzer/', '/api/v1/placeorder']);
    // A mode field on the order body is security theatre: OpenAlgo routes on
    // get_analyze_mode() and would ignore it.
    expect(calls[1].body).not.toHaveProperty('mode');
  });

  it('adds no round trip to a live order on a cold cache', async () => {
    const { paths, feed } = harness({ ...analyzer('analyze'), ...placeOk });
    await feed.place({ ...order, mode: 'live' });
    expect(paths()).toEqual(['/api/v1/placeorder']);
  });

  it('refuses a live order for free once any response has revealed the sandbox', async () => {
    // Sandbox responses stamp mode: "analyze"; live ones say nothing at all, so
    // the cache is warmed by the book poll the terminal already runs.
    const { paths, feed } = harness({
      '/api/v1/positionbook': { status: 'success', mode: 'analyze', data: [] },
      ...placeOk,
    });
    await feed.getPositions();
    await expect(feed.place({ ...order, mode: 'live' })).rejects.toThrow(/refusing to place/);
    expect(paths()).toEqual(['/api/v1/positionbook']);
  });

  it('reuses a fresh reading instead of probing again', async () => {
    let t = 0;
    const { paths, feed } = harness({ ...analyzer('analyze'), ...placeOk }, { now: () => t, modeCacheMs: 5000 });
    await feed.place({ ...order, mode: 'analyzer' });
    t = 4000;
    await feed.place({ ...order, mode: 'analyzer' });
    expect(paths()).toEqual(['/api/v1/analyzer/', '/api/v1/placeorder', '/api/v1/placeorder']);
  });

  it('stops trusting a reading once it is stale', async () => {
    let t = 0;
    const { paths, feed } = harness({ ...analyzer('analyze'), ...placeOk }, { now: () => t, modeCacheMs: 5000 });
    await feed.place({ ...order, mode: 'analyzer' });
    t = 6000;
    await feed.place({ ...order, mode: 'analyzer' });
    expect(paths()).toEqual(['/api/v1/analyzer/', '/api/v1/placeorder', '/api/v1/analyzer/', '/api/v1/placeorder']);
  });

  it('refuses the paper order when the server cannot be asked at all', async () => {
    const { calls, feed } = harness({ '/api/v1/analyzer/': { status: 'success' }, ...placeOk });
    await expect(feed.place({ ...order, mode: 'analyzer' })).rejects.toThrow(/no readable mode/);
    expect(calls.some((c) => c.path === '/api/v1/placeorder')).toBe(false);
  });

  it('checks both directions under verifyMode: always', async () => {
    const { paths, feed } = harness({ ...analyzer('analyze'), ...placeOk }, { verifyMode: 'always' });
    await expect(feed.place({ ...order, mode: 'live' })).rejects.toThrow(/refusing to place/);
    expect(paths()).toEqual(['/api/v1/analyzer/']);
  });

  it('leaves the caller alone under verifyMode: off', async () => {
    const { paths, feed } = harness({ ...analyzer('live'), ...placeOk }, { verifyMode: 'off' });
    await feed.place({ ...order, mode: 'analyzer' });
    expect(paths()).toEqual(['/api/v1/placeorder']);
  });

  it('reads the mode from the analyze_mode flag when the word is absent', async () => {
    const { feed } = harness({ '/api/v1/analyzer/': { status: 'success', data: { analyze_mode: true } } });
    expect(await feed.getServerMode()).toBe('analyzer');
    expect(feed.serverMode()).toBe('analyzer');
  });

  it('never reads the silence of a live response as evidence of live', async () => {
    const { feed } = harness({ '/api/v1/positionbook': { status: 'success', data: [] } });
    await feed.getPositions();
    expect(feed.serverMode()).toBeUndefined();
  });
});
