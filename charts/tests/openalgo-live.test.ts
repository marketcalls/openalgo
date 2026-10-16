import { describe, it, expect } from 'vitest';
import { OpenAlgoLiveDataFeed, intervalToSeconds } from '../src/feed/openalgo-live';
import type { Bar } from '../src/model/bar';

describe('intervalToSeconds', () => {
  it('maps bare and prefixed daily/weekly tokens', () => {
    expect(intervalToSeconds('D')).toBe(86400);
    expect(intervalToSeconds('W')).toBe(604800);
    expect(intervalToSeconds('1D')).toBe(86400);
    expect(intervalToSeconds('1W')).toBe(604800);
  });
  it('maps intraday tokens', () => {
    expect(intervalToSeconds('1s')).toBe(1);
    expect(intervalToSeconds('1m')).toBe(60);
    expect(intervalToSeconds('5m')).toBe(300);
    expect(intervalToSeconds('1h')).toBe(3600);
    expect(intervalToSeconds('4h')).toBe(14400);
  });
  it('throws for unknown tokens instead of silently meaning one minute', () => {
    // Falling back to 60 drew minute bars under a label the caller chose, which
    // is worse than refusing: a subscription now fails at subscribe time.
    expect(() => intervalToSeconds('bogus')).toThrow();
    expect(() => intervalToSeconds('')).toThrow();
  });
});

// A driveable in-memory socket for the WS feed.
function fakeSocket(): any {
  const s: any = {
    sent: [] as string[], readyState: 1,
    onopen: null, onclose: null, onerror: null, onmessage: null,
    send(d: string) { s.sent.push(d); },
    close() {},
  };
  return s;
}
function ltpFrame(fields: Record<string, unknown>): { data: string } {
  return { data: JSON.stringify({ data: fields }) };
}

function makeFeed(volumeMode: 'ltq-sum' | 'day-delta'): { feed: OpenAlgoLiveDataFeed; sock: () => any } {
  let sock: any;
  const feed = new OpenAlgoLiveDataFeed({
    apiKey: 'k', baseUrl: '', wsUrl: 'ws://test', volumeMode,
    socketFactory: () => (sock = fakeSocket()),
  });
  return { feed, sock: () => sock };
}

describe('OpenAlgoLiveDataFeed.subscribeBars', () => {
  it('filters ticks by both symbol and exchange', () => {
    const { feed, sock } = makeFeed('ltq-sum');
    const bars: Bar[] = [];
    feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: '1h', from: 0 }, (b) => bars.push(b));
    const s = sock();
    s.onmessage(ltpFrame({ symbol: 'X', exchange: 'BSE', ltp: 100, ltq: 1, timestamp: 1700000000 })); // wrong exchange
    s.onmessage(ltpFrame({ symbol: 'Y', exchange: 'NSE', ltp: 100, ltq: 1, timestamp: 1700000000 })); // wrong symbol
    expect(bars).toHaveLength(0);
    s.onmessage(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 101, ltq: 2, timestamp: 1700000000 })); // match
    expect(bars.length).toBeGreaterThan(0);
    expect(bars[bars.length - 1].close).toBe(101);
  });

  it('diffs cumulative day volume in day-delta mode', () => {
    const { feed, sock } = makeFeed('day-delta');
    const bars: Bar[] = [];
    feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: '1h', from: 0 }, (b) => bars.push(b));
    const s = sock();
    const t = 1700000000; // same hour bucket for both ticks
    s.onmessage(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 100, volume: 1000, timestamp: t }));
    s.onmessage(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 102, volume: 1500, timestamp: t + 60 }));
    const last = bars[bars.length - 1];
    expect(last.volume).toBe(500); // 1500 - 1000, not the raw cumulative
  });

  it('marks the bar a builder opens from a stale seed provisional, and the bucket after it not', () => {
    // History ended on the previous minute, so the first tick opens the current
    // bucket at whatever price it happens to carry: provisional. The next
    // bucket opens on its first trade, because the builder streamed this one.
    const { feed, sock } = makeFeed('ltq-sum');
    const seen: Array<[number, boolean | undefined]> = [];
    feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: '1m', from: 0 },
      (b, meta) => seen.push([b.time, meta?.provisional]),
      { seedFrom: { time: 1699999980, open: 1, high: 1, low: 1, close: 1, volume: 1 } });
    const s = sock();
    s.onmessage(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 100, ltq: 1, timestamp: 1700000050 }));
    s.onmessage(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 101, ltq: 1, timestamp: 1700000055 }));
    s.onmessage(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 102, ltq: 1, timestamp: 1700000100 }));
    expect(seen).toEqual([[1700000040, true], [1700000040, true], [1700000100, undefined]]);
  });

  it('uses the current time when a tick omits its timestamp (never buckets at the epoch)', () => {
    const { feed, sock } = makeFeed('ltq-sum');
    const bars: Bar[] = [];
    feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: '1m', from: 0 }, (b) => bars.push(b));
    sock().onmessage(ltpFrame({ symbol: 'X', exchange: 'NSE', ltp: 100, ltq: 1 })); // no timestamp
    expect(bars.length).toBeGreaterThan(0);
    expect(bars[bars.length - 1].time).toBeGreaterThan(1_600_000_000); // a recent epoch, not 0
  });
});
