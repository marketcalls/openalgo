/**
 * Hardening regressions for the composed live feed (`src/feed/openalgo-live.ts`).
 *
 * Every case here asserts on what reached the wire, not on internal counters:
 * the defects were all "the socket was told the wrong thing", and a test that
 * inspects a private map would keep passing while the frames stayed wrong.
 */
import { describe, it, expect } from 'vitest';
import { OpenAlgoLiveDataFeed } from '../src/feed/openalgo-live';
import { registerInterval } from '../src/feed/intervals';
import type { Bar } from '../src/model/bar';
import type { MarketDepth } from '../src/feed/types';

interface FakeSocket {
  sent: string[];
  readyState: number;
  onopen: (() => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
  send(d: string): void;
  close(): void;
}

function fakeSocket(): FakeSocket {
  const s: FakeSocket = {
    sent: [], readyState: 1,
    onopen: null, onclose: null, onerror: null, onmessage: null,
    send(d: string) { s.sent.push(d); },
    close() {},
  };
  return s;
}

function makeFeed(config: Partial<{ volumeMode: 'ltq-sum' | 'day-delta'; depthLevel: number }> = {}): {
  feed: OpenAlgoLiveDataFeed;
  sock: () => FakeSocket;
} {
  let sock: FakeSocket | undefined;
  const feed = new OpenAlgoLiveDataFeed({
    apiKey: 'k', baseUrl: '', wsUrl: 'ws://test',
    ...config,
    socketFactory: () => (sock = fakeSocket()),
  });
  // Answer the handshake the socket layer now gates on. Every case below is
  // about what reached the wire after the connection was usable, so the gate is
  // opened once here rather than repeated in thirteen test bodies.
  sock?.onmessage?.({ data: JSON.stringify({ type: 'auth', status: 'success' }) });
  return { feed, sock: () => sock as FakeSocket };
}

/** Every frame the socket was given, parsed. Auth is included; callers filter. */
function frames(s: FakeSocket): Record<string, unknown>[] {
  return s.sent.map((t) => JSON.parse(t) as Record<string, unknown>);
}

function actions(s: FakeSocket, action: string): Record<string, unknown>[] {
  return frames(s).filter((f) => f.action === action);
}

function ltpFrame(fields: Record<string, unknown>): { data: string } {
  return { data: JSON.stringify({ data: fields }) };
}

function depthFrame(symbol: string, exchange: string): { data: string } {
  return {
    data: JSON.stringify({
      data: { symbol, exchange, ltp: 100, depth: { buy: [{ price: 99, quantity: 5 }], sell: [{ price: 101, quantity: 7 }] } },
    }),
  };
}

describe('subscription ownership is reference counted', () => {
  it('one consumer leaving does not unsubscribe the symbol for the others', () => {
    const { feed, sock } = makeFeed();
    const a: Bar[] = [];
    const b: Bar[] = [];
    const req = { symbol: 'X', exchange: 'NSE', interval: '1m', from: 0 };
    const offA = feed.subscribeBars(req, (bar) => a.push(bar));
    const offB = feed.subscribeBars(req, (bar) => b.push(bar));
    const s = sock();

    // Shared stream: one remote subscribe for two consumers.
    expect(actions(s, 'subscribe')).toHaveLength(1);

    offA();
    expect(actions(s, 'unsubscribe')).toHaveLength(0);

    // The defect: B went silent here because A's unsubscribe hit the wire.
    s.onmessage?.(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 101, ltq: 3, timestamp: 1700000000 }));
    expect(b.map((bar) => bar.close)).toEqual([101]);
    expect(a).toHaveLength(0); // A really did detach

    offB();
    expect(actions(s, 'unsubscribe')).toHaveLength(1);
  });

  it('unsubscribes remotely only once the last depth consumer leaves', () => {
    const { feed, sock } = makeFeed();
    const seen: MarketDepth[] = [];
    const req = { symbol: 'X', exchange: 'NSE', interval: '1m', from: 0 };
    const offA = feed.subscribeDepth(req, () => {});
    const offB = feed.subscribeDepth(req, (d) => seen.push(d));
    const s = sock();

    offA();
    expect(actions(s, 'unsubscribe')).toHaveLength(0);
    s.onmessage?.(depthFrame('X', 'NSE'));
    expect(seen).toHaveLength(1);

    offB();
    expect(actions(s, 'unsubscribe')).toHaveLength(1);
  });

  it('a double release does not spend another consumer\'s share', () => {
    const { feed, sock } = makeFeed();
    const req = { symbol: 'X', exchange: 'NSE', interval: '1m', from: 0 };
    const offA = feed.subscribeBars(req, () => {});
    feed.subscribeBars(req, () => {});
    const s = sock();

    offA();
    offA(); // careless host, or a StrictMode double cleanup
    expect(actions(s, 'unsubscribe')).toHaveLength(0);
  });

  it('counts bars and depth on one symbol separately', () => {
    const { feed, sock } = makeFeed();
    const req = { symbol: 'X', exchange: 'NSE', interval: '1m', from: 0 };
    const offBars = feed.subscribeBars(req, () => {});
    const offDepthA = feed.subscribeDepth(req, () => {});
    feed.subscribeDepth(req, () => {});
    const s = sock();
    expect(actions(s, 'subscribe')).toHaveLength(2); // one LTP, one Depth

    offDepthA();
    expect(actions(s, 'unsubscribe')).toHaveLength(0); // the second depth consumer still holds it

    offBars();
    const unsub = actions(s, 'unsubscribe');
    expect(unsub).toHaveLength(1);
    expect(unsub[0].mode).toBe(1); // LTP left, Depth stayed
  });

  it('negotiates the maximum depth required, not the most recent', () => {
    const { feed, sock } = makeFeed();
    const req = { symbol: 'X', exchange: 'NSE', interval: '1m', from: 0 };
    feed.subscribeDepth(req, () => {}, { depthLevel: 20 });
    feed.subscribeDepth(req, () => {}, { depthLevel: 5 });
    const s = sock();

    // The shallow consumer must not shrink the book under the deep one.
    const subs = actions(s, 'subscribe');
    expect(subs).toHaveLength(1);
    expect(subs[0].depth).toBe(20);
  });

  it('upgrades the wire when a later consumer needs a deeper book', () => {
    const { feed, sock } = makeFeed();
    const req = { symbol: 'X', exchange: 'NSE', interval: '1m', from: 0 };
    feed.subscribeDepth(req, () => {}, { depthLevel: 5 });
    feed.subscribeDepth(req, () => {}, { depthLevel: 50 });
    const s = sock();

    const subs = actions(s, 'subscribe');
    expect(subs).toHaveLength(2);
    expect(subs[1].depth).toBe(50);
  });
});

describe('session-anchored intervals bucket on their own grid', () => {
  it('honours IntervalBucketing.anchorSec instead of the epoch grid', () => {
    // Hourly bars anchored to the 09:15 IST open (03:45 UTC), the documented
    // case for an anchor: an interval that does not divide the trading day
    // evenly. The epoch grid would open these at 03:00 and 04:00 UTC, so the
    // live bar and the history bar for the same hour disagree on their open.
    const anchorSec = Date.UTC(2023, 10, 14, 3, 45, 0) / 1000;
    const dispose = registerInterval({
      code: 'SESSIONHOUR', bucketing: { mode: 'interval', seconds: 3600, anchorSec },
    });
    try {
      const { feed, sock } = makeFeed();
      const bars: Bar[] = [];
      feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: 'SESSIONHOUR', from: 0 }, (b) => bars.push(b));
      const s = sock();
      // 03:46:30 UTC, ninety seconds into the session's first hourly bucket.
      s.onmessage?.(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 100, ltq: 1, timestamp: anchorSec + 90 }));
      expect(bars[0].time).toBe(anchorSec); // the epoch grid says 03:00 UTC

      // 04:30 UTC is still inside the 03:45 bucket; the epoch grid would have
      // closed the 03:00 bar at 04:00 and opened a second one here.
      s.onmessage?.(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 105, ltq: 1, timestamp: anchorSec + 2700 }));
      expect(bars.map((b) => b.time)).toEqual([anchorSec, anchorSec]);

      // 04:45 UTC opens the next anchored bucket.
      s.onmessage?.(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 106, ltq: 1, timestamp: anchorSec + 3600 }));
      expect(bars[2].time).toBe(anchorSec + 3600);
    } finally {
      dispose();
    }
  });
});

describe('volumeMode day-delta has a wire path', () => {
  it('subscribes Quote, the only mode carrying a cumulative day volume', () => {
    const { feed, sock } = makeFeed({ volumeMode: 'day-delta' });
    feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: '1m', from: 0 }, () => {});
    const subs = actions(sock(), 'subscribe');
    expect(subs).toHaveLength(1);
    expect(subs[0].mode).toBe(2); // 2 = Quote; LTP frames never carry `volume`
  });

  // Compatibility guard, not a regression test: it holds before and after the
  // fix, and exists so the Quote path never spreads to the default mode.
  it('leaves the default on LTP', () => {
    const { feed, sock } = makeFeed();
    feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: '1m', from: 0 }, () => {});
    expect(actions(sock(), 'subscribe')[0].mode).toBe(1);
  });

  it('uses Quote for a count-driven interval too, which reads volume the same way', () => {
    const dispose = registerInterval({ code: 'V1000', bucketing: { mode: 'volume', perBar: 1000 } });
    try {
      const { feed, sock } = makeFeed({ volumeMode: 'day-delta' });
      feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: 'V1000', from: 0 }, () => {});
      expect(actions(sock(), 'subscribe')[0].mode).toBe(2);
    } finally {
      dispose();
    }
  });
});

describe('depth level reaches the wire', () => {
  // Compatibility guard, not a regression test: a caller that names no level
  // must still get exactly the frame this feed has always sent.
  it('sends no depth key when nothing asked for one', () => {
    const { feed, sock } = makeFeed();
    feed.subscribeDepth({ symbol: 'X', exchange: 'NSE', interval: '1m', from: 0 }, () => {});
    const sub = actions(sock(), 'subscribe')[0];
    expect(sub.mode).toBe(3);
    expect(sub.depth).toBeUndefined();
    expect(sub.depth_level).toBeUndefined();
  });

  // `depth` is what the proxy reads (docs/prompt/websockets-format.md in the
  // platform). 1.x sent only `depth_level`, which nothing read, so a 20-level
  // request was served at five with no error. The old key stays beside the
  // new one for consumers that copied it from this library.
  it('sends the per-call level under the key the proxy reads, and the old one', () => {
    const { feed, sock } = makeFeed();
    feed.subscribeDepth({ symbol: 'X', exchange: 'NSE', interval: '1m', from: 0 }, () => {}, { depthLevel: 30 });
    const sub = actions(sock(), 'subscribe')[0];
    expect(sub.depth).toBe(30);
    expect(sub.depth_level).toBe(30);
  });

  it('falls back to the configured default, and the per-call level overrides it', () => {
    const { feed, sock } = makeFeed({ depthLevel: 20 });
    feed.subscribeDepth({ symbol: 'A', exchange: 'NSE', interval: '1m', from: 0 }, () => {});
    feed.subscribeDepth({ symbol: 'B', exchange: 'NSE', interval: '1m', from: 0 }, () => {}, { depthLevel: 50 });
    const subs = actions(sock(), 'subscribe');
    expect(subs[0].depth).toBe(20);
    expect(subs[1].depth).toBe(50);
  });
});
