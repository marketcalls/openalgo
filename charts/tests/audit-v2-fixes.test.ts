import { describe, it, expect } from 'vitest';
import { OpenAlgoTradeFeed, mapOrder, mapPosition } from '../src/feed/openalgo-trade';
import { OpenAlgoWsFeed, formatSubscribe, type SocketLike } from '../src/feed/openalgo-ws';
import { intervalToSeconds } from '../src/feed/openalgo-live';
import { Pane } from '../src/core/pane';
import { PriceLine } from '../src/primitives/price-line';
import { fakeDocument } from './helpers/fake-dom';

function captureFeed() {
  const calls: { url: string; body: Record<string, unknown> }[] = [];
  const fetchImpl = (async (url: string, init?: RequestInit) => {
    calls.push({ url, body: JSON.parse(String(init?.body)) });
    return { ok: true, status: 200, json: async () => ({ orderid: 'OA1' }) } as Response;
  }) as unknown as typeof fetch;
  return { calls, feed: new OpenAlgoTradeFeed({ baseUrl: 'http://x', apiKey: 'k', fetchImpl }) };
}

describe('V2-H1: trade adapter matches OpenAlgo order contract', () => {
  it('place sends the mandatory product + strategy fields', async () => {
    const { calls, feed } = captureFeed();
    await feed.place({ symbol: 'SBIN', exchange: 'NSE', side: 'BUY', type: 'LIMIT', qty: 10, price: 16, product: 'CNC', mode: 'live' });
    expect(calls[0].body).toMatchObject({ strategy: 'openalgo-charts', symbol: 'SBIN', action: 'BUY', exchange: 'NSE', pricetype: 'LIMIT', product: 'CNC', quantity: 10 });
  });

  it('place defaults product to MIS when unspecified', async () => {
    const { calls, feed } = captureFeed();
    await feed.place({ symbol: 'SBIN', side: 'BUY', type: 'MARKET', qty: 1, mode: 'live' });
    expect(calls[0].body.product).toBe('MIS');
  });

  it('modify sends the full documented payload from cached order context', async () => {
    const { calls, feed } = captureFeed();
    await feed.place({ symbol: 'SBIN', exchange: 'NSE', side: 'BUY', type: 'LIMIT', qty: 10, price: 16, product: 'CNC', mode: 'live' });
    await feed.modify('OA1', { price: 16.5 });
    const m = calls[1].body;
    expect(calls[1].url).toBe('http://x/api/v1/modifyorder');
    expect(m).toMatchObject({ orderid: 'OA1', strategy: 'openalgo-charts', symbol: 'SBIN', action: 'BUY', exchange: 'NSE', pricetype: 'LIMIT', product: 'CNC', quantity: 10, price: 16.5 });
  });

  it('modify of an unknown order throws (no silent partial payload)', async () => {
    const { feed } = captureFeed();
    await expect(feed.modify('ghost', { price: 1 })).rejects.toThrow();
  });

  it('coerces string quantities/prices from the books', () => {
    const o = mapOrder({ orderid: 'X', symbol: 'SBIN', action: 'SELL', pricetype: 'SL', quantity: '5', price: 99, trigger_price: '98.5', order_status: 'open' });
    expect(o.qty).toBe(5);
    expect(o.triggerPrice).toBe(98.5);
    const p = mapPosition({ symbol: 'YESBANK', quantity: '-104', average_price: '17.2' });
    expect(p.netQty).toBe(-104);
    expect(p.avgPrice).toBeCloseTo(17.2);
  });
});

describe('V2-H2: WS schema + pre-auth gating', () => {
  it('uses the documented per-symbol subscribe schema (numeric mode)', () => {
    const msg = JSON.parse(formatSubscribe('LTP', 'SBIN', 'NSE'));
    expect(msg).toEqual({ action: 'subscribe', symbol: 'SBIN', exchange: 'NSE', mode: 1 });
  });

  /**
   * REWRITTEN in the 1.6 hardening round. This used to assert that a subscribe
   * queued before the transport opened was flushed the instant it did, right
   * behind the handshake. That is the behaviour the round removed: a proxy that
   * discards frames arriving before it has authenticated the key swallows that
   * subscribe, and the chart then believes it is subscribed and is permanently
   * silent. Nothing but the handshake leaves the socket until the server
   * answers it, and the desired subscription state is replayed on the answer.
   */
  it('sends nothing before the socket opens, then only the handshake, and replays on the ack', () => {
    const sent: string[] = [];
    let sock!: SocketLike;
    const feed = new OpenAlgoWsFeed({
      url: 'ws://x', apiKey: 'k',
      socketFactory: () => { sock = { send: (d) => sent.push(d), close: () => {}, onopen: null, onclose: null, onmessage: null, readyState: 0 }; return sock; },
    });
    feed.connect();
    feed.subscribe('LTP', 'SBIN', 'NSE'); // before open: recorded, not sent
    expect(sent).toHaveLength(0);
    sock.onopen?.(); // transport open: the handshake, and nothing else
    expect(sent).toHaveLength(1);
    expect(JSON.parse(sent[0])).toEqual({ action: 'authenticate', api_key: 'k' });
    expect(feed.isReady()).toBe(false);
    sock.onmessage?.({ data: JSON.stringify({ type: 'auth', status: 'success' }) }); // the gate opens
    expect(feed.isReady()).toBe(true);
    expect(sent).toHaveLength(2);
    expect(JSON.parse(sent[1])).toMatchObject({ action: 'subscribe', symbol: 'SBIN', mode: 1 });
    feed.subscribe('LTP', 'RELIANCE', 'NSE'); // after the ack: immediate
    expect(sent).toHaveLength(3);
  });
});

describe('V2-M1: interval parsing for the live feed', () => {
  it('maps interval tokens to seconds', () => {
    expect(intervalToSeconds('1m')).toBe(60);
    expect(intervalToSeconds('5m')).toBe(300);
    expect(intervalToSeconds('1h')).toBe(3600);
    expect(intervalToSeconds('D')).toBe(86400); // bare daily token
    expect(intervalToSeconds('W')).toBe(604800); // bare weekly token
    expect(() => intervalToSeconds('bogus')).toThrow();
  });
});

describe('V2-M3: destroy detaches primitives', () => {
  it('Pane.destroy calls detached() on every attached primitive', () => {
    const pane = new Pane(fakeDocument());
    let detached = 0;
    const line = new PriceLine({ price: 100, color: '#fff', lineWidth: 1, dashed: false, id: 'x' });
    const origDetached = line.detached.bind(line);
    line.detached = () => { detached++; origDetached(); };
    pane.addPrimitive(line, { requestUpdate: () => {} });
    pane.destroy();
    expect(detached).toBe(1);
  });
});
