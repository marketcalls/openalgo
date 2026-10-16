/**
 * Hardening of the OpenAlgo WebSocket adapter: handshake gating, backoff that
 * only resets on a real session, jitter, topic identity, and a close() that
 * leaves a reusable instance.
 *
 * Every test here was checked against the pre-fix adapter and fails there.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  OpenAlgoWsFeed, parseMessage, parseTopic, classifyAuthAck, readSequence, backoffDelayMs,
  type WsControlMessage, type WsState,
} from '../src/feed/openalgo-ws';

interface Fake {
  sent: string[];
  closed: number;
  readyState: number;
  onopen: (() => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
  send(d: string): void;
  close(): void;
  /** Drive an inbound frame. */
  emit(v: unknown): void;
  /** Answer the handshake the way the documented proxy does. */
  ack(): void;
}

function fakeSocket(): Fake {
  const s: Fake = {
    sent: [], closed: 0, readyState: 1,
    onopen: null, onclose: null, onerror: null, onmessage: null,
    send(d: string) { s.sent.push(d); },
    close() { s.closed += 1; },
    emit(v: unknown) { s.onmessage?.({ data: typeof v === 'string' ? v : JSON.stringify(v) }); },
    ack() { s.emit({ type: 'auth', status: 'success', message: 'Authentication successful' }); },
  };
  return s;
}

function actionsOf(sock: Fake): string[] {
  return sock.sent.map((m) => String((JSON.parse(m) as { action?: string }).action));
}

/** A feed over a growing list of fake sockets; heartbeat off unless a test wants it. */
function makeFeed(cfg: Partial<ConstructorParameters<typeof OpenAlgoWsFeed>[0]> = {}): {
  ws: OpenAlgoWsFeed; sockets: Fake[]; states: WsState[]; control: WsControlMessage[];
} {
  const sockets: Fake[] = [];
  const ws = new OpenAlgoWsFeed({
    url: 'ws://x', apiKey: 'k',
    heartbeat: { timeoutMs: 0 },
    reconnect: { baseDelayMs: 100, jitter: false },
    ...cfg,
    socketFactory: () => { const s = fakeSocket(); sockets.push(s); return s; },
  });
  const states: WsState[] = [];
  const control: WsControlMessage[] = [];
  ws.onState((s) => states.push(s));
  ws.onControl((m) => control.push(m));
  return { ws, sockets, states, control };
}

afterEach(() => { vi.useRealTimers(); });

describe('handshake gating', () => {
  it('holds every data frame until the server acknowledges the auth frame', () => {
    vi.useFakeTimers();
    const { ws, sockets, states } = makeFeed();
    ws.connect();
    ws.subscribe('LTP', 'X', 'NSE');
    ws.subscribeOrders();
    // Transport open is not a usable socket: only the handshake has gone out.
    expect(actionsOf(sockets[0])).toEqual(['authenticate']);
    expect(ws.isReady()).toBe(false);
    expect(states).not.toContain('open');

    sockets[0].ack();
    expect(ws.isReady()).toBe(true);
    expect(actionsOf(sockets[0])).toEqual(['authenticate', 'subscribe', 'subscribe_orders']);
    expect(states).toContain('open');

    // Post-ack subscriptions go straight out, and nothing is sent twice.
    ws.subscribe('LTP', 'Y', 'NSE');
    expect(actionsOf(sockets[0])).toEqual(['authenticate', 'subscribe', 'subscribe_orders', 'subscribe']);
    ws.close();
  });

  it('treats an unanswered handshake as a failed connection, not a live one', () => {
    vi.useFakeTimers();
    const { ws, sockets, states } = makeFeed({ auth: { ackTimeoutMs: 2000 } });
    ws.connect();
    ws.subscribe('LTP', 'X', 'NSE');
    vi.advanceTimersByTime(1999);
    expect(sockets[0].closed).toBe(0);

    vi.advanceTimersByTime(1);
    expect(sockets[0].closed).toBe(1); // we hung up on it ourselves
    expect(states).toContain('error');
    expect(actionsOf(sockets[0])).toEqual(['authenticate']); // never subscribed into the void

    // and it is retried, so a slow proxy still recovers
    vi.advanceTimersByTime(100);
    expect(sockets).toHaveLength(2);
    sockets[1].ack();
    expect(actionsOf(sockets[1])).toEqual(['authenticate', 'subscribe']);
    ws.close();
  });

  it('a refused key is fatal: no retry storm, but connect() revives it', () => {
    vi.useFakeTimers();
    const { ws, sockets, control } = makeFeed();
    ws.connect();
    sockets[0].emit({ type: 'auth', status: 'error', message: 'Invalid openalgo apikey' });
    expect(sockets[0].closed).toBe(1);
    vi.advanceTimersByTime(60000);
    expect(sockets).toHaveLength(1); // the same key retried on a timer only gets blocked
    expect(control.some((m) => m.type === 'client_warning' && m.code === 'AUTH_FAILED')).toBe(true);
    expect(control.some((m) => m.type === 'auth' && m.status === 'error')).toBe(true); // still surfaced verbatim

    ws.connect(); // explicit user action
    expect(sockets).toHaveLength(2);
    ws.close();
  });

  it('auth.requireAck false keeps the old ungated behaviour and says so', () => {
    vi.useFakeTimers();
    const { ws, sockets, control } = makeFeed({ auth: { requireAck: false } });
    ws.connect();
    ws.subscribe('LTP', 'X', 'NSE');
    expect(actionsOf(sockets[0])).toEqual(['authenticate', 'subscribe']);
    expect(control.filter((m) => m.code === 'AUTH_UNACKNOWLEDGED')).toHaveLength(1);
    ws.close();
  });
});

describe('backoff', () => {
  it('does not reset the attempt counter on a transport open that never authenticates', () => {
    vi.useFakeTimers();
    const { ws, sockets } = makeFeed();
    ws.connect();
    // A server that accepts the connection and drops it immediately.
    sockets[0].onclose?.();
    vi.advanceTimersByTime(100);
    expect(sockets).toHaveLength(2); // attempt 0: 100ms

    sockets[1].onclose?.();
    vi.advanceTimersByTime(100);
    expect(sockets).toHaveLength(2); // attempt 1 is 200ms, so nothing yet
    vi.advanceTimersByTime(100);
    expect(sockets).toHaveLength(3);
    ws.close();
  });

  it('resets the attempt counter once a session is actually authenticated', () => {
    vi.useFakeTimers();
    const { ws, sockets } = makeFeed();
    ws.connect();
    ws.subscribe('LTP', 'X', 'NSE');
    sockets[0].onclose?.();
    vi.advanceTimersByTime(100);
    sockets[1].ack(); // a real session
    sockets[1].onclose?.();
    vi.advanceTimersByTime(100);
    expect(sockets).toHaveLength(3); // back to the base delay
    expect(actionsOf(sockets[2])).toEqual(['authenticate']); // replay still waits for its own ack
    sockets[2].ack();
    expect(actionsOf(sockets[2])).toEqual(['authenticate', 'subscribe']);
    ws.close();
  });

  it('jitters the delay so a fleet does not reconnect in lockstep', () => {
    vi.useFakeTimers();
    const { ws, sockets } = makeFeed({ reconnect: { baseDelayMs: 100, random: () => 0 } });
    ws.connect();
    sockets[0].onclose?.();
    vi.advanceTimersByTime(49);
    expect(sockets).toHaveLength(1);
    vi.advanceTimersByTime(1); // full jitter puts attempt 0 at [50, 100)
    expect(sockets).toHaveLength(2);
    ws.close();
  });

  it('says it gave up instead of going quiet when maxAttempts runs out', () => {
    vi.useFakeTimers();
    const { ws, sockets, control } = makeFeed({ reconnect: { baseDelayMs: 100, jitter: false, maxAttempts: 1 } });
    ws.connect();
    sockets[0].onclose?.();
    vi.advanceTimersByTime(100);
    expect(sockets).toHaveLength(2);
    sockets[1].onclose?.();
    vi.advanceTimersByTime(10000);
    expect(sockets).toHaveLength(2);
    expect(control.some((m) => m.code === 'RECONNECT_ABANDONED')).toBe(true);
    ws.close();
  });

  it('backoffDelayMs stays inside [ceiling/2, ceiling) and respects the cap', () => {
    const opts = { baseDelayMs: 1000, maxDelayMs: 30000 };
    for (let n = 0; n < 12; n++) {
      const ceiling = Math.min(opts.maxDelayMs, opts.baseDelayMs * 2 ** n);
      expect(backoffDelayMs(n, opts, () => 0)).toBe(ceiling / 2);
      expect(backoffDelayMs(n, opts, () => 0.9999)).toBeLessThan(ceiling);
      expect(backoffDelayMs(n, opts, () => 0.9999)).toBeGreaterThanOrEqual(ceiling / 2);
    }
    expect(backoffDelayMs(3, { ...opts, jitter: false }, () => 0)).toBe(8000);
  });
});

describe('liveness watchdog', () => {
  // UPDATED by the integration pass: the watchdog no longer hangs up on silence
  // alone. OpenAlgo's proxy keeps the connection alive with protocol-level
  // pings, which a browser answers itself and never reports to JavaScript, and
  // it broadcasts nothing else on a schedule, so a quiet symbol out of hours
  // produces no inbound frame at all. A bare timeout would have closed and
  // resubscribed a healthy socket every 45s all night. It now asks first.
  it('probes before it concludes, and reconnects only when the probe goes unanswered', () => {
    vi.useFakeTimers();
    const { ws, sockets, control } = makeFeed({ heartbeat: { timeoutMs: 45000, probeMs: 5000 } });
    ws.connect();
    sockets[0].ack();
    vi.advanceTimersByTime(45000);
    // Silence is a question, not a verdict.
    expect(sockets[0].closed).toBe(0);
    expect(actionsOf(sockets[0]).filter((a) => a === 'ping')).toHaveLength(1);
    vi.advanceTimersByTime(4999);
    expect(sockets[0].closed).toBe(0);
    vi.advanceTimersByTime(1);
    expect(sockets[0].closed).toBe(1);
    expect(control.some((m) => m.code === 'HEARTBEAT_DEAD')).toBe(true);
    vi.advanceTimersByTime(100);
    expect(sockets).toHaveLength(2);
    ws.close();
  });

  it('an answer of any kind clears the probe, including an error the proxy sends back', () => {
    vi.useFakeTimers();
    const { ws, sockets } = makeFeed({ heartbeat: { timeoutMs: 45000, probeMs: 5000 } });
    ws.connect();
    sockets[0].ack();
    vi.advanceTimersByTime(45000);
    // A build that does not know the action answers an error; that still proves
    // the far end is there, which is the only thing the probe asked.
    sockets[0].emit(JSON.stringify({ status: 'error', code: 'INVALID_ACTION', message: 'Invalid action: ping' }));
    vi.advanceTimersByTime(44999);
    expect(sockets[0].closed).toBe(0);
    ws.close();
  });

  it('any inbound frame keeps it alive, including a ping on a quiet symbol', () => {
    vi.useFakeTimers();
    const { ws, sockets } = makeFeed({ heartbeat: { timeoutMs: 45000, probeMs: 5000 } });
    ws.connect();
    sockets[0].ack();
    for (let i = 0; i < 4; i++) {
      vi.advanceTimersByTime(30000);
      sockets[0].emit('ping');
    }
    expect(sockets[0].closed).toBe(0);
    expect(actionsOf(sockets[0]).filter((a) => a === 'pong')).toHaveLength(4);
    // Deferred by a frame, not disabled by one: after the last ping the timeout
    // still runs, the probe still goes out, and silence to THAT is still death.
    vi.advanceTimersByTime(45000);
    expect(sockets[0].closed).toBe(0);
    vi.advanceTimersByTime(5000);
    expect(sockets[0].closed).toBe(1);
    ws.close();
  });
});

describe('message identity', () => {
  it('falls back to the topic when the payload carries no symbol', () => {
    const r = parseMessage({ type: 'market_data', mode: 1, topic: 'SBIN.NSE', data: { ltp: 772.5 } });
    expect(r?.kind).toBe('ltp');
    if (r?.kind === 'ltp') expect(r.event).toMatchObject({ symbol: 'SBIN', exchange: 'NSE', ltp: 772.5 });

    const d = parseMessage({ type: 'market_data', mode: 3, topic: 'SBIN.NSE', data: { depth: { buy: [{ price: 100, quantity: 5 }], sell: [] } } });
    expect(d?.kind).toBe('depth');
    if (d?.kind === 'depth') expect([d.symbol, d.exchange]).toEqual(['SBIN', 'NSE']);
  });

  it('the payload wins, and each field falls back on its own', () => {
    const r = parseMessage({ topic: 'SBIN.NSE', data: { symbol: 'INFY', ltp: 1 } });
    if (r?.kind === 'ltp') expect([r.event.symbol, r.event.exchange]).toEqual(['INFY', 'NSE']);
    const e = parseMessage({ topic: 'SBIN.NSE', data: { symbol: '', exchange: '', ltp: 1 } });
    if (e?.kind === 'ltp') expect([e.event.symbol, e.event.exchange]).toEqual(['SBIN', 'NSE']);
  });

  it('parseTopic only accepts the documented SYMBOL.EXCHANGE form', () => {
    expect(parseTopic('SBIN.NSE')).toEqual({ symbol: 'SBIN', exchange: 'NSE' });
    expect(parseTopic('SBIN.NSE.LTP')).toBeNull();
    expect(parseTopic('NSE:SBIN')).toBeNull(); // guessing here would misattribute the tick
    expect(parseTopic('.NSE')).toBeNull();
    expect(parseTopic(undefined)).toBeNull();
  });

  it('delivers a topic-only tick to onLtp', () => {
    vi.useFakeTimers();
    const { ws, sockets } = makeFeed();
    const seen: string[] = [];
    ws.onLtp((e) => seen.push(`${e.symbol}.${e.exchange}@${e.ltp}`));
    ws.connect();
    sockets[0].ack();
    sockets[0].emit({ type: 'market_data', mode: 1, topic: 'RELIANCE.NSE', data: { ltp: 1135 } });
    expect(seen).toEqual(['RELIANCE.NSE@1135']);
    ws.close();
  });
});

describe('close() leaves a coherent instance', () => {
  it('drops the subscription bookkeeping with the socket and stays reusable', () => {
    vi.useFakeTimers();
    const { ws, sockets } = makeFeed();
    ws.connect();
    sockets[0].ack();
    ws.subscribe('LTP', 'X', 'NSE');
    ws.subscribeOrders();
    ws.close();

    // Reopened: nothing is subscribed until the caller asks again.
    ws.connect();
    sockets[1].ack();
    expect(actionsOf(sockets[1])).toEqual(['authenticate']);

    ws.subscribe('LTP', 'Y', 'NSE');
    // And the reopened session still auto-reconnects: close() must not leave
    // the user-intent flag latched forever.
    sockets[1].onclose?.();
    vi.advanceTimersByTime(100);
    expect(sockets).toHaveLength(3);
    sockets[2].ack();
    const replay = sockets[2].sent.filter((m) => m.includes('"action":"subscribe"'));
    expect(replay).toHaveLength(1);
    expect(replay[0]).toContain('"symbol":"Y"'); // X died with the closed session
    ws.close();
  });

  it('unsubscribing while gated removes it from the replay instead of racing it', () => {
    vi.useFakeTimers();
    const { ws, sockets } = makeFeed();
    ws.connect();
    ws.subscribe('LTP', 'X', 'NSE');
    ws.unsubscribe('LTP', 'X', 'NSE');
    sockets[0].ack();
    expect(actionsOf(sockets[0])).toEqual(['authenticate']);
    ws.close();
  });
});

describe('sequence gaps (only when the server numbers its frames)', () => {
  it('drops duplicates and warns on a gap', () => {
    vi.useFakeTimers();
    const { ws, sockets, control } = makeFeed();
    const seen: number[] = [];
    ws.onLtp((e) => seen.push(e.ltp));
    ws.connect();
    sockets[0].ack();
    const tick = (seq: number, ltp: number): void => sockets[0].emit({ type: 'market_data', topic: 'X.NSE', seq, data: { ltp } });
    tick(1, 100);
    tick(2, 101);
    tick(2, 999); // duplicate after a resubscribe
    tick(5, 105); // 3 and 4 never arrived
    expect(seen).toEqual([100, 101, 105]);
    const gap = control.find((m) => m.code === 'SEQUENCE_GAP');
    expect(gap?.message).toContain('2 frame(s) missing');

    // The documented stream numbers nothing, and nothing is invented for it: an
    // unsequenced topic keeps every tick, repeats included.
    for (const ltp of [50, 50, 49]) sockets[0].emit({ type: 'market_data', topic: 'Y.NSE', data: { ltp } });
    expect(seen).toEqual([100, 101, 105, 50, 50, 49]);
    expect(control.filter((m) => m.code === 'SEQUENCE_GAP')).toHaveLength(1);
    ws.close();
  });

  it('a reconnect is treated as a gap, because the stream cannot prove otherwise', () => {
    vi.useFakeTimers();
    const { ws, sockets, control } = makeFeed();
    ws.connect();
    sockets[0].ack();
    expect(control.some((m) => m.code === 'STREAM_RESYNC')).toBe(false); // first session, nothing missed
    sockets[0].onclose?.();
    vi.advanceTimersByTime(100);
    sockets[1].ack();
    expect(control.some((m) => m.code === 'STREAM_RESYNC')).toBe(true);
    ws.close();
  });

  it('readSequence reads root or data, and nothing else', () => {
    expect(readSequence({ seq: 7 })).toBe(7);
    expect(readSequence({ data: { sequence: 8 } })).toBe(8);
    expect(readSequence({ data: { sequence_number: 9 } })).toBe(9);
    expect(readSequence({ data: { ltp: 100 } })).toBeUndefined();
    expect(readSequence({ seq: 'nope' })).toBeUndefined();
  });
});

describe('classifyAuthAck', () => {
  it('never reads silence or an unrelated frame as an acknowledgement', () => {
    expect(classifyAuthAck({ type: 'auth', status: 'success' })).toBe('ok');
    expect(classifyAuthAck({ type: 'auth', status: 'error' })).toBe('failed');
    expect(classifyAuthAck({ type: 'error', message: 'bad key' })).toBe('failed');
    expect(classifyAuthAck({ type: 'market_data', data: { ltp: 1 } })).toBeNull();
    expect(classifyAuthAck({ type: 'subscribe', status: 'success' })).toBeNull();
    expect(classifyAuthAck({ status: 'success', message: 'Authentication successful' })).toBe('ok');
    expect(classifyAuthAck({ status: 'success' })).toBeNull(); // says nothing about auth
    expect(classifyAuthAck('ping')).toBeNull();
  });
});
