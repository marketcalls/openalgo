/**
 * Integration regressions found by tracing this round's changes across the
 * boundaries their owners could not see over.
 *
 * Each case here failed against the six owner diffs as they were handed in,
 * even though every owner's own file and own suite were green. They are
 * boundary defects: a marker one file raises and another file never sets, a
 * frame shape the real OpenAlgo proxy sends and the parser did not recognise,
 * a state the broker can report and the shared table had no edge for.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  OpenAlgoWsFeed, classifyAuthAck, type SocketLike, type WsControlMessage,
} from '../src/feed/openalgo-ws';
import { OpenAlgoTradeFeed } from '../src/feed/openalgo-trade';
import { OpenAlgoLiveDataFeed } from '../src/feed/openalgo-live';
import { OrderEngine, isPreflightFailure } from '../src/trade/order-engine';
import type { OrderConstraints } from '../src/trade/validation';
import { transition } from '../src/trade/order-state-machine';
import type { DataFeed } from '../src/feed/types';

const C: OrderConstraints = { tickSize: 0.05, freezeQty: 1000 };

interface Fake extends SocketLike {
  sent: string[];
  closed: number;
  emit: (data: string) => void;
}

function fakeSocket(): Fake {
  const s: Fake = {
    sent: [], closed: 0, readyState: 1,
    onopen: null, onclose: null, onerror: null, onmessage: null,
    send: (d: string) => { s.sent.push(d); },
    close: () => { s.closed++; },
    emit: (d: string) => s.onmessage?.({ data: d }),
  };
  return s;
}

afterEach(() => { vi.useRealTimers(); });

/* ── 1. the refusal the real proxy actually sends ───────────────────────── */

/**
 * `websocket_proxy/server.py` answers a bad key with `send_error`, which puts
 * `{ status:'error', code, message }` on the wire with NO `type` field at all;
 * only the SUCCESS frame carries `type: 'auth'`. Classifying refusals by type
 * alone therefore recognised none of them against the shipping proxy, and the
 * one failure a human has to fix was retried on a backoff timer instead.
 */
describe('an auth refusal is recognised in the shape the OpenAlgo proxy sends it', () => {
  it('classifies a typeless status:error frame as a refusal', () => {
    expect(classifyAuthAck({ status: 'error', code: 'AUTHENTICATION_ERROR', message: 'Invalid API key' })).toBe('failed');
    // Still not an acknowledgement, and still not a refusal, when it says nothing about auth.
    expect(classifyAuthAck({ type: 'market_data', data: { ltp: 1 } })).toBeNull();
    expect(classifyAuthAck({ type: 'auth', status: 'success' })).toBe('ok');
  });

  it('goes fatal on it instead of retrying a key the server just rejected', () => {
    vi.useFakeTimers();
    const sockets: Fake[] = [];
    const control: WsControlMessage[] = [];
    const ws = new OpenAlgoWsFeed({
      url: 'ws://x', apiKey: 'bad',
      reconnect: { baseDelayMs: 100, jitter: false },
      heartbeat: { timeoutMs: 0 },
      socketFactory: () => { const s = fakeSocket(); sockets.push(s); return s; },
    });
    ws.onControl((m) => control.push(m));
    ws.connect();
    sockets[0].emit(JSON.stringify({ status: 'error', code: 'AUTHENTICATION_ERROR', message: 'Invalid API key' }));

    expect(control.some((m) => m.code === 'AUTH_FAILED' && m.message === 'Invalid API key')).toBe(true);
    expect(sockets[0].closed).toBe(1);
    // No retry storm: not on the backoff timer, and not on the auth timeout either.
    vi.advanceTimersByTime(60000);
    expect(sockets).toHaveLength(1);
    ws.close();
  });
});

/* ── 2. the pre-flight marker, raised in one file and set in another ────── */

function tradeFeed(routes: Record<string, unknown>, cfg: Record<string, unknown> = {}): {
  feed: OpenAlgoTradeFeed; paths: string[];
} {
  const paths: string[] = [];
  const fetchImpl = (async (url: string) => {
    const path = String(url).replace('http://x', '');
    paths.push(path);
    const r = routes[path];
    if (r === undefined) return { ok: false, status: 500, json: async () => ({ message: 'boom' }) } as Response;
    return { ok: true, status: 200, json: async () => r } as Response;
  }) as unknown as typeof fetch;
  return { feed: new OpenAlgoTradeFeed({ baseUrl: 'http://x', apiKey: 'k', fetchImpl, ...cfg }), paths };
}

describe('the trade feed marks the failures that provably never left', () => {
  it('marks the mode refusal, which happens before the order is written', async () => {
    const { feed } = tradeFeed({
      '/api/v1/analyzer/': { status: 'success', data: { mode: 'live', analyze_mode: false } },
    });
    const err = await feed.place({ symbol: 'X', side: 'BUY', type: 'MARKET', qty: 1, mode: 'analyzer' }).catch((e: unknown) => e);
    expect(isPreflightFailure(err)).toBe(true);
  });

  it('marks a modify with no cached context', async () => {
    const { feed } = tradeFeed({});
    const err = await feed.modify('nope', { price: 100 }).catch((e: unknown) => e);
    expect(isPreflightFailure(err)).toBe(true);
  });

  it('does NOT mark a non-ok HTTP response: that request plainly left', async () => {
    const { feed } = tradeFeed({}, { verifyMode: 'off' });
    const err = await feed.place({ symbol: 'X', side: 'BUY', type: 'MARKET', qty: 1, mode: 'live' }).catch((e: unknown) => e);
    expect(isPreflightFailure(err)).toBe(false);
  });
});

describe('engine and feed agree on when an idempotency token may be reoffered', () => {
  it('releases the token for a pre-flight refusal and holds it for a transport failure', async () => {
    // Server is live, caller believes it is on the sandbox: refused before the
    // placeorder is written, so the same token is free to be offered again.
    const refusing = tradeFeed({
      '/api/v1/analyzer/': { status: 'success', data: { mode: 'live', analyze_mode: false } },
    });
    const eng1 = new OrderEngine({ feed: refusing.feed, constraints: C, armed: true, mode: 'analyzer' });
    const a1 = await eng1.placeOrder({ symbol: 'X', side: 'BUY', type: 'MARKET', qty: 1, clientToken: 't' });
    expect(a1.intent).toBe('BLOCKED');
    const a2 = await eng1.placeOrder({ symbol: 'X', side: 'BUY', type: 'MARKET', qty: 1, clientToken: 't' });
    expect(a2.reason).not.toMatch(/duplicate/); // the retry is allowed through
    expect(refusing.paths.filter((p) => p === '/api/v1/placeorder')).toHaveLength(0);

    // A 500 from placeorder is a different thing: the request left, so the
    // token stays claimed and the retry is refused.
    const failing = tradeFeed({}, { verifyMode: 'off' });
    const eng2 = new OrderEngine({ feed: failing.feed, constraints: C, armed: true });
    const b1 = await eng2.placeOrder({ symbol: 'X', side: 'BUY', type: 'MARKET', qty: 1, clientToken: 't' });
    expect(b1.intent).toBe('AMBIGUOUS');
    const b2 = await eng2.placeOrder({ symbol: 'X', side: 'BUY', type: 'MARKET', qty: 1, clientToken: 't' });
    expect(b2.reason).toMatch(/duplicate clientToken/);
    expect(failing.paths.filter((p) => p === '/api/v1/placeorder')).toHaveLength(1);
  });
});

/* ── 3. a broker rejecting an order it had already accepted ─────────────── */

describe('an authoritative rejection lands on every field, not just the honest ones', () => {
  it('moves a working order to rejected', () => {
    expect(transition('working', 'reject')).toBe('rejected');
    expect(transition('partial', 'reject')).toBe('rejected');
    // The modify/cancel round trips still fall back to working, unchanged.
    expect(transition('modify_pending', 'reject')).toBe('working');
    expect(transition('cancel_pending', 'reject')).toBe('working');
  });

  it('leaves no order reading working after the broker said rejected', async () => {
    const { feed } = tradeFeed({
      '/api/v1/placeorder': { status: 'success', orderid: 'B1' },
    }, { verifyMode: 'off' });
    const eng = new OrderEngine({ feed, constraints: C, armed: true });
    const r = await eng.placeOrder({ symbol: 'X', side: 'BUY', type: 'LIMIT', qty: 10, price: 100 });
    const id = r.clientId as string;
    eng.onBrokerUpdate('B1', 'working');
    expect(eng.state(id)).toBe('working');
    eng.onBrokerUpdate('B1', 'rejected');
    expect(eng.brokerStatus(id)).toBe('rejected');
    expect(eng.intentState(id)).toBe('SETTLED');
    expect(eng.state(id)).toBe('rejected');
  });
});

/* ── 4. socket policy is reachable through the composed feed ────────────── */

describe('the composed live feed can reach the socket options the gate made necessary', () => {
  it('passes auth.requireAck through, so a proxy that answers nothing still works', () => {
    let sock: Fake | undefined;
    const feed = new OpenAlgoLiveDataFeed({
      apiKey: 'k', baseUrl: '', wsUrl: 'ws://x',
      auth: { requireAck: false },
      socketFactory: () => (sock = fakeSocket()),
    });
    // No ack is ever delivered, and the subscribe still reaches the wire.
    feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: '1m', from: 0 }, () => {});
    const actions = (sock as Fake).sent.map((m) => (JSON.parse(m) as { action?: string }).action);
    expect(actions).toEqual(['authenticate', 'subscribe']);
    feed.close();
  });

  it('names a depth level through the DataFeed interface, not only the concrete class', () => {
    let sock: Fake | undefined;
    const live = new OpenAlgoLiveDataFeed({
      apiKey: 'k', baseUrl: '', wsUrl: 'ws://x', socketFactory: () => (sock = fakeSocket()),
    });
    (sock as Fake).emit(JSON.stringify({ type: 'auth', status: 'success' }));
    const feed: DataFeed = live; // the type a chart holds
    feed.subscribeDepth?.({ symbol: 'X', exchange: 'NSE', interval: '1m', from: 0 }, () => {}, { depthLevel: 30 });
    const sub = (sock as Fake).sent.map((m) => JSON.parse(m) as Record<string, unknown>).find((f) => f.action === 'subscribe');
    expect(sub?.depth_level).toBe(30);
    live.close();
  });
});
