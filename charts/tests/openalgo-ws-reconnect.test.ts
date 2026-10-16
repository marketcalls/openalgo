import { describe, it, expect, vi, afterEach } from 'vitest';
import { OpenAlgoWsFeed, parseOrderUpdate, type OrderUpdateEvent } from '../src/feed/openalgo-ws';

function fakeSocket(): any {
  const s: any = {
    sent: [] as string[], readyState: 1,
    onopen: null, onclose: null, onerror: null, onmessage: null,
    send(d: string) { s.sent.push(d); },
    close() {},
  };
  return s;
}

afterEach(() => { vi.useRealTimers(); });

/**
 * Answer the handshake, which openalgo-charts 1.6 requires before any data
 * frame leaves the socket. A proxy that discards pre-auth frames otherwise
 * swallows the subscribe and the chart goes silent believing it is subscribed.
 */
function ack(s: any): void {
  s.onmessage({ data: JSON.stringify({ type: 'auth', status: 'success' }) });
}

describe('OpenAlgoWsFeed reconnect', () => {
  it('reconnects with backoff and replays subscriptions after an unexpected close', () => {
    vi.useFakeTimers();
    const sockets: any[] = [];
    const ws = new OpenAlgoWsFeed({
      url: 'ws://x', apiKey: 'k', reconnect: { baseDelayMs: 100 },
      socketFactory: () => { const s = fakeSocket(); sockets.push(s); return s; },
    });
    ws.connect();
    ack(sockets[0]);
    ws.subscribe('LTP', 'X', 'NSE');
    expect(sockets).toHaveLength(1);
    expect(sockets[0].sent.some((m: string) => m.includes('subscribe') && m.includes('X'))).toBe(true);

    // Unexpected drop -> should schedule a reconnect.
    sockets[0].onclose();
    vi.advanceTimersByTime(100);

    // A fresh socket authenticated and, once acknowledged, replayed the subscription.
    expect(sockets).toHaveLength(2);
    expect(sockets[1].sent.some((m: string) => m.includes('authenticate'))).toBe(true);
    ack(sockets[1]);
    expect(sockets[1].sent.some((m: string) => m.includes('subscribe') && m.includes('X'))).toBe(true);
    ws.close();
  });

  it('does not reconnect after an intentional close()', () => {
    vi.useFakeTimers();
    const sockets: any[] = [];
    const ws = new OpenAlgoWsFeed({
      url: 'ws://x', apiKey: 'k', reconnect: { baseDelayMs: 50 },
      socketFactory: () => { const s = fakeSocket(); sockets.push(s); return s; },
    });
    ws.connect();
    ws.subscribe('LTP', 'X', 'NSE');
    ws.close();
    sockets[0].onclose(); // the browser fires onclose after close()
    vi.advanceTimersByTime(1000);
    expect(sockets).toHaveLength(1); // no reconnect
  });

  it('honors reconnect.enabled = false', () => {
    vi.useFakeTimers();
    const sockets: any[] = [];
    const ws = new OpenAlgoWsFeed({
      url: 'ws://x', apiKey: 'k', reconnect: { enabled: false },
      socketFactory: () => { const s = fakeSocket(); sockets.push(s); return s; },
    });
    ws.connect();
    sockets[0].onclose();
    vi.advanceTimersByTime(60000);
    expect(sockets).toHaveLength(1);
    ws.close();
  });
});

describe('OpenAlgoWsFeed order updates', () => {
  const rawUpdate = {
    type: 'order_update', user_id: 'u', mode: 'analyze', broker: 'demo',
    orderid: '240221025997024', symbol: 'RELIANCE', exchange: 'NSE', action: 'BUY',
    quantity: 10, price: 1424.0, trigger_price: 0, pricetype: 'LIMIT', product: 'MIS',
    order_status: 'Complete', filled_quantity: 10, pending_quantity: 0,
    average_price: 1423.85, rejection_reason: '',
  };

  it('parseOrderUpdate normalizes the documented payload (and only that type)', () => {
    const e = parseOrderUpdate(rawUpdate)!;
    expect(e.orderId).toBe('240221025997024');
    expect(e.action).toBe('BUY');
    expect(e.status).toBe('complete'); // lowercased
    expect(e.triggerPrice).toBeUndefined(); // 0 becomes undefined
    expect(e.filledQuantity).toBe(10);
    expect(e.averagePrice).toBeCloseTo(1423.85);
    expect(parseOrderUpdate({ type: 'market_data', data: { ltp: 1 } })).toBeNull();
    expect(parseOrderUpdate('ping')).toBeNull();
  });

  it('subscribeOrders sends the action, dispatches events, and replays on reconnect', () => {
    vi.useFakeTimers();
    const sockets: any[] = [];
    const ws = new OpenAlgoWsFeed({
      url: 'ws://x', apiKey: 'k', reconnect: { baseDelayMs: 100 },
      socketFactory: () => { const s = fakeSocket(); sockets.push(s); return s; },
    });
    const events: OrderUpdateEvent[] = [];
    ws.onOrderUpdate((e) => events.push(e));
    ws.connect();
    ack(sockets[0]);
    ws.subscribeOrders();
    expect(sockets[0].sent.some((m: string) => m.includes('subscribe_orders'))).toBe(true);

    sockets[0].onmessage({ data: JSON.stringify(rawUpdate) });
    expect(events).toHaveLength(1);
    expect(events[0].symbol).toBe('RELIANCE');

    // unexpected drop: reconnect replays the order-stream subscription too
    sockets[0].onclose();
    vi.advanceTimersByTime(100);
    expect(sockets).toHaveLength(2);
    ack(sockets[1]);
    expect(sockets[1].sent.some((m: string) => m.includes('subscribe_orders'))).toBe(true);
    ws.close();
  });
});
