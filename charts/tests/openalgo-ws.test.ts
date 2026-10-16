import { describe, expect, it } from 'vitest';
import { OpenAlgoWsFeed, parseMessage, type LtpEvent, type SocketLike } from '../src/feed/openalgo-ws';
import type { MarketDepth } from '../src/feed/types';

// The proxy wraps the broker payload with identity; it does not send a topic.
const ltpFrame = {
  type: 'market_data', symbol: 'RELIANCE', exchange: 'NSE', mode: 1, broker: 'zerodha',
  data: { ltp: 1424, timestamp: 1756376445123 },
};
const quoteFrame = {
  type: 'market_data', symbol: 'RELIANCE', exchange: 'NSE', mode: 2, broker: 'zerodha',
  data: {
    ltp: 1424, change: 6, change_percent: 0.42, volume: 100000,
    open: 1415, high: 1432.5, low: 1408, close: 1418,
    last_trade_quantity: 50, avg_trade_price: 1419.35, timestamp: 1756376445123,
  },
};
const depthFrame = {
  type: 'market_data', symbol: 'RELIANCE', exchange: 'NSE', mode: 3, broker: 'zerodha',
  data: {
    ltp: 1424, timestamp: 1756376445123,
    depth: {
      buy: [
        { price: 1423.9, quantity: 50, orders: 3 },
        { price: 1423.5, quantity: 35, orders: 2 },
        { price: 1423, quantity: 42, orders: 4 },
        { price: 1422.5, quantity: 28, orders: 1 },
        { price: 1422, quantity: 33, orders: 5 },
      ],
      sell: [
        { price: 1424.1, quantity: 47, orders: 2 },
        { price: 1424.5, quantity: 39, orders: 3 },
        { price: 1425, quantity: 41, orders: 4 },
        { price: 1425.5, quantity: 32, orders: 2 },
        { price: 1426, quantity: 30, orders: 1 },
      ],
    },
  },
};

describe('OpenAlgo proxy market-data envelope', () => {
  it('parses documented LTP identity and the nested millisecond timestamp', () => {
    expect(parseMessage(ltpFrame)).toEqual({
      kind: 'ltp',
      event: { symbol: 'RELIANCE', exchange: 'NSE', ltp: 1424, timeSec: 1756376445 },
    });
  });

  it('parses documented Quote identity, quantity, volume and timestamp', () => {
    expect(parseMessage(quoteFrame)).toEqual({
      kind: 'ltp',
      event: {
        symbol: 'RELIANCE', exchange: 'NSE', ltp: 1424,
        ltq: 50, volume: 100000, timeSec: 1756376445,
      },
    });
  });

  it('parses documented Depth identity and all five book levels', () => {
    expect(parseMessage(depthFrame)).toEqual({
      kind: 'depth', symbol: 'RELIANCE', exchange: 'NSE',
      depth: {
        ltp: 1424,
        timeSec: 1756376445,
        bids: [
          { price: 1423.9, qty: 50 }, { price: 1423.5, qty: 35 }, { price: 1423, qty: 42 },
          { price: 1422.5, qty: 28 }, { price: 1422, qty: 33 },
        ],
        asks: [
          { price: 1424.1, qty: 47 }, { price: 1424.5, qty: 39 }, { price: 1425, qty: 41 },
          { price: 1425.5, qty: 32 }, { price: 1426, qty: 30 },
        ],
      },
    });
  });

  it('leaves a missing or invalid depth timestamp unspecified', () => {
    for (const timestamp of [undefined, 'invalid', NaN]) {
      const result = parseMessage({ ...depthFrame, data: { ...depthFrame.data, timestamp } });
      expect(result?.kind === 'depth' && result.depth.timeSec).toBeUndefined();
    }
  });

  it('uses the market event time when a cached quote has a newer delivery timestamp', () => {
    // Captured field shape: a previous-session event delivered on reconnect.
    const data = { ltt: 1789732772, timestamp: 1789833463417 };
    for (const frame of [ltpFrame, quoteFrame]) {
      expect(parseMessage({ ...frame, data: { ...frame.data, ...data } }))
        .toMatchObject({ kind: 'ltp', event: { timeSec: 1789732772 } });
    }
    expect(parseMessage({ ...depthFrame, data: { ...depthFrame.data, ...data } }))
      .toMatchObject({ kind: 'depth', depth: { timeSec: 1789732772 } });
  });

  it.each([1789732772, 1789732772000, '1789732772', '1789732772000', '2026-09-18T11:59:32Z'])(
    'normalizes explicit market timestamps in seconds, milliseconds or ISO form: %s', (ltt) => {
      expect(parseMessage({ ...ltpFrame, data: { ltp: 100, ltt, timestamp: 1789833463417 } }))
        .toMatchObject({ kind: 'ltp', event: { timeSec: 1789732772 } });
    },
  );

  it('prefers explicit trade/exchange fields and falls back past invalid timestamps', () => {
    const parse = (data: Record<string, unknown>) => parseMessage({ ...ltpFrame, data: { ltp: 100, ...data } });
    expect(parse({ last_trade_time: 1789732700, ltt: 1789732772, timestamp: 1789833463417 }))
      .toMatchObject({ event: { timeSec: 1789732700 } });
    expect(parse({ ltt: 0, exchange_timestamp: '1789732772', timestamp: 1789833463417 }))
      .toMatchObject({ event: { timeSec: 1789732772 } });
    expect(parse({ ltt: 'invalid', exchange_timestamp: Infinity, timestamp: '1756376445123' }))
      .toMatchObject({ event: { timeSec: 1756376445 } });
    expect(parse({ ltt: -1, timestamp: NaN })).toMatchObject({ event: { timeSec: 0 } });
    expect(parse({ ltt: '-1', timestamp: 1789732772 })).toMatchObject({ event: { timeSec: 1789732772 } });
  });

  it('retains nested identity precedence for existing broker payloads', () => {
    expect(parseMessage({
      ...ltpFrame, topic: 'SBIN.BSE',
      data: { ...ltpFrame.data, symbol: 'INFY', exchange: 'NSE_INDEX' },
    })).toMatchObject({ kind: 'ltp', event: { symbol: 'INFY', exchange: 'NSE_INDEX' } });
  });

  it('uses envelope identity before topic when nested identity is empty', () => {
    expect(parseMessage({
      ...ltpFrame, topic: 'SBIN.BSE',
      data: { ...ltpFrame.data, symbol: '', exchange: '' },
    })).toMatchObject({ kind: 'ltp', event: { symbol: 'RELIANCE', exchange: 'NSE' } });
  });

  it('retains topic fallback when nested and envelope identity are missing', () => {
    expect(parseMessage({
      type: 'market_data', symbol: '', exchange: '', topic: 'SBIN.NSE',
      data: { ltp: 772.5, symbol: '', exchange: '' },
    })).toMatchObject({ kind: 'ltp', event: { symbol: 'SBIN', exchange: 'NSE', ltp: 772.5 } });
  });

  it('retains flat broker payloads with top-level timestamps', () => {
    expect(parseMessage({
      symbol: 'SBIN', exchange: 'NSE', last_price: 772.5, ltq: 7, timestamp: 1756376445,
    })).toEqual({
      kind: 'ltp', event: { symbol: 'SBIN', exchange: 'NSE', ltp: 772.5, ltq: 7, timeSec: 1756376445 },
    });
  });

  it('dispatches proxy tick and depth frames to instrument-filtered subscribers', () => {
    const socket: SocketLike = {
      send: () => {}, close: () => {}, onopen: null, onclose: null, onmessage: null, readyState: 1,
    };
    const feed = new OpenAlgoWsFeed({
      url: 'ws://test', apiKey: 'test', socketFactory: () => socket,
      heartbeat: { timeoutMs: 0 }, reconnect: { enabled: false },
    });
    const ticks: LtpEvent[] = [];
    const books: MarketDepth[] = [];
    feed.onLtp((event) => {
      if (event.symbol === 'RELIANCE' && event.exchange === 'NSE') ticks.push(event);
    });
    feed.onDepth((symbol, exchange, depth) => {
      if (symbol === 'RELIANCE' && exchange === 'NSE') books.push(depth);
    });
    feed.connect();
    socket.onmessage?.({ data: JSON.stringify({ type: 'auth', status: 'success' }) });
    for (const frame of [ltpFrame, quoteFrame, depthFrame]) {
      socket.onmessage?.({ data: JSON.stringify(frame) });
    }
    expect(ticks.map((event) => [event.ltp, event.timeSec])).toEqual([[1424, 1756376445], [1424, 1756376445]]);
    expect(books).toHaveLength(1);
    expect(books[0].bids[0]).toEqual({ price: 1423.9, qty: 50 });
    feed.close();
  });
});
